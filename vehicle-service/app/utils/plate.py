"""Indian vehicle registration validation & standardisation.

Supported (after sanitisation):
  - Standard series: MH02AB1234, DL01C1234, KA05MN1234, GJ01RT1234
    pattern: 2 letters (state) + 1-2 digits (RTO) + 0-3 letters (series) + 4 digits
  - Legacy / short series: KA05A1 .. KA05A123 (1-4 trailing digits)
  - BH (Bharat) series: 21BH1234AA / 22BH1234A
    pattern: 2 digits (year) + BH + 4 digits + 1-2 letters

Sanitisation: strip whitespace, remove spaces/hyphens/dots, uppercase.
`chassis_number` / `engine_number`: optional, last 5 chars, alphanumeric.
"""

from __future__ import annotations

import re

STANDARD_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$")
LEGACY_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{1,4}$")
BH_RE = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")
SHORT5_RE = re.compile(r"^[A-Z0-9]{5}$")
_SANITISE_RE = re.compile(r"[\s\-\.]+")


class PlateValidationError(ValueError):
    pass


def sanitize_plate(raw: str) -> str:
    """Strip spaces/hyphens/dots and uppercase. Does not validate."""
    if raw is None:
        return ""
    cleaned = _SANITISE_RE.sub("", raw.strip().upper())
    return cleaned


def is_bh_series(normalized: str) -> bool:
    return bool(BH_RE.match(normalized))


def is_standard_series(normalized: str) -> bool:
    return bool(STANDARD_RE.match(normalized) or LEGACY_RE.match(normalized))


def is_valid_plate(normalized: str) -> bool:
    return is_bh_series(normalized) or is_standard_series(normalized)


def normalize_plate(raw: str) -> str:
    """Sanitise + validate. Returns normalized plate or raises PlateValidationError."""
    if not raw or not raw.strip():
        raise PlateValidationError("registration number is required")
    normalized = sanitize_plate(raw)
    if len(normalized) < 6 or len(normalized) > 13:
        raise PlateValidationError(
            f"invalid registration number '{raw.strip()}': length must be 6-13 after sanitisation"
        )
    if not is_valid_plate(normalized):
        raise PlateValidationError(
            f"invalid registration number '{raw.strip()}': must match MH02AB1234 / DL01C1234 / 21BH1234AA formats"
        )
    return normalized


def validate_short_id(value: str | None, field_name: str) -> str | None:
    """Validate optional chassis/engine last-5. Returns uppercased value or None."""
    if value is None:
        return None
    text = str(value).strip().upper()
    if text == "":
        return None
    if not SHORT5_RE.match(text):
        raise PlateValidationError(
            f"invalid {field_name}: must be exactly the last 5 alphanumeric characters"
        )
    return text
