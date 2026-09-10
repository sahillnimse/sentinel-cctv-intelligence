"""Federation layer API.

List what systems this platform can talk to, discover cameras from any of
them, and onboard the results into the registry. The console's Federation page
drives all three.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import adapters
from ..db import get_db
from ..models import Camera
from ..security import claims_from_request, rank
from ..utils import redact_url

log = logging.getLogger("sentinel.routers.adapters")

router = APIRouter(prefix="/adapters", tags=["federation"])


@router.get("")
def list_adapters():
    return adapters.describe()


@router.get("/{key}/discover")
def discover(key: str, request: Request, probe: bool = False):
    adapter = adapters.get(key)
    if adapter is None:
        raise HTTPException(404, f"No adapter '{key}'")
    try:
        found = adapter.discover()
    except Exception as exc:
        log.exception("discovery failed for %s", key)
        raise HTTPException(502, f"Discovery failed: {exc}")

    claims = claims_from_request(request)
    is_admin = claims is not None and rank(claims.get("role", "")) >= rank("admin")
    out = []
    for cam in found:
        reachable = cam.reachable
        if probe:
            try:
                reachable = adapter.probe(cam)
            except Exception:
                reachable = None
        rtsp, whep = cam.rtsp_url, cam.whep_url
        if not is_admin:
            rtsp, whep = redact_url(rtsp), redact_url(whep)
        out.append({
            "external_id": cam.external_id, "name": cam.name,
            "rtsp_url": rtsp, "hls_url": cam.hls_url,
            "whep_url": whep, "department": cam.department,
            "camera_type": cam.camera_type, "location_name": cam.location_name,
            "latitude": cam.latitude, "longitude": cam.longitude,
            "codec": cam.codec, "resolution": cam.resolution,
            "vendor": cam.vendor, "reachable": reachable, "extra": cam.extra,
        })
    return {"adapter": key, "count": len(out), "cameras": out}


@router.post("/{key}/onboard")
def onboard(key: str, db: Session = Depends(get_db)):
    """Discover through one adapter and merge into the registry.

    Existing rows are updated by external_id rather than duplicated, so
    re-running onboarding is safe and picks up changed stream URLs.
    """
    adapter = adapters.get(key)
    if adapter is None:
        raise HTTPException(404, f"No adapter '{key}'")
    try:
        found = adapter.discover()
    except Exception as exc:
        log.exception("discovery failed for %s", key)
        raise HTTPException(502, f"Discovery failed: {exc}")

    existing = {c.external_id: c for c in db.query(Camera)
                .filter(Camera.external_id != "").all()}

    created = updated = 0
    for cam in found:
        fields = cam.as_camera_fields()
        row = existing.get(cam.external_id)
        if row is None:
            db.add(Camera(**fields))
            created += 1
        else:
            for k, v in fields.items():
                # Don't overwrite curated metadata with an adapter's blanks.
                if v in ("", 0, 0.0) and getattr(row, k, None):
                    continue
                setattr(row, k, v)
            updated += 1

    db.commit()
    return {"adapter": key, "created": created, "updated": updated,
            "discovered": len(found)}
