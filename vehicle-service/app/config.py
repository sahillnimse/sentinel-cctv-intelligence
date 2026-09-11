"""Centralised environment-driven configuration.

All values are overridable via environment variables or a `.env` file.
Strict handling: the app fails fast on invalid values (pydantic validation)
instead of silently using wrong defaults.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # vehicle-service/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    # --- app ---
    app_name: str = "vehicle-challan-service"
    app_env: str = Field(default="local", description="local | staging | production")
    app_version: str = "1.0.0"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"

    # --- redis cache ---
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 86400  # 24h default
    cache_key_prefix: str = "vehicle:challan"
    batch_key_prefix: str = "vehicle:batch"
    redis_timeout_s: float = 5.0

    # --- primary provider (e.g. SurePass / RapidAPI) ---
    primary_provider_name: str = "primary"
    primary_provider_base_url: str = ""
    primary_provider_api_key: str = ""
    primary_provider_timeout_s: float = 8.0
    # RapidAPI RTO variant (https://<host>/getVehicleInfo with
    # x-rapidapi-key / x-rapidapi-host headers). When RAPIDAPI_HOST is set
    # it takes precedence for the primary provider wiring.
    rapidapi_key: str = ""
    rapidapi_host: str = ""
    rapidapi_base_url: str = ""
    rapidapi_path: str = "/getVehicleInfo"

    # --- secondary provider (e.g. Attestr / Cashfree) ---
    secondary_provider_name: str = "secondary"
    secondary_provider_base_url: str = ""
    secondary_provider_api_key: str = ""
    secondary_provider_timeout_s: float = 8.0

    # --- resiliency ---
    retry_max_attempts: int = 3
    retry_base_delay_s: float = 1.0
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout_s: float = 60.0

    # --- rate limiting (slowapi, per-IP) ---
    rate_limit_per_minute: int = 60
    rate_limit_batch_per_minute: int = 10

    # --- batch ---
    batch_max_vehicles: int = 50
    batch_job_ttl_seconds: int = 86400

    # --- audit db (optional postgres; empty disables) ---
    database_url: str = ""

    # --- dev/testing ---
    # When true (or when provider URLs/keys are empty) providers return
    # deterministic mock payloads instead of calling the network. This keeps
    # local dev, CI and health checks bill-free. Never enable in production
    # with real keys configured — real calls take precedence when URLs exist
    # unless this is explicitly true.
    mock_providers: bool = False

    @field_validator("cache_ttl_seconds", "batch_job_ttl_seconds")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be positive")
        return v

    @field_validator("log_level")
    @classmethod
    def _log_level(cls, v: str) -> str:
        return v.upper()

    # -- RapidAPI helpers -------------------------------------------------
    @property
    def effective_rapidapi_host(self) -> str:
        return (self.rapidapi_host or "").strip().strip('"').strip("'")

    @property
    def effective_rapidapi_key(self) -> str:
        return (self.rapidapi_key or self.primary_provider_api_key or "").strip().strip('"').strip("'")

    @property
    def effective_rapidapi_base_url(self) -> str:
        if self.rapidapi_base_url.strip():
            return self.rapidapi_base_url.strip().rstrip("/")
        if self.primary_provider_base_url.strip():
            return self.primary_provider_base_url.strip().rstrip("/")
        if self.effective_rapidapi_host:
            return f"https://{self.effective_rapidapi_host}"
        return ""

    def is_rapidapi_primary(self) -> bool:
        host = self.effective_rapidapi_host.lower()
        base = (self.effective_rapidapi_base_url or "").lower()
        return bool(self.effective_rapidapi_key) and ("rapidapi" in host or "rapidapi" in base)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
