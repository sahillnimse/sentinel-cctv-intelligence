"""Deterministic HERO demo seeder.

Guarantees a crisp, repeatable "trace a stolen vehicle across the grid" demo:
seeds a clean multi-camera path for a single hero plate with fixed, evenly
spaced timestamps (NEVER datetime.now(), so the trace looks identical every
run), makes sure the plate is on the watchlist, and fires an alert so the
dashboard lights up live.

Router prefix "/demo" (served at /api/demo/... once registered in main.py).
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from .. import ws
from ..db import SessionLocal
from ..models import (Alert, Camera, Sighting, VehicleDetection,
                      WatchlistEntry)
from ..utils.camgraph import haversine
from ..utils.plates import normalize

router = APIRouter(prefix="/demo", tags=["demo"])

# Fixed fallback used only when no base_ts is given and the DB has no sightings.
# Deliberately a constant (not now()) so the demo is byte-for-byte reproducible.
FALLBACK_TS = datetime(2026, 9, 7, 10, 0, 0)
CITY_SPEED_KMPH = 35.0     # assumed travel speed for realistic hop spacing
MIN_STEP_SECONDS = 90      # minimum dwell between cameras
DEFAULT_PLATE = "GJ01AB1234"


def _coherent_path(cameras, count):
    """Pick a geographically coherent path: start at the first camera, then
    greedily hop to the nearest not-yet-visited camera. Keeps the hero route in
    one locality so it reads as a genuine journey (no impossible-hop flags)."""
    pool = list(cameras)
    if not pool:
        return []
    path = [pool.pop(0)]
    while pool and len(path) < count:
        last = path[-1]
        pool.sort(key=lambda c: haversine(last.latitude, last.longitude,
                                          c.latitude, c.longitude))
        path.append(pool.pop(0))
    return path


def _parse_ts(raw: str | None):
    if not raw:
        return None
    try:
        # tolerate a trailing 'Z'
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None


def _existing_snapshot(db, camera_id: int) -> str:
    """Reuse a real snapshot filename for this camera if one exists, so the
    evidence panel shows an actual image instead of a broken thumbnail."""
    s = (db.query(Sighting)
         .filter(Sighting.camera_id == camera_id, Sighting.snapshot != "")
         .order_by(Sighting.id.desc()).first())
    if s and s.snapshot:
        return s.snapshot
    v = (db.query(VehicleDetection)
         .filter(VehicleDetection.camera_id == camera_id,
                 VehicleDetection.snapshot != "")
         .order_by(VehicleDetection.id.desc()).first())
    if v and v.snapshot:
        return v.snapshot
    return ""


@router.post("/seed")
def seed(plate: str = Query(DEFAULT_PLATE),
         count: int = Query(6, ge=1, le=50),
         base_ts: str | None = Query(None)):
    """Seed a deterministic hero path for `plate` across up to `count` cameras."""
    hero = normalize(plate) or DEFAULT_PLATE
    db = SessionLocal()
    try:
        # Pick real cameras with a stream; build a geographically coherent path
        # so the hero route is a plausible single-locality journey.
        pool = db.query(Camera).filter(Camera.rtsp_url != "").order_by(Camera.id).all()
        if not pool:
            pool = db.query(Camera).order_by(Camera.id).all()
        if not pool:
            return {"plate": hero, "cameras": [], "sightings_created": 0,
                    "alert_id": None, "detail": "no cameras in database"}
        cameras = _coherent_path(pool, count)

        # Resolve the base timestamp deterministically (never now()).
        base = _parse_ts(base_ts)
        if base is None:
            latest = db.query(Sighting.ts).order_by(Sighting.ts.desc()).first()
            base = latest[0] if latest and latest[0] else FALLBACK_TS

        # Ensure the hero plate is on the watchlist (create if missing).
        entry = (db.query(WatchlistEntry)
                 .filter(WatchlistEntry.plate == hero).first())
        if entry is None:
            entry = WatchlistEntry(
                plate=hero, label="Hero demo - stolen vehicle",
                reason="stolen", active=True, created_at=base,
            )
            db.add(entry)
            db.flush()
        elif not entry.active:
            entry.active = True

        out_cams: list[dict] = []
        last_sighting: Sighting | None = None
        last_cam: Camera | None = None

        elapsed = 0.0  # seconds from base, accumulated by realistic travel time
        prev = None
        for i, cam in enumerate(cameras):
            if prev is not None:
                dist_km = haversine(prev.latitude, prev.longitude,
                                    cam.latitude, cam.longitude) / 1000.0
                travel_s = (dist_km / CITY_SPEED_KMPH) * 3600.0
                elapsed += max(MIN_STEP_SECONDS, travel_s)
            prev = cam
            ts = base + timedelta(seconds=elapsed)
            conf = min(0.88 + 0.01 * i, 0.97)
            snap = _existing_snapshot(db, cam.id)

            sighting = Sighting(
                camera_id=cam.id, plate=hero, plate_raw=hero,
                confidence=conf, ts=ts, pts_ms=0.0, snapshot=snap,
            )
            db.add(sighting)

            db.add(VehicleDetection(
                camera_id=cam.id, vehicle_type="car", plate=hero,
                plate_confidence=conf, ts=ts, snapshot=snap,
                img_x=0.5, img_y=0.9,
            ))
            db.flush()

            last_sighting = sighting
            last_cam = cam
            out_cams.append({"id": cam.id, "name": cam.name, "ts": ts})

        # Alert on the final sighting so the dashboard lights up live.
        alert = Alert(
            sighting_id=last_sighting.id, watchlist_id=entry.id,
            camera_id=last_cam.id, plate=hero, ts=last_sighting.ts,
        )
        db.add(alert)
        db.flush()

        db.commit()

        ws.broadcast({
            "type": "alert", "alert_id": alert.id, "plate": hero,
            "watchlist_plate": entry.plate, "label": entry.label,
            "reason": entry.reason, "camera_id": last_cam.id,
            "camera_name": last_cam.name, "location": last_cam.location_name,
            "ts": last_sighting.ts, "snapshot": last_sighting.snapshot,
            "confidence": last_sighting.confidence,
        })

        return {
            "plate": hero,
            "cameras": out_cams,
            "sightings_created": len(out_cams),
            "alert_id": alert.id,
        }
    finally:
        db.close()


@router.post("/simulate/start")
def simulate_start():
    from .. import sim
    started = sim.start()
    return {"running": sim.running(), "started": started}


@router.post("/simulate/stop")
def simulate_stop():
    from .. import sim
    sim.stop()
    return {"running": False}


@router.get("/simulate/status")
def simulate_status():
    from .. import sim
    return {"running": sim.running()}


@router.post("/clear")
def clear(plate: str = Query(DEFAULT_PLATE)):
    """Delete everything seeded for `plate` (FK-safe order): Alerts, then
    VehicleDetections and Sightings, then the WatchlistEntry."""
    hero = normalize(plate) or DEFAULT_PLATE
    db = SessionLocal()
    try:
        alerts = db.query(Alert).filter(Alert.plate == hero).delete(
            synchronize_session=False)
        vehicles = db.query(VehicleDetection).filter(
            VehicleDetection.plate == hero).delete(synchronize_session=False)
        sightings = db.query(Sighting).filter(
            Sighting.plate == hero).delete(synchronize_session=False)
        watchlist = db.query(WatchlistEntry).filter(
            WatchlistEntry.plate == hero).delete(synchronize_session=False)
        db.commit()
        return {
            "plate": hero,
            "alerts_deleted": alerts,
            "vehicle_detections_deleted": vehicles,
            "sightings_deleted": sightings,
            "watchlist_deleted": watchlist,
        }
    finally:
        db.close()
