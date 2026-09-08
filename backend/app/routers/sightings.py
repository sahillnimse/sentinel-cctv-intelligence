from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..anpr.worker import check_watchlist
from ..db import get_db
from ..models import Camera, Sighting, WatchlistEntry
from ..schemas import RoutePoint, SightingIn, SightingOut, TraceResult
from ..utils.camgraph import route_summary, validate_route
from ..utils.plates import normalize, plates_match

router = APIRouter(prefix="/sightings", tags=["sightings"])


def _matching_plates(db, target: str, fuzzy: bool) -> list[str]:
    """Plate strings in the database that resolve to `target`.

    Fuzzy matching cannot be pushed into SQL, but it does not need to run over
    every sighting. Distinct plate strings are bounded by the number of
    vehicles seen, not by how many times each was seen, so we match against
    that small set and then fetch only the sightings that matter.
    """
    if not fuzzy:
        return [target]
    seen = [p for (p,) in db.query(Sighting.plate).distinct().all() if p]
    return [p for p in seen if plates_match(p, target)]


def _build_route(db, plate: str, fuzzy: bool) -> list[RoutePoint]:
    target = normalize(plate)
    if not target:
        raise HTTPException(400, "Empty plate")

    plates = _matching_plates(db, target, fuzzy)
    if not plates:
        return []

    sightings = (db.query(Sighting)
                 .options(joinedload(Sighting.camera))
                 .filter(Sighting.plate.in_(plates))
                 .order_by(Sighting.ts)
                 .all())

    pts = [
        {"sighting_id": s.id, "camera_id": s.camera_id,
         "camera_name": s.camera.name if s.camera else "?",
         "location_name": s.camera.location_name if s.camera else "",
         "latitude": s.camera.latitude if s.camera else 0,
         "longitude": s.camera.longitude if s.camera else 0,
         "plate": s.plate, "confidence": s.confidence, "ts": s.ts,
         "snapshot": s.snapshot}
        for s in sightings
    ]
    validate_route(pts)  # annotates gap_km/gap_s/speed_kmph/flagged/reason in place
    return [RoutePoint(**p) for p in pts]


@router.get("", response_model=list[SightingOut])
def list_sightings(plate: str | None = None, camera_id: int | None = None,
                   limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(Sighting)
    if plate:
        q = q.filter(Sighting.plate == normalize(plate))
    if camera_id:
        q = q.filter(Sighting.camera_id == camera_id)
    return q.order_by(Sighting.ts.desc()).limit(min(limit, 1000)).all()


@router.get("/route/{plate}", response_model=list[RoutePoint])
def route(plate: str, fuzzy: bool = True, db: Session = Depends(get_db)):
    """The test case: plate number -> timestamped, location-wise movement history,
    with spatio-temporal validation (impossible hops flagged)."""
    return _build_route(db, plate, fuzzy)


@router.get("/trace/{plate}", response_model=TraceResult)
def trace(plate: str, fuzzy: bool = True, db: Session = Depends(get_db)):
    """Unified investigative trace — route + validation summary + VAHAN owner
    enrichment + watchlist status in a single payload (drives the hero demo)."""
    target = normalize(plate)
    route_pts = _build_route(db, plate, fuzzy)
    pts_dicts = [p.model_dump() for p in route_pts]
    summary = route_summary(pts_dicts)

    vahan = {}
    try:
        from .vahan import enrich
        vahan = enrich(target)
    except Exception:
        vahan = {}

    # Every government authority's view of this vehicle, folded into the same
    # payload. A stolen-vehicle FIR from eGujCop is the answer the test case is
    # actually looking for, and an investigator should not have to know which
    # system holds it. One authority failing must not lose the others.
    try:
        from .. import integrations
        registry = integrations.lookup_vehicle(target)
    except Exception:
        registry = []

    # Match the watchlist the same way the live alert pipeline does. Exact
    # equality here contradicted the rest of the trace: the route is assembled
    # fuzzily, and alerts are raised fuzzily, so tracing a plate the OCR read
    # as 2BH9249H against a watchlist holding 26BH9249H found the route and
    # then reported the vehicle as clear.
    entries = (db.query(WatchlistEntry)
               .filter(WatchlistEntry.active.is_(True)).all())
    wl = next((e for e in entries if plates_match(target, e.plate)), None)
    if wl is None and fuzzy:
        # Also consider the plate strings actually recorded for this vehicle,
        # in case the watchlist holds the clean plate and the query was a misread.
        for p in {pt.plate for pt in route_pts}:
            wl = next((e for e in entries if plates_match(p, e.plate)), None)
            if wl is not None:
                break

    return TraceResult(
        plate=target, route=route_pts, summary=summary, vahan=vahan,
        watchlisted=wl is not None, watchlist_reason=(wl.reason if wl else ""),
        registry=registry,
        registry_alerts=[a for r in registry for a in r.get("alerts", [])],
    )


@router.post("", response_model=SightingOut)
def create_sighting(body: SightingIn, db: Session = Depends(get_db)):
    """Manual sighting injection — used for development and integration tests
    of the route/alert flow before live ANPR is wired up. Runs the same
    watchlist correlation as the live pipeline."""
    cam = db.get(Camera, body.camera_id)
    if cam is None:
        raise HTTPException(404, "Camera not found")
    sighting = Sighting(
        camera_id=body.camera_id, plate=normalize(body.plate),
        plate_raw=body.plate, confidence=body.confidence,
        ts=body.ts or datetime.utcnow(),
    )
    db.add(sighting)
    db.flush()
    check_watchlist(db, sighting, cam)
    db.commit()
    db.refresh(sighting)
    return sighting
