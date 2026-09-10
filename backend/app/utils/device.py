"""Where inference runs: CUDA when it genuinely works, CPU otherwise.

Every model in the process goes through here so the whole pipeline agrees on
one device, resolved once and logged once.

The reason this is a probe and not a capability check: onnxruntime-gpu lists
``CUDAExecutionProvider`` in ``get_available_providers()`` purely because it was
compiled with it. If the CUDA or cuDNN DLLs are missing at runtime, session
creation fails or silently falls back, and the only symptom is that everything
is mysteriously slow. So we build a throwaway session and confirm it really
placed work on the GPU before telling the rest of the app it has one.

INFERENCE_DEVICE controls it:
    auto   use CUDA if the probe passes, else CPU (the default)
    cuda   require CUDA, and log loudly if the probe fails
    cpu    never touch the GPU
"""

import logging
import os
import sys
import threading
from pathlib import Path

from ..config import settings

log = logging.getLogger("sentinel.device")

_lock = threading.Lock()
_resolved: dict | None = None
_dll_dirs_added = False


def _load_bundled_cuda_libraries() -> int:
    """Make the pip-installed NVIDIA libraries loadable on Windows.

    The nvidia-* wheels drop their DLLs under site-packages/nvidia/**/bin, a
    directory on no search path at all. Two things are needed:

    1. os.add_dll_directory, so the directories are searchable.
    2. Preloading each DLL by absolute path with ctypes.

    The second is the one that actually matters. add_dll_directory only affects
    loads that opt into LOAD_LIBRARY_SEARCH_USER_DIRS; it does not cover the
    loader resolving a dependency *of* a DLL, which is what happens when
    onnxruntime_providers_cuda.dll asks for cublasLt64_13.dll. Once a library
    is already in the process by absolute path, the loader matches it by module
    name and the dependency resolves. Without this the CUDA provider is
    rejected with a message that reads like the toolkit is missing when it is
    sitting in the virtualenv.

    Repeated passes because these libraries depend on each other and the first
    pass loads them in directory order, not dependency order.

    No-op off Windows, where the wheels carry an rpath.
    """
    global _dll_dirs_added
    if _dll_dirs_added or not sys.platform.startswith("win"):
        return 0
    _dll_dirs_added = True

    import ctypes

    files: list[Path] = []
    for site_dir in {Path(p) for p in sys.path if p and Path(p).name == "site-packages"}:
        nvidia = site_dir / "nvidia"
        if nvidia.is_dir():
            files.extend(nvidia.rglob("*.dll"))
    if not files:
        return 0

    for directory in {f.parent for f in files}:
        try:
            os.add_dll_directory(str(directory))
        except OSError:
            pass

    pending, loaded = list(files), 0
    while pending:
        still_failing = []
        for dll in pending:
            try:
                ctypes.WinDLL(str(dll))
                loaded += 1
            except OSError:
                still_failing.append(dll)
        if len(still_failing) == len(pending):
            break  # no progress this pass, the rest are genuinely unloadable
        pending = still_failing

    log.debug("preloaded %d of %d bundled CUDA libraries", loaded, len(files))
    return loaded


def _cuda_options() -> dict:
    """Provider options tuned for a small consumer card.

    All 30-odd camera workers share one InferenceSession, so there is a single
    arena rather than one per thread. On a 4 GB card the default exhaustive
    convolution search can still spike past what is free, so the search is
    capped and the arena is bounded when CUDA_MEM_LIMIT_MB is set.
    """
    opts = {
        "device_id": settings.cuda_device_id,
        # EXHAUSTIVE benchmarks every algorithm on first use. That costs seconds
        # of warmup per input shape and transient memory we do not have.
        "cudnn_conv_algo_search": "HEURISTIC",
        "arena_extend_strategy": "kSameAsRequested",
    }
    if settings.cuda_mem_limit_mb > 0:
        opts["gpu_mem_limit"] = settings.cuda_mem_limit_mb * 1024 * 1024
    return opts


