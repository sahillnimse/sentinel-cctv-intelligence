"""Face-recognition engine for wanted / missing-person watchlists.

Ported from the sibling Lost & Found engine (D:/rfdetr/crowd_analytics):
MTCNN face detector + InceptionResnetV1 (VGGFace2) embedder, weights loaded
locally from backend/models/vggface2.pt — no runtime download.

Lazy-loaded and zero-cost until a person is actually enrolled: the worker only
calls match() when person watchlist refs exist, and the model only loads on the
first call. If torch/facenet aren't installed the API still runs (face features
degrade gracefully to "unavailable").

The problem statement's watchlist explicitly names *wanted persons* and
*missing persons* — this is the half of the test case ANPR can't cover.
"""

import threading

import numpy as np

from ..config import BASE_DIR

MODELS_DIR = BASE_DIR / "models"
FACENET_WEIGHTS = MODELS_DIR / "vggface2.pt"

# cosine-sim threshold for a confident face match (VGGFace2 embeddings)
MATCH_THRESHOLD = 0.62
MIN_FACE_PROB = 0.90

_lock = threading.Lock()
_engine = None
_load_error: str | None = None


class _FaceEngine:
    def __init__(self):
        import torch
        from facenet_pytorch import MTCNN, InceptionResnetV1

        from ..utils.device import torch_device

        self.torch = torch
        # Follows the same INFERENCE_DEVICE setting as the ONNX models, but
        # falls back independently: a CUDA onnxruntime and a CUDA torch are
        # separate installs and either can be absent.
        self.device = torch_device()
        self.mtcnn = MTCNN(
            image_size=160, margin=14, keep_all=True, post_process=True,
            min_face_size=24, thresholds=[0.6, 0.7, 0.7], device=self.device,
        )
        resnet = InceptionResnetV1(pretrained=None, classify=False)
        state = torch.load(str(FACENET_WEIGHTS), map_location="cpu", weights_only=True)
        resnet.load_state_dict(state, strict=False)  # drop unused logits head
        self.resnet = resnet.eval().to(self.device)

    def embeddings(self, img_bgr) -> list[tuple[np.ndarray, np.ndarray]]:
        """All faces in a BGR image -> [(xyxy box, L2-normalised 512-d emb)]."""
        from PIL import Image

        torch = self.torch
        pil = Image.fromarray(img_bgr[:, :, ::-1])
        with torch.inference_mode():
            boxes, probs = self.mtcnn.detect(pil)
            if boxes is None or len(boxes) == 0:
                return []
            faces = self.mtcnn.extract(pil, boxes, save_path=None)
            if faces is None:
                return []
            if faces.ndim == 3:
                faces = faces.unsqueeze(0)
            emb = self.resnet(faces.to(self.device))
            emb = torch.nn.functional.normalize(emb, dim=1).cpu().numpy().astype(np.float32)
        out = []
        for i, box in enumerate(boxes):
            if probs is not None and probs[i] is not None and probs[i] < MIN_FACE_PROB:
                continue
            out.append((np.asarray(box, dtype=np.float32), emb[i]))
        return out


def available() -> bool:
    try:
        _get()
        return True
    except RuntimeError:
        return False


def load_status() -> str:
    if _engine is not None:
        return "loaded (facenet vggface2, cpu)"
    return _load_error or "not loaded yet"


def _get() -> "_FaceEngine":
    global _engine, _load_error
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is None:
            try:
                if not FACENET_WEIGHTS.exists():
                    raise FileNotFoundError(f"missing {FACENET_WEIGHTS}")
                _engine = _FaceEngine()
                _load_error = None
            except Exception as exc:
                _load_error = f"{type(exc).__name__}: {exc}"
                raise RuntimeError(f"face engine unavailable ({_load_error})") from exc
    return _engine


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def enroll(photo_bgr) -> np.ndarray | None:
    """Reference embedding from an enrollment photo — the largest face."""
    faces = _get().embeddings(photo_bgr)
    if not faces:
        return None
    faces.sort(key=lambda f: (f[0][2] - f[0][0]) * (f[0][3] - f[0][1]), reverse=True)
    return faces[0][1]


def match(frame_bgr, refs, threshold: float = MATCH_THRESHOLD):
    """Match every face in a frame against enrolled person refs.

    refs: list of dicts {id, label, reason, emb (np.float32 512-d)}.
    Returns best match per ref above threshold:
      [{id, label, reason, sim, box:(x1,y1,x2,y2)}]
    """
    if not refs:
        return []
    faces = _get().embeddings(frame_bgr)
    if not faces:
        return []
    results = []
    for ref in refs:
        remb = ref.get("emb")
        if remb is None:
            continue
        best_sim, best_box = 0.0, None
        for box, femb in faces:
            s = cosine(remb, femb)
            if s > best_sim:
                best_sim, best_box = s, box
        if best_box is not None and best_sim >= threshold:
            x1, y1, x2, y2 = (int(v) for v in best_box)
            results.append({
                "id": ref.get("id"), "label": ref.get("label"),
                "reason": ref.get("reason"), "sim": round(best_sim, 3),
                "box": (x1, y1, x2, y2),
            })
    return results


def emb_to_bytes(emb: np.ndarray) -> bytes:
    return np.asarray(emb, dtype=np.float32).tobytes()


def bytes_to_emb(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


if __name__ == "__main__":
    import sys

    import cv2

    print("status:", load_status())
    e = enroll(cv2.imread(sys.argv[1]))
    print("enrolled emb:", None if e is None else e.shape)
    print("loaded:", load_status())
