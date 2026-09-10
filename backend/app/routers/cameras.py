import csv
import io
import json
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Camera
from ..schemas import CameraIn, CameraOut
from ..security import claims_from_request, rank
from ..utils import redact_url

router = APIRouter(prefix="/cameras", tags=["cameras"])


def _is_admin(request: Request) -> bool:
    claims = claims_from_request(request)
    return claims is not None and rank(claims.get("role", "")) >= rank("admin")


@router.get("", response_model=list[CameraOut])
def list_cameras(request: Request, department: str | None = None, status: str | None = None,
                 db: Session = Depends(get_db)):
    q = db.query(Camera)
    if department:
        q = q.filter(Camera.department == department)
    if status:
        q = q.filter(Camera.status == status)
    rows = q.order_by(Camera.id).all()
    if _is_admin(request):
        return rows
    # Non-admin readers get credential-redacted URLs. Build fresh CameraOut
    # copies rather than mutating the ORM rows, so a later commit in this
    # session can never persist the "***@" marker over the real credentials
    # the workers need to connect.
    out = []
    for c in rows:
        payload = CameraOut.model_validate(c)
        if payload.rtsp_url:
            payload = payload.model_copy(update={"rtsp_url": redact_url(payload.rtsp_url)})
        out.append(payload)
    return out


@router.post("", response_model=CameraOut)
def create_camera(body: CameraIn, db: Session = Depends(get_db)):
    cam = Camera(**body.model_dump())
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return cam


@router.put("/{camera_id}", response_model=CameraOut)
def update_camera(camera_id: int, body: CameraIn, db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(404, "Camera not found")
    for k, v in body.model_dump().items():
        # A non-admin client only ever saw "***@" in place of credentials, and
        # may round-trip a GET body back into PUT. Never let the redaction
        # marker overwrite the stored secret the workers connect with.
        if k == "rtsp_url" and isinstance(v, str) and "***@" in v:
            continue
        setattr(cam, k, v)
    db.commit()
    db.refresh(cam)
    return cam


@router.delete("/{camera_id}")
def delete_camera(camera_id: int, db: Session = Depends(get_db)):
    from ..models import Alert, Sighting, VehicleDetection
    cam = db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(404, "Camera not found")
    # Manual cascade: no ON DELETE CASCADE in models, so orphan rows would
    # otherwise leave alerts pointing at missing sightings.
    sight_ids = [r[0] for r in db.query(Sighting.id).filter(Sighting.camera_id == camera_id).all()]
    if sight_ids:
        db.query(Alert).filter(Alert.sighting_id.in_(sight_ids)).delete(synchronize_session=False)
        db.query(Sighting).filter(Sighting.id.in_(sight_ids)).delete(synchronize_session=False)
    db.query(VehicleDetection).filter(VehicleDetection.camera_id == camera_id).delete(synchronize_session=False)
    db.query(Alert).filter(Alert.camera_id == camera_id).delete(synchronize_session=False)
    db.delete(cam)
    db.commit()
    return {"deleted": camera_id}


@router.post("/import")
async def bulk_import(file: UploadFile, db: Session = Depends(get_db)):
    """Bulk onboarding from CSV.

    Columns: name, department, camera_type, rtsp_url, latitude, longitude, location_name
    (header row required; extra columns ignored). See seed_data/cameras_sample.csv.
    """
    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    created, errors = 0, []
    for i, row in enumerate(reader, start=2):
        try:
            cam = Camera(
                name=row["name"].strip(),
                department=row.get("department", "Police").strip() or "Police",
                camera_type=row.get("camera_type", "IP").strip() or "IP",
                rtsp_url=row.get("rtsp_url", "").strip(),
                latitude=float(row.get("latitude") or 23.2156),
                longitude=float(row.get("longitude") or 72.6369),
                location_name=row.get("location_name", "").strip(),
            )
            db.add(cam)
            created += 1
        except (KeyError, ValueError) as exc:
            errors.append({"line": i, "error": str(exc)})
    db.commit()
    return {"created": created, "errors": errors}


@router.get("/departments")
def departments(db: Session = Depends(get_db)):
    rows = db.query(Camera.department).distinct().all()
    return sorted({r[0] for r in rows})


@router.get("/coverage")
def coverage(db: Session = Depends(get_db)):
    """FOV wedges for every camera as GeoJSON — the 'territory' each camera
    watches, drawn on the 3D map."""
    from ..utils.geo import fov_polygon
    feats = []
    for c in db.query(Camera).all():
        feats.append({
            "type": "Feature",
            "properties": {"id": c.id, "name": c.name, "status": c.status,
                           "department": c.department},
            "geometry": {"type": "Polygon",
                         "coordinates": [fov_polygon(c.latitude, c.longitude,
                                                     c.heading, c.fov_deg, c.range_m)]},
        })
    return {"type": "FeatureCollection", "features": feats}


@router.post("/sync-grid")
def sync_grid(db: Session = Depends(get_db)):
    """Onboard the Sentinel camera grid.

    Reads the live catalogue (cameras.json) when reachable; the catalogue sits
    behind the grid access password, so without a session cookie configured we
    fall back to the documented id range cam01..cam30. RTSP itself needs no auth.
    """
    items, source = [], "catalogue"
    try:
        req = urllib.request.Request(settings.grid_catalog_url,
                                     headers={"User-Agent": "sentinel-platform/0.1"})
        if settings.grid_access_cookie:
            req.add_header("Cookie", settings.grid_access_cookie)
        with urllib.request.urlopen(req, timeout=10) as resp:
            if "json" not in (resp.headers.get("Content-Type") or ""):
                raise ValueError("catalogue returned non-JSON (login page?)")
            data = json.load(resp)
        raw = data.get("cameras", data) if isinstance(data, dict) else data
        for it in raw:
            if isinstance(it, str):
                items.append({"id": it})
            elif isinstance(it, dict) and it.get("id"):
                items.append(it)
    except Exception as exc:
        source = f"fallback cam01..cam30 ({exc})"
        items = [{"id": f"cam{i:02d}"} for i in range(1, 31)]

    created = updated = 0
    from ..adapters.sentinel_grid import grid_hls_url, grid_rtsp_url
    for idx, it in enumerate(items):
        cid = str(it["id"])
        rtsp = grid_rtsp_url(cid)
        hls = grid_hls_url(cid)
        cam = db.query(Camera).filter(Camera.external_id == cid).first()
        if cam is None:
            # Spread unknown positions around Ahmedabad so the GIS map is usable;
            # replace with real coordinates when the catalogue provides them.
            lat = float(it.get("latitude") or 23.0225 + 0.012 * (idx % 6) - 0.03)
            lon = float(it.get("longitude") or 72.5714 + 0.012 * (idx // 6) - 0.03)
            cam = Camera(
                external_id=cid,
                name=it.get("name") or f"Grid {cid.upper()}",
                department=it.get("department") or "Police",
                camera_type=it.get("type") or "IP",
                rtsp_url=rtsp, hls_url=hls,
                latitude=lat, longitude=lon,
                location_name=it.get("location") or "Sentinel grid",
                heading=float(it.get("heading") or (idx * 47) % 360),  # spread cones
            )
            db.add(cam)
            created += 1
        else:
            cam.rtsp_url, cam.hls_url = rtsp, hls
            updated += 1
    db.commit()
    return {"source": source, "created": created, "updated": updated,
            "whep_base": settings.grid_whep_base}
