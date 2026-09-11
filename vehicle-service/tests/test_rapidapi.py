"""RapidAPI wiring tests (no live network; respx-mocked)."""

from __future__ import annotations

import httpx
import respx

from app.config import Settings
from app.providers.primary_provider import PrimaryProvider


def _rapid_settings(**over) -> Settings:
    base = dict(
        primary_provider_base_url="",
        primary_provider_api_key="",
        rapidapi_key="test-key",
        rapidapi_host="in-rto-vehicle-information-india.p.rapidapi.com",
        rapidapi_base_url="",
        rapidapi_path="/getVehicleInfo",
        mock_providers=False,
        retry_max_attempts=1,
        retry_base_delay_s=0.01,
    )
    base.update(over)
    return Settings(**base)


def test_is_rapidapi_primary() -> None:
    assert _rapid_settings().is_rapidapi_primary() is True
    s = _rapid_settings(rapidapi_key="", rapidapi_host="", primary_provider_base_url="")
    assert s.is_rapidapi_primary() is False


def test_rapidapi_uses_mock_when_flag_on() -> None:
    s = _rapid_settings(mock_providers=True)
    assert PrimaryProvider(s)._use_mock() is True


def test_rapidapi_live_when_configured() -> None:
    s = _rapid_settings()
    assert PrimaryProvider(s)._use_mock() is False


async def test_rapidapi_request_shape() -> None:
    s = _rapid_settings()
    provider = PrimaryProvider(s)
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://in-rto-vehicle-information-india.p.rapidapi.com/getVehicleInfo").mock(
            return_value=httpx.Response(200, json={"data": {"challans": []}})
        )
        data = await provider.fetch_fines("GJ01AB1234")
        assert data == {"data": {"challans": []}}
        req = route.calls[0].request
        assert req.headers["x-rapidapi-key"] == "test-key"
        assert req.headers["x-rapidapi-host"] == "in-rto-vehicle-information-india.p.rapidapi.com"
        import json as _json

        body = _json.loads(req.content.decode())
        assert body["vehicle_no"] == "GJ01AB1234"
        assert body["consent"] == "Y"


async def test_rapidapi_404_is_permanent() -> None:
    import pytest

    from app.providers.base import PermanentProviderError

    s = _rapid_settings()
    provider = PrimaryProvider(s)
    with respx.mock as router:
        router.post("https://in-rto-vehicle-information-india.p.rapidapi.com/getVehicleInfo").mock(
            return_value=httpx.Response(404, json={"message": "API doesn't exists"})
        )
        try:
            await provider.fetch_fines("GJ01AB1234")
            raise AssertionError("should have raised")
        except PermanentProviderError as exc:
            assert "404" in str(exc)


async def test_rapidapi_429_is_transient() -> None:
    import pytest

    from app.providers.base import TransientProviderError

    s = _rapid_settings()
    provider = PrimaryProvider(s)
    with respx.mock as router:
        router.post("https://in-rto-vehicle-information-india.p.rapidapi.com/getVehicleInfo").mock(
            return_value=httpx.Response(429, json={"message": "Too many requests"})
        )
        try:
            await provider.fetch_fines("GJ01AB1234")
            raise AssertionError("should have raised")
        except TransientProviderError as exc:
            assert "429" in str(exc)
