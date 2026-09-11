"""Cache layer + service-level caching behaviour."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.providers.base import mock_payload
from app.providers.manager import ProviderManager
from app.providers.primary_provider import PrimaryProvider
from app.services.vehicle_service import VehicleService


async def test_cache_key_format(cache) -> None:
    assert cache.challan_key("MH02AB1234") == "vehicle:challan:MH02AB1234"


async def test_cache_roundtrip(cache) -> None:
    assert await cache.get_json("missing") is None
    assert await cache.set_json("k", {"a": 1}, ttl=60) is True
    assert await cache.get_json("k") == {"a": 1}


async def test_cache_get_failure_is_miss(settings) -> None:
    from app.core.cache import CacheClient

    broken = CacheClient(settings)
    broken._redis = AsyncMock()
    broken._redis.get.side_effect = ConnectionError("down")
    assert await broken.get_json("x") is None

    broken._redis.set.side_effect = ConnectionError("down")
    assert await broken.set_json("x", {"a": 1}) is False


async def test_service_caches_and_hits(settings, cache) -> None:
    primary = PrimaryProvider(settings)  # mock mode
    manager = ProviderManager([primary], settings)
    service = VehicleService(settings, cache, manager)

    first = await service.get_fines("MH02AB1234")
    assert first.cache_hit is False
    assert first.vehicle_number == "MH02AB1234"
    assert first.summary.total_pending_challans == 2
    assert first.summary.total_pending_amount == 1500
    assert first.summary.total_paid_challans == 1
    assert len(first.challans) == 3

    # Second call must come from cache even if providers now explode.
    manager.fetch_with_failover = AsyncMock(side_effect=AssertionError("should not be called"))
    second = await service.get_fines("mh 02 ab 1234")
    assert second.cache_hit is True
    assert second.vehicle_number == "MH02AB1234"


async def test_force_refresh_bypasses_cache(settings, cache) -> None:
    primary = PrimaryProvider(settings)
    manager = ProviderManager([primary], settings)
    service = VehicleService(settings, cache, manager)

    await service.get_fines("DL01C1234")
    calls = {"n": 0}
    orig = manager.fetch_with_failover

    async def counting(*a, **k):
        calls["n"] += 1
        return await orig(*a, **k)

    manager.fetch_with_failover = counting  # type: ignore[method-assign]
    refreshed = await service.get_fines("DL01C1234", force_refresh=True)
    assert refreshed.cache_hit is False
    assert calls["n"] == 1


async def test_normalize_secondary_shape(settings, cache) -> None:
    from app.providers.secondary_provider import SecondaryProvider

    secondary = SecondaryProvider(settings)
    manager = ProviderManager([secondary], settings)
    service = VehicleService(settings, cache, manager)
    resp = await service.get_fines("KA05MN1234")
    assert resp.summary.total_pending_challans == 2
    assert resp.challans[0].challan_number == "MH12345678"


async def test_mock_payload_shape() -> None:
    payload = mock_payload("MH02AB1234", provider="primary")
    assert payload["vehicle_number"] == "MH02AB1234"
    assert len(payload["challans"]) == 3
