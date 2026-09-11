"""Primary provider adapter (RapidAPI RTO / SurePass shape).

Two modes, selected automatically:
  RapidAPI mode (when RAPIDAPI_HOST + key are configured):
    POST {base}/getVehicleInfo
    headers: x-rapidapi-key, x-rapidapi-host, Content-Type: application/json
    body: {"vehicle_no": "MH02AB1234", "consent": "Y",
           "consent_text": "I hereby give my consent ..."}
  Generic mode (any other vendor):
    POST {base}/challan with Bearer token.
The normaliser accepts both shapes, so vendor field renames do not break the API.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

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


class PrimaryProvider(BaseChallanProvider):
    name = "primary"

    def __init__(self, settings: Settings, client: Optional[httpx.AsyncClient] = None) -> None:
        self._settings = settings
        self._client = client
        self._owns_client = client is None

    def _use_mock(self) -> bool:
        if self._settings.mock_providers:
            return True
        # Live if either generic base_url or RapidAPI host+key is present.
        if self._settings.is_rapidapi_primary():
            return False
        return not self._settings.primary_provider_base_url

    def _is_rapidapi(self) -> bool:
        return self._settings.is_rapidapi_primary()

    async def _request(
        self,
        vehicle_number: str,
        chassis_number: Optional[str],
        engine_number: Optional[str],
    ) -> httpx.Response:
        client = self._client or httpx.AsyncClient(timeout=self._settings.primary_provider_timeout_s)
        try:
            if self._is_rapidapi():
                base = self._settings.effective_rapidapi_base_url
                path = (self._settings.rapidapi_path or "/getVehicleInfo").strip() or "/getVehicleInfo"
                if not path.startswith("/"):
                    path = f"/{path}"
                return await client.post(
                    f"{base}{path}",
                    json={
                        "vehicle_no": vehicle_number,
                        "consent": "Y",
                        "consent_text": "I hereby give my consent for vehicle information fetch",
                    },
                    headers={
                        "x-rapidapi-key": self._settings.effective_rapidapi_key,
                        "x-rapidapi-host": self._settings.effective_rapidapi_host,
                        "Content-Type": "application/json",
                    },
                )
            return await client.post(
                f"{self._settings.primary_provider_base_url.rstrip('/')}/challan",
                json={
                    "vehicle_number": vehicle_number,
                    "chassis_number": chassis_number,
                    "engine_number": engine_number,
                },
                headers={"Authorization": f"Bearer {self._settings.primary_provider_api_key}"} if self._settings.primary_provider_api_key else {},
            )
        finally:
            if self._owns_client:
                await client.aclose()

    async def fetch_fines(
        self,
        vehicle_number: str,
        chassis_number: Optional[str] = None,
        engine_number: Optional[str] = None,
    ) -> dict[str, Any]:
        if self._use_mock():
            log.info("primary provider mock hit", extra={"vehicle": vehicle_number})
            return mock_payload(vehicle_number, provider="primary")

        attempts = max(1, self._settings.retry_max_attempts)

        @retry(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=self._settings.retry_base_delay_s, min=1, max=10),
            retry=retry_if_exception_type(TransientProviderError),
            reraise=True,
        )
        async def _do() -> dict[str, Any]:
            try:
                resp = await self._request(vehicle_number, chassis_number, engine_number)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                raise TransientProviderError(f"primary network error: {exc}") from exc
            except httpx.HTTPError as exc:
                raise TransientProviderError(f"primary http error: {exc}") from exc
            if is_retryable_status(resp.status_code):
                raise TransientProviderError(f"primary retryable status {resp.status_code}")
            if 400 <= resp.status_code < 500:
                raise PermanentProviderError(f"primary rejected request ({resp.status_code})")
            try:
                data = resp.json()
            except ValueError as exc:
                raise PermanentProviderError(f"primary returned non-JSON: {exc}") from exc
            if not isinstance(data, dict):
                raise PermanentProviderError("primary returned unexpected payload")
            return data

        return await _do()

    async def health_check(self) -> dict[str, Any]:
        if self._use_mock():
            return {"name": "primary", "status": "up (mock)", "mock": True}
        if self._is_rapidapi():
            # No cheap unauthenticated health endpoint on RapidAPI; report
            # wiring without burning quota.
            return {
                "name": "primary",
                "status": "up (rapidapi configured)",
                "host": self._settings.effective_rapidapi_host,
                "mock": False,
            }
        try:
            client = self._client or httpx.AsyncClient(timeout=5.0)
            try:
                resp = await client.get(f"{self._settings.primary_provider_base_url.rstrip('/')}/health")
                return {"name": "primary", "status": "up" if resp.status_code < 500 else "degraded", "code": resp.status_code}
            finally:
                if self._owns_client:
                    await client.aclose()
        except Exception as exc:
            return {"name": "primary", "status": "down", "error": str(exc)}
