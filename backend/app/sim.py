"""Sandbox simulation mode.

When the live camera grid is unreachable (e.g. no on-site network, or the demo
feeds are offline), this generates a continuous stream of realistic vehicle
detections so the whole platform — map blips, live feed, analytics, NOC, trace —
stays alive and demonstrable. It is clearly a SIMULATION, not real data; the UI
labels the feeds accordingly.

Starting the simulator stops the (useless, grid-down) camera workers so they
don't fight it over camera status.
"""

import logging
import random
import threading
from collections import defaultdict
from datetime import datetime, timedelta

from . import ws
from .config import settings
from .db import SessionLocal
from .models import Camera, Sighting, VehicleDetection, WatchlistEntry
from .utils.plates import normalize, plates_match


def _index_crops() -> dict:
    """Map camera id -> list of real cached vehicle-crop filenames, so every
    simulated detection can carry an actual frame from that camera (the
    detection is then visually credited + linked to its footage)."""
    by_cam = defaultdict(list)
    try:
        for p in settings.snapshot_dir.glob("veh_cam*.jpg"):
            try:
                cid = int(p.stem.split("_")[1].replace("cam", ""))
                by_cam[cid].append(p.name)
            except (IndexError, ValueError):
                continue
    except OSError:
        pass
    return by_cam

log = logging.getLogger("sentinel.sim")

_thread: threading.Thread | None = None
_stop = threading.Event()

_TYPES = ["car"] * 60 + ["motorcycle"] * 25 + ["truck"] * 10 + ["bus"] * 5
_STATES = ["GJ01", "GJ05", "GJ18", "GJ06", "GJ03", "GJ27", "GJ21", "MH12"]
_LETTERS = "ABCDEFGHJKLMNPQR"
TICK_SECONDS = 2.5
PRUNE_AFTER_MIN = 75  # bound the DB — drop sim detections older than this


def running() -> bool:
    return _thread is not None and _thread.is_alive()


def _plate(rng: random.Random) -> str:
    return (f"{rng.choice(_STATES)}{rng.choice(_LETTERS)}{rng.choice(_LETTERS)}"
            f"{rng.randint(1000, 9999)}")


def start() -> bool:
    global _thread
    if running():
        return False
    from .anpr.worker import stop_all
    stop_all()  # release grid-down workers so they don't overwrite camera status
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="demo-sim")
    _thread.start()
    log.info("sandbox simulation started")
    return True


def stop() -> None:
    _stop.set()
    log.info("sandbox simulation stopping")


def _loop() -> None:
    rng = random.Random(7)
    db = SessionLocal()
    try:
        # bring the fleet online for the sandbox
        for c in db.query(Camera).all():
            c.status = "online"
            c.last_seen = datetime.utcnow()
        db.commit()

        watch = [w for w in db.query(WatchlistEntry).filter(
            WatchlistEntry.active.is_(True), WatchlistEntry.kind != "person").all()]
        crops = _index_crops()  # real cached frames per camera for evidence thumbnails
        log.info("sim: indexed crops for %d cameras", len(crops))
        tick = 0
        while not _stop.is_set():
            now = datetime.utcnow()
            cams = db.query(Camera).all()
            if cams:
                for _ in range(rng.randint(3, 7)):
                    c = rng.choice(cams)
                    c.last_seen = now
                    if c.status != "online":
                        c.status = "online"
                    vt = rng.choice(_TYPES)
                    has_plate = rng.random() < 0.33
                    pl = normalize(_plate(rng)) if has_plate else ""
                    snap = rng.choice(crops[c.id]) if crops.get(c.id) else ""
                    db.add(VehicleDetection(
                        camera_id=c.id, vehicle_type=vt, plate=pl,
                        plate_confidence=round(rng.uniform(0.6, 0.95), 2) if has_plate else 0.0,
                        ts=now, snapshot=snap,
                        img_x=round(rng.uniform(0.15, 0.85), 3),
                        img_y=round(rng.uniform(0.6, 0.95), 3)))
                    if has_plate:
                        s = Sighting(camera_id=c.id, plate=pl, plate_raw=pl,
                                     confidence=round(rng.uniform(0.7, 0.95), 2),
                                     ts=now, pts_ms=0.0, snapshot=snap)
                        db.add(s)
                        ev = {"type": "sighting", "camera_id": c.id,
                              "camera_name": c.name, "plate": pl,
                              "confidence": s.confidence, "ts": now, "snapshot": snap}
                        # occasional watchlist hit -> alert event for the live feed
                        for w in watch:
                            if plates_match(pl, w.plate):
                                ev = {"type": "alert", "camera_id": c.id,
                                      "camera_name": c.name, "plate": pl,
                                      "reason": w.reason, "label": w.label,
                                      "location": c.location_name, "ts": now,
                                      "snapshot": snap, "confidence": s.confidence}
                                break
                        ws.broadcast(ev)
                db.commit()

            tick += 1
            if tick % 40 == 0:  # prune old sim rows to keep the DB bounded
                cutoff = now - timedelta(minutes=PRUNE_AFTER_MIN)
                db.query(VehicleDetection).filter(
                    VehicleDetection.ts < cutoff).delete(synchronize_session=False)
                db.query(Sighting).filter(
                    Sighting.ts < cutoff, Sighting.pts_ms == 0.0).delete(synchronize_session=False)
                db.commit()
            _stop.wait(TICK_SECONDS)
    except Exception:
        log.exception("sim loop crashed")
    finally:
        db.close()
