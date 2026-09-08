"""Analytics aggregation for the infographic dashboard — time-series, vehicle
mix, department comparison, hourly traffic pattern and busiest cameras.

All derived from VehicleDetection over a rolling window; grouping done in Python
to stay portable across SQLite/Postgres."""

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Camera, VehicleDetection
from ..utils.camgraph import haversine

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


@router.get("/gap-analysis")
def gap_analysis(cell_km: float = 2.0, reach_km: float = 1.5,
                 stale_minutes: int = 30, db: Session = Depends(get_db)):
    """Coverage gap report for the registry (Model 1 deliverable).

    Lays a grid over the bounding box of onboarded cameras and marks each cell
    covered if a camera sits within reach_km of its centre. Cells with no
    camera in reach are gaps and are returned so the map can shade them and
    the State can target new camera spend.

    Also reports ageing/unhealthy infrastructure: cameras that are offline, or
    whose last_seen is stale, or that have no stream URL configured.
    """
    cams = db.query(Camera).all()
    located = [c for c in cams if c.latitude and c.longitude]
    if not located:
        return {"cells": [], "summary": {"total_cells": 0, "covered": 0,
                                         "gaps": 0, "coverage_pct": 0.0},
                "unhealthy": [], "by_department": []}

    lats = [c.latitude for c in located]
    lngs = [c.longitude for c in located]
    pad = cell_km / 111.0
    lat0, lat1 = min(lats) - pad, max(lats) + pad
    lng0, lng1 = min(lngs) - pad, max(lngs) + pad

    step_lat = cell_km / 111.0
    mid_lat = (lat0 + lat1) / 2
    step_lng = cell_km / max(111.0 * math.cos(math.radians(mid_lat)), 1e-6)

    cells = []
    covered = 0
    lat = lat0
    while lat < lat1 and len(cells) < 4000:
        lng = lng0
        while lng < lng1 and len(cells) < 4000:
            clat, clng = lat + step_lat / 2, lng + step_lng / 2
            near = min((haversine(clat, clng, c.latitude, c.longitude) / 1000.0
                        for c in located), default=1e9)
            is_covered = near <= reach_km
            covered += is_covered
            cells.append({
                "lat": round(clat, 6), "lng": round(clng, 6),
                "lat_step": round(step_lat, 6), "lng_step": round(step_lng, 6),
                "covered": is_covered, "nearest_km": round(near, 2),
            })
            lng += step_lng
        lat += step_lat

    stale_before = datetime.utcnow() - timedelta(minutes=stale_minutes)
    unhealthy = []
    for c in cams:
        problems = []
        if c.status == "offline":
            problems.append("offline")
        if not (c.rtsp_url or c.hls_url):
            problems.append("no stream URL")
        if c.last_seen is None:
            problems.append("never seen")
        elif c.last_seen < stale_before:
            problems.append(f"stale since {c.last_seen:%H:%M}")
        if not (c.latitude and c.longitude):
            problems.append("no coordinates")
        if problems:
            unhealthy.append({"id": c.id, "name": c.name, "department": c.department,
                              "status": c.status, "problems": problems})

    dept = defaultdict(lambda: {"total": 0, "online": 0})
    for c in cams:
        dept[c.department]["total"] += 1
        dept[c.department]["online"] += c.status == "online"

    n = len(cells)
    return {
        "params": {"cell_km": cell_km, "reach_km": reach_km},
        "cells": cells,
        "summary": {
            "total_cells": n, "covered": covered, "gaps": n - covered,
            "coverage_pct": round(100 * covered / n, 1) if n else 0.0,
            "cameras_located": len(located), "cameras_total": len(cams),
        },
        "unhealthy": sorted(unhealthy, key=lambda u: -len(u["problems"]))[:50],
        "by_department": [{"department": d, **v} for d, v in
                          sorted(dept.items(), key=lambda x: -x[1]["total"])],
    }
