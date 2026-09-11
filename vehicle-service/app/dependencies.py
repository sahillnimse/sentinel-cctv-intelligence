"""Shared FastAPI dependencies (singletons wired at startup)."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import Settings, get_settings
from app.core.cache import CacheClient
from app.providers.manager import ProviderManager
from app.providers.primary_provider import PrimaryProvider
from app.providers.secondary_provider import SecondaryProvider
from app.services.batch_service import BatchService
from app.services.vehicle_service import VehicleService

settings: Settings = get_settings()
limiter = Limiter(key_func=get_remote_address)

cache = CacheClient(settings)
primary = PrimaryProvider(settings)
secondary = SecondaryProvider(settings)
provider_manager = ProviderManager([primary, secondary], settings)
vehicle_service = VehicleService(settings, cache, provider_manager)
batch_service = BatchService(settings, cache, vehicle_service)


def get_vehicle_service() -> VehicleService:
    return vehicle_service


def get_batch_service() -> BatchService:
    return batch_service


def get_cache() -> CacheClient:
    return cache


def get_provider_manager() -> ProviderManager:
    return provider_manager
