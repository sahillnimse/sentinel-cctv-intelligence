"""Per-camera ingestion worker.

One thread per camera, built for the Sentinel grid's live-camera semantics:

  - RTSP forced over TCP (env set in config.py) with HLS as fallback source
  - reconnect with exponential backoff (2s -> 30s cap), never tight-loops
  - timing driven by stream PTS (CAP_PROP_POS_MSEC), not arrival time;
    PTS jumping backwards at the loop-point discontinuity is tolerated
  - cap.grab() on every frame, full decode only for sampled frames, so
    30 concurrent 1080p streams don't melt the CPU
  - inter-frame gaps and join-time decoder warnings are non-fatal

Also doubles as the health monitor: updates camera.status / last_seen.
"""

import hashlib
import logging
import threading
import time
from datetime import datetime

from ..config import settings  # must come before cv2: sets FFmpeg capture opts

import cv2

from .. import ws
from ..db import SessionLocal
from ..models import (Alert, Camera, Sighting, VehicleDetection,
                      WatchlistEntry)
from ..agent import plate_llm
from ..utils.plates import (coerce_indian, edit_distance, fold_ambiguous,
                            is_valid_indian, normalize, plates_match)
from . import pipeline

log = logging.getLogger("sentinel.worker")

_workers: dict[int, "CameraWorker"] = {}
_lock = threading.Lock()

DEDUP_SECONDS = 10        # suppress duplicate plate on same camera within window
VEHICLE_DEDUP_SECONDS = 8  # suppress re-logging a vehicle lingering in a cell
FACE_INTERVAL = 4.0       # per-camera throttle for the (heavy) face pass
FACE_DEDUP_SECONDS = 20   # suppress repeat person alerts on one camera
PERSON_REF_TTL = 20.0     # refresh the enrolled-person cache this often

# Face matching is heavy on CPU; cap how many run at once across all workers,
# and cache the enrolled-person refs so we hit the DB rarely. Zero cost when no
# person is on the watchlist (the common case) — refs is empty, face pass skips.
_face_sem = threading.Semaphore(2)
_person_refs = {"mono": -1e9, "refs": []}
_person_lock = threading.Lock()


def _sha256_file(path) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _get_person_refs(db, mono_now: float):
    """Cached list of enrolled wanted/missing persons {id,label,reason,emb}."""
    with _person_lock:
        if mono_now - _person_refs["mono"] < PERSON_REF_TTL:
            return _person_refs["refs"]
    refs = []
    try:
        from ..face import engine as face
        rows = (db.query(WatchlistEntry)
                .filter(WatchlistEntry.kind == "person",
                        WatchlistEntry.active.is_(True),
                        WatchlistEntry.embedding.isnot(None)).all())
        for r in rows:
            refs.append({"id": r.id, "label": r.label or "person",
                         "reason": r.reason, "emb": face.bytes_to_emb(r.embedding)})
    except Exception:
        refs = []
    with _person_lock:
        _person_refs["mono"] = mono_now
        _person_refs["refs"] = refs
    return refs
BACKOFF_START = 2.0
BACKOFF_CAP = 30.0
STATUS_COMMIT_SECONDS = 10  # throttle last_seen/status DB writes
PREVIEW_SECONDS = 3.0     # how often the worker publishes a preview JPEG
PTS_BUCKET_MS = 2000      # clip-position bucket size for loop dedup (~sample rate)

# BGR colors for on-video annotation
VBOX_COLOR = {"car": (238, 211, 34), "motorcycle": (153, 217, 52),
              "bus": (36, 191, 251), "truck": (75, 90, 251), "vehicle": (200, 200, 200)}


