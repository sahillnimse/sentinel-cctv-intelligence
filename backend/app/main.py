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
from .models import Base, Camera
from .db import SessionLocal
from .routers import (adapters, alerts, analytics, auth, cameras, copilot, demo,
                      edge, evidence, fleet, integrations, sightings, streams,
                      vahan, vehicles, watchlist)

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
    """Drop detections and sightings older than `cutoff`, and the alerts that
    reference them.

    Alerts must go first. An alert carries sighting_id, and its evidence is the
    sighting's snapshot; deleting the sighting alone leaves an alert pointing at
    a row that no longer exists, which the alerts view then renders with no
    evidence behind it. Anything an operator has not acknowledged is kept
    regardless of age — an outstanding alert is not housekeeping.
    """
    from .models import Alert, Sighting, VehicleDetection

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
    db.commit()
    return {"alerts": alerts, "sightings": sightings, "detections": detections}


def _autostart_workers():
    """Bring the grid live on boot — no manual 'start analytics'. Workers are
    staggered on a background thread so 30 HEVC decoders don't spin up at once
    and spike memory (that OOM-crashed an early build). AUTOSTART_MAX_CAMERAS
    caps how many come up on constrained machines."""
    import threading
    import time

    db = SessionLocal()
    try:
        cams = db.query(Camera).filter(Camera.rtsp_url != "").order_by(Camera.id).all()
        ids = [c.id for c in cams][: settings.autostart_max_cameras]
    finally:
        db.close()

    def stagger():
        for cid in ids:
            start_worker(cid)
            time.sleep(settings.autostart_stagger_ms / 1000.0)
        log.info("auto-started analytics on %d cameras", len(ids))

    threading.Thread(target=stagger, name="autostart", daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    _migrate()
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


@app.middleware("http")
async def rbac_and_audit(request, call_next):
    """One gate for every /api call.

    Mutations need a token whose role meets the path's requirement. Reads are
    open unless auth_enforce_reads is set. Every mutation is written to the
    audit trail with the caller, the outcome and the path.
    """
    from fastapi.responses import JSONResponse

    from .security import (audit, claims_from_header, rank, required_read_role,
                           required_role)

    path = request.url.path
    method = request.method

    if not path.startswith("/api") or path.startswith("/api/auth/login"):
        return await call_next(request)

    claims = claims_from_header(request.headers.get("authorization"))
    is_read = method in READ_METHODS

    if is_read:
        if settings.auth_enforce_reads and claims is None:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        # Some reads are sensitive regardless of the global read setting.
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
          vahan.router, evidence.router, demo.router, fleet.router,
          analytics.router, edge.router, adapters.router,
          integrations.router):
    app.include_router(r, prefix="/api")

app.mount("/snapshots", StaticFiles(directory=settings.snapshot_dir), name="snapshots")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "sentinel-backend"}
