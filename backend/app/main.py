import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from . import ws
from .anpr.worker import start_worker, stop_all
from .config import settings
from .db import engine
from .models import Base, Camera, User, has_stream
from .db import SessionLocal
from .routers import (adapters, alerts, analytics, auth, cameras, copilot, demo,
                      edge, evidence, fleet, integrations, ops, reports,
                      sightings, streams, users, vahan, vehicle_trace, vehicles, watchlist)

log = logging.getLogger("sentinel")
logging.basicConfig(level=logging.INFO)

# Columns added after the first schema shipped. SQLite create_all() won't ALTER
# existing tables, so add any missing columns in place (preserves data).
_MIGRATIONS = {
    "cameras": {"heading": "FLOAT DEFAULT 0.0", "fov_deg": "FLOAT DEFAULT 55.0",
                "range_m": "FLOAT DEFAULT 80.0", "hls_url": "TEXT DEFAULT ''",
                "external_id": "VARCHAR(50) DEFAULT ''"},
    "sightings": {"pts_ms": "FLOAT DEFAULT 0.0", "sha256": "VARCHAR(64) DEFAULT ''"},
    "vehicle_detections": {"img_x": "FLOAT DEFAULT 0.5", "img_y": "FLOAT DEFAULT 0.9",
                           "sha256": "VARCHAR(64) DEFAULT ''"},
    "watchlist": {"kind": "VARCHAR(20) DEFAULT 'vehicle'", "embedding": "BLOB",
                  "photo": "VARCHAR(300) DEFAULT ''"},
}


def _migrate():
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in _MIGRATIONS.items():
            if table not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col not in have:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {ddl}'))
                    log.info("migrated: %s.%s added", table, col)


def _retention_prune():
    """Bound the DB: periodically drop detections/sightings older than the
    retention window. Applies in both live and sandbox modes so looping clips or
    a long session never stack the DB unbounded. Real evidence within the window
    is untouched. Runs on a daemon thread."""
    import threading
    import time
    from datetime import timedelta

    mins = settings.detection_retention_min
    if not mins or mins <= 0:
        return

    def loop():
        while True:
            time.sleep(300)  # every 5 min
            try:
                from .db import SessionLocal as _S
                dbp = _S()
                try:
                    n = prune_older_than(dbp, datetime.utcnow() - timedelta(minutes=mins))
                    if any(n.values()):
                        log.info("retention prune: %s (older than %dm)", n, mins)
                finally:
                    dbp.close()
            except Exception:
                log.exception("retention prune failed")

    threading.Thread(target=loop, name="retention-prune", daemon=True).start()


def prune_older_than(db, cutoff: datetime) -> dict[str, int]:
    """Drop detections, sightings and cached vendor traces older than
    `cutoff`, and the alerts that reference them.

    Alerts must go first. An alert carries sighting_id, and its evidence is the
    sighting's snapshot; deleting the sighting alone leaves an alert pointing at
    a row that no longer exists, which the alerts view then renders with no
    evidence behind it. Anything an operator has not acknowledged is kept
    regardless of age — an outstanding alert is not housekeeping.

    Cached vendor traces go too. That table holds RTO data about named owners
    that we did not collect ourselves, so it is not exempt from the retention
    window just because it is a cache. A row is dropped once it is past its
    TTL — nothing will ever serve it again — and never outlives the window
    even if the TTL is set longer than the window.
    """
    from datetime import timedelta

    from .models import Alert, Sighting, VehicleDetection, VehicleTraceCache

    stale_sightings = db.query(Sighting.id).filter(Sighting.ts < cutoff).subquery()
    alerts = (db.query(Alert)
              .filter(Alert.sighting_id.in_(db.query(stale_sightings.c.id)),
                      Alert.acknowledged.is_(True))
              .delete(synchronize_session=False))

    # Keep any sighting still referenced by a surviving (unacknowledged) alert.
    referenced = db.query(Alert.sighting_id).subquery()
    sightings = (db.query(Sighting)
                 .filter(Sighting.ts < cutoff,
                         ~Sighting.id.in_(db.query(referenced.c.sighting_id)))
                 .delete(synchronize_session=False))

    detections = (db.query(VehicleDetection)
                  .filter(VehicleDetection.ts < cutoff)
                  .delete(synchronize_session=False))

    ttl_cutoff = datetime.utcnow() - timedelta(
        seconds=max(60, settings.vehicle_trace_cache_ttl_s))
    traces = (db.query(VehicleTraceCache)
              .filter(VehicleTraceCache.updated_at < max(cutoff, ttl_cutoff))
              .delete(synchronize_session=False))
    db.commit()
    return {"alerts": alerts, "sightings": sightings, "detections": detections,
            "traces": traces}


