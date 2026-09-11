"""Failover orchestration across providers with per-provider circuit breakers."""

from __future__ import annotations

from typing import Any, Optional

from app.config import Settings
from app.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from app.core.logging import get_logger
from app.providers.base import (
    AllProvidersFailed,
    BaseChallanProvider,
    PermanentProviderError,
    TransientProviderError,
)

log = get_logger(__name__)


class ProviderManager:
    """Try providers in order; fail over on transient errors or open circuits.

    Permanent 4xx errors are NOT failed over by default for the same vehicle
    when they indicate a bad request — except we still try the next provider
    once, because vendors differ in what they accept (e.g. chassis required).
    Circuit breakers only count transient failures.
    """

    def __init__(
        self,
        providers: list[BaseChallanProvider],
        settings: Settings,
        breakers: Optional[dict[str, CircuitBreaker]] = None,
    ) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self._providers = providers
        self._settings = settings
        self._breakers: dict[str, CircuitBreaker] = breakers or {
            p.name: CircuitBreaker(
                name=p.name,
                failure_threshold=settings.circuit_failure_threshold,
                recovery_timeout_s=settings.circuit_recovery_timeout_s,
            )
            for p in providers
        }

    @property
    def breakers(self) -> dict[str, CircuitBreaker]:
        return self._breakers

    async def fetch_with_failover(
        self,
        vehicle_number: str,
        chassis_number: Optional[str] = None,
        engine_number: Optional[str] = None,
    ) -> tuple[dict[str, Any], str]:
        errors: list[str] = []
        for provider in self._providers:
            breaker = self._breakers.get(provider.name)
            if breaker is not None and not breaker.can_execute():
                msg = f"{provider.name}: circuit open, skipped"
                log.warning("provider skipped (circuit open)", extra={"provider": provider.name})
                errors.append(msg)
                continue
            try:
                raw = await provider.fetch_fines(vehicle_number, chassis_number, engine_number)
            except (TransientProviderError, PermanentProviderError) as exc:
                err = f"{provider.name}: {exc}"
                errors.append(err)
                log.warning("provider failed", extra={"provider": provider.name, "error": str(exc)})
                # Only transient failures trip the breaker.
                if isinstance(exc, TransientProviderError) and breaker is not None:
                    breaker.record_failure()
                # Fail over to next provider regardless (vendors accept
                # different optional fields), unless it was the last one.
                continue
            except CircuitOpenError as exc:
                errors.append(f"{provider.name}: {exc}")
                continue
            except Exception as exc:  # defensive: a buggy adapter must not kill failover
                errors.append(f"{provider.name}: unexpected {exc}")
                log.exception("provider unexpected error", extra={"provider": provider.name})
                if breaker is not None:
                    breaker.record_failure()
                continue
            if breaker is not None:
                breaker.record_success()
            log.info("provider succeeded", extra={"provider": provider.name, "vehicle": vehicle_number})
            return raw, provider.name
        raise AllProvidersFailed(errors)
