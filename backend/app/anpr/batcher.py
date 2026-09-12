"""Shared inference batcher.

Every camera runs on its own thread, and each was calling the detector session
directly. On one accelerator that means N threads contending for the same
device, which costs more in context switching than it buys in parallelism, and
it leaves the model running one image per call no matter how many cameras are
waiting.

This module puts one collector thread in front of the session. Workers hand it
a prepared blob and block; the collector gathers whatever arrives inside a
short window and runs them together. Two things follow:

  - accelerator access is serialised, so thirty workers no longer thrash it
  - when the exported model has a dynamic batch dimension, several frames go
    through in one call

Most YOLO exports pin batch to 1. That case is handled rather than assumed:
`run_vehicle_blobs` loops instead of stacking, and callers see no difference.
Preprocessing stays on the worker thread so the collector only ever does
inference.

Disabled by configuration, or with no collector running, `analyze` falls
straight through to the in-thread path.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

from ..config import settings
from . import pipeline

log = logging.getLogger("sentinel.batcher")

_queue: "queue.Queue[_Request]" = queue.Queue(maxsize=256)
_thread: threading.Thread | None = None
_lock = threading.Lock()
_stop = threading.Event()

_stats = {"batches": 0, "frames": 0, "max_batch": 0, "errors": 0}
_stats_lock = threading.Lock()


class _Request:
    __slots__ = ("blob", "ratio", "shape", "done", "result", "error")

    def __init__(self, blob, ratio, shape):
        self.blob = blob
        self.ratio = ratio
        self.shape = shape
        self.done = threading.Event()
        self.result = None
        self.error: BaseException | None = None


def enabled() -> bool:
    return bool(settings.inference_batching_enabled)


def start() -> bool:
    """Start the collector. Idempotent; returns False if already running."""
    global _thread
    if not enabled():
        return False
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        _stop.clear()
        _thread = threading.Thread(target=_run, name="inference-batcher", daemon=True)
        _thread.start()
        log.info("inference batcher started (max batch %d, wait %d ms)",
                 settings.inference_batch_size, settings.inference_batch_wait_ms)
        return True


def stop() -> None:
    _stop.set()


def running() -> bool:
    return _thread is not None and _thread.is_alive() and not _stop.is_set()


def stats() -> dict:
    with _stats_lock:
        s = dict(_stats)
    s["running"] = running()
    s["dynamic_batch"] = pipeline.vehicle_batch_dim_is_dynamic()
    s["mean_batch"] = round(s["frames"] / s["batches"], 2) if s["batches"] else 0.0
    return s


def _drain(first: _Request) -> list[_Request]:
    """Collect `first` plus whatever else arrives inside the wait window."""
    batch = [first]
    cap = max(1, settings.inference_batch_size)
    deadline = time.monotonic() + max(0, settings.inference_batch_wait_ms) / 1000.0
    while len(batch) < cap:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            batch.append(_queue.get(timeout=remaining))
        except queue.Empty:
            break
    return batch


def _run() -> None:
    while not _stop.is_set():
        try:
            first = _queue.get(timeout=0.5)
        except queue.Empty:
            continue
        batch = _drain(first)
        try:
            outs = pipeline.run_vehicle_blobs([r.blob for r in batch])
            for req, out in zip(batch, outs):
                req.result = pipeline.decode_objects(out, req.ratio, req.shape)
        except BaseException as exc:  # noqa: BLE001 - relayed to every caller
            log.exception("batched inference failed for %d frame(s)", len(batch))
            with _stats_lock:
                _stats["errors"] += 1
            for req in batch:
                req.error = exc
        finally:
            with _stats_lock:
                _stats["batches"] += 1
                _stats["frames"] += len(batch)
                _stats["max_batch"] = max(_stats["max_batch"], len(batch))
            for req in batch:
                # Free the tensor before waking the caller; a stalled worker
                # should not pin a batch worth of frames in memory.
                req.blob = None
                req.done.set()


def detect(frame_bgr, timeout: float = 20.0):
    """Detect vehicles and people in one frame, via the batcher when it is up.

    Returns (vehicles, persons). Falls back to running in the calling thread if
    the collector is not running, the queue is saturated, or the wait times
    out, so a batcher problem degrades throughput rather than dropping frames.
    """
    if not running():
        return pipeline._detect_objects(frame_bgr)

    blob, ratio = pipeline.preprocess(frame_bgr)
    req = _Request(blob, ratio, frame_bgr.shape)
    try:
        _queue.put(req, timeout=1.0)
    except queue.Full:
        log.warning("inference queue full; running detection inline")
        return pipeline._detect_objects(frame_bgr)

    if not req.done.wait(timeout):
        log.warning("batched inference timed out; running detection inline")
        return pipeline._detect_objects(frame_bgr)
    if req.error is not None:
        raise req.error
    return req.result
