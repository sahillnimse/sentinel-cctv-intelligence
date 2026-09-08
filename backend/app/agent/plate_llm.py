"""LLM vision fallback for plates that fail the Indian format.

When OCR produces a read that isn't a valid Indian plate and can't be fixed by
positional coercion, we ask a vision model (via OpenRouter) to re-read the plate
crop. Runs on a background thread with a bounded queue so ingestion never blocks;
results are written back to the sighting/vehicle rows.

Gated on OPENROUTER_API_KEY — a no-op until the key is set.
"""

import base64
import logging
import queue
import threading

import httpx

from ..config import settings
from ..db import SessionLocal
from ..models import Sighting, VehicleDetection
from ..utils.plates import coerce_indian, is_valid_indian, normalize

log = logging.getLogger("sentinel.plate_llm")

_q: "queue.Queue[dict]" = queue.Queue(maxsize=200)
_started = False

PROMPT = (
    "This is a cropped photo of an Indian vehicle number plate. Read the plate "
    "exactly. Indian plates follow STATE(2 letters) DISTRICT(1-2 digits) "
    "SERIES(1-3 letters) NUMBER(4 digits), e.g. GJ01AB1234. Reply with ONLY the "
    "plate as uppercase letters and digits, no spaces. If unreadable, reply NONE."
)


def enabled() -> bool:
    return bool(settings.openrouter_api_key)


def submit(snapshot_path: str, sighting_id: int | None = None,
           vehicle_id: int | None = None, current: str = "") -> None:
    """Queue a plate crop for LLM correction (dropped silently if full/disabled)."""
    if not enabled():
        return
    try:
        _q.put_nowait({"path": snapshot_path, "sighting_id": sighting_id,
                       "vehicle_id": vehicle_id, "current": current})
    except queue.Full:
        pass


def start() -> None:
    global _started
    if _started or not enabled():
        return
    _started = True
    threading.Thread(target=_worker, name="plate-llm", daemon=True).start()
    log.info("LLM plate-correction worker started (model=%s)", settings.openrouter_model)


def _worker() -> None:
    while True:
        job = _q.get()
        try:
            corrected = _correct(job["path"], job["current"])
        except Exception as exc:
            log.warning("plate LLM failed: %s", exc)
            corrected = None
        if corrected and is_valid_indian(corrected):
            _writeback(job, corrected)
        _q.task_done()


def _correct(path: str, current: str) -> str | None:
    full = settings.snapshot_dir / path if not str(path).startswith("/") else path
    try:
        data = open(full, "rb").read()
    except OSError:
        return None
    b64 = base64.b64encode(data).decode()
    payload = {
        "model": settings.openrouter_model,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT + (f" OCR guessed '{current}'." if current else "")},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
    }
    with httpx.Client(base_url=settings.openrouter_base_url, timeout=40,
                      headers={"Authorization": f"Bearer {settings.openrouter_api_key}",
                               "X-Title": "SENTINEL Plate Correction"}) as c:
        r = c.post("/chat/completions", json=payload)
    if r.status_code != 200:
        log.warning("openrouter %s: %s", r.status_code, r.text[:160])
        return None
    text = r.json()["choices"][0]["message"]["content"].strip().upper()
    if "NONE" in text:
        return None
    cand = normalize(text)
    return cand if is_valid_indian(cand) else coerce_indian(cand)


def _writeback(job: dict, plate: str) -> None:
    db = SessionLocal()
    try:
        if job.get("sighting_id"):
            s = db.get(Sighting, job["sighting_id"])
            if s:
                s.plate = plate
                s.plate_raw = f"{s.plate_raw} | llm:{plate}"
        if job.get("vehicle_id"):
            v = db.get(VehicleDetection, job["vehicle_id"])
            if v:
                v.plate = plate
        db.commit()
        log.info("LLM corrected plate -> %s", plate)
    finally:
        db.close()
