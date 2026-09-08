"""MOCK VAHAN + SARTHI vehicle-registry enrichment.

============================ INTEGRATION CONTRACT ============================
This is a DETERMINISTIC MOCK of the Government of India VAHAN (vehicle
registration) and SARTHI (driving licence) e-services. It ships no real data
and makes no external HTTP calls. A production deployment must replace the body
of ``enrich`` with authenticated calls to the official APIs (e.g. the Parivahan
NIC endpoints / a state-authorised RC-verification vendor) while KEEPING THE
SAME RETURN SHAPE so downstream code (clone detection, copilot, dashboards)
needs no change.

Real record fields returned by VAHAN RC lookup that this mock imitates:
    owner_name, rc_status, make, model, color, vehicle_class, fuel,
    registered_rto, registration_date, insurance_valid, puc_valid

Determinism guarantee: for any given normalized plate, the same record is
returned every time (derived from a stable hash of the plate). This keeps demos
and screenshots reproducible without a datastore.
=============================================================================
"""

import hashlib

from fastapi import APIRouter
from pydantic import BaseModel

from ..utils.plates import normalize

router = APIRouter(prefix="/vahan", tags=["vahan"])

# --- Mock reference tables --------------------------------------------------

OWNER_NAMES = [
    "Rajesh Patel", "Amit Shah", "Priya Sharma", "Kiran Desai",
    "Suresh Mehta", "Neha Joshi", "Vikram Solanki", "Anjali Trivedi",
    "Mahesh Chauhan", "Deepak Rana", "Sunita Parmar", "Harshad Vyas",
    "Bhavesh Gohil", "Ritu Makwana", "Jignesh Bhatt", "Falguni Dave",
]

# rc_status is weighted toward ACTIVE; the tail carries the interesting cases.
RC_STATUSES = (
    ["ACTIVE"] * 14 + ["EXPIRED"] * 3 + ["BLACKLISTED"] * 2 + ["STOLEN"] * 1
)

MAKES_MODELS = {
    "Maruti": ["Swift", "Alto", "Baleno", "Dzire", "Wagon R", "Ertiga"],
    "Hyundai": ["i20", "Creta", "Venue", "i10 Grand", "Verna"],
    "Tata": ["Nexon", "Punch", "Tiago", "Altroz", "Harrier"],
    "Honda": ["City", "Amaze", "Activa", "WR-V"],
    "Mahindra": ["Scorpio", "Thar", "XUV700", "Bolero"],
    "Bajaj": ["Pulsar", "Chetak", "Platina", "RE Auto"],
    "Hero": ["Splendor", "HF Deluxe", "Passion", "Xtreme"],
}
MAKES = list(MAKES_MODELS.keys())

COLORS = ["white", "silver", "black", "red", "blue", "grey"]

# vehicle_class aligned to the maker's typical output where it matters.
TWO_WHEELER_MAKES = {"Bajaj", "Hero"}
VEHICLE_CLASSES = ["LMV", "MCWG", "HMV", "Auto"]

FUELS = ["Petrol", "Diesel", "CNG", "Electric"]

# Gujarat RTO district-code -> office name.
GJ_RTO = {
    "GJ01": "Ahmedabad",
    "GJ18": "Gandhinagar",
    "GJ05": "Surat",
    "GJ06": "Vadodara",
    "GJ03": "Rajkot",
    "GJ11": "Junagadh",
    "GJ21": "Navsari",
}

# --- Hero / demo overrides --------------------------------------------------
# Clean, story-driven records for the plates used in scripted demos. These
# override the hash mock so a walkthrough always shows the intended narrative.
HERO_VAHAN = {
    "GJ01AB1234": {
        "owner_name": "Rajesh Patel",
        "rc_status": "STOLEN",
        "make": "Maruti",
        "model": "Swift",
        "color": "white",
        "vehicle_class": "LMV",
        "fuel": "Petrol",
        "registered_rto": "Ahmedabad",
        "registration_date": "2019-03-14",
        "insurance_valid": True,
        "puc_valid": False,
    },
    "GJ05CD5678": {
        "owner_name": "Neha Joshi",
        "rc_status": "ACTIVE",
        "make": "Hyundai",
        "model": "Creta",
        "color": "silver",
        "vehicle_class": "LMV",
        "fuel": "Diesel",
        "registered_rto": "Surat",
        "registration_date": "2021-07-02",
        "insurance_valid": True,
        "puc_valid": True,
    },
    "GJ18EF9012": {
        "owner_name": "Vikram Solanki",
        "rc_status": "BLACKLISTED",
        "make": "Mahindra",
        "model": "Scorpio",
        "color": "black",
        "vehicle_class": "LMV",
        "fuel": "Diesel",
        "registered_rto": "Gandhinagar",
        "registration_date": "2017-11-25",
        "insurance_valid": False,
        "puc_valid": False,
    },
}


