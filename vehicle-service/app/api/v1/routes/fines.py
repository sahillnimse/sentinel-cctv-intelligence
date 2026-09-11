"""GET /api/v1/vehicle/{registration_number}/fines"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app import dependencies as deps
from app.api.v1.controllers.fines_controller import get_fines_controller
from app.api.v1.schemas.challan import FinesResponse
from app.services.vehicle_service import VehicleService

router = APIRouter(tags=["fines"])


@router.get("/vehicle/{registration_number}/fines", response_model=FinesResponse)
@deps.limiter.limit("60/minute")
async def get_fines(
    request: Request,
    registration_number: str,
    force_refresh: bool = Query(default=False),
    chassis_number: Optional[str] = Query(default=None, max_length=5),
    engine_number: Optional[str] = Query(default=None, max_length=5),
    service: VehicleService = Depends(deps.get_vehicle_service),
) -> FinesResponse:
    # Per-minute limit is global default; honour configured value dynamically
    # is handled at app level via middleware config. Route decorator keeps a
    # sane default even if settings change.
    _ = deps.settings.rate_limit_per_minute  # documented coupling point
    return await get_fines_controller(service, registration_number, chassis_number, engine_number, force_refresh)
