"""HTTP-level tests with dependency overrides (no real Redis/network)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import dependencies as deps
from app.config import Settings
from app.core.cache import CacheClient
from app.main import create_app
from app.providers.manager import ProviderManager
from app.providers.primary_provider import PrimaryProvider
from app.services.batch_service import BatchService
from app.services.vehicle_service import VehicleService


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        redis_url="redis://localhost:6379/0",
        cache_ttl_seconds=60,
        mock_providers=True,
        retry_max_attempts=2,
        retry_base_delay_s=0.01,
        circuit_failure_threshold=5,
        circuit_recovery_timeout_s=60.0,
        batch_max_vehicles=5,
        batch_job_ttl_seconds=60,
        database_url="",
    )


@pytest.fixture
def client(test_settings: Settings):
    from fakeredis.aioredis import FakeRedis

    fake = FakeRedis(decode_responses=True)
    cache = CacheClient(test_settings)
    cache._redis = fake
    primary = PrimaryProvider(test_settings)
    from app.providers.secondary_provider import SecondaryProvider

    manager = ProviderManager([primary, SecondaryProvider(test_settings)], test_settings)
    vehicles = VehicleService(test_settings, cache, manager)
    batches = BatchService(test_settings, cache, vehicles)

    app = create_app()
    app.dependency_overrides[deps.get_cache] = lambda: cache
    app.dependency_overrides[deps.get_provider_manager] = lambda: manager
    app.dependency_overrides[deps.get_vehicle_service] = lambda: vehicles
    app.dependency_overrides[deps.get_batch_service] = lambda: batches
    # Disable rate limiting for deterministic tests.
    app.state.limiter.enabled = False
    with TestClient(app) as c:
        yield c


def test_get_fines_shape_and_summary(client: TestClient) -> None:
    resp = client.get("/api/v1/vehicle/MH02AB1234/fines")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["vehicle_number"] == "MH02AB1234"
    assert body["cache_hit"] is False
    assert body["summary"] == {
        "total_pending_challans": 2,
        "total_pending_amount": 1500,
        "total_paid_challans": 1,
    }
    assert len(body["challans"]) == 3
    first = body["challans"][0]
    assert set(first) == {"challan_number", "offense_details", "amount", "offense_date", "location", "status"}


def test_get_fines_cache_hit_second_time(client: TestClient) -> None:
    client.get("/api/v1/vehicle/DL01C1234/fines")
    resp = client.get("/api/v1/vehicle/dl 01 c 1234/fines")
    assert resp.status_code == 200
    assert resp.json()["cache_hit"] is True


def test_get_fines_force_refresh(client: TestClient) -> None:
    client.get("/api/v1/vehicle/KA05MN1234/fines")
    resp = client.get("/api/v1/vehicle/KA05MN1234/fines?force_refresh=true")
    assert resp.status_code == 200
    assert resp.json()["cache_hit"] is False


def test_get_fines_invalid_plate(client: TestClient) -> None:
    resp = client.get("/api/v1/vehicle/NOTAPLATE!!/fines")
    assert resp.status_code == 422


def test_get_fines_bad_chassis(client: TestClient) -> None:
    resp = client.get("/api/v1/vehicle/MH02AB1234/fines?chassis_number=AB")
    assert resp.status_code == 422


def test_batch_enqueue_and_poll(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/vehicle/batch-fines",
        json={"vehicles": [{"registration_number": "MH02AB1234"}, {"registration_number": "21BH1234AA"}]},
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    # Background task may still be running; poll until terminal.
    import time

    status = None
    for _ in range(50):
        poll = client.get(f"/api/v1/vehicle/batch-fines/{job_id}")
        assert poll.status_code == 200
        status = poll.json()
        if status["status"] in ("COMPLETED", "PARTIAL", "FAILED"):
            break
        time.sleep(0.05)
    assert status is not None
    assert status["total"] == 2
    assert status["completed"] == 2
    assert status["failed"] == 0
    assert len(status["results"]) == 2
    assert all(r["ok"] for r in status["results"])


def test_batch_unknown_job(client: TestClient) -> None:
    assert client.get("/api/v1/vehicle/batch-fines/nope").status_code == 404


def test_health_ok(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "redis" in body and "providers" in body
    assert len(body["providers"]) == 2
