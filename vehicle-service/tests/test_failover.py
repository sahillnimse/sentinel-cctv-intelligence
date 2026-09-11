"""Provider failover + circuit breaker + retry tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from app.config import Settings
from app.core.circuit_breaker import CircuitBreaker
from app.providers.base import AllProvidersFailed, PermanentProviderError, TransientProviderError
from app.providers.manager import ProviderManager
from app.providers.primary_provider import PrimaryProvider


class _Failing:
    name = "failing"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0

    async def fetch_fines(self, *a, **k):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise self._exc

    async def health_check(self):  # type: ignore[no-untyped-def]
        return {"name": self.name, "status": "down"}


class _Ok:
    name = "ok"

    def __init__(self, payload=None) -> None:
        self.payload = payload or {"challans": []}
        self.calls = 0

    async def fetch_fines(self, *a, **k):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self.payload

    async def health_check(self):  # type: ignore[no-untyped-def]
        return {"name": self.name, "status": "up"}


async def test_failover_on_transient(settings: Settings) -> None:
    failing = _Failing(TransientProviderError("primary 503"))
    ok = _Ok({"challans": []})
    manager = ProviderManager([failing, ok], settings)  # type: ignore[list-item]
    raw, name = await manager.fetch_with_failover("MH02AB1234")
    assert name == "ok"
    assert failing.calls == 1 and ok.calls == 1


async def test_failover_on_timeout(settings: Settings) -> None:
    failing = _Failing(TransientProviderError("primary timeout"))
    ok = _Ok({"challans": []})
    manager = ProviderManager([failing, ok], settings)  # type: ignore[list-item]
    _, name = await manager.fetch_with_failover("MH02AB1234")
    assert name == "ok"


async def test_failover_on_rate_limit(settings: Settings) -> None:
    failing = _Failing(TransientProviderError("primary retryable status 429"))
    ok = _Ok({"challans": []})
    manager = ProviderManager([failing, ok], settings)  # type: ignore[list-item]
    _, name = await manager.fetch_with_failover("MH02AB1234")
    assert name == "ok"


async def test_all_fail_raises(settings: Settings) -> None:
    manager = ProviderManager(  # type: ignore[list-item]
        [_Failing(TransientProviderError("a down")), _Failing(TransientProviderError("b down"))],
        settings,
    )
    with pytest.raises(AllProvidersFailed):
        await manager.fetch_with_failover("MH02AB1234")


async def test_circuit_opens_and_skips(settings: Settings) -> None:
    failing = _Failing(TransientProviderError("boom"))
    ok = _Ok({"challans": []})
    manager = ProviderManager([failing, ok], settings)  # type: ignore[list-item]
    # threshold=2 (from conftest settings): two failures open the breaker.
    await manager.fetch_with_failover("MH02AB1234")
    await manager.fetch_with_failover("MH02AB1234")
    breaker = manager.breakers["failing"]
    assert breaker.state.value == "open"
    before = failing.calls
    _, name = await manager.fetch_with_failover("MH02AB1234")
    assert name == "ok"
    assert failing.calls == before  # skipped, no extra call


def test_circuit_half_open_recovery() -> None:
    breaker = CircuitBreaker(name="t", failure_threshold=1, recovery_timeout_s=0.01)
    breaker.record_failure()
    assert breaker.state.value == "open"
    import time

    time.sleep(0.02)
    assert breaker.can_execute() is True  # half-open probe allowed
    breaker.record_success()
    assert breaker.state.value == "closed"


async def test_primary_retries_transient_then_succeeds() -> None:
    settings = Settings(
        primary_provider_base_url="https://vendor.example",
        primary_provider_api_key="k",
        rapidapi_key="",
        rapidapi_host="",
        rapidapi_base_url="",
        mock_providers=False,
        retry_max_attempts=3,
        retry_base_delay_s=0.01,
    )
    provider = PrimaryProvider(settings)
    with respx.mock(assert_all_called=False) as router:
        router.post("https://vendor.example/challan").mock(
            side_effect=[
                httpx.Response(503, json={"error": "x"}),
                httpx.Response(200, json={"challans": []}),
            ]
        )
        data = await provider.fetch_fines("MH02AB1234")
        assert data == {"challans": []}


async def test_primary_4xx_is_permanent() -> None:
    settings = Settings(
        primary_provider_base_url="https://vendor.example",
        rapidapi_key="",
        rapidapi_host="",
        rapidapi_base_url="",
        mock_providers=False,
        retry_max_attempts=2,
        retry_base_delay_s=0.01,
    )
    provider = PrimaryProvider(settings)
    with respx.mock as router:
        router.post("https://vendor.example/challan").mock(return_value=httpx.Response(400, json={}))
        with pytest.raises(PermanentProviderError):
            await provider.fetch_fines("MH02AB1234")


async def test_manager_never_crashes_on_buggy_adapter(settings: Settings) -> None:
    class Buggy:
        name = "buggy"

        async def fetch_fines(self, *a, **k):  # type: ignore[no-untyped-def]
            raise RuntimeError("bug")

        async def health_check(self):  # type: ignore[no-untyped-def]
            return {"name": "buggy", "status": "down"}

    ok = _Ok({"challans": []})
    manager = ProviderManager([Buggy(), ok], settings)  # type: ignore[list-item]
    _, name = await manager.fetch_with_failover("MH02AB1234")
    assert name == "ok"
