"""Vehicle RTO + challan trace (mocked; no live vendor calls)."""

from app.integrations import vehicle_trace as svc


def test_sanitize_plate():
    assert svc.sanitize_plate(" up16cd1996 ") == "UP16CD1996"
    assert svc.sanitize_plate("MH-02-AB-1234") == "MH02AB1234"


def test_validate_plate_ok():
    assert svc.validate_plate_or_raise("UP16CD1996") == "UP16CD1996"


def test_validate_plate_bad():
    import pytest
    with pytest.raises(ValueError):
        svc.validate_plate_or_raise("NOTAPLATE!!")
    with pytest.raises(ValueError):
        svc.validate_plate_or_raise("")


def test_parse_challans_mock_shape():
    items, summary = svc.parse_challans(svc.mock_challans("UP16CD1996"))
    assert len(items) == 2
    assert summary["pending_count"] == 2
    assert summary["pending_amount"] == 1500


def test_parse_challans_empty():
    items, summary = svc.parse_challans({"status": True, "data": {}})
    assert items == [] and summary["pending_count"] == 0


def test_fetch_trace_mock(monkeypatch):
    import asyncio
    monkeypatch.setattr(svc.settings, "rapidapi_key", "")
    monkeypatch.setattr(svc.settings, "rapidapi_host", "")
    monkeypatch.setattr(svc.settings, "rapidapi_challan_host", "")
    res = asyncio.run(svc.fetch_trace("UP16CD1996"))
    assert res["plate"] == "UP16CD1996"
    assert res["rc"]["ok"] is True
    assert res["challans"]["summary"]["pending_count"] == 2


def test_trace_routes_registered(anon, monkeypatch):
    monkeypatch.setattr(svc.settings, "rapidapi_key", "")
    monkeypatch.setattr(svc.settings, "rapidapi_host", "")
    monkeypatch.setattr(svc.settings, "rapidapi_challan_host", "")
    r = anon.get("/api/vehicle/UP16CD1996/trace")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plate"] == "UP16CD1996"
    assert "rc" in body and "challans" in body
    assert body["challans"]["summary"]["pending_count"] == 2


def test_trace_invalid_plate(anon):
    r = anon.get("/api/vehicle/NOPE!!/trace")
    assert r.status_code == 422
