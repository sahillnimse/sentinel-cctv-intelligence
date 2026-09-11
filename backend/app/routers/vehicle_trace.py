"""Vehicle RTO + penalty trace (RapidAPI, proxied server-side).

GET /api/vehicle/{plate}/trace fans out to RC + challan vendors in parallel
and returns a UI-ready payload. The RapidAPI key never reaches the browser.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..integrations import vehicle_trace as svc

router = APIRouter(prefix="/vehicle", tags=["vehicle-trace"])


@router.get("/{plate}/trace")
async def trace(plate: str, refresh: bool = False, db: Session = Depends(get_db)):
    """Repeat lookups answer from cache (fast, no billing); refresh=true or TTL
    expiry re-fetches live from both vendors in parallel."""
    try:
        clean = svc.validate_plate_or_raise(plate)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return await svc.fetch_trace(clean, db=db, refresh=refresh)


@router.get("/{plate}/rc")
async def rc(plate: str):
    try:
        clean = svc.validate_plate_or_raise(plate)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"plate": clean, **await svc.fetch_rc(clean)}


@router.get("/{plate}/challans")
async def challans(plate: str):
    try:
        clean = svc.validate_plate_or_raise(plate)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    res = await svc.fetch_challans(clean)
    items, summary = svc.parse_challans(res.get("payload") if res.get("ok") else None)
    return {"plate": clean, "ok": res.get("ok", False), "mocked": res.get("mocked", False),
            "error": res.get("error"), "items": items, "summary": summary}
