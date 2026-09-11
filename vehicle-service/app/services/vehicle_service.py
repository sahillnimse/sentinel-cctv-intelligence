"""Vehicle fines orchestration: validation -> cache -> providers -> normalise."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.api.v1.schemas.challan import ChallanItem, ChallanSummary, FinesResponse
from app.config import Settings
from app.core.cache import CacheClient
from app.core.logging import get_logger
from app.db import audit as audit_db
from app.providers.base import AllProvidersFailed
from app.providers.manager import ProviderManager
from app.utils.plate import normalize_plate, validate_short_id

log = get_logger(__name__)


def _status(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    if text in ("PENDING", "UNPAID", "DUE", "OPEN"):
        return "PENDING"
    if text in ("PAID", "CLOSED", "SETTLED"):
        return "PAID"
    if text in ("DISPOSED", "DISMISSED", "CONTESTED"):
        return "DISPOSED"
    return "UNKNOWN"


def _pick(d: dict, *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in d and d[key] not in (None, ""):
            return d[key]
    return default


def normalize_raw_payload(raw: dict[str, Any]) -> list[ChallanItem]:
    """Map messy vendor JSON into clean ChallanItems.

    Accepts:
      - mock/primary: {"challans": [{challan_number|challanNo, offense_details|offence, ...}]}
      - primary alt:  {"data": {"challans": [...]}} / {"violations": [...]}
      - secondary:    {"data": {"violations": [{id, reason, penalty, issued_at, city, state}]}}
      - RapidAPI RTO: {"result"|"data"|"response": {...}} with optional
        challan-like lists (challans, challan_details, pending_challans,
        blacklist_details). RC-only responses (no challan list) yield [].
    Unknown shapes yield an empty list (no crash on vendor renames).
    """
    items: list[dict[str, Any]] = []
    if not isinstance(raw, dict):
        return []
    candidates: list[Any] = [
        raw.get("challans"),
        raw.get("violations"),
        raw.get("challan_details"),
        raw.get("pending_challans"),
        raw.get("challanDetails"),
    ]
    for container_key in ("data", "result", "response", "output"):
        container = raw.get(container_key)
        if isinstance(container, dict):
            candidates.extend([
                container.get("challans"),
                container.get("violations"),
                container.get("challan_details"),
                container.get("pending_challans"),
                container.get("blacklist_details"),
                container.get("challanDetails"),
            ])
            # Some vendors nest twice: data.result.challans
            inner = container.get("result") if isinstance(container.get("result"), dict) else None
            if inner:
                candidates.extend([inner.get("challans"), inner.get("violations")])
    for cand in candidates:
        if isinstance(cand, list) and cand:
            items = cand
            break
    # Fallback to previous exact-shape logic for empty-but-present lists.
    if not items:
        if isinstance(raw.get("challans"), list):
            items = raw["challans"]
        elif isinstance(raw.get("violations"), list):
            items = raw["violations"]
        elif isinstance(raw.get("data"), dict):
            data = raw["data"]
            if isinstance(data.get("violations"), list):
                items = data["violations"]
            elif isinstance(data.get("challans"), list):
                items = data["challans"]
            elif isinstance(data.get("data"), list):
                items = data["data"]

    out: list[ChallanItem] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        out.append(
            ChallanItem(
                challan_number=str(_pick(entry, "challan_number", "challan_no", "challanNo", "id", "challanId", "challan_no", default="UNKNOWN")),
                offense_details=str(_pick(entry, "offense_details", "offence", "reason", "offense", "violation", "offence_desc", default="")),
                amount=float(_pick(entry, "amount", "fine", "penalty", "fine_amount", "total_amount", "fineAmount", default=0) or 0),
                offense_date=str(_pick(entry, "offense_date", "date", "issued_at", "offenseDate", "violation_date", "challan_date", default="")),
                location=str(_pick(entry, "location", "place", "city", "state_code", "rto", default="")),
                status=_status(_pick(entry, "status", "state", "payment_status", default="UNKNOWN")),  # type: ignore[arg-type]
            )
        )
    return out


def build_summary(challans: list[ChallanItem]) -> ChallanSummary:
    pending = [c for c in challans if c.status == "PENDING"]
    paid = [c for c in challans if c.status == "PAID"]
    return ChallanSummary(
        total_pending_challans=len(pending),
        total_pending_amount=sum(c.amount for c in pending),
        total_paid_challans=len(paid),
    )


class VehicleService:
    def __init__(self, settings: Settings, cache: CacheClient, providers: ProviderManager) -> None:
        self._settings = settings
        self._cache = cache
        self._providers = providers

    async def get_fines(
        self,
        raw_plate: str,
        chassis_number: Optional[str] = None,
        engine_number: Optional[str] = None,
        force_refresh: bool = False,
    ) -> FinesResponse:
        vehicle_number = normalize_plate(raw_plate)  # raises PlateValidationError -> 422
        chassis = validate_short_id(chassis_number, "chassis_number")
        engine = validate_short_id(engine_number, "engine_number")

        cache_key = self._cache.challan_key(vehicle_number)
        if not force_refresh:
            cached = await self._cache.get_json(cache_key)
            if isinstance(cached, dict) and cached.get("vehicle_number") == vehicle_number:
                log.info("cache hit", extra={"vehicle": vehicle_number})
                cached["cache_hit"] = True
                return FinesResponse(**cached)

        log.info("cache miss; calling providers", extra={"vehicle": vehicle_number, "force_refresh": force_refresh})
        try:
            raw, provider_name = await self._providers.fetch_with_failover(vehicle_number, chassis, engine)
        except AllProvidersFailed as exc:
            log.warning("all providers failed", extra={"vehicle": vehicle_number, "errors": exc.errors})
            raise

        challans = normalize_raw_payload(raw)
        summary = build_summary(challans)
        response = FinesResponse(
            vehicle_number=vehicle_number,
            fetched_at=datetime.now(timezone.utc),
            cache_hit=False,
            provider=provider_name,
            summary=summary,
            challans=challans,
        )
        await self._cache.set_json(cache_key, response.model_dump(mode="json"))
        try:
            audit_db.record_query(
                vehicle_number, provider_name, False,
                summary.total_pending_challans, float(summary.total_pending_amount),
            )
        except Exception:
            pass
        return response
