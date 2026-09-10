"""Standalone ONNX inference for the Awiros/anpr-ocr PP-OCRv5 recognition model.

Pure onnxruntime + cv2 + numpy — no Paddle dependencies.

Usage:
    ocr = AwirosOCR(model_path, dict_path)
    text, conf = ocr.read(crop_bgr)
"""
from __future__ import annotations

import cv2
import numpy as np
import onnxruntime as ort

# Model input shape (C, H, W) — fixed at export time.
_INPUT_SHAPE = (3, 48, 320)


class AwirosOCR:
    def __init__(self, model_path: str, dict_path: str, num_threads: int = 0,
                 providers=None):
        if providers is None:
            from ..utils.device import onnx_providers

            providers = onnx_providers()
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # Critical: the model's weights/activations produce denormal floats,
        # which make fp32 convs ~200x slower on x86 without this flag.
        so.add_session_config_entry("session.set_denormal_as_zero", "1")
        if num_threads > 0:
            so.intra_op_num_threads = num_threads
        self.session = ort.InferenceSession(
            model_path, sess_options=so, providers=providers
        )
        self.input_name = self.session.get_inputs()[0].name

        # CTC character map: index 0 = blank, then dict chars, then space
        # (matches PaddleOCR CTCLabelDecode with use_space_char=True).
        with open(dict_path, "r", encoding="utf-8") as f:
            chars = [line.rstrip("\n\r") for line in f if line.rstrip("\n\r")]
        self.characters = ["blank"] + chars + [" "]

    def _preprocess(self, img_bgr: np.ndarray) -> np.ndarray:
        _, h, w = _INPUT_SHAPE
        ih, iw = img_bgr.shape[:2]
        new_w = min(int(iw * h / ih), w)
        new_w = max(new_w, 1)
        resized = cv2.resize(img_bgr, (new_w, h))
        if new_w < w:
            padded = np.zeros((h, w, 3), dtype=np.uint8)
            padded[:, :new_w, :] = resized
            resized = padded
        img = resized.astype(np.float32) / 255.0
        img = (img - 0.5) / 0.5
        return img.transpose((2, 0, 1))[np.newaxis, ...]

    def _ctc_decode(self, probs: np.ndarray) -> tuple[str, float]:
        # probs: (T, num_classes), already softmaxed by the model head.
        idx = probs.argmax(axis=1)
        conf = probs[np.arange(len(idx)), idx]
        # collapse repeats, then drop blanks (index 0)
        keep = np.ones(len(idx), dtype=bool)
        keep[1:] = idx[1:] != idx[:-1]
        keep &= idx != 0
        if not keep.any():
            return "", 0.0
        chars = [self.characters[i] for i in idx[keep]]
        return "".join(chars), float(conf[keep].mean())

    def read(self, crop_bgr: np.ndarray) -> tuple[str, float]:
        """Recognize text in a BGR plate crop. Returns (text, confidence)."""
        if crop_bgr is None or crop_bgr.size == 0:
            return "", 0.0
        if crop_bgr.ndim == 2:
            crop_bgr = cv2.cvtColor(crop_bgr, cv2.COLOR_GRAY2BGR)
        x = self._preprocess(crop_bgr)
        out = self.session.run(None, {self.input_name: x})[0]  # (1, T, C)
        return self._ctc_decode(out[0])
