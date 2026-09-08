"""Operational endpoints: readiness and metrics.

`/api/health` answers "is the process up", which a load balancer needs and
nothing else. `/api/health/ready` answers "can this node actually do its job",
which is the question that matters when a district node is quietly failing:
the process is alive, the database is unreachable, and no alert fires because
the liveness probe is green.

`/api/metrics` is Prometheus text format, scraped rather than polled by hand.
Written directly rather than pulling in a client library — the exposition
format is a handful of lines and one fewer dependency is worth more here than
the abstraction.
"""

import shutil
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..anpr import pipeline
from ..anpr.worker import worker_status
from ..config import settings
from ..db import get_db
from ..models import Alert, Camera, Sighting, VehicleDetection

router = APIRouter(tags=["ops"])

_STARTED = time.time()

# Below this, snapshot writes and the database will start failing, so the node
# should be reported degraded before it actually breaks.
DISK_WARN_MB = 500


def _check_database(db: Session) -> dict:
    t0 = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 2)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _check_disk() -> dict:
    try:
        usage = shutil.disk_usage(settings.snapshot_dir)
        free_mb = usage.free / (1024 * 1024)
        return {"ok": free_mb > DISK_WARN_MB, "free_mb": round(free_mb),
                "warn_below_mb": DISK_WARN_MB}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _check_analytics() -> dict:
    workers = worker_status()
    alive = [w for w in workers if w["alive"]]
    failing = [w for w in workers if w.get("last_error")]
    return {
        # No workers running is a valid state, not a failure — an operator may
        # simply not have started any.
        "ok": len(failing) < max(len(workers), 1),
        "models_loaded": pipeline.available(),
        "model_status": pipeline.load_status(),
        "workers_total": len(workers),
        "workers_alive": len(alive),
        "workers_failing": len(failing),
    }


def _check_edge() -> dict:
    from .. import edge
    fw = edge.get_forwarder()
    spool = edge.get_spool()
    if not edge.enabled():
        return {"ok": True, "enabled": False}
    stats = fw.stats() if fw is not None else (spool.stats() if spool else {})
    pending = stats.get("pending", 0)
    return {"ok": True, "enabled": True, "uplink_online": stats.get("online", True),
            "pending": pending, "oldest_age_s": stats.get("oldest_age_s", 0)}


@router.get("/health/ready")
def ready(db: Session = Depends(get_db)):
    """Readiness: every dependency this node needs to do useful work."""
    checks = {
        "database": _check_database(db),
        "disk": _check_disk(),
        "analytics": _check_analytics(),
        "edge": _check_edge(),
    }
    ok = all(c.get("ok") for c in checks.values())
    body = {
        "status": "ready" if ok else "degraded",
        "uptime_s": round(time.time() - _STARTED, 1),
        "checks": checks,
    }
    # 503 so an orchestrator takes this node out of rotation instead of
    # sending it traffic it cannot serve.
    return Response(content=__import__("json").dumps(body, default=str),
                    media_type="application/json",
                    status_code=200 if ok else 503)


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)):
    """Prometheus exposition format."""
    now = datetime.utcnow()
    hour_ago = now - timedelta(hours=1)

    cams = db.query(Camera).all()
    by_status = {"online": 0, "offline": 0, "unknown": 0}
    for c in cams:
        by_status[c.status if c.status in by_status else "unknown"] += 1

    workers = worker_status()
    frames = sum(w.get("frames_processed", 0) for w in workers)

    detections_1h = db.query(VehicleDetection).filter(VehicleDetection.ts >= hour_ago).count()
    plates_1h = db.query(Sighting).filter(Sighting.ts >= hour_ago).count()
    alerts_open = db.query(Alert).filter(Alert.acknowledged.is_(False)).count()

    disk = _check_disk()
    edge_state = _check_edge()

    lines = [
        "# HELP sentinel_uptime_seconds Time since this node started.",
        "# TYPE sentinel_uptime_seconds gauge",
        f"sentinel_uptime_seconds {time.time() - _STARTED:.1f}",

        "# HELP sentinel_cameras Cameras in the registry by connectivity status.",
        "# TYPE sentinel_cameras gauge",
        *(f'sentinel_cameras{{status="{s}"}} {n}' for s, n in by_status.items()),

        "# HELP sentinel_workers Ingestion workers by state.",
        "# TYPE sentinel_workers gauge",
        f'sentinel_workers{{state="alive"}} {sum(1 for w in workers if w["alive"])}',
        f'sentinel_workers{{state="failing"}} {sum(1 for w in workers if w.get("last_error"))}',

        "# HELP sentinel_frames_processed_total Frames decoded and analysed since start.",
        "# TYPE sentinel_frames_processed_total counter",
        f"sentinel_frames_processed_total {frames}",

        "# HELP sentinel_detections_1h Vehicle detections in the last hour.",
        "# TYPE sentinel_detections_1h gauge",
        f"sentinel_detections_1h {detections_1h}",

        "# HELP sentinel_plate_reads_1h Confirmed plate reads in the last hour.",
        "# TYPE sentinel_plate_reads_1h gauge",
        f"sentinel_plate_reads_1h {plates_1h}",

        "# HELP sentinel_alerts_open Watchlist alerts awaiting acknowledgement.",
        "# TYPE sentinel_alerts_open gauge",
        f"sentinel_alerts_open {alerts_open}",

        "# HELP sentinel_disk_free_mb Free space on the snapshot volume.",
        "# TYPE sentinel_disk_free_mb gauge",
        f"sentinel_disk_free_mb {disk.get('free_mb', 0)}",

        "# HELP sentinel_models_loaded Whether the ANPR cascade is loaded.",
        "# TYPE sentinel_models_loaded gauge",
        f"sentinel_models_loaded {1 if pipeline.available() else 0}",

        "# HELP sentinel_edge_spool_pending Events queued on this edge node.",
        "# TYPE sentinel_edge_spool_pending gauge",
        f"sentinel_edge_spool_pending {edge_state.get('pending', 0)}",

        "# HELP sentinel_edge_uplink_online Whether the edge uplink is reachable.",
        "# TYPE sentinel_edge_uplink_online gauge",
        f"sentinel_edge_uplink_online {1 if edge_state.get('uplink_online', True) else 0}",
    ]
    return Response(content="\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
