"""Session-wide output reports.

The evidence router exports one vehicle's route. This one exports what a whole
evaluation session produced: every vehicle and plate detected, with timestamps
and the camera that saw it.

That is a named submission deliverable — the government-feed demonstration
must be accompanied by "an output report showing detected vehicles and plates
with corresponding timestamps" — and it is not something the per-plate export
can answer, because at report time nobody knows which plates to ask for.

CSV is the primary format because it is what an evaluator can open, sort and
check. PDF is offered for filing. Both carry the SHA-256 of each snapshot so
the artifact can be checked against the images it references.
"""

import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import Alert, Camera, Sighting, VehicleDetection
from .evidence import file_sha256

router = APIRouter(prefix="/reports", tags=["reports"])


def _window(minutes: int | None, since: str | None) -> datetime | None:
    if since:
        try:
            return datetime.fromisoformat(since)
        except ValueError:
            pass
    if minutes and minutes > 0:
        return datetime.utcnow() - timedelta(minutes=minutes)
    return None


def _collect(db: Session, cutoff: datetime | None, plates_only: bool, limit: int = 10000):
    q = db.query(VehicleDetection)
    if cutoff is not None:
        q = q.filter(VehicleDetection.ts >= cutoff)
    if plates_only:
        q = q.filter(VehicleDetection.plate != "")
    detections = q.order_by(VehicleDetection.ts.desc()).limit(limit).all()

    sq = db.query(Sighting).options(joinedload(Sighting.camera))
    if cutoff is not None:
        sq = sq.filter(Sighting.ts >= cutoff)
    sightings = sq.order_by(Sighting.ts.desc()).limit(limit).all()

    cams = {c.id: c for c in db.query(Camera).all()}
    return detections, sightings, cams


@router.get("/detections")
def detections_summary(minutes: int | None = Query(None, ge=1),
                       since: str | None = None,
                       db: Session = Depends(get_db)):
    """What the report contains, as JSON, so the console can preview it."""
    cutoff = _window(minutes, since)
    detections, sightings, cams = _collect(db, cutoff, plates_only=False)

    plates = {}
    for s in sightings:
        entry = plates.setdefault(s.plate, {"plate": s.plate, "reads": 0,
                                            "cameras": set(), "first": s.ts,
                                            "last": s.ts, "best_confidence": 0.0})
        entry["reads"] += 1
        entry["cameras"].add(s.camera_id)
        entry["first"] = min(entry["first"], s.ts)
        entry["last"] = max(entry["last"], s.ts)
        entry["best_confidence"] = max(entry["best_confidence"], s.confidence)

    by_type = {}
    for d in detections:
        by_type[d.vehicle_type or "vehicle"] = by_type.get(d.vehicle_type or "vehicle", 0) + 1

    alert_q = db.query(Alert)
    if cutoff is not None:
        alert_q = alert_q.filter(Alert.ts >= cutoff)

    return {
        "window": {"since": cutoff.isoformat() if cutoff else None,
                   "minutes": minutes, "scope": "all recorded data"
                   if cutoff is None else f"last {minutes or 'n'} minutes"},
        "totals": {
            "vehicle_detections": len(detections),
            "plate_reads": len(sightings),
            "distinct_plates": len(plates),
            "cameras_reporting": len({d.camera_id for d in detections}),
            "cameras_onboarded": len(cams),
            "alerts_raised": alert_q.count(),
        },
        "by_vehicle_type": [{"type": t, "count": n} for t, n in
                            sorted(by_type.items(), key=lambda x: -x[1])],
        "plates": sorted(
            ({"plate": v["plate"], "reads": v["reads"],
              "cameras": len(v["cameras"]),
              "first_seen": v["first"], "last_seen": v["last"],
              "best_confidence": round(v["best_confidence"], 3)}
             for v in plates.values()),
            key=lambda p: p["first_seen"]),
    }


@router.get("/detections.csv")
def detections_csv(minutes: int | None = Query(None, ge=1),
                   since: str | None = None,
                   plates_only: bool = False,
                   db: Session = Depends(get_db)):
    """Every plate read in the window, one row per read.

    This is the artifact that accompanies the government-feed demonstration.
    """
    cutoff = _window(minutes, since)
    _, sightings, cams = _collect(db, cutoff, plates_only)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["timestamp_utc", "plate", "raw_read", "confidence",
                "camera_id", "camera_name", "department", "location",
                "latitude", "longitude", "stream_pts_ms", "snapshot",
                "snapshot_sha256"])
    for s in sightings:
        cam = cams.get(s.camera_id)
        w.writerow([
            s.ts.isoformat() if s.ts else "",
            s.plate, s.plate_raw, f"{s.confidence:.3f}",
            s.camera_id,
            cam.name if cam else "",
            cam.department if cam else "",
            cam.location_name if cam else "",
            cam.latitude if cam else "",
            cam.longitude if cam else "",
            f"{s.pts_ms:.0f}" if s.pts_ms else "",
            s.snapshot,
            s.sha256 or file_sha256(s.snapshot),
        ])

    stamp = (cutoff or datetime.utcnow()).strftime("%Y%m%d-%H%M")
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="sentinel-detections-{stamp}.csv"'},
    )


@router.get("/vehicles.csv")
def vehicles_csv(minutes: int | None = Query(None, ge=1),
                 since: str | None = None,
                 db: Session = Depends(get_db)):
    """Every vehicle detected, including those whose plate was unreadable.

    Kept separate from detections.csv on purpose: an evaluator checking plate
    yield needs the denominator, not just the successful reads.
    """
    cutoff = _window(minutes, since)
    detections, _, cams = _collect(db, cutoff, plates_only=False)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["timestamp_utc", "vehicle_type", "plate", "plate_confidence",
                "camera_id", "camera_name", "department", "location",
                "snapshot", "snapshot_sha256"])
    for d in detections:
        cam = cams.get(d.camera_id)
        w.writerow([
            d.ts.isoformat() if d.ts else "",
            d.vehicle_type, d.plate or "",
            f"{d.plate_confidence:.3f}" if d.plate_confidence else "",
            d.camera_id,
            cam.name if cam else "",
            cam.department if cam else "",
            cam.location_name if cam else "",
            d.snapshot, d.sha256 or file_sha256(d.snapshot),
        ])

    stamp = (cutoff or datetime.utcnow()).strftime("%Y%m%d-%H%M")
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="sentinel-vehicles-{stamp}.csv"'},
    )


@router.get("/registry.csv")
def registry_csv(db: Session = Depends(get_db)):
    """The camera registry as CSV.

    Model 1 names export alongside search and filtering, and it round-trips:
    this is the same shape /api/cameras/import accepts, so a registry can be
    exported, edited and re-imported.
    """
    cams = db.query(Camera).order_by(Camera.id).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["external_id", "name", "department", "camera_type",
                "latitude", "longitude", "location_name", "rtsp_url", "hls_url",
                "heading", "fov_deg", "range_m", "status", "last_seen",
                "analytics_enabled"])
    for c in cams:
        w.writerow([c.external_id, c.name, c.department, c.camera_type,
                    c.latitude, c.longitude, c.location_name,
                    c.rtsp_url, c.hls_url, c.heading, c.fov_deg, c.range_m,
                    c.status, c.last_seen.isoformat() if c.last_seen else "",
                    "yes" if c.analytics_enabled else "no"])

    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sentinel-registry.csv"'},
    )
