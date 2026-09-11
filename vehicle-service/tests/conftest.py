"""Shared fixtures: isolated settings + fakeredis-backed cache."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.core.cache import CacheClient


@pytest.fixture
def settings() -> Settings:
    return Settings(
        redis_url="redis://localhost:6379/0",
        cache_ttl_seconds=60,
        mock_providers=True,
        retry_max_attempts=2,
        retry_base_delay_s=0.01,
        circuit_failure_threshold=2,
        circuit_recovery_timeout_s=60.0,
        batch_max_vehicles=5,
        batch_job_ttl_seconds=60,
        database_url="",
    )


@pytest.fixture
def fake_redis():
    from fakeredis.aioredis import FakeRedis

    return FakeRedis(decode_responses=True)


@pytest.fixture
def cache(settings: Settings, fake_redis) -> CacheClient:
    client = CacheClient(settings)
    client._redis = fake_redis  # inject fake; avoids real network
    return client