def _autostart_workers():
    """Bring the grid live on boot — no manual 'start analytics'. Workers are
    staggered on a background thread so 30 HEVC decoders don't spin up at once
    and spike memory (that OOM-crashed an early build).

    AUTOSTART_MAX_CAMERAS picks how many come up:
      negative  every camera that has a stream URL
      0         none, wait for an operator to press Start All
      positive  a cap, for constrained machines

    Zero reads naturally as "no limit" but means the opposite, and a wall of
    permanently idle tiles gives the operator nothing to go on, so the choice
    is logged either way.
    """
    import threading
    import time

    cap = settings.autostart_max_cameras
    db = SessionLocal()
    try:
        ids = [c.id for c in
               db.query(Camera).filter(has_stream()).order_by(Camera.id).all()]
    finally:
        db.close()

    eligible = len(ids)
    if cap == 0:
        log.warning("autostart disabled (AUTOSTART_MAX_CAMERAS=0): %d cameras "
                    "have a stream but none will start until an operator "
                    "presses Start All. Set it negative to start every camera.",
                    eligible)
        return
    if cap > 0:
        ids = ids[:cap]
    if eligible > len(ids):
        log.warning("autostart capped at %d of %d streamable cameras "
                    "(AUTOSTART_MAX_CAMERAS=%d); the rest stay idle on the "
                    "live wall", len(ids), eligible, cap)

    def stagger():
        for cid in ids:
            start_worker(cid)
            time.sleep(settings.autostart_stagger_ms / 1000.0)
        log.info("auto-started analytics on %d of %d streamable cameras",
                 len(ids), eligible)

    threading.Thread(target=stagger, name="autostart", daemon=True).start()


def _seed_accounts():
    """Create the starter accounts on an empty users table.

    Only ever runs when the table has no rows. Once a deployment manages its
    own accounts, editing ADMIN_PASSWORD in .env must not resurrect or alter
    anything, and deleting a seeded account must not bring it back on restart.
    """
    from .security import bootstrap_users
    from .utils import passwords

    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return
        seeded = []
        for username, (password, role) in bootstrap_users().items():
            db.add(User(
                username=username.strip().lower(),
                password_hash=passwords.hash_password(password),
                role=role,
                full_name=f"Seed {role}",
                active=True,
                # The shipped defaults are public knowledge, so an account
                # still using one is required to change it at first sign-in.
                must_change_password=passwords.policy_error(password) is not None,
                created_by="system-bootstrap",
            ))
            seeded.append(f"{username}({role})")
        db.commit()
        if seeded:
            log.warning("seeded starter accounts: %s — sign in and change these "
                        "passwords, then create real accounts under Users",
                        ", ".join(seeded))
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    _migrate()
    _seed_accounts()
    ws.set_loop(asyncio.get_running_loop())
    from . import edge as edge_tier
    edge_tier.start()
    from .agent import plate_llm
    plate_llm.start()
    _retention_prune()
    if settings.demo_simulate:
        from . import sim
        sim.start()  # sandbox mode: generate live detections (also stops workers)
    else:
        _autostart_workers()
    yield
    stop_all()
    from . import edge as edge_tier
    edge_tier.stop()


