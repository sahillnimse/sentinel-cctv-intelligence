"""Batch fleet-check schemas."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class BatchVehicleItem(BaseModel):
    registration_number: str
    chassis_number: Optional[str] = None
    engine_number: Optional[str] = None


class BatchFinesRequest(BaseModel):
    vehicles: list[BatchVehicleItem] = Field(min_length=1)
    force_refresh: bool = False


class BatchFinesResponse(BaseModel):
    job_id: str
    status: Literal["QUEUED", "PROCESSING", "COMPLETED", "PARTIAL"] = "QUEUED"
    total: int
    message: str = ""


class BatchVehicleResult(BaseModel):
    registration_number: str
    normalized: Optional[str] = None
    ok: bool
    provider: Optional[str] = None
    cache_hit: Optional[bool] = None
    summary: Optional[dict] = None
    challan_count: int = 0
    error: Optional[str] = None


class BatchJobStatus(BaseModel):
    job_id: str
    status: Literal["QUEUED", "PROCESSING", "COMPLETED", "PARTIAL", "FAILED"]
    total: int
    completed: int
    failed: int
    results: list[BatchVehicleResult] = Field(default_factory=list)
