"""ANPR pipeline: vehicle-first cascade + pluggable OCR.

Architecture chosen by the 7-agent bake-off on real Sentinel grid footage
(bench/results/): tiled full-frame plate detection was 4-8 s/frame with junk
OCR; the vehicle->plate cascade is ~0.6 s/frame with better recall.

  Stage 1  YOLO11n (ONNX, 960px) finds vehicles (car/motorcycle/bus/truck)
  Stage 2  yolo-v9-t-384 plate detector runs on each upscaled vehicle crop
  Gates    plate aspect ratio + minimum source width (kills logo/sign FPs)
  OCR      Awiros Indian PP-OCRv5 (ONNX) when backend/models/awiros_rec.onnx
           exists — the only bake-off candidate with verified correct reads —
           else fast-plate-ocr cct-s-v2-global as fallback.

Everything is lazy-loaded; the API server runs without ML deps installed.
Install with:  pip install -r requirements-ml.txt
Smoke test:    python -m app.anpr.pipeline <image.jpg>
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import BASE_DIR

MODELS_DIR = BASE_DIR / "models"
VEHICLE_ONNX = MODELS_DIR / "yolo11n_960.onnx"
AWIROS_ONNX = MODELS_DIR / "awiros_rec.onnx"
AWIROS_DICT = MODELS_DIR / "awiros_dict.txt"

# COCO class ids for vehicles
VEHICLE_CLASSES = (2, 3, 5, 7)  # car, motorcycle, bus, truck
VEHICLE_LABELS = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
VEHICLE_CONF = 0.25
# People come out of the same forward pass; the cascade simply discarded them.
# Crowd counting therefore costs one more slice of the score matrix, not
# another inference. A higher floor than vehicles because distant partial
# figures are where this detector invents people.
PERSON_CLASS = 0
PERSON_CONF = 0.35
PERSON_MIN_SIDE = 18  # px in source frame; smaller boxes are noise, not people
VEHICLE_INPUT = 960
PLATE_MIN_WIDTH_SRC = 40   # px in source frame — below this, detection is noise
OCR_MIN_WIDTH_SRC = 45     # below this OCR output is provably garbage on this footage
PLATE_AR_RANGE = (1.3, 6.5)  # w/h; low end admits two-line bike plates

_vehicle_sess = None
_plate_detector = None
_ocr = None
_ocr_kind = "none"
_load_error: str | None = None


@dataclass
class PlateRead:
    plate: str
    confidence: float
    box: tuple[int, int, int, int]  # x1, y1, x2, y2 in full-frame coords


@dataclass
class VehicleDetection:
    vehicle_type: str                       # car | motorcycle | bus | truck | vehicle
    box: tuple[int, int, int, int]          # vehicle box, full-frame coords
    plate: str                              # normalized plate text, "" if unread
    plate_confidence: float
    plate_box: tuple[int, int, int, int] | None


@dataclass
class SceneAnalysis:
    """Everything one frame yielded: the vehicle log and the people in shot.

    Both come from a single detector pass, so asking for people costs nothing
    beyond the extra class slice.
    """

    vehicles: list[VehicleDetection]
    persons: list[tuple[int, int, int, int]]  # person boxes, full-frame coords

    @property
    def person_count(self) -> int:
        return len(self.persons)


def available() -> bool:
    try:
        _ensure_loaded()
        return True
    except RuntimeError:
        return False


def load_status() -> str:
    if _plate_detector is not None:
        from ..utils.device import status as device_status

        return (f"loaded on {device_status()} (ocr={_ocr_kind}, "
                f"vehicle={'onnx' if _vehicle_sess else 'MISSING - tiled fallback'})")
    return _load_error or "not loaded yet"


def _ensure_loaded() -> None:
    global _vehicle_sess, _plate_detector, _ocr, _ocr_kind, _load_error
    if _plate_detector is not None:
        return
    try:
        from open_image_models import LicensePlateDetector

        from ..utils.device import active_device, onnx_providers

        providers = onnx_providers()

        _plate_detector = LicensePlateDetector(
            detection_model="yolo-v9-t-384-license-plate-end2end", conf_thresh=0.25,
            providers=providers,
        )

        if VEHICLE_ONNX.exists():
            import onnxruntime as ort

            _vehicle_sess = ort.InferenceSession(
                str(VEHICLE_ONNX), providers=providers
            )

        if AWIROS_ONNX.exists() and AWIROS_DICT.exists():
            from .awiros_ocr import AwirosOCR

            _ocr = AwirosOCR(str(AWIROS_ONNX), str(AWIROS_DICT), providers=providers)
            _ocr_kind = "awiros-indian"
        else:
            from fast_plate_ocr import LicensePlateRecognizer

            # This one takes its own device argument as well as providers; pass
            # both so it cannot pick a different device from everything else.
            _ocr = LicensePlateRecognizer(
                "cct-s-v2-global-model",
                device=active_device(), providers=providers,
            )
            _ocr_kind = "cct-s-v2-global"
        _load_error = None
    except Exception as exc:
        _load_error = f"{type(exc).__name__}: {exc}"
        raise RuntimeError(
            "ANPR models unavailable. Install ML deps first: "
            f"pip install -r requirements-ml.txt ({_load_error})"
        ) from exc


# --- Stage 1: vehicle detection (YOLO11n ONNX) ------------------------------

def _letterbox(img, size):
    import cv2

    h, w = img.shape[:2]
    r = min(size / w, size / h)
    nw, nh = int(round(w * r)), int(round(h * r))
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    canvas[:nh, :nw] = cv2.resize(img, (nw, nh))
    return canvas, r


def preprocess(frame_bgr):
    """Frame -> (CHW float blob, letterbox ratio). Public so the batcher can
    prepare frames on the calling worker's thread and hand over only tensors."""
    img, r = _letterbox(frame_bgr, VEHICLE_INPUT)
    blob = img[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
    return blob, r


def vehicle_batch_dim_is_dynamic() -> bool:
    """True when the exported model accepts more than one image per call.

    Most YOLO exports pin batch to 1. Asking rather than assuming means the
    batcher degrades to sequential execution instead of throwing on the first
    frame of a live deployment.
    """
    if _vehicle_sess is None:
        return False
    try:
        dim = _vehicle_sess.get_inputs()[0].shape[0]
    except Exception:
        return False
    return not isinstance(dim, int) or dim < 1


def run_vehicle_blobs(blobs: list) -> list:
    """Run the detector over prepared blobs, returning one (84, N) output each.

    Batches into a single call when the model allows it, otherwise loops. The
    caller sees the same result either way.
    """
    _ensure_loaded()
    if _vehicle_sess is None:
        return [None] * len(blobs)
    name = _vehicle_sess.get_inputs()[0].name
    if len(blobs) > 1 and vehicle_batch_dim_is_dynamic():
        stacked = np.stack(blobs).astype(np.float32)
        out = _vehicle_sess.run(None, {name: stacked})[0]
        return [out[i] for i in range(out.shape[0])]
    return [_vehicle_sess.run(None, {name: b[None].astype(np.float32)})[0][0]
            for b in blobs]


def _decode(out, r, frame_shape, class_ids, conf_thresh, min_side):
    """YOLO11 head (84, N) -> [(box, class_id)] in full-frame coords.

    Rows 0-3 are cxcywh, rows 4-83 are per-class scores. Non-maximum
    suppression runs per class group, so people and vehicles never suppress
    each other.
    """
    import cv2

    if out is None:
        return []
    boxes_cxcywh = out[:4].T
    scores = out[4:].T[:, list(class_ids)]
    conf = scores.max(axis=1)
    cls = np.array(class_ids)[scores.argmax(axis=1)]
    keep = conf >= conf_thresh
    if not keep.any():
        return []
    boxes_cxcywh, conf, cls = boxes_cxcywh[keep], conf[keep], cls[keep]
    xywh = np.column_stack([
        boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2,
        boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2,
        boxes_cxcywh[:, 2], boxes_cxcywh[:, 3],
    ])
    idx = cv2.dnn.NMSBoxes(xywh.tolist(), conf.tolist(), float(conf_thresh), 0.45)
    if idx is None or len(idx) == 0:
        return []
    h, w = frame_shape[:2]
    out_boxes = []
    for i in np.array(idx).flatten():
        x, y, bw, bh = xywh[i] / r
        x1, y1 = max(int(x), 0), max(int(y), 0)
        x2, y2 = min(int(x + bw), w), min(int(y + bh), h)
        if x2 - x1 > min_side and y2 - y1 > min_side:
            out_boxes.append(((x1, y1, x2, y2), int(cls[i])))
    return out_boxes


def decode_objects(out, r, frame_shape):
    """One detector output -> (vehicles, persons)."""
    vehicles = [(box, VEHICLE_LABELS.get(cid, "vehicle"))
                for box, cid in _decode(out, r, frame_shape, VEHICLE_CLASSES,
                                        VEHICLE_CONF, 40)]
    persons = [box for box, _ in _decode(out, r, frame_shape, (PERSON_CLASS,),
                                         PERSON_CONF, PERSON_MIN_SIDE)]
    return vehicles, persons


def _detect_objects(frame_bgr):
    """Single forward pass -> (vehicles, persons)."""
    blob, r = preprocess(frame_bgr)
    out = run_vehicle_blobs([blob])[0]
    return decode_objects(out, r, frame_bgr.shape)


def _detect_vehicles(frame_bgr) -> list[tuple[tuple[int, int, int, int], str]]:
    """Return [(box, label)] for detected vehicles in full-frame coords."""
    return _detect_objects(frame_bgr)[0]


# --- Stage 2: plate detection on vehicle crops ------------------------------

def _detect_plates_on_vehicle(frame_bgr, vbox) -> list[tuple[float, tuple[int, int, int, int]]]:
    import cv2

    vx1, vy1, vx2, vy2 = vbox
    # pad vehicle box 12%
    pw, ph = int((vx2 - vx1) * 0.12), int((vy2 - vy1) * 0.12)
    h, w = frame_bgr.shape[:2]
    vx1, vy1 = max(vx1 - pw, 0), max(vy1 - ph, 0)
    vx2, vy2 = min(vx2 + pw, w), min(vy2 + ph, h)
    crop = frame_bgr[vy1:vy2, vx1:vx2]
    if crop.size == 0:
        return []
    # upscale so the plate is big enough for the 384px detector
    scale = min(max(1.0, 320 / min(crop.shape[:2])), 3.0)
    if scale > 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    plates = []
    for det in _plate_detector.predict(crop):
        b = det.bounding_box
        x1 = int(b.x1 / scale) + vx1
        y1 = int(b.y1 / scale) + vy1
        x2 = int(b.x2 / scale) + vx1
        y2 = int(b.y2 / scale) + vy1
        bw, bh = x2 - x1, y2 - y1
        if bw < PLATE_MIN_WIDTH_SRC or bh < 8:
            continue
        ar = bw / max(bh, 1)
        if not (PLATE_AR_RANGE[0] <= ar <= PLATE_AR_RANGE[1]):
            continue  # kills logos / signage false positives
        plates.append((float(det.confidence), (x1, y1, x2, y2)))
    return plates


def _detect_tiled_fallback(frame_bgr) -> list[tuple[float, tuple[int, int, int, int]]]:
    """Full-frame + 2x2 overlapping tiles — used only when the vehicle ONNX
    model is missing. Slower and noisier than the cascade."""
    h, w = frame_bgr.shape[:2]
    boxes = []

    def collect(img, ox, oy):
        for det in _plate_detector.predict(img):
            b = det.bounding_box
            boxes.append((float(det.confidence),
                          (int(b.x1) + ox, int(b.y1) + oy, int(b.x2) + ox, int(b.y2) + oy)))

    collect(frame_bgr, 0, 0)
    if max(h, w) > 900:
        tw, th = int(w * 0.65), int(h * 0.65)
        for oy in (0, h - th):
            for ox in (0, w - tw):
                collect(frame_bgr[oy : oy + th, ox : ox + tw], ox, oy)
    boxes.sort(key=lambda d: -d[0])
    kept = []
    for conf, (x1, y1, x2, y2) in boxes:
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if not any(kx1 - 10 <= cx <= kx2 + 10 and ky1 - 10 <= cy <= ky2 + 10
                   for _, (kx1, ky1, kx2, ky2) in kept):
            kept.append((conf, (x1, y1, x2, y2)))
    return kept


# --- OCR --------------------------------------------------------------------

def _run_ocr(crop_bgr) -> tuple[str, float]:
    import cv2

    if _ocr_kind == "awiros-indian":
        text, conf = _ocr.read(crop_bgr)
        # Awiros emits its training label "Unreadable" (and lowercase fragments
        # of it) for illegible plates, sometimes at high confidence. Real Indian
        # plates are uppercase+digits only — any lowercase means "no read".
        if any(c.islower() for c in text):
            return "", 0.0
        return text, conf
    # cct-s-v2: needs 3-channel input; upscale small crops
    if crop_bgr.shape[1] < 128:
        s = 160 / crop_bgr.shape[1]
        crop_bgr = cv2.resize(crop_bgr, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    preds = _ocr.run(crop_bgr, return_confidence=True)
    if not preds:
        return "", 0.0
    text = (preds[0].plate or "").strip().replace("_", "")
    cp = preds[0].char_probs
    return text, (float(cp.mean()) if cp is not None else 0.0)


def _best_plate_read(frame_bgr, plate_boxes, min_confidence):
    """OCR the highest-confidence readable plate box; return the best read."""
    import cv2

    h, w = frame_bgr.shape[:2]
    best = ("", 0.0, None)
    for det_conf, (x1, y1, x2, y2) in sorted(plate_boxes, key=lambda p: -(p[1][2] - p[1][0])):
        if x2 - x1 < OCR_MIN_WIDTH_SRC:
            continue
        mx, my = int((x2 - x1) * 0.06) + 2, int((y2 - y1) * 0.12) + 2
        crop = frame_bgr[max(y1 - my, 0) : min(y2 + my, h), max(x1 - mx, 0) : min(x2 + mx, w)]
        if crop.size == 0:
            continue
        try:
            text, ocr_conf = _run_ocr(crop)
        except Exception:
            continue
        conf = min(det_conf, ocr_conf) if ocr_conf > 0 else det_conf * 0.5
        if text and conf >= min_confidence and conf > best[1]:
            best = (text, conf, (x1, y1, x2, y2))
    return best


# --- Public API -------------------------------------------------------------

def analyze_scene(frame_bgr: np.ndarray, min_confidence: float = 0.5,
                  objects=None) -> SceneAnalysis:
    """Full scene read: every vehicle with its best plate, plus the people.

    `objects` accepts an already-decoded (vehicles, persons) pair so the shared
    batcher can run the detector once for several cameras and hand the result
    back here. Left as None, this runs the detector itself.
    """
    _ensure_loaded()
    results: list[VehicleDetection] = []
    persons: list[tuple[int, int, int, int]] = []

    if _vehicle_sess is not None:
        vehicles, persons = objects if objects is not None else _detect_objects(frame_bgr)
        for vbox, label in vehicles:
            plate_boxes = _detect_plates_on_vehicle(frame_bgr, vbox)
            text, conf, pbox = _best_plate_read(frame_bgr, plate_boxes, min_confidence)
            results.append(VehicleDetection(
                vehicle_type=label, box=vbox, plate=text,
                plate_confidence=conf, plate_box=pbox,
            ))
    else:
        # No vehicle model: plate-only detection, one "vehicle" per plate. There
        # is no person channel in this path, so crowd counting reports nothing
        # rather than guessing.
        for det_conf, pbox in _detect_tiled_fallback(frame_bgr):
            text, conf, rbox = _best_plate_read(frame_bgr, [(det_conf, pbox)], min_confidence)
            if text:
                results.append(VehicleDetection(
                    vehicle_type="vehicle", box=pbox, plate=text,
                    plate_confidence=conf, plate_box=rbox,
                ))
    return SceneAnalysis(vehicles=results, persons=persons)


def analyze(frame_bgr: np.ndarray, min_confidence: float = 0.5) -> list[VehicleDetection]:
    """Detect every vehicle and its best plate. This is the full vehicle log:
    vehicles with no readable plate are still returned (plate="")."""
    return analyze_scene(frame_bgr, min_confidence).vehicles


def read_plates(frame_bgr: np.ndarray, min_confidence: float = 0.5) -> list[PlateRead]:
    """Backwards-compatible: just the vehicles that yielded a plate read."""
    return [
        PlateRead(plate=v.plate, confidence=v.plate_confidence, box=v.plate_box or v.box)
        for v in analyze(frame_bgr, min_confidence) if v.plate
    ]


if __name__ == "__main__":
    # Smoke test: python -m app.anpr.pipeline path\to\image.jpg
    import sys

    import cv2

    img = cv2.imread(sys.argv[1])
    if img is None:
        raise SystemExit(f"could not read image: {sys.argv[1]}")
    print("status:", load_status())
    for v in analyze(img, 0.25):
        print(v.vehicle_type, v.box, "plate:", v.plate or "-", round(v.plate_confidence, 2))
    print("loaded:", load_status())
