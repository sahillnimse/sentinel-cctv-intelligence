"""Vehicle RTO + E-Challan trace via RapidAPI (server-side only).

The browser never sees RAPIDAPI_KEY. The frontend calls one backend endpoint
and this module fans out to both vendors in parallel with asyncio.gather.

Endpoint contracts (both POST + x-rapidapi-* headers):
  RC:      POST https://{RAPIDAPI_HOST}{RAPIDAPI_RC_PATH}
           body {"vehicle_no": "UP16CD1996", "consent": "Y", ...}
  Challan: POST https://{RAPIDAPI_CHALLAN_HOST}{RAPIDAPI_CHALLAN_PATH}
           body {"vehicle_no": "UP16CD1996", ...}

Vendor field names drift, so parsing is defensive: _dig() walks several
candidate keys and the API always returns a stable shape with per-source
ok/error flags instead of raising, except for invalid plates (422 at router).
When keys/hosts are missing, deterministic mocks shaped like the real payloads
are returned so the UI is demonstrable without billing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional

import httpx

from ..config import settings
from ..utils.plates import is_valid_indian, normalize

log = logging.getLogger("sentinel.vehicle_trace")


def sanitize_plate(raw: str) -> str:
    return normalize(raw or "")


def _strip(v: Any) -> str:
    return str(v or "").strip().strip('"').strip("'")


def _creds() -> tuple[str, str, str]:
    return (_strip(settings.rapidapi_key), _strip(settings.rapidapi_host),
            _strip(settings.rapidapi_challan_host))


def is_live() -> bool:
    key, host, challan_host = _creds()
    return bool(key and (host or challan_host))


def _headers(host: str) -> dict[str, str]:
    key, _, _ = _creds()
    return {
        "x-rapidapi-key": key,
        "x-rapidapi-host": host,
        "Content-Type": "application/json",
    }


def _dig(obj: Any, *keys: str, default: Any = None) -> Any:
    """First present non-empty value across candidate keys (dicts and lists)."""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] not in (None, ""):
                return obj[k]
    if isinstance(obj, list):
        for item in obj:
            found = _dig(item, *keys, default=None)
            if found not in (None, ""):
                return found
    return default


def _coerce_float(v: Any) -> float:
    try:
        return float(str(v).replace(",", "").replace("₹", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _status_of(v: Any) -> str:
    t = str(v or "").strip().upper()
    if t in ("PENDING", "UNPAID", "DUE", "OPEN", "ACTIVE", "NOT PAID"):
        return "PENDING" if t != "ACTIVE" else t
    if t in ("PAID", "CLOSED", "SETTLED", "DISPOSED", "RESOLVED"):
        return "PAID" if t == "PAID" else "DISPOSED" if t == "DISPOSED" else "PAID"
    if "PEND" in t:
        return "PENDING"
    if "PAID" in t or "CLOSE" in t or "SETTL" in t:
        return "PAID"
    return "PENDING" if t else "UNKNOWN"


async def _post(url: str, host: str, payload: dict) -> tuple[Optional[dict], Optional[dict]]:
    """Returns (data, error). Error is a small dict with code+message, never raised."""
    try:
        async with httpx.AsyncClient(timeout=settings.rapidapi_timeout_s) as client:
            resp = await client.post(url, json=payload, headers=_headers(host))
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        return None, {"code": "upstream_timeout", "message": f"Vendor unreachable: {exc.__class__.__name__}"}
    except httpx.HTTPError as exc:
        return None, {"code": "upstream_error", "message": f"Vendor request failed: {exc.__class__.__name__}"}
    if resp.status_code == 429:
        return None, {"code": "rate_limited", "message": "Vendor rate limit hit (429). Wait a minute and retry."}
    if resp.status_code == 404:
        return None, {"code": "endpoint_not_found",
                      "message": f"Vendor endpoint not found (404 at {url}). Check RAPIDAPI_*_PATH."}
    if resp.status_code == 403:
        return None, {"code": "forbidden", "message": "Vendor refused the key (403). Check subscription."}
    if 400 <= resp.status_code < 500:
        return None, {"code": "not_found", "message": f"Vendor has no record ({resp.status_code})."}
    if resp.status_code >= 500:
        return None, {"code": "upstream_error", "message": f"Vendor error ({resp.status_code}). Retry shortly."}
    try:
        data = resp.json()
    except ValueError:
        return None, {"code": "bad_payload", "message": "Vendor returned non-JSON."}
    if not isinstance(data, dict):
        return None, {"code": "bad_payload", "message": "Vendor returned an unexpected shape."}
    # Vendors wrap success as {"status": true/false, ...}.
    if data.get("status") is False and not _dig(data, "data", "result", "response", default=None):
        msg = str(_dig(data, "message", "error", "msg", default="Vehicle not found in RTO database."))
        return None, {"code": "not_found", "message": msg}
    return data, None


# --- mocks (no keys configured) -------------------------------------------

def mock_rc(plate: str) -> dict:
    return {
        "status": True,
        "mock": True,
        "data": {
            "registration_no": plate,
            "maker_model": "CIVIC 1.6 ZX MT (I-DTEC)",
            "rc_status": "ACTIVE",
            "body_type_desc": "SEDAN",
            "vehicle_class": "Motor Car",
            "owner_name": "RAHUL VERMA",
            "ownership": "1",
            "registration_authority": "NOIDA RTO - UP16",
            "registration_date": "2019-04-04",
            "chassis_no": "MAKFCXXXXX12345",
            "engine_no": "N15AXXXXX6789",
            "fuel_type": "Diesel",
            "fuel_norms": "BS-IV",
            "vehicle_color": "White",
            "seat_capacity": "5",
            "unload_weight": "1240",
            "vehicle_info": {"brand_name": "Honda"},
            "fitness_upto": "2034-04-03",
            "road_tax_paid_upto": "2029-04-03",
            "insurance_company": "HDFC Ergo",
            "insurance_upto": "2026-10-01",
            "puc_upto": "2026-05-20",
        },
    }


def mock_challans(plate: str) -> dict:
    return {
        "status": True,
        "mock": True,
        "data": {
            "vehicle_no": plate,
            "challans": [
                {"challan_number": "UP16567890123456", "offense": "Over-speeding",
                 "offense_date": "2026-08-01 14:30:00", "location": "Noida Expressway",
                 "amount": 1000, "status": "PENDING"},
                {"challan_number": "UP16567890123457", "offense": "Red light jump",
                 "offense_date": "2026-07-15 10:00:00", "location": "Sector 18, Noida",
                 "amount": 500, "status": "PENDING"},
            ],
        },
    }


# --- live fetchers ---------------------------------------------------------

async def fetch_rc(plate: str) -> dict:
    key, host, _ = _creds()
    if not (key and host):
        return {"ok": True, "mocked": True, "payload": mock_rc(plate)}
    url = f"https://{host}{settings.rapidapi_rc_path or '/getVehicleInfo'}"
    data, err = await _post(url, host, {
        "vehicle_no": plate, "consent": "Y",
        "consent_text": "I hereby give my consent for vehicle information fetch",
    })
    if err:
        return {"ok": False, "mocked": False, "error": err}
    return {"ok": True, "mocked": False, "payload": data}


async def fetch_challans(plate: str) -> dict:
    key, _, challan_host = _creds()
    if not (key and challan_host):
        # Fall back to RC host for challans when only one host is configured;
        # else mock. This keeps single-host deployments useful.
        _, host, _ = _creds()
        if key and host:
            url = f"https://{host}{settings.rapidapi_challan_path or '/getChallans'}"
            data, err = await _post(url, host, {"vehicle_no": plate})
            if err and err.get("code") == "endpoint_not_found":
                return {"ok": True, "mocked": True, "payload": mock_challans(plate),
                        "notice": "Challan endpoint missing on RC host; showing sample data."}
            if err:
                return {"ok": False, "mocked": False, "error": err}
            return {"ok": True, "mocked": False, "payload": data}
        return {"ok": True, "mocked": True, "payload": mock_challans(plate)}
    url = f"https://{challan_host}{settings.rapidapi_challan_path or '/getChallans'}"
    data, err = await _post(url, challan_host, {"vehicle_no": plate, "vehicle_number": plate})
    if err:
        return {"ok": False, "mocked": False, "error": err}
    return {"ok": True, "mocked": False, "payload": data}


def parse_challans(payload: Optional[dict]) -> tuple[list[dict], dict]:
    """Normalize vendor challan JSON -> (items, summary). Never raises."""
    raw_list: Any = []
    if isinstance(payload, dict):
        for container_key in ("data", "result", "response"):
            container = payload.get(container_key)
            if isinstance(container, dict):
                for k in ("challans", "challan_details", "pending_challans", "violations", "list"):
                    if isinstance(container.get(k), list):
                        raw_list = container[k]
                        break
            if raw_list:
                break
        if not raw_list:
            for k in ("challans", "challan_details", "violations"):
                if isinstance(payload.get(k), list):
                    raw_list = payload[k]
                    break
    items: list[dict] = []
    for e in raw_list if isinstance(raw_list, list) else []:
        if not isinstance(e, dict):
            continue
        amount = _coerce_float(_dig(e, "amount", "fine", "penalty", "fine_amount", "total_amount", default=0))
        status = _status_of(_dig(e, "status", "state", "payment_status", default="PENDING"))
        items.append({
            "challan_number": str(_dig(e, "challan_number", "challan_no", "challanNo", "id", default="UNKNOWN")),
            "offense": str(_dig(e, "offense", "offence", "reason", "violation", "offense_details", default="—")),
            "offense_date": str(_dig(e, "offense_date", "date", "issued_at", "violation_date", "challan_date", default="")),
            "location": str(_dig(e, "location", "place", "city", "jurisdiction", default="—")),
            "amount": amount,
            "status": status,
        })
    pending = [i for i in items if i["status"] == "PENDING"]
    summary = {"pending_count": len(pending),
               "pending_amount": sum(i["amount"] for i in pending),
               "total_count": len(items)}
    return items, summary


async def fetch_trace(plate_raw: str, db=None, refresh: bool = False) -> dict:
    plate = sanitize_plate(plate_raw)
    if db is not None and not refresh:
        hit = _cache_get(db, plate)
        if hit is not None:
            rc_res, ch_block, stored_at = hit
            return {
                "plate": plate,
                "rc": rc_res,
                "challans": ch_block,
                "meta": {"mocked": bool(rc_res.get("mocked") or ch_block.get("mocked")),
                         "duration_ms": 0, "live": is_live(),
                         "cached": True, "cached_at": stored_at},
            }
    started = time.monotonic()
    rc_res, ch_res = await asyncio.gather(fetch_rc(plate), fetch_challans(plate))
    items, summary = parse_challans((ch_res.get("payload") if ch_res.get("ok") else None))
    ms = int((time.monotonic() - started) * 1000)
    ch_block = {"ok": ch_res.get("ok", False), "mocked": ch_res.get("mocked", False),
                "error": ch_res.get("error"), "notice": ch_res.get("notice"),
                "items": items, "summary": summary,
                "raw_status": (ch_res.get("payload") or {}).get("status") if isinstance(ch_res.get("payload"), dict) else None}
    if db is not None and (rc_res.get("ok") or ch_block.get("ok")):
        _cache_put(db, plate, rc_res, ch_block)
    return {
        "plate": plate,
        "rc": rc_res,
        "challans": ch_block,
        "meta": {"mocked": bool(rc_res.get("mocked") or ch_block.get("mocked")),
                 "duration_ms": ms, "live": is_live(),
                 "cached": False, "cached_at": None},
    }


def _cache_get(db, plate: str):
    """Fresh cached (rc, challans, stored_at) or None. Fail-open: any cache
    problem (including a missing table before restart) falls through to live."""
    try:
        from ..models import VehicleTraceCache
        row = db.get(VehicleTraceCache, plate)
        if row is None:
            return None
        age = (datetime.utcnow() - (row.updated_at or datetime.utcnow())).total_seconds()
        if age > max(60, settings.vehicle_trace_cache_ttl_s):
            return None
        return json.loads(row.rc_json), json.loads(row.challans_json), row.updated_at.isoformat()
    except Exception as exc:
        log.warning("trace cache read failed for %s: %s", plate, exc)
        return None


def _cache_put(db, plate: str, rc_res: dict, ch_block: dict) -> None:
    try:
        from ..models import VehicleTraceCache
        row = db.get(VehicleTraceCache, plate)
        payload_rc = json.dumps(rc_res, default=str)
        payload_ch = json.dumps(ch_block, default=str)
        if row is None:
            db.add(VehicleTraceCache(plate=plate, rc_json=payload_rc,
                                     challans_json=payload_ch, updated_at=datetime.utcnow()))
        else:
            row.rc_json = payload_rc
            row.challans_json = payload_ch
            row.updated_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        log.warning("trace cache write failed for %s: %s", plate, exc)
        try:
            db.rollback()
        except Exception:
            pass


def validate_plate_or_raise(plate_raw: str) -> str:
    plate = sanitize_plate(plate_raw)
    if not plate:
        raise ValueError("Registration number is required.")
    if not 6 <= len(plate) <= 13 or not is_valid_indian(plate):
        raise ValueError(f"Invalid registration number '{(plate_raw or '').strip()}'. Expected MH02AB1234 / UP16CD1996 / 21BH1234AA.")
    return plate