def _probe_cuda() -> tuple[bool, str]:
    """Actually run a tiny graph on the GPU. Returns (ok, detail)."""
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as exc:
        return False, f"onnxruntime not installed ({exc})"

    if "CUDAExecutionProvider" not in ort.get_available_providers():
        return False, ("this onnxruntime build has no CUDA provider — install "
                       "onnxruntime-gpu (see requirements-ml.txt)")

    _load_bundled_cuda_libraries()

    # Smallest possible real graph: one Relu. Enough to force provider
    # initialisation, which is where a missing cuDNN shows up.
    try:
        from onnx import TensorProto, helper

        node = helper.make_node("Relu", ["x"], ["y"])
        graph = helper.make_graph(
            [node], "probe",
            [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 4])],
            [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 4])],
        )
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
        sess = ort.InferenceSession(
            model.SerializeToString(),
            providers=[("CUDAExecutionProvider", _cuda_options()), "CPUExecutionProvider"],
        )
        if "CUDAExecutionProvider" not in sess.get_providers():
            return False, "CUDA provider was rejected at session creation"
        sess.run(None, {"x": np.zeros((1, 4), dtype=np.float32)})
        return True, "ok"
    except Exception as exc:  # noqa: BLE001 - any failure means fall back
        return False, f"{type(exc).__name__}: {exc}"


def _resolve() -> dict:
    global _resolved
    with _lock:
        if _resolved is not None:
            return _resolved

        want = (settings.inference_device or "auto").strip().lower()
        if want not in ("auto", "cuda", "cpu"):
            log.warning("INFERENCE_DEVICE=%r is not auto/cuda/cpu — using auto", want)
            want = "auto"

        if want == "cpu":
            _resolved = {"device": "cpu", "providers": ["CPUExecutionProvider"],
                         "detail": "INFERENCE_DEVICE=cpu"}
            log.info("inference device: CPU (pinned by configuration)")
            return _resolved

        ok, detail = _probe_cuda()
        if ok:
            _resolved = {
                "device": "cuda",
                "providers": [("CUDAExecutionProvider", _cuda_options()),
                              "CPUExecutionProvider"],
                "detail": detail,
            }
            log.info("inference device: CUDA (device_id=%s)", settings.cuda_device_id)
        else:
            _resolved = {"device": "cpu", "providers": ["CPUExecutionProvider"],
                         "detail": detail}
            if want == "cuda":
                # Asked for the GPU and did not get it. Never silently degrade:
                # the whole point of setting this is knowing which you got.
                log.error("INFERENCE_DEVICE=cuda but CUDA is unusable, running on "
                          "CPU instead: %s", detail)
            else:
                log.info("inference device: CPU (%s)", detail)
        return _resolved


def onnx_providers() -> list:
    """Provider list to hand to any onnxruntime InferenceSession."""
    return list(_resolve()["providers"])


def active_device() -> str:
    """'cuda' or 'cpu' — what inference is actually running on."""
    return _resolve()["device"]


def torch_device() -> str:
    """Device string for the torch-based face engine.

    Kept in step with the ONNX choice so one setting governs both, but checked
    against torch separately: the ONNX GPU build and a CUDA torch build are
    independent installs and either can be missing.
    """
    if active_device() != "cuda":
        return "cpu"
    try:
        import torch
    except ImportError:
        return "cpu"
    if not torch.cuda.is_available():
        log.warning("ONNX is on CUDA but this torch build is CPU-only — the face "
                    "engine will run on CPU. Install a CUDA torch build to move it.")
        return "cpu"
    return f"cuda:{settings.cuda_device_id}"


def status() -> str:
    """One-line description for the operations console."""
    r = _resolve()
    if r["device"] == "cuda":
        return f"cuda:{settings.cuda_device_id}"
    return "cpu" if r["detail"] == "ok" else f"cpu ({r['detail']})"


def reset_for_tests() -> None:
    """Drop the cached resolution. Tests change settings between cases."""
    global _resolved
    with _lock:
        _resolved = None