def _digest(plate: str) -> list[int]:
    """Stable list of ints derived from the plate (deterministic per plate)."""
    h = hashlib.sha256(plate.encode("utf-8")).digest()
    return list(h)


def _pick(seq, n: int):
    return seq[n % len(seq)]


def _rto_for_plate(plate: str) -> str:
    """Map the plate's state+district prefix to a Gujarat RTO name."""
    prefix = plate[:4]  # e.g. "GJ01"
    return GJ_RTO.get(prefix, "Gujarat RTO")


def _stable_date(nums: list[int]) -> str:
    """Deterministic plausible registration date string YYYY-MM-DD."""
    year = 2012 + (nums[4] % 13)          # 2012..2024
    month = 1 + (nums[5] % 12)
    day = 1 + (nums[6] % 28)
    return f"{year:04d}-{month:02d}-{day:02d}"


def enrich(plate: str) -> dict:
    """Return a mock VAHAN/SARTHI record for ``plate``.

    Importable by other modules (clone detection, copilot, alerting). The plate
    is normalized first. Deterministic: same plate -> same record.
    """
    norm = normalize(plate)
    if not norm:
        return {
            "plate": "",
            "found": False,
            "source": "mock-vahan",
            "note": "empty plate",
        }

    if norm in HERO_VAHAN:
        rec = dict(HERO_VAHAN[norm])
        rec.update({"plate": norm, "found": True, "source": "mock-vahan-hero"})
        return rec

    n = _digest(norm)
    make = _pick(MAKES, n[3])
    model = _pick(MAKES_MODELS[make], n[7])
    if make in TWO_WHEELER_MAKES:
        vehicle_class = "Auto" if "Auto" in model or "RE" in model else "MCWG"
    else:
        vehicle_class = _pick(["LMV", "LMV", "LMV", "HMV"], n[8])

    return {
        "plate": norm,
        "found": True,
        "source": "mock-vahan",
        "owner_name": _pick(OWNER_NAMES, n[0]),
        "rc_status": _pick(RC_STATUSES, n[1]),
        "make": make,
        "model": model,
        "color": _pick(COLORS, n[2]),
        "vehicle_class": vehicle_class,
        "fuel": _pick(FUELS, n[9]),
        "registered_rto": _rto_for_plate(norm),
        "registration_date": _stable_date(n),
        "insurance_valid": bool(n[10] % 5),   # ~80% valid
        "puc_valid": bool(n[11] % 4),         # ~75% valid
    }


@router.get("/{plate}")
def get_vahan(plate: str):
    """Enriched (mock) VAHAN record for a plate."""
    return enrich(plate)


class CloneCheckIn(BaseModel):
    plate: str
    detected_color: str | None = None
    detected_type: str | None = None


# Map coarse detected vehicle_type -> plausible registry vehicle_class values.
_TYPE_TO_CLASSES = {
    "car": {"LMV"},
    "truck": {"HMV"},
    "bus": {"HMV"},
    "motorcycle": {"MCWG"},
    "vehicle": {"LMV", "MCWG", "HMV", "Auto"},  # unknown -> never a mismatch
}


@router.post("/clone-check")
def clone_check(body: CloneCheckIn):
    """Compare a live detection against the registry record.

    A "clone" (fake/duplicate plate) is suspected when the physically observed
    colour or vehicle type contradicts what the registry says for that plate.
    """
    vahan = enrich(body.plate)
    reasons: list[str] = []

    det_color = (body.detected_color or "").strip().lower()
    reg_color = str(vahan.get("color", "")).strip().lower()
    if det_color and reg_color and det_color != reg_color:
        reasons.append(
            f"colour mismatch: detected '{det_color}' vs registry '{reg_color}'"
        )

    det_type = (body.detected_type or "").strip().lower()
    if det_type:
        allowed = _TYPE_TO_CLASSES.get(det_type)
        reg_class = str(vahan.get("vehicle_class", "")).strip().upper()
        if allowed and reg_class and reg_class not in allowed:
            reasons.append(
                f"vehicle-type mismatch: detected '{det_type}' vs registry "
                f"class '{reg_class}'"
            )

    if reasons:
        return {
            "suspected_clone": True,
            "reason": "; ".join(reasons),
            "vahan": vahan,
            "detected": {"color": det_color or None, "type": det_type or None},
        }

    return {
        "suspected_clone": False,
        "reason": "detected attributes consistent with registry",
        "vahan": vahan,
        "detected": {"color": det_color or None, "type": det_type or None},
    }
