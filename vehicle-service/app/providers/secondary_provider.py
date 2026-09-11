"""Secondary provider adapter (Attestr / Cashfree shape).

Intentionally uses a DIFFERENT raw shape to prove the normaliser:
  {"data": {"vehicle": "MH02AB1234", "violations": [
      {"id":..., "reason":..., "penalty":..., "issued_at":..., "city":..., "state":...}
  ]}}
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings
from app.core.logging import get_logger
from app.providers.base import (
    BaseChallanProvider,
    PermanentProviderError,
    TransientProviderError,
    is_retryable_status,
    mock_payload,
)

log = get_logger(__name__)


class SecondaryProvider(BaseChallanProvider):
    name = "secondary"

    def __init__(self, settings: Settings, client: Optional[httpx.AsyncClient] = None) -> None:
        self._settings = settings
        self._client = client
        self._owns_client = client is None

    def _use_mock(self) -> bool:
        return self._settings.mock_providers or not self._settings.secondary_provider_base_url

    def _to_secondary_shape(self, vehicle_number: str) -> dict[str, Any]:
        mock = mock_payload(vehicle_number, provider="secondary")
        return {
            "data": {
                "vehicle": vehicle_number,
                "violations": [
                    {
                        "id": c["challan_number"],
                        "reason": c["offense_details"],
                        "penalty": c["amount"],
                        "issued_at": c["offense_date"],
                        "city": c["location"],
                        "state": "PENDING" if c["status"] == "PENDING" else "PAID",
                    }
                    for c in mock["challans"]
                ],
            }
        }

    async def fetch_fines(
        self,
        vehicle_number: str,
        chassis_number: Optional[str] = None,
        engine_number: Optional[str] = None,
    ) -> dict[str, Any]:
        if self._use_mock():
            log.info("secondary provider mock hit", extra={"vehicle": vehicle_number})
            return self._to_secondary_shape(vehicle_number)

        attempts = max(1, self._settings.retry_max_attempts)

        @retry(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=self._settings.retry_base_delay_s, min=1, max=10),
            retry=retry_if_exception_type(TransientProviderError),
            reraise=True,
        )
        async def _do() -> dict[str, Any]:
            client = self._client or httpx.AsyncClient(timeout=self._settings.secondary_provider_timeout_s)
            try:
                try:
                    resp = await client.get(
                        f"{self._settings.secondary_provider_base_url.rstrip('/')}/fines",
                        params={"vehicle": vehicle_number},
                        headers={"X-API-Key": self._settings.secondary_provider_api_key} if self._settings.secondary_provider_api_key else {},
                    )
                except (httpx.TimeoutException, httpx.ConnectError) as exc:
                    raise TransientProviderError(f"secondary network error: {exc}") from exc
                except httpx.HTTPError as exc:
                    raise TransientProviderError(f"secondary http error: {exc}") from exc
            finally:
                if self._owns_client:
                    await client.aclose()
            if is_retryable_status(resp.status_code):
                raise TransientProviderError(f"secondary retryable status {resp.status_code}")
            if 400 <= resp.status_code < 500:
                raise PermanentProviderError(f"secondary rejected request ({resp.status_code})")
            try:
                data = resp.json()
            except ValueError as exc:
                raise PermanentProviderError(f"secondary returned non-JSON: {exc}") from exc
            if not isinstance(data, dict):
                raise PermanentProviderError("secondary returned unexpected payload")
            return data

        return await _do()

    async def health_check(self) -> dict[str, Any]:
        if self._use_mock():
            return {"name": "secondary", "status": "up (mock)", "mock": True}
        try:
            client = self._client or httpx.AsyncClient(timeout=5.0)
            try:
                resp = await client.get(f"{self._settings.secondary_provider_base_url.rstrip('/')}/health")
                return {"name": "secondary", "status": "up" if resp.status_code < 500 else "degraded", "code": resp.status_code}
            finally:
                if self._owns_client:
                    await client.aclose()
        except Exception as exc:
            return {"name": "secondary", "status": "down", "error": str(exc)}