def _annotate(frame, vehicles):
    """Draw vehicle boxes + plate labels on a copy of the frame."""
    out = frame.copy()
    for v in vehicles:
        x1, y1, x2, y2 = v.box
        color = VBOX_COLOR.get(v.vehicle_type, (200, 200, 200))
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        label = v.vehicle_type.upper()
        if v.plate:
            label = f"{label}  {v.plate}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(out, (x1, y1 - th - 8), (x1 + tw + 8, y1), color, -1)
        cv2.putText(out, label, (x1 + 4, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (10, 15, 22), 1, cv2.LINE_AA)
        if v.plate_box:
            px1, py1, px2, py2 = v.plate_box
            cv2.rectangle(out, (px1, py1), (px2, py2), (34, 211, 238), 2)
    return out


class PlateVoter:
    """Levenshtein-anchored consensus across consecutive reads of one camera.

    Single-frame OCR on this footage misreads the same physical plate several
    different ways (bake-off: GJ12L7948 / GJ12EL2928 / GJ12EC7928 = one real
    plate). Reads are grouped into tracks by plate-box proximity; a plate is
    confirmed once >=2 reads agree within edit distance 2 and the best-
    supported read (after positional digit/letter coercion) is a valid Indian
    plate. Positional majority voting was tested and rejected — it cannot
    align insertions/deletions.
    """

    WINDOW = 15.0  # seconds a track stays alive without new reads

    def __init__(self):
        self._tracks: list[dict] = []

    def add(self, box, text, conf, mono_now) -> str | None:
        text = normalize(text)
        if len(text) < 6:
            return None
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        radius = max(box[2] - box[0], 40) * 2.0

        self._tracks = [t for t in self._tracks if mono_now - t["last"] < self.WINDOW]
        track = None
        for t in self._tracks:
            if abs(t["cx"] - cx) < radius and abs(t["cy"] - cy) < radius:
                track = t
                break
        if track is None:
            track = {"cx": cx, "cy": cy, "last": mono_now, "reads": [], "published": set()}
            self._tracks.append(track)
        track.update(cx=cx, cy=cy, last=mono_now)
        track["reads"].append((text, conf))
        return self._consensus(track)

    def _consensus(self, track) -> str | None:
        reads = track["reads"][-12:]
        if len(reads) < 2:
            return None
        # anchor = read with highest edit-distance-weighted support
        best, best_score = None, -1.0
        for t, _ in reads:
            ft = fold_ambiguous(t)
            score = sum(
                oc * (1 - edit_distance(ft, fold_ambiguous(o)) / max(len(t), len(o), 1))
                for o, oc in reads
            )
            if score > best_score:
                best, best_score = t, score
        supporters = sum(
            1 for o, _ in reads
            if edit_distance(fold_ambiguous(best), fold_ambiguous(o)) <= 2
        )
        if supporters < 2:
            return None
        cand = coerce_indian(best)
        if cand and cand not in track["published"]:
            track["published"].add(cand)
            return cand
        return None


class CameraWorker(threading.Thread):
    def __init__(self, camera_id: int):
        super().__init__(daemon=True, name=f"camera-{camera_id}")
        self.camera_id = camera_id
        self.stop_event = threading.Event()
        self.last_error: str | None = None
        self.frames_processed = 0
        self.source_url: str | None = None
        self._recent: dict[str, float] = {}  # plate -> monotonic ts of last sighting
        self._recent_vehicles: dict[tuple, float] = {}  # spatial cell -> ts
        self._voter = PlateVoter()
        self._last_face = 0.0                    # monotonic ts of last face pass
        self._recent_faces: dict[int, float] = {}  # watchlist person id -> last alert ts
        # clip-position (PTS) buckets we've already logged. The grid feeds are
        # looping clips, so we log each unique moment of the clip ONCE — this
        # covers the whole clip across loops without missing the start, and a
        # vehicle at a given clip position is logged once (still trackable),
        # never re-counted on every replay.
        self._seen_pts: set[int] = set()

    def run(self) -> None:
        db = SessionLocal()
        try:
            cam = db.get(Camera, self.camera_id)
            if cam is None:
                self.last_error = "camera not found"
                return
            if not (cam.rtsp_url or cam.hls_url):
                self.last_error = "camera has no stream URL"
                return
            self._loop(db, cam)
        except Exception as exc:  # never let a worker die silently
            log.exception("camera %s worker crashed", self.camera_id)
            self.last_error = str(exc)
        finally:
            db.close()
            with _lock:
                _workers.pop(self.camera_id, None)

    def _loop(self, db, cam: Camera) -> None:
        interval = settings.sample_interval_ms / 1000.0
        analytics = cam.analytics_enabled and pipeline.available()
        if cam.analytics_enabled and not analytics:
            log.warning("camera %s: ANPR models not available (%s) — running health-only",
                        cam.id, pipeline.load_status())

        sources = [u for u in (cam.rtsp_url, cam.hls_url) if u]
        src_i = 0
        backoff = BACKOFF_START
        cap = None
        last_sample = 0.0
        last_status_commit = 0.0

        while not self.stop_event.is_set():
            if cap is None:
                self.source_url = sources[src_i % len(sources)]
                cap = cv2.VideoCapture(self.source_url, cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    cap.release()
                    cap = None
                    self.last_error = f"could not open {self.source_url}"
                    self._set_status(db, cam, "offline")
                    src_i += 1  # rotate RTSP <-> HLS
                    if self.stop_event.wait(backoff):
                        break
                    backoff = min(backoff * 2, BACKOFF_CAP)
                    continue
                log.info("camera %s connected via %s", cam.id, self.source_url)
                self._set_status(db, cam, "online")
                backoff = BACKOFF_START
                last_status_commit = time.monotonic()
                # note: we deliberately keep self._seen_pts across reconnects so a
                # replay of the same clip positions isn't logged twice

            # Demux every frame (keeps the live stream drained) but only pay
            # for a full decode when the sampling interval has elapsed.
            if not cap.grab():
                # Supervised feeds restart; inter-frame gaps are normal but a
                # failed grab means the connection dropped — back off, reconnect.
                cap.release()
                cap = None
                self._set_status(db, cam, "offline")
                if self.stop_event.wait(backoff):
                    break
                backoff = min(backoff * 2, BACKOFF_CAP)
                continue

            now = time.monotonic()
            if now - last_status_commit > STATUS_COMMIT_SECONDS:
                last_status_commit = now
                self._set_status(db, cam, "online")

            if now - last_sample < interval:
                continue
            last_sample = now

            ok, frame = cap.retrieve()
            if not ok or frame is None:
                continue
            pts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            self.frames_processed += 1

            # Dedup by clip position: log each moment of the looping clip once.
            # A frame whose PTS bucket we've already logged is a replay — we
            # still run analytics (so the preview stays annotated) but skip the
            # duplicate DB write. Buckets ~ the sample interval so first-pass
            # frames all log; every subsequent loop hits already-seen buckets.
            bucket = int(pts_ms // PTS_BUCKET_MS) if pts_ms and pts_ms > 0 else None
            fresh = bucket is None or bucket not in self._seen_pts
            if bucket is not None:
                self._seen_pts.add(bucket)

            vehicles = []
            if analytics:
                try:
                    vehicles = pipeline.analyze(frame, settings.min_plate_confidence)
                except Exception as exc:
                    self.last_error = str(exc)
                if vehicles and fresh:  # log only clip moments we haven't seen
                    for v in vehicles:
                        self._log_vehicle(db, cam, frame, v, now)
                        if v.plate:
                            self._record(db, cam, frame, v, pts_ms, now)
                    db.commit()

                # Face pass for wanted/missing persons. Zero cost when nobody is
                # enrolled; otherwise throttled + globally semaphore-capped so a
                # heavy model doesn't run on 30 threads at once.
                if now - self._last_face > FACE_INTERVAL:
                    self._last_face = now
                    refs = _get_person_refs(db, now)
                    if refs and _face_sem.acquire(blocking=False):
                        try:
                            from ..face import engine as face
                            for m in face.match(frame, refs):
                                self._person_alert(db, cam, frame, m, now)
                            db.commit()
                        except Exception as exc:
                            self.last_error = f"face: {exc}"
                        finally:
                            _face_sem.release()

            # publish an annotated preview so the dashboard shows marked-up
            # detection without opening its own RTSP connection (30 tiles
            # polling the gateway would melt it)
            if now - getattr(self, "_last_preview", 0.0) > PREVIEW_SECONDS:
                self._last_preview = now
                shown = _annotate(frame, vehicles) if vehicles else frame
                small = cv2.resize(shown, (640, 360)) if shown.shape[1] > 640 else shown
                cv2.imwrite(str(settings.snapshot_dir / f"live_cam{cam.id}.jpg"), small,
                            [cv2.IMWRITE_JPEG_QUALITY, 72])

        if cap is not None:
            cap.release()
        self._set_status(db, cam, "offline")

    def _log_vehicle(self, db, cam: Camera, frame, v, mono_now: float) -> None:
        """Store every vehicle detection (with its best-effort plate), deduped
        spatially per camera so a vehicle lingering in view isn't logged on
        every frame."""
        box = v.box
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        key = (v.vehicle_type, round(cx / 60), round(cy / 60))
        last = self._recent_vehicles.get(key)
        if last is not None and mono_now - last < VEHICLE_DEDUP_SECONDS:
            return
        self._recent_vehicles[key] = mono_now
        # prune the dedup map opportunistically
        if len(self._recent_vehicles) > 200:
            self._recent_vehicles = {
                k: t for k, t in self._recent_vehicles.items()
                if mono_now - t < VEHICLE_DEDUP_SECONDS
            }

        plate = normalize(v.plate)
        # always keep a cropped photo of the vehicle for the log
        snap = ""
        x1, y1, x2, y2 = box
        h, w = frame.shape[:2]
        crop = frame[max(y1, 0):min(y2, h), max(x1, 0):min(x2, w)]
        if crop.size:
            snap = f"veh_cam{cam.id}_{int(time.time()*1000)}.jpg"
            cw = crop.shape[1]
            out = cv2.resize(crop, (240, max(1, int(240 * crop.shape[0] / cw)))) if cw > 240 else crop
            cv2.imwrite(str(settings.snapshot_dir / snap), out, [cv2.IMWRITE_JPEG_QUALITY, 74])

        # normalized ground-contact point (bbox bottom-centre) for geo projection
        img_x = ((x1 + x2) / 2) / max(w, 1)
        img_y = y2 / max(h, 1)
        vd = VehicleDetection(
            camera_id=cam.id, vehicle_type=v.vehicle_type, plate=plate,
            plate_confidence=v.plate_confidence, ts=datetime.utcnow(), snapshot=snap,
            img_x=round(img_x, 4), img_y=round(img_y, 4),
            sha256=_sha256_file(settings.snapshot_dir / snap) if snap else "",
        )
        db.add(vd)

        # LLM vision fallback: a read that isn't a valid Indian plate and can't
        # be coerced gets re-read from the crop by a vision model (if a key is set).
        if plate and snap and not is_valid_indian(plate) and not coerce_indian(plate):
            db.flush()
            plate_llm.submit(snap, vehicle_id=vd.id, current=plate)

    def _record(self, db, cam: Camera, frame, read, pts_ms: float, mono_now: float) -> None:
        plate = normalize(read.plate)
        if len(plate) < 5:
            return

        # Every plausible read feeds the consensus voter; a track is confirmed
        # once >=2 reads agree (edit distance <=2) and coerce to a valid
        # Indian plate. Raw reads are stored only when they already look like
        # a plate — never publish pure OCR garbage.
        box = read.plate_box or read.box
        consensus = self._voter.add(box, plate, read.plate_confidence, mono_now)

        if is_valid_indian(plate) or len(plate) >= 7:
            self._store(db, cam, frame, plate, read.plate, read.plate_confidence,
                        box, pts_ms, mono_now, confirmed=False)
        if consensus and consensus != plate:
            self._store(db, cam, frame, consensus, f"consensus of track ({plate},...)",
                        max(read.plate_confidence, 0.8), box, pts_ms, mono_now,
                        confirmed=True)

    def _store(self, db, cam: Camera, frame, plate: str, plate_raw: str,
               confidence: float, box, pts_ms: float, mono_now: float,
               confirmed: bool) -> None:
        last = self._recent.get(plate)
        if last is not None and mono_now - last < DEDUP_SECONDS:
            return
        self._recent[plate] = mono_now
        # Prune like _recent_vehicles does. Without this the map keeps one entry
        # per distinct plate string forever, and noisy OCR invents new strings
        # continuously, so a worker left running for days grows without bound.
        if len(self._recent) > 500:
            self._recent = {p: t for p, t in self._recent.items()
                            if mono_now - t < DEDUP_SECONDS}

        # annotated snapshot for evidence
        x1, y1, x2, y2 = box
        annotated = frame.copy()
        color = (80, 220, 120) if confirmed else (0, 200, 255)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        cv2.putText(annotated, plate, (x1, max(y1 - 8, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        fname = f"cam{cam.id}_{plate}_{int(time.time())}.jpg"
        cv2.imwrite(str(settings.snapshot_dir / fname), annotated)

        sighting = Sighting(
            camera_id=cam.id, plate=plate, plate_raw=plate_raw,
            confidence=confidence, ts=datetime.utcnow(),
            pts_ms=pts_ms, snapshot=fname,
            sha256=_sha256_file(settings.snapshot_dir / fname),
        )
        db.add(sighting)
        db.flush()

        ws.broadcast({
            "type": "sighting", "camera_id": cam.id, "camera_name": cam.name,
            "plate": plate, "confidence": confidence, "confirmed": confirmed,
            "ts": sighting.ts, "pts_ms": pts_ms, "snapshot": fname,
        })
        check_watchlist(db, sighting, cam)

    def _person_alert(self, db, cam: Camera, frame, m, mono_now: float) -> None:
        """A wanted/missing person matched on this camera — persist + broadcast."""
        pid = m.get("id")
        last = self._recent_faces.get(pid)
        if last is not None and mono_now - last < FACE_DEDUP_SECONDS:
            return
        self._recent_faces[pid] = mono_now

        x1, y1, x2, y2 = m["box"]
        annotated = frame.copy()
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (238, 90, 255), 2)
        label = f"{m['label']} {int(m['sim'] * 100)}%"
        cv2.putText(annotated, label, (x1, max(y1 - 8, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (238, 90, 255), 2)
        fname = f"face_cam{cam.id}_{pid}_{int(time.time())}.jpg"
        cv2.imwrite(str(settings.snapshot_dir / fname), annotated)

        # persist via a Sighting (plate slot carries the person label) + Alert,
        # reusing the alert infra so it shows on the Alerts page and audit trail
        tag = f"FACE:{m['label']}"[:20]
        sighting = Sighting(camera_id=cam.id, plate=tag, plate_raw=m["label"],
                            confidence=m["sim"], ts=datetime.utcnow(), snapshot=fname,
                            sha256=_sha256_file(settings.snapshot_dir / fname))
        db.add(sighting)
        db.flush()
        db.add(Alert(sighting_id=sighting.id, watchlist_id=pid, camera_id=cam.id,
                     plate=tag, ts=sighting.ts))
        db.flush()
        ws.broadcast({
            "type": "alert", "kind": "person", "camera_id": cam.id,
            "camera_name": cam.name, "plate": m["label"], "label": m["label"],
            "reason": m.get("reason", "wanted"), "confidence": m["sim"],
            "location": cam.location_name, "ts": sighting.ts, "snapshot": fname,
        })
        log.info("PERSON ALERT %s on camera %s (%.2f)", m["label"], cam.id, m["sim"])

    def _set_status(self, db, cam: Camera, status: str) -> None:
        cam.status = status
        if status == "online":
            cam.last_seen = datetime.utcnow()
        db.commit()


def check_watchlist(db, sighting: Sighting, cam: Camera) -> None:
    """Fuzzy-match a sighting against active watchlist entries; raise alerts."""
    entries = db.query(WatchlistEntry).filter(WatchlistEntry.active.is_(True)).all()
    for entry in entries:
        if plates_match(sighting.plate, entry.plate):
            alert = Alert(
                sighting_id=sighting.id, watchlist_id=entry.id,
                camera_id=cam.id, plate=sighting.plate, ts=sighting.ts,
            )
            db.add(alert)
            db.flush()
            ws.broadcast({
                "type": "alert", "alert_id": alert.id, "plate": sighting.plate,
                "watchlist_plate": entry.plate, "label": entry.label,
                "reason": entry.reason, "camera_id": cam.id, "camera_name": cam.name,
                "location": cam.location_name, "ts": sighting.ts,
                "snapshot": sighting.snapshot, "confidence": sighting.confidence,
            })


def start_worker(camera_id: int) -> bool:
    with _lock:
        if camera_id in _workers and _workers[camera_id].is_alive():
            return False
        worker = CameraWorker(camera_id)
        _workers[camera_id] = worker
        worker.start()
        return True


def stop_worker(camera_id: int) -> bool:
    with _lock:
        worker = _workers.get(camera_id)
    if worker is None:
        return False
    worker.stop_event.set()
    return True


def worker_status() -> list[dict]:
    with _lock:
        return [
            {
                "camera_id": w.camera_id,
                "alive": w.is_alive(),
                "frames_processed": w.frames_processed,
                "source_url": w.source_url,
                "last_error": w.last_error,
            }
            for w in _workers.values()
        ]


def stop_all() -> None:
    with _lock:
        workers = list(_workers.values())
    for w in workers:
        w.stop_event.set()
