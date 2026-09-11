"""Validation & standardisation tests."""

import pytest

from app.utils.plate import (
    PlateValidationError,
    is_valid_plate,
    normalize_plate,
    sanitize_plate,
    validate_short_id,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("MH02AB1234", "MH02AB1234"),
        ("mh02ab1234", "MH02AB1234"),
        ("MH 02 AB 1234", "MH02AB1234"),
        ("MH-02-AB-1234", "MH02AB1234"),
        ("DL01C1234", "DL01C1234"),
        ("KA05MN1234", "KA05MN1234"),
        ("GJ01RT1234", "GJ01RT1234"),
        ("21BH1234AA", "21BH1234AA"),
        ("22bh1234a", "22BH1234A"),
        ("KA05A123", "KA05A123"),
    ],
)
def test_valid_plates(raw: str, expected: str) -> None:
    assert normalize_plate(raw) == expected
    assert is_valid_plate(expected)


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "AB", "123", "MH02", "XX!!1234", "MH02AB12345EXTRA", "BH1234", "M H", "12345678901234"],
)
def test_invalid_plates(raw: str) -> None:
    with pytest.raises(PlateValidationError):
        normalize_plate(raw)


def test_sanitize_strips_and_uppercases() -> None:
    assert sanitize_plate(" mh-02 ab.1234 ") == "MH02AB1234"


def test_short_ids() -> None:
    assert validate_short_id("abc12", "chassis_number") == "ABC12"
    assert validate_short_id(None, "chassis_number") is None
    assert validate_short_id("   ", "engine_number") is None
    with pytest.raises(PlateValidationError):
        validate_short_id("AB12", "chassis_number")
    with pytest.raises(PlateValidationError):
        validate_short_id("ABC123", "engine_number")
    with pytest.raises(PlateValidationError):
        validate_short_id("AB#12", "chassis_number")
