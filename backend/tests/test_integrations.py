"""Government database connectors.

Every connector is a deterministic mock, so the properties worth testing are
the contract ones: same subject gives the same answer, an authority that has
no view of a subject type says so rather than inventing one, and one authority
failing does not take the others down with it.
"""

import pytest

from app import integrations
from app.integrations.base import LookupResult


class TestRegistry:
    def test_all_five_required_systems_present(self):
        keys = {c["key"] for c in integrations.describe()}
        # VAHAN and SARTHI ship as one connector; the brief names five systems.
        assert {"vahan", "egujcop", "afis", "nafis"} <= keys

    def test_describe_reports_required_fields(self):
        for c in integrations.describe():
            assert c["key"] and c["label"] and c["authority"]
            assert c["kind"] in {"vehicle", "person", "both"}
            assert isinstance(c["live"], bool)

    def test_none_claim_to_be_live(self):
        # If one of these ever reports live=True without real credentials
        # wired in, the demo is lying about its data.
        assert all(c["live"] is False for c in integrations.describe())

    def test_unknown_connector(self):
        assert integrations.get("interpol") is None


class TestDeterminism:
    @pytest.mark.parametrize("plate", ["GJ01AB1234", "MH12XY9999", "26BH9249H"])
    def test_vehicle_lookup_is_stable(self, plate):
        a = integrations.lookup_vehicle(plate)
        b = integrations.lookup_vehicle(plate)
        assert a == b

    def test_person_lookup_is_stable(self):
        assert integrations.lookup_person("SUSPECT-001") == \
               integrations.lookup_person("SUSPECT-001")

    def test_normalisation_means_formatting_does_not_matter(self):
        a = integrations.get("egujcop").lookup_vehicle("GJ 01 AB 1234")
        b = integrations.get("egujcop").lookup_vehicle("gj01ab1234")
        assert a.record == b.record

    def test_different_subjects_differ(self):
        seen = {str(integrations.get("egujcop").lookup_vehicle(f"GJ01AB{i:04d}").record)
                for i in range(40)}
        assert len(seen) > 1, "mock returns the same record for every plate"


class TestScope:
    def test_vehicle_fan_out_skips_person_only_authorities(self):
        keys = {r["connector"] for r in integrations.lookup_vehicle("GJ01AB1234")}
        assert "afis" not in keys and "nafis" not in keys
        assert "vahan" in keys and "egujcop" in keys

    def test_person_fan_out_skips_vehicle_only_authorities(self):
        keys = {r["connector"] for r in integrations.lookup_person("SUSPECT-001")}
        assert "vahan" not in keys
        assert {"egujcop", "afis", "nafis"} <= keys

    def test_biometric_has_no_view_of_vehicles(self):
        assert integrations.get("afis").lookup_vehicle("GJ01AB1234") is None
        assert integrations.get("nafis").lookup_vehicle("GJ01AB1234") is None

    def test_vahan_has_no_person_index(self):
        assert integrations.get("vahan").lookup_person("SUSPECT-001") is None


class TestResults:
    def test_empty_subject_is_not_found(self):
        for key in ("vahan", "egujcop"):
            assert integrations.get(key).lookup_vehicle("").found is False

    def test_not_found_is_an_answer_not_an_error(self):
        results = integrations.lookup_vehicle("ZZ99ZZ0000")
        assert all("error" not in r for r in results)

    def test_hits_carry_alerts_explaining_why(self):
        # Across a spread of plates, at least one authority should raise
        # something, and anything raised must be non-empty text.
        alerts = [a for i in range(60)
                  for r in integrations.lookup_vehicle(f"GJ01AB{i:04d}")
                  for a in r["alerts"]]
        assert alerts, "no authority ever raises an alert"
        assert all(isinstance(a, str) and a.strip() for a in alerts)

    def test_egujcop_stolen_record_is_internally_consistent(self):
        for i in range(200):
            r = integrations.get("egujcop").lookup_vehicle(f"GJ01AB{i:04d}")
            if r.found and r.record.get("reported_stolen"):
                assert r.record["fir_number"]
                assert r.record["police_station"]
                assert r.record["status"] != "RECOVERED"
                assert r.alerts
                return
        pytest.fail("no stolen record produced across 200 plates")


class TestResilience:
    def test_one_broken_authority_does_not_lose_the_others(self, monkeypatch):
        broken = integrations.get("egujcop")

        def explode(_subject):
            raise ConnectionError("CCTNS gateway timeout")

        monkeypatch.setattr(broken, "lookup_vehicle", explode)
        results = integrations.lookup_vehicle("GJ01AB1234")

        by_key = {r["connector"]: r for r in results}
        assert by_key["egujcop"]["source"] == "error"
        assert by_key["vahan"]["found"] is True, \
            "a failing authority took a working one down with it"


class TestLookupResult:
    def test_serialises_for_the_api(self):
        d = LookupResult("x", "GJ01AB1234", found=True,
                         record={"a": 1}, alerts=["why"]).as_dict()
        assert set(d) == {"connector", "subject", "found", "record", "alerts", "source"}
