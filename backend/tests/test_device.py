"""Device selection for the inference stack.

The failure this guards against is the quiet one: a GPU that is configured,
reported as available, and not actually used. onnxruntime-gpu lists
CUDAExecutionProvider whenever it was compiled with it, whether or not the CUDA
libraries can be loaded, so availability is not evidence. Every test here is
about the difference between claiming a device and having one.

These run on any machine. Where a GPU is required to assert something, the test
adapts rather than skipping silently, so a CPU-only CI box still checks the
fallback path is correct.
"""

import pytest

from app.config import settings
from app.utils import device


@pytest.fixture(autouse=True)
def clean_device_cache():
    """The resolution is cached process-wide; these tests change the setting."""
    original = settings.inference_device
    device.reset_for_tests()
    yield
    settings.inference_device = original
    device.reset_for_tests()


def _resolve_with(value):
    settings.inference_device = value
    device.reset_for_tests()
    return device.active_device()


class TestDeviceSelection:
    def test_cpu_is_honoured_without_probing(self):
        """cpu must never touch the GPU, even on a machine that has one."""
        assert _resolve_with("cpu") == "cpu"
        assert device.onnx_providers() == ["CPUExecutionProvider"]

    def test_auto_resolves_to_something_real(self):
        """auto returns whichever device this machine can actually run on."""
        assert _resolve_with("auto") in ("cuda", "cpu")

    def test_unknown_value_falls_back_to_auto(self):
        """A typo in the env file must not crash the app or pin an odd device."""
        assert _resolve_with("gpu-please") in ("cuda", "cpu")

    def test_resolution_is_cached(self):
        """The probe builds a session; doing that per call would be costly."""
        _resolve_with("auto")
        assert device._resolve() is device._resolve()


class TestProviderList:
    def test_cpu_is_always_the_last_resort(self):
        """Whatever accelerator is chosen, CPU stays in the list behind it, so a
        single unsupported operator degrades that node instead of failing the
        whole session."""
        _resolve_with("auto")
        names = [p[0] if isinstance(p, tuple) else p for p in device.onnx_providers()]
        assert names[-1] == "CPUExecutionProvider"

    def test_cuda_carries_tuned_options(self):
        """The GPU entry must be a (name, options) pair, not a bare string.

        A bare string silently takes ONNX Runtime's defaults, which include an
        exhaustive convolution algorithm search. That costs seconds of warmup
        per input shape and transient memory a 4 GB card does not have.
        """
        if _resolve_with("auto") != "cuda":
            pytest.skip("no usable CUDA on this machine")
        cuda = device.onnx_providers()[0]
        assert isinstance(cuda, tuple)
        assert cuda[0] == "CUDAExecutionProvider"
        assert cuda[1]["cudnn_conv_algo_search"] == "HEURISTIC"

    def test_providers_returns_a_copy(self):
        """Callers pass this straight into a session; a shared mutable list
        would let one model's edit follow every later model."""
        _resolve_with("auto")
        first = device.onnx_providers()
        first.append("BogusProvider")
        assert "BogusProvider" not in device.onnx_providers()

    def test_memory_cap_is_applied_when_set(self):
        if _resolve_with("auto") != "cuda":
            pytest.skip("no usable CUDA on this machine")
        original = settings.cuda_mem_limit_mb
        try:
            settings.cuda_mem_limit_mb = 2048
            device.reset_for_tests()
            assert device.onnx_providers()[0][1]["gpu_mem_limit"] == 2048 * 1024 * 1024
        finally:
            settings.cuda_mem_limit_mb = original
            device.reset_for_tests()

    def test_no_memory_cap_by_default(self):
        if _resolve_with("auto") != "cuda":
            pytest.skip("no usable CUDA on this machine")
        if settings.cuda_mem_limit_mb == 0:
            assert "gpu_mem_limit" not in device.onnx_providers()[0][1]


class TestTorchDevice:
    def test_never_claims_cuda_when_onnx_is_on_cpu(self):
        """One setting governs both stacks, so they must not disagree."""
        _resolve_with("cpu")
        assert device.torch_device() == "cpu"

    def test_falls_back_when_torch_is_absent_or_cpu_only(self):
        """A CUDA onnxruntime and a CUDA torch are separate installs. Reporting
        a GPU for torch on the strength of the ONNX probe would crash the face
        engine on a machine with only one of the two."""
        if _resolve_with("auto") != "cuda":
            pytest.skip("no usable CUDA on this machine")
        try:
            import torch
        except ImportError:
            assert device.torch_device() == "cpu"
            return
        expected = f"cuda:{settings.cuda_device_id}" if torch.cuda.is_available() else "cpu"
        assert device.torch_device() == expected


class TestStatusReporting:
    def test_status_names_the_device(self):
        assert _resolve_with("cpu") == "cpu"
        assert device.status().startswith("cpu")

    def test_cpu_fallback_explains_itself(self):
        """When auto lands on CPU, the reason has to reach the operator. A bare
        'cpu' gives them nothing to act on."""
        if _resolve_with("auto") == "cuda":
            assert device.status() == f"cuda:{settings.cuda_device_id}"
        else:
            assert device.status() != "cpu" or device._resolve()["detail"] == "ok"


class TestProbeHonesty:
    def test_probe_runs_a_real_graph(self):
        """The whole point of the probe is that it executes, not that it asks.

        If this ever becomes a capability check again, a machine with the GPU
        wheel but no CUDA libraries will report cuda and run on CPU at a third
        of the speed with nothing in the logs.
        """
        ok, detail = device._probe_cuda()
        assert isinstance(ok, bool)
        assert detail, "the probe must always explain its verdict"
        if not ok:
            assert detail != "ok"

    def test_probe_verdict_matches_auto_resolution(self):
        ok, _ = device._probe_cuda()
        assert _resolve_with("auto") == ("cuda" if ok else "cpu")
