import time

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
    """Dashboard preview. Cache-only: serves the worker-published frame.

    Never opens RTSP on the request path — the grid is offline-capable and
    a synchronous VideoCapture.read() blocks the HTTP worker for ~30s per
    tile (see cap_ffmpeg timeout spam), starving login and other APIs.
    Workers publish live_cam{id}.jpg every ~3s when running; otherwise 404
    fast and the frontend shows the Analytics Idle tile.
    """
    live = settings.snapshot_dir / f"live_cam{camera_id}.jpg"
    if live.exists():
        fresh = time.time() - live.stat().st_mtime < 20
        headers = {"Cache-Control": "no-cache"}
        if not fresh:
            headers["X-Sentinel-Stale"] = "1"
        return Response(content=live.read_bytes(), media_type="image/jpeg",
                        headers=headers)
    # Fast 404 — do not touch RTSP here. Verify camera exists for a clear msg.
    if db.get(Camera, camera_id) is None:
        raise HTTPException(404, "Camera not found")
    raise HTTPException(404, "No snapshot yet (analytics idle or offline)")
