"""Bulk fleet checks backed by Redis job records + asyncio background tasks.

Design: POST creates a job record (QUEUED) in Redis and schedules
`process_job` via `asyncio.create_task`. GET polls the record. Results are
stored inline in the job (fine for <= batch_max_vehicles items).

Swap-in path: replace `enqueue` with arq/celery `send_job` and keep the same
Redis schema — route/controller/schama contracts do not change.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from app.api.v1.schemas.batch import BatchJobStatus, BatchVehicleResult
from app.config import Settings
from app.core.cache import CacheClient
from app.core.logging import get_logger
from app.services.vehicle_service import VehicleService
from app.utils.plate import normalize_plate

log = get_logger(__name__)


class BatchService:
    def __init__(self, settings: Settings, cache: CacheClient, vehicle_service: VehicleService) -> None:
        self._settings = settings
        self._cache = cache
        self._vehicles = vehicle_service

    async def _read_job(self, job_id: str) -> Optional[dict]:
        data = await self._cache.get_json(self._cache.batch_key(job_id))
        return data if isinstance(data, dict) else None

    async def _write_job(self, job: dict, ttl: Optional[int] = None) -> None:
        await self._cache.set_json(
            self._cache.batch_key(job["job_id"]), job,
            ttl=ttl if ttl is not None else self._settings.batch_job_ttl_seconds,
        )

    async def enqueue(
        self,
        vehicles: list[dict],
        force_refresh: bool = False,
        start_background: bool = True,
    ) -> dict:
        if len(vehicles) > self._settings.batch_max_vehicles:
            raise ValueError(f"batch too large: max {self._settings.batch_max_vehicles}")
        job_id = uuid.uuid4().hex
        job = {
            "job_id": job_id,
            "status": "QUEUED",
            "total": len(vehicles),
            "completed": 0,
            "failed": 0,
            "results": [],
            "_pending": [
                {
                    "registration_number": v.get("registration_number", ""),
                    "chassis_number": v.get("chassis_number"),
                    "engine_number": v.get("engine_number"),
                }
                for v in vehicles
            ],
            "_force_refresh": force_refresh,
        }
        await self._write_job(job)
        log.info("batch enqueued", extra={"job_id": job_id, "total": len(vehicles)})
        if start_background:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                loop.create_task(self.process_job(job_id))
            else:
                await self.process_job(job_id)
        return {"job_id": job_id, "status": "QUEUED", "total": len(vehicles)}

    async def get_status(self, job_id: str) -> Optional[BatchJobStatus]:
        job = await self._read_job(job_id)
        if job is None:
            return None
        results = [BatchVehicleResult(**r) for r in job.get("results", [])]
        return BatchJobStatus(
            job_id=job["job_id"],
            status=job.get("status", "QUEUED"),  # type: ignore[arg-type]
            total=job.get("total", 0),
            completed=job.get("completed", 0),
            failed=job.get("failed", 0),
            results=results,
        )

    async def process_job(self, job_id: str) -> None:
        job = await self._read_job(job_id)
        if job is None:
            return
        job["status"] = "PROCESSING"
        await self._write_job(job)
        force_refresh: bool = bool(job.get("_force_refresh", False))

        for item in job.get("_pending", []):
            raw_plate: str = item.get("registration_number", "")
            try:
                normalized = normalize_plate(raw_plate)
            except Exception as exc:
                job["results"].append({
                    "registration_number": raw_plate,
                    "normalized": None,
                    "ok": False,
                    "provider": None,
                    "cache_hit": None,
                    "summary": None,
                    "challan_count": 0,
                    "error": str(exc),
                })
                job["failed"] += 1
                job["completed"] += 1
                await self._write_job(job)
                continue
            try:
                resp = await self._vehicles.get_fines(
                    raw_plate,
                    chassis_number=item.get("chassis_number"),
                    engine_number=item.get("engine_number"),
                    force_refresh=force_refresh,
                )
                job["results"].append({
                    "registration_number": raw_plate,
                    "normalized": resp.vehicle_number,
                    "ok": True,
                    "provider": resp.provider,
                    "cache_hit": resp.cache_hit,
                    "summary": resp.summary.model_dump(),
                    "challan_count": len(resp.challans),
                    "error": None,
                })
            except Exception as exc:
                job["results"].append({
                    "registration_number": raw_plate,
                    "normalized": normalized,
                    "ok": False,
                    "provider": None,
                    "cache_hit": None,
                    "summary": None,
                    "challan_count": 0,
                    "error": str(exc),
                })
                job["failed"] += 1
            job["completed"] += 1
            await self._write_job(job)

        job.pop("_pending", None)
        job.pop("_force_refresh", None)
        job["status"] = "COMPLETED" if job["failed"] == 0 else ("PARTIAL" if job["completed"] > job["failed"] else "FAILED")
        await self._write_job(job)
        log.info("batch finished", extra={"job_id": job_id, "status": job["status"]})
