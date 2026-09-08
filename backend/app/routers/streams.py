import time

import cv2
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..anpr import pipeline
from ..anpr.worker import start_worker, stop_worker, worker_status
from ..config import settings
from ..db import get_db
from ..models import Camera

router = APIRouter(prefix="/streams", tags=["streams"])


@router.post("/{camera_id}/start")
def start(camera_id: int, db: Session = Depends(get_db)):
    if db.get(Camera, camera_id) is None:
        raise HTTPException(404, "Camera not found")
    started = start_worker(camera_id)
    return {"camera_id": camera_id, "started": started, "anpr": pipeline.load_status()}


@router.post("/{camera_id}/stop")
def stop(camera_id: int):
    return {"camera_id": camera_id, "stopping": stop_worker(camera_id)}


@router.post("/start-all")
def start_all(db: Session = Depends(get_db)):
    cams = db.query(Camera).filter(Camera.rtsp_url != "").all()
    started = [c.id for c in cams if start_worker(c.id)]
    return {"started": started, "total_with_url": len(cams)}


@router.get("/status")
def status():
    return {"anpr": pipeline.load_status(), "workers": worker_status(),
            "go2rtc_url": settings.go2rtc_url,
            "whep_base": settings.grid_whep_base}


@router.get("/{camera_id}/snapshot")
def snapshot(camera_id: int, db: Session = Depends(get_db)):
    """Dashboard preview. Serves the running worker's published frame when
    fresh; otherwise serves the last cached frame (so tiles still show real
    footage when the grid is offline / in sandbox mode); RTSP grab is the last
    resort for a camera with no cached frame."""
    live = settings.snapshot_dir / f"live_cam{camera_id}.jpg"
    fresh = live.exists() and time.time() - live.stat().st_mtime < 20
    from .. import sim
    if live.exists() and (fresh or sim.running() or True):
        return Response(content=live.read_bytes(), media_type="image/jpeg",
                        headers={"Cache-Control": "no-cache"})
    cam = db.get(Camera, camera_id)
    if cam is None or not cam.rtsp_url:
        raise HTTPException(404, "Camera not found or has no stream URL")
    cap = cv2.VideoCapture(cam.rtsp_url)
    try:
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok:
        raise HTTPException(502, "Could not read frame from stream")
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise HTTPException(500, "Encode failed")
    return Response(content=buf.tobytes(), media_type="image/jpeg")
