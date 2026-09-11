"""GET /health — verifies Redis and upstream provider connectivity."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import dependencies as deps
from app.config import Settings, get_settings
from app.core.cache import CacheClient
from app.providers.manager import ProviderManager

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    cache: CacheClient = Depends(deps.get_cache),
    manager: ProviderManager = Depends(deps.get_provider_manager),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    redis_up = await cache.ping()
    providers = []
    for provider in manager._providers:  # intentional: health reflects wiring order
        try:
            info = await provider.health_check()
        except Exception as exc:  # pragma: no cover - defensive
            info = {"name": getattr(provider, "name", "?"), "status": "down", "error": str(exc)}
        breaker = manager.breakers.get(getattr(provider, "name", ""))
        info["circuit"] = breaker.state.value if breaker else "unknown"
        providers.append(info)

    degraded = (not redis_up) or any(p.get("status") == "down" for p in providers)
    body = {
        "status": "degraded" if degraded else "ok",
        "version": settings.app_version,
        "env": settings.app_env,
        "redis": "up" if redis_up else "down",
        "providers": providers,
    }
    return JSONResponse(status_code=200 if redis_up else 503, content=body)
