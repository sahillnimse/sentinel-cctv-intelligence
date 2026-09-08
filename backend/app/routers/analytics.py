"""Analytics aggregation for the infographic dashboard — time-series, vehicle
mix, department comparison, hourly traffic pattern and busiest cameras.

All derived from VehicleDetection over a rolling window; grouping done in Python
to stay portable across SQLite/Postgres."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Camera, VehicleDetection

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
def summary(minutes: int = 60, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    since = now - timedelta(minutes=minutes)
    rows = (db.query(VehicleDetection)
            .filter(VehicleDetection.ts >= since).all())
    cams = {c.id: c for c in db.query(Camera).all()}

    # --- time series: ~12 buckets across the window ---
    n_buckets = 12
    bucket_min = max(1, minutes // n_buckets)
    buckets = []
    for b in range(n_buckets):
        start = since + timedelta(minutes=bucket_min * b)
        buckets.append({"t": start, "vehicles": 0, "plates": 0})

    def bucket_index(ts):
        idx = int((ts - since).total_seconds() // (bucket_min * 60))
        return min(max(idx, 0), n_buckets - 1)

    by_type = Counter()
    by_dept = Counter()
    by_hour = Counter()
    by_cam = Counter()
    plates_total = 0
    for v in rows:
        bi = bucket_index(v.ts)
        buckets[bi]["vehicles"] += 1
        by_type[v.vehicle_type or "vehicle"] += 1
        cam = cams.get(v.camera_id)
        dept = cam.department if cam else "Unknown"
        by_dept[dept] += 1
        by_cam[cam.name if cam else f"cam{v.camera_id}"] += 1
        by_hour[v.ts.hour] += 1
        if v.plate:
            buckets[bi]["plates"] += 1
            plates_total += 1

    series = [{"t": b["t"].strftime("%H:%M"), "vehicles": b["vehicles"],
               "plates": b["plates"]} for b in buckets]

    online = sum(1 for c in cams.values() if c.status == "online")
    total = len(rows)
    return {
        "window_minutes": minutes,
        "totals": {
            "vehicles": total, "plates": plates_total,
            "plate_yield_pct": round(100 * plates_total / total, 1) if total else 0.0,
            "cameras_online": online, "cameras_total": len(cams),
        },
        "series": series,
        "by_type": [{"type": t, "count": c} for t, c in
                    sorted(by_type.items(), key=lambda x: -x[1])],
        "by_department": [{"department": d, "vehicles": c} for d, c in
                          sorted(by_dept.items(), key=lambda x: -x[1])],
        "by_hour": [{"hour": h, "count": by_hour.get(h, 0)} for h in range(24)],
        "top_cameras": [{"name": n, "vehicles": c} for n, c in by_cam.most_common(7)],
    }
