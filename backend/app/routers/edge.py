"""Edge node status and the ingest endpoint the edge forwards to.

Two halves of the same story. `/api/edge/status` reports this node's own
spool, so an operator can see a district buffering during an outage.
`/api/edge/ingest` is what a remote edge node POSTs its queued detections to
when its link returns — the central tier accepting metadata, never video.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..edge import get_spool, get_forwarder
from ..models import Camera, Sighting, VehicleDetection

router = APIRouter(prefix="/edge", tags=["edge"])


class SpooledEvent(BaseModel):
    kind: str                 # "sighting" | "vehicle"
    external_id: str = ""     # grid camera id, so the centre can resolve locally
    camera_id: int | None = None
    plate: str = ""
    plate_raw: str = ""
    confidence: float = 0.0
    vehicle_type: str = "vehicle"
    ts: datetime | None = None
    pts_ms: float = 0.0
    snapshot: str = ""
    sha256: str = ""


class IngestBatch(BaseModel):
    node_id: str = "edge"
    events: list[SpooledEvent]


@router.get("/status")
def status():
    fw = get_forwarder()
    if fw is not None:
        return {"enabled": True, **fw.stats()}
    spool = get_spool()
    if spool is not None:
        return {"enabled": True, "online": True, "delivered": 0, "alive": False,
                **spool.stats()}
    return {"enabled": False, "pending": 0, "online": True}


@router.post("/ingest")
def ingest(batch: IngestBatch, db: Session = Depends(get_db)):
    """Accept a drained batch from an edge node.

    Cameras are resolved by external_id first so an edge node never has to know
    the centre's primary keys. Unknown cameras are skipped rather than
    invented — a mismatched registry is an operational problem to surface, not
    to paper over.
    """
    by_ext = {c.external_id: c for c in db.query(Camera)
              .filter(Camera.external_id != "").all()}

    accepted = skipped = 0
    for e in batch.events:
        cam = by_ext.get(e.external_id) if e.external_id else None
        if cam is None and e.camera_id is not None:
            cam = db.get(Camera, e.camera_id)
        if cam is None:
            skipped += 1
            continue

        ts = e.ts or datetime.utcnow()
        if e.kind == "sighting" and e.plate:
            db.add(Sighting(camera_id=cam.id, plate=e.plate, plate_raw=e.plate_raw,
                            confidence=e.confidence, ts=ts, pts_ms=e.pts_ms,
                            snapshot=e.snapshot, sha256=e.sha256))
        else:
            db.add(VehicleDetection(camera_id=cam.id, vehicle_type=e.vehicle_type,
                                    plate=e.plate, plate_confidence=e.confidence,
                                    ts=ts, snapshot=e.snapshot, sha256=e.sha256))
        accepted += 1

    db.commit()
    return {"node_id": batch.node_id, "accepted": accepted, "skipped": skipped}
