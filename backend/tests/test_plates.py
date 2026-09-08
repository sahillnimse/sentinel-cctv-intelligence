"""Plate normalisation, fuzzy matching and Indian-format coercion.

These are the functions the whole test case rests on: if a plate read as
GJ01HR4875 does not match watchlist entry GJ01HR4879, the vehicle is missed.
The bench run on real grid frames showed the raw OCR drifting in exactly the
last one or two characters, so that is what is exercised here.
"""

import pytest

from app.utils.plates import (coerce_indian, edit_distance, fold_ambiguous,
                              is_valid_indian, normalize, plates_match)


class TestNormalize:
    @pytest.mark.parametrize("raw,expected", [
        ("gj01ab1234", "GJ01AB1234"),
        ("GJ 01 AB 1234", "GJ01AB1234"),
        ("GJ-01-AB-1234", "GJ01AB1234"),
        ("  gj01ab1234  ", "GJ01AB1234"),
        ("", ""),
    ])
    def test_normalize(self, raw, expected):
        assert normalize(raw) == expected

    def test_none_is_empty(self):
        assert normalize(None) == ""


class TestEditDistance:
    @pytest.mark.parametrize("a,b,expected", [
        ("ABC", "ABC", 0),
        ("ABC", "ABD", 1),
        ("ABC", "AB", 1),
        ("", "ABC", 3),
        ("GJ01HR4879", "GJ01HR4875", 1),
        ("GJ01UR4879", "GJ01UR48799", 1),
    ])
    def test_distance(self, a, b, expected):
        assert edit_distance(a, b) == expected

    def test_symmetric(self):
        assert edit_distance("GJ01AB1234", "GA01AB1234") == \
               edit_distance("GA01AB1234", "GJ01AB1234")


class TestFoldAmbiguous:
    def test_letters_fold_to_digits(self):
        assert fold_ambiguous("O0I1Z2S5B8") == "0011225588"

    def test_confusions_collapse(self):
        # The two spellings a CCTV OCR produces for one physical plate.
        assert fold_ambiguous("GJ01AB1Z34") == fold_ambiguous("GJ01A81234")


class TestPlatesMatch:
    def test_exact(self):
        assert plates_match("GJ01AB1234", "GJ01AB1234")

    def test_single_character_drift_matches(self):
        # The failure mode measured on real footage.
        assert plates_match("GJ01HR4875", "GJ01HR4879")

    def test_ambiguous_character_matches(self):
        assert plates_match("GJ01AB1Z34", "GJ01AB1234")

    def test_two_character_drift_rejected_by_default(self):
        assert not plates_match("GJ01HR4855", "GJ01HR4879")

    def test_widened_budget_accepts_two(self):
        assert plates_match("GJ01HR4855", "GJ01HR4879", max_dist=2)

    def test_different_plates_do_not_match(self):
        assert not plates_match("GJ01AB1234", "MH12XY9999")

    def test_empty_never_matches(self):
        assert not plates_match("", "GJ01AB1234")
        assert not plates_match("GJ01AB1234", "")

    def test_length_gap_short_circuits(self):
        assert not plates_match("GJ01", "GJ01AB1234")


class TestIndianFormat:
    @pytest.mark.parametrize("plate", [
        "GJ01AB1234", "GJ1AB1234", "MH12A1234", "GJ01ABC1234", "26BH9249H",
    ])
    def test_valid(self, plate):
        assert is_valid_indian(plate)

    @pytest.mark.parametrize("plate", [
        "GJ01AB123", "1234567890", "GJGJGJGJ", "", "GJ01AB12345678",
    ])
    def test_invalid(self, plate):
        assert not is_valid_indian(plate)


class TestCoerceIndian:
    def test_already_valid_passes_through(self):
        assert coerce_indian("GJ01AB1234") == "GJ01AB1234"

    def test_digit_in_letter_position_corrected(self):
        # OCR read the series letters as digits.
        assert coerce_indian("GJ01481234") == "GJ01AB1234"

    def test_letter_in_digit_position_corrected(self):
        assert coerce_indian("GJO1AB1234") == "GJ01AB1234"

    def test_unrecoverable_returns_none(self):
        assert coerce_indian("!!!!") is None
        assert coerce_indian("GJ") is None

    def test_too_long_returns_none(self):
        assert coerce_indian("GJ01AB1234567") is None
