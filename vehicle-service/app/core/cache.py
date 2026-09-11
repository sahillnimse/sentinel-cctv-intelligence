"""Async Redis cache client with JSON helpers and graceful degradation."""

from __future__ import annotations

import json
from typing import Any, Optional

from app.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)


class CacheClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._redis = None  # lazy: avoids connecting at import time

    def _client(self):  # type: ignore[no-untyped-def]
        if self._redis is None:
            from redis import asyncio as aioredis

            self._redis = aioredis.from_url(
                self._settings.redis_url,
                socket_connect_timeout=self._settings.redis_timeout_s,
                socket_timeout=self._settings.redis_timeout_s,
                decode_responses=True,
            )
        return self._redis

    # -- key builders -----------------------------------------------------
    def challan_key(self, vehicle_number: str) -> str:
        return f"{self._settings.cache_key_prefix}:{vehicle_number}"

    def batch_key(self, job_id: str) -> str:
        return f"{self._settings.batch_key_prefix}:{job_id}"

    # -- primitives -------------------------------------------------------
    async def ping(self) -> bool:
        try:
            pong = await self._client().ping()
            return bool(pong)
        except Exception as exc:
            log.warning("redis ping failed", extra={"error": str(exc)})
            return False

    async def get_json(self, key: str) -> Optional[Any]:
        try:
            raw = await self._client().get(key)
        except Exception as exc:
            log.warning("redis GET failed; treating as miss", extra={"key": key, "error": str(exc)})
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            log.warning("redis value not JSON; treating as miss", extra={"key": key})
            return None

    async def set_json(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        ttl = ttl if ttl is not None else self._settings.cache_ttl_seconds
        try:
            await self._client().set(key, json.dumps(value, default=str), ex=ttl)
            return True
        except Exception as exc:
            log.warning("redis SET failed; continuing without cache", extra={"key": key, "error": str(exc)})
            return False

    async def delete(self, key: str) -> None:
        try:
            await self._client().delete(key)
        except Exception as exc:
            log.warning("redis DELETE failed", extra={"key": key, "error": str(exc)})

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None
