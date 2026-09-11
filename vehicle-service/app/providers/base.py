"""Provider-agnostic interface + shared errors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class ProviderError(Exception):
    """Base for all upstream failures."""


class TransientProviderError(ProviderError):
    """Retryable: timeouts, 5xx, 429. Eligible for retry + failover."""


class PermanentProviderError(ProviderError):
    """Non-retryable: 4xx (except 429), bad payload, auth errors."""


class AllProvidersFailed(ProviderError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors) if errors else "all providers failed")


class BaseChallanProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def fetch_fines(
        self,
        vehicle_number: str,
        chassis_number: Optional[str] = None,
        engine_number: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return the provider's RAW JSON payload. Must raise ProviderError on failure."""
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        raise NotImplementedError


def is_retryable_status(status: int) -> bool:
    return status == 429 or 500 <= status <= 599


def mock_payload(vehicle_number: str, provider: str) -> dict[str, Any]:
    """Deterministic bill-free payload used when no credentials are configured."""
    return {
        "provider": provider,
        "vehicle_number": vehicle_number,
        "mock": True,
        "challans": [
            {
                "challan_number": "MH12345678",
                "offense_details": "Driving without seatbelt",
                "amount": 500,
                "offense_date": "2026-08-01 14:30:00",
                "location": "Mumbai",
                "status": "PENDING",
            },
            {
                "challan_number": "MH87654321",
                "offense_details": "Signal jumping",
                "amount": 1000,
                "offense_date": "2026-07-15 10:00:00",
                "location": "Pune",
                "status": "PENDING",
            },
            {
                "challan_number": "MH11223344",
                "offense_details": "Overspeeding",
                "amount": 2000,
                "offense_date": "2025-12-02 09:15:00",
                "location": "Thane",
                "status": "PAID",
            },
        ],
    }
