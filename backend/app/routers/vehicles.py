from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Camera, VehicleDetection
from ..utils.geo import project

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("")
def list_vehicles(camera_id: int | None = None, vehicle_type: str | None = None,
                  with_plate: bool | None = None, minutes: int | None = None,
                  limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(VehicleDetection)
    if camera_id:
        q = q.filter(VehicleDetection.camera_id == camera_id)
    if vehicle_type:
        q = q.filter(VehicleDetection.vehicle_type == vehicle_type)
    if with_plate is True:
        q = q.filter(VehicleDetection.plate != "")
    elif with_plate is False:
        q = q.filter(VehicleDetection.plate == "")
    if minutes:
        q = q.filter(VehicleDetection.ts >= datetime.utcnow() - timedelta(minutes=minutes))
    rows = q.order_by(VehicleDetection.ts.desc()).limit(min(limit, 500)).all()
    cams = {c.id: c for c in db.query(Camera).all()}
    return [
        {"id": v.id, "camera_id": v.camera_id,
         "camera_name": cams[v.camera_id].name if v.camera_id in cams else "?",
         "location": cams[v.camera_id].location_name if v.camera_id in cams else "",
         "vehicle_type": v.vehicle_type, "plate": v.plate,
         "plate_confidence": round(v.plate_confidence, 2),
         "ts": v.ts, "snapshot": v.snapshot}
        for v in rows
    ]


@router.get("/geo")
def vehicles_geo(seconds: int = 20, limit: int = 400, db: Session = Depends(get_db)):
    """Recent vehicle detections projected to geo-coordinates, for the live 3D
    map. Short window by default so the map shows 'what's on the roads now'."""
    since = datetime.utcnow() - timedelta(seconds=seconds)
    rows = (db.query(VehicleDetection).filter(VehicleDetection.ts >= since)
            .order_by(VehicleDetection.ts.desc()).limit(min(limit, 1000)).all())
    cams = {c.id: c for c in db.query(Camera).all()}
    out = []
    for v in rows:
        cam = cams.get(v.camera_id)
        if cam is None:
            continue
        lat, lon = project(cam.latitude, cam.longitude, cam.heading, cam.fov_deg,
                           cam.range_m, v.img_x, v.img_y)
        out.append({"id": v.id, "lat": lat, "lon": lon, "type": v.vehicle_type,
                    "plate": v.plate, "camera_id": v.camera_id,
                    "camera": cam.name, "ts": v.ts, "snapshot": v.snapshot})
    return out


@router.get("/stats")
def vehicle_stats(minutes: int = 60, db: Session = Depends(get_db)):
    since = datetime.utcnow() - timedelta(minutes=minutes)
    base = db.query(VehicleDetection).filter(VehicleDetection.ts >= since)
    total = base.count()
    with_plate = base.filter(VehicleDetection.plate != "").count()
    by_type = dict(
        db.query(VehicleDetection.vehicle_type, func.count(VehicleDetection.id))
        .filter(VehicleDetection.ts >= since)
        .group_by(VehicleDetection.vehicle_type).all()
    )
    return {"window_minutes": minutes, "total": total, "with_plate": with_plate,
            "by_type": by_type}
