from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Camera, VehicleDetection

router = APIRouter(prefix="/fleet", tags=["fleet"])


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


@router.get("/health")
def fleet_health(db: Session = Depends(get_db)):
    """Network Operations Center fleet-health aggregation: overall + per-department
    camera status, recent analytics yield, and worst/busiest camera lists."""
    now = datetime.utcnow()
    since_60 = now - timedelta(minutes=60)
    since_30 = now - timedelta(minutes=30)

    cams = db.query(Camera).all()

    # ---- overall camera status ----
    total = len(cams)
    online = sum(1 for c in cams if c.status == "online")
    offline = sum(1 for c in cams if c.status == "offline")
    unknown = total - online - offline
    overall = {
        "total_cameras": total,
        "online": online,
        "offline": offline,
        "unknown": unknown,
        "online_pct": _pct(online, total),
    }

    # ---- by department ----
    dept_stats: dict[str, dict] = {}
    for c in cams:
        dept = c.department or "Unassigned"
        d = dept_stats.setdefault(dept, {"department": dept, "total": 0, "online": 0})
        d["total"] += 1
        if c.status == "online":
            d["online"] += 1
    by_department = []
    for d in sorted(dept_stats.values(), key=lambda x: x["department"]):
        by_department.append({
            "department": d["department"],
            "total": d["total"],
            "online": d["online"],
            "online_pct": _pct(d["online"], d["total"]),
        })

    # ---- analytics yield (last 60 min) per department + overall ----
    cam_dept = {c.id: (c.department or "Unassigned") for c in cams}
    # vehicles per camera
    veh_rows = (
        db.query(VehicleDetection.camera_id, func.count(VehicleDetection.id))
        .filter(VehicleDetection.ts >= since_60)
        .group_by(VehicleDetection.camera_id).all()
    )
    plate_rows = (
        db.query(VehicleDetection.camera_id, func.count(VehicleDetection.id))
        .filter(VehicleDetection.ts >= since_60, VehicleDetection.plate != "")
        .group_by(VehicleDetection.camera_id).all()
    )
    yield_by_dept: dict[str, dict] = {}
    for dept in set(cam_dept.values()):
        yield_by_dept[dept] = {"department": dept, "vehicles": 0, "plates": 0}
    total_veh = 0
    total_plates = 0
    for cam_id, cnt in veh_rows:
        dept = cam_dept.get(cam_id, "Unassigned")
        yield_by_dept.setdefault(dept, {"department": dept, "vehicles": 0, "plates": 0})
        yield_by_dept[dept]["vehicles"] += cnt
        total_veh += cnt
    for cam_id, cnt in plate_rows:
        dept = cam_dept.get(cam_id, "Unassigned")
        yield_by_dept.setdefault(dept, {"department": dept, "vehicles": 0, "plates": 0})
        yield_by_dept[dept]["plates"] += cnt
        total_plates += cnt

    analytics_yield_depts = []
    for d in sorted(yield_by_dept.values(), key=lambda x: x["department"]):
        analytics_yield_depts.append({
            "department": d["department"],
            "vehicles": d["vehicles"],
            "plates": d["plates"],
            "plate_yield_pct": _pct(d["plates"], d["vehicles"]),
        })
    analytics_yield = {
        "window_minutes": 60,
        "overall": {
            "department": "ALL",
            "vehicles": total_veh,
            "plates": total_plates,
            "plate_yield_pct": _pct(total_plates, total_veh),
        },
        "by_department": analytics_yield_depts,
    }

    # ---- per-camera vehicle counts (30m and 60m) ----
    veh_30 = dict(
        db.query(VehicleDetection.camera_id, func.count(VehicleDetection.id))
        .filter(VehicleDetection.ts >= since_30)
        .group_by(VehicleDetection.camera_id).all()
    )
    veh_60 = dict(veh_rows)

    # ---- worst cameras: offline OR (online but 0 vehicles in last 30 min) ----
    worst = []
    for c in cams:
        v30 = veh_30.get(c.id, 0)
        is_bad = c.status == "offline" or (c.status == "online" and v30 == 0)
        if is_bad:
            worst.append({
                "id": c.id,
                "name": c.name,
                "department": c.department or "Unassigned",
                "status": c.status,
                "last_seen": c.last_seen,
                "vehicles_30m": v30,
            })
    # offline first, then online-but-idle; stable-ish ordering by name
    worst.sort(key=lambda x: (x["status"] != "offline", x["name"]))
    worst_cameras = worst[:8]

    # ---- busiest cameras: top 6 by vehicles in last 60 min ----
    cam_by_id = {c.id: c for c in cams}
    busiest_sorted = sorted(veh_60.items(), key=lambda kv: kv[1], reverse=True)
    busiest_cameras = []
    for cam_id, cnt in busiest_sorted[:6]:
        c = cam_by_id.get(cam_id)
        if c is None:
            continue
        busiest_cameras.append({
            "id": c.id,
            "name": c.name,
            "department": c.department or "Unassigned",
            "vehicles": cnt,
        })

    return {
        "generated_at": now,
        "overall": overall,
        "by_department": by_department,
        "analytics_yield": analytics_yield,
        "worst_cameras": worst_cameras,
        "busiest_cameras": busiest_cameras,
    }
