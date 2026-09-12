"""Crowd density and anomaly reporting.

Crowd counts come from the same detector pass as the vehicle log, so this is a
read side over rows the workers already wrote. Anomalies are per-camera
departures from that camera's own rolling median, which is why every response
carries the baseline alongside the value: a count means nothing to an operator
without the normal it is being compared against.

Mutations go through the RBAC and audit middleware like every other /api call,
so acknowledging an anomaly is attributable.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Anomaly, Camera, CrowdCount

router = APIRouter(prefix="/crowd", tags=["crowd"])

MAX_LIMIT = 500


def _camera_map(db: Session) -> dict:
    return {c.id: c for c in db.query(Camera).all()}


def _anomaly_row(a: Anomaly, cams: dict) -> dict:
    cam = cams.get(a.camera_id)
    return {
        "id": a.id,
        "camera_id": a.camera_id,
        "camera_name": cam.name if cam else f"camera {a.camera_id}",
        "location": cam.location_name if cam else "",
        "department": cam.department if cam else "",
        "kind": a.kind,
        "severity": a.severity,
        "detail": a.detail,
        "value": a.value,
        "baseline": a.baseline,
        "ts": a.ts,
        "snapshot": a.snapshot,
        "sha256": a.sha256,
        "acknowledged": a.acknowledged,
    }


@router.get("/summary")
def crowd_summary(minutes: int = 60, db: Session = Depends(get_db)):
    """Crowd density over a rolling window: a time series, a per-camera latest
    reading, and the cameras currently furthest above their own normal."""
    minutes = max(1, min(minutes, 60 * 24))
    now = datetime.utcnow()
    since = now - timedelta(minutes=minutes)
    rows = (db.query(CrowdCount)
            .filter(CrowdCount.ts >= since)
            .order_by(CrowdCount.ts).all())
    cams = _camera_map(db)

    n_buckets = 12
    bucket_min = max(1, minutes // n_buckets)
    series = [{"t": since + timedelta(minutes=bucket_min * b),
               "people": 0, "samples": 0} for b in range(n_buckets)]

    latest: dict[int, CrowdCount] = {}
    for r in rows:
        idx = int((r.ts - since).total_seconds() // (bucket_min * 60))
        idx = min(max(idx, 0), n_buckets - 1)
        series[idx]["people"] += r.person_count
        series[idx]["samples"] += 1
        prev = latest.get(r.camera_id)
        if prev is None or r.ts >= prev.ts:
            latest[r.camera_id] = r

    # Mean rather than sum per bucket: cameras report on their own schedule, so
    # a raw sum makes a bucket that happened to catch more samples look busier.
    for b in series:
        b["people"] = round(b["people"] / b["samples"], 1) if b["samples"] else 0

    per_camera = []
    for cid, r in latest.items():
        cam = cams.get(cid)
        over = (r.person_count / r.baseline) if r.baseline > 0 else 0.0
        per_camera.append({
            "camera_id": cid,
            "camera_name": cam.name if cam else f"camera {cid}",
            "location": cam.location_name if cam else "",
            "department": cam.department if cam else "",
            "people": r.person_count,
            "baseline": r.baseline,
            "ratio": round(over, 2),
            "ts": r.ts,
        })
    per_camera.sort(key=lambda c: (-c["ratio"], -c["people"]))

    counts = [r.person_count for r in rows]
    return {
        "window_minutes": minutes,
        "series": series,
        "cameras": per_camera,
        "totals": {
            "samples": len(rows),
            "cameras_reporting": len(latest),
            "people_now": sum(c["people"] for c in per_camera),
            "peak": max(counts) if counts else 0,
            "mean": round(sum(counts) / len(counts), 1) if counts else 0.0,
        },
    }


@router.get("/anomalies")
def list_anomalies(limit: int = 100, kind: str = "", severity: str = "",
                   acknowledged: bool | None = None, camera_id: int | None = None,
                   db: Session = Depends(get_db)):
    """Most recent anomalies first, filterable the way the console filters."""
    limit = max(1, min(limit, MAX_LIMIT))
    q = db.query(Anomaly)
    if kind:
        q = q.filter(Anomaly.kind == kind)
    if severity:
        q = q.filter(Anomaly.severity == severity)
    if acknowledged is not None:
        q = q.filter(Anomaly.acknowledged.is_(acknowledged))
    if camera_id is not None:
        q = q.filter(Anomaly.camera_id == camera_id)
    rows = q.order_by(Anomaly.ts.desc()).limit(limit).all()
    cams = _camera_map(db)
    return {"items": [_anomaly_row(a, cams) for a in rows], "count": len(rows)}


@router.get("/anomalies/summary")
def anomaly_summary(hours: int = 24, db: Session = Depends(get_db)):
    hours = max(1, min(hours, 24 * 30))
    since = datetime.utcnow() - timedelta(hours=hours)
    rows = db.query(Anomaly).filter(Anomaly.ts >= since).all()
    by_kind = Counter(a.kind for a in rows)
    by_severity = Counter(a.severity for a in rows)
    by_camera: dict[int, int] = defaultdict(int)
    for a in rows:
        by_camera[a.camera_id] += 1
    cams = _camera_map(db)
    top = sorted(by_camera.items(), key=lambda kv: -kv[1])[:7]
    return {
        "window_hours": hours,
        "total": len(rows),
        "open": sum(1 for a in rows if not a.acknowledged),
        "by_kind": [{"kind": k, "count": c} for k, c in by_kind.most_common()],
        "by_severity": [{"severity": s, "count": c} for s, c in by_severity.most_common()],
        "top_cameras": [
            {"camera_id": cid,
             "camera_name": cams[cid].name if cid in cams else f"camera {cid}",
             "count": c}
            for cid, c in top
        ],
    }


@router.post("/anomalies/{anomaly_id}/ack")
def acknowledge(anomaly_id: int, db: Session = Depends(get_db)):
    """Acknowledge one anomaly. Retention preserves anything unacknowledged,
    so this is also what lets housekeeping eventually clear it."""
    row = db.get(Anomaly, anomaly_id)
    if row is None:
        raise HTTPException(status_code=404, detail="anomaly not found")
    row.acknowledged = True
    db.commit()
    return {"ok": True, "id": anomaly_id, "acknowledged": True}
