"""Thin HTTP adapters: routes -> controllers -> services.

Controllers translate domain exceptions into HTTP status codes and add
structured logs. No business logic lives here.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from app.api.v1.schemas.batch import BatchFinesRequest, BatchFinesResponse, BatchJobStatus
from app.api.v1.schemas.challan import FinesResponse
from app.core.logging import get_logger
from app.providers.base import AllProvidersFailed
from app.services.batch_service import BatchService
from app.services.vehicle_service import VehicleService
from app.utils.plate import PlateValidationError

log = get_logger(__name__)


async def get_fines_controller(
    service: VehicleService,
    registration_number: str,
    chassis_number: Optional[str],
    engine_number: Optional[str],
    force_refresh: bool,
) -> FinesResponse:
    try:
        return await service.get_fines(registration_number, chassis_number, engine_number, force_refresh)
    except PlateValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AllProvidersFailed as exc:
        raise HTTPException(status_code=502, detail=f"upstream providers unavailable: {exc}") from exc


async def create_batch_controller(service: BatchService, body: BatchFinesRequest) -> BatchFinesResponse:
    try:
        result = await service.enqueue(
            [v.model_dump() for v in body.vehicles], force_refresh=body.force_refresh
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return BatchFinesResponse(
        job_id=result["job_id"],
        status="QUEUED",  # type: ignore[arg-type]
        total=result["total"],
        message="Batch queued. Poll GET /api/v1/vehicle/batch-fines/{job_id}.",
    )


async def get_batch_controller(service: BatchService, job_id: str) -> BatchJobStatus:
    status = await service.get_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="job not found or expired")
    return status
