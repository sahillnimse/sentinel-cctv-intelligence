import time

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import WatchlistEntry
from ..schemas import WatchlistIn, WatchlistOut
from ..utils.plates import normalize

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistOut])
def list_entries(db: Session = Depends(get_db)):
    return db.query(WatchlistEntry).order_by(WatchlistEntry.created_at.desc()).all()


@router.post("/person", response_model=WatchlistOut)
async def add_person(label: str = Form(...), reason: str = Form("wanted"),
                     photo: UploadFile = File(...), db: Session = Depends(get_db)):
    """Enroll a wanted/missing person from a photo — extracts a face embedding
    and arms live face-recognition alerts across the grid."""
    try:
        from ..face import engine as face
    except Exception as exc:
        raise HTTPException(503, f"Face engine unavailable: {exc}")
    import cv2

    raw = await photo.read()
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Could not decode photo — upload a JPEG/PNG")
    try:
        emb = face.enroll(img)
    except Exception as exc:
        raise HTTPException(503, f"Face engine error: {exc}")
    if emb is None:
        raise HTTPException(422, "No clear face found — use a closer, front-facing photo")

    fname = f"person_{int(time.time()*1000)}.jpg"
    cv2.imwrite(str(settings.snapshot_dir / fname), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    entry = WatchlistEntry(kind="person", plate="", label=label, reason=reason,
                           embedding=face.emb_to_bytes(emb), photo=fname)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.post("", response_model=WatchlistOut)
def add_entry(body: WatchlistIn, db: Session = Depends(get_db)):
    plate = normalize(body.plate)
    if not plate:
        raise HTTPException(400, "Plate is empty after normalisation — enter a valid registration number")
    entry = WatchlistEntry(**{**body.model_dump(), "plate": plate})
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.put("/{entry_id}", response_model=WatchlistOut)
def update_entry(entry_id: int, body: WatchlistIn, db: Session = Depends(get_db)):
    entry = db.get(WatchlistEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "Entry not found")
    data = body.model_dump()
    data["plate"] = normalize(data["plate"])
    if entry.kind == "vehicle" and not data["plate"]:
        raise HTTPException(400, "Plate is empty after normalisation — enter a valid registration number")
    for k, v in data.items():
        setattr(entry, k, v)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(WatchlistEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "Entry not found")
    db.delete(entry)
    db.commit()
    return {"deleted": entry_id}
