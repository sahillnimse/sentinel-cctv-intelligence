"""POST /api/v1/vehicle/batch-fines + GET /api/v1/vehicle/batch-fines/{job_id}"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app import dependencies as deps
from app.api.v1.controllers.fines_controller import create_batch_controller, get_batch_controller
from app.api.v1.schemas.batch import BatchFinesRequest, BatchFinesResponse, BatchJobStatus
from app.services.batch_service import BatchService

router = APIRouter(tags=["batch"])


@router.post("/vehicle/batch-fines", response_model=BatchFinesResponse, status_code=202)
@deps.limiter.limit("10/minute")
async def create_batch(
    request: Request,
    body: BatchFinesRequest,
    service: BatchService = Depends(deps.get_batch_service),
) -> BatchFinesResponse:
    return await create_batch_controller(service, body)


@router.get("/vehicle/batch-fines/{job_id}", response_model=BatchJobStatus)
async def get_batch(job_id: str, service: BatchService = Depends(deps.get_batch_service)) -> BatchJobStatus:
    return await get_batch_controller(service, job_id)
