"""Unified e-challan response schemas (Pydantic v2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChallanItem(BaseModel):
    challan_number: str
    offense_details: str = ""
    amount: float = 0
    offense_date: str = ""
    location: str = ""
    status: Literal["PENDING", "PAID", "DISPOSED", "UNKNOWN"] = "UNKNOWN"


class ChallanSummary(BaseModel):
    total_pending_challans: int = 0
    total_pending_amount: float = 0
    total_paid_challans: int = 0


class FinesResponse(BaseModel):
    vehicle_number: str
    fetched_at: datetime
    cache_hit: bool
    provider: str = "cache"
    summary: ChallanSummary
    challans: list[ChallanItem] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    detail: str