app = FastAPI(title="SENTINEL — Unified CCTV Intelligence Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

READ_METHODS = {"GET", "HEAD", "OPTIONS"}

# While an account is flagged for a forced password change, these are the only
# calls its session may make: change the password, read its own profile, or
# sign out. Everything else is refused until the temporary password is gone.
_PASSWORD_CHANGE_ALLOW = {
    ("POST", "/api/users/me/password"),
    ("GET", "/api/users/me"),
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/logout"),
}


@app.middleware("http")
async def rbac_and_audit(request, call_next):
    """One gate for every /api call and for /snapshots.

    Mutations need a JWT (or the shared EDGE_TOKEN on ingest). Reads need a
    token when auth_enforce_reads is set. Snapshot files follow the same
    read policy.
    Every mutation is written to the audit trail with the caller, the outcome
    and the path.
    """
    from fastapi.responses import JSONResponse

    from .security import (audit, claims_from_request, edge_token_ok, is_public,
                           rank, required_read_role, required_role,
                           session_state)

    path = request.url.path
    method = request.method

    if is_public(path) or (not path.startswith("/api") and not path.startswith("/snapshots")):
        return await call_next(request)

    claims = claims_from_request(request)

    # A JWT is valid on its signature alone until it expires, so a deactivated
    # account, a demoted one, or one whose password was just reset would keep
    # working for up to TOKEN_TTL_HOURS. Check the account behind the token is
    # still entitled to this session, and treat a revoked one as anonymous.
    # A session on a temporary password is similarly confined: until the
    # password is changed, only the change itself (plus reading your own
    # profile and signing out) is allowed. Enforcing this here rather than in
    # the UI means the temporary password cannot quietly drive the API.
    if claims is not None:
        db = SessionLocal()
        try:
            state = session_state(db, claims)
            if state == "revoked":
                audit(db, user=claims.get("sub", ""), role=claims.get("role", ""),
                      action=method, target=path, status=401,
                      detail={"reason": "session revoked"})
                claims = None
            elif (state == "must_change_password"
                    and (method, path) not in _PASSWORD_CHANGE_ALLOW):
                audit(db, user=claims.get("sub", ""), role=claims.get("role", ""),
                      action=method, target=path, status=403,
                      detail={"reason": "password change required"})
                return JSONResponse(
                    {"detail": "You must change your temporary password "
                               "before using the console",
                     "must_change_password": True},
                    status_code=403)
        finally:
            db.close()
        if claims is None:
            return JSONResponse(
                {"detail": "Session is no longer valid — sign in again"},
                status_code=401)

    request.state.claims = claims

    if path.startswith("/snapshots"):
        # Snapshots follow the global read policy: open in the sandbox
        # (AUTH_ENFORCE_READS=false) so Guest browsing and <img> tags work
        # without a session; strictly gated in deployment (default true).
        if settings.auth_enforce_reads and claims is None:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return await call_next(request)

    is_read = method in READ_METHODS

    if path.startswith("/api/edge/ingest") and not is_read:
        if edge_token_ok(request.headers.get("authorization")):
            claims = {"sub": "edge", "role": "operator"}
            request.state.claims = claims
        elif claims is None:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        elif rank(claims.get("role", "")) < rank("operator"):
            db = SessionLocal()
            try:
                audit(db, user=claims.get("sub", ""), role=claims.get("role", ""),
                      action=method, target=path, status=403,
                      detail={"required_role": "operator"})
            finally:
                db.close()
            return JSONResponse({"detail": "Requires operator role or higher"},
                                status_code=403)
        response = await call_next(request)
        db = SessionLocal()
        try:
            audit(db, user=claims.get("sub", ""), role=claims.get("role", ""),
                  action=method, target=path, status=response.status_code)
        finally:
            db.close()
        return response

    if is_read:
        if settings.auth_enforce_reads and claims is None:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        need_read = required_read_role(path)
        if need_read is not None:
            if claims is None:
                return JSONResponse({"detail": "Not authenticated"}, status_code=401)
            if rank(claims.get("role", "")) < rank(need_read):
                return JSONResponse(
                    {"detail": f"Requires {need_read} role or higher"}, status_code=403)
        return await call_next(request)

    need = required_role(path)
    if need is not None:
        if claims is None:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        if rank(claims.get("role", "")) < rank(need):
            db = SessionLocal()
            try:
                audit(db, user=claims.get("sub", ""), role=claims.get("role", ""),
                      action=method, target=path, status=403,
                      detail={"required_role": need})
            finally:
                db.close()
            return JSONResponse(
                {"detail": f"Requires {need} role or higher"}, status_code=403)

    response = await call_next(request)

    db = SessionLocal()
    try:
        audit(db,
              user=(claims or {}).get("sub", ""),
              role=(claims or {}).get("role", ""),
              action=method, target=path, status=response.status_code)
    finally:
        db.close()
    return response

for r in (auth.router, cameras.router, watchlist.router, sightings.router,
          alerts.router, streams.router, copilot.router, vehicles.router,
          vahan.router, vehicle_trace.router, evidence.router, demo.router, fleet.router,
          analytics.router, edge.router, adapters.router,
          integrations.router, reports.router, ops.router, users.router):
    app.include_router(r, prefix="/api")

app.mount("/snapshots", StaticFiles(directory=settings.snapshot_dir), name="snapshots")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "sentinel-backend"}
