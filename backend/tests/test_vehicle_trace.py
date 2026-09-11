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
    assert body["meta"]["cached"] is False


def test_trace_cache_hit_skips_vendors(anon, monkeypatch):
    monkeypatch.setattr(svc.settings, "rapidapi_key", "")
    monkeypatch.setattr(svc.settings, "rapidapi_host", "")
    monkeypatch.setattr(svc.settings, "rapidapi_challan_host", "")
    assert anon.get("/api/vehicle/GJ01AB1234/trace").status_code == 200
    calls = {"n": 0}

    async def counting_rc(plate):
        calls["n"] += 1
        return {"ok": True, "mocked": True, "payload": svc.mock_rc(plate)}

    async def counting_ch(plate):
        calls["n"] += 1
        return {"ok": True, "mocked": True, "payload": svc.mock_challans(plate)}

    monkeypatch.setattr(svc, "fetch_rc", counting_rc)
    monkeypatch.setattr(svc, "fetch_challans", counting_ch)
    r = anon.get("/api/vehicle/GJ01AB1234/trace")
    assert r.status_code == 200
    assert r.json()["meta"]["cached"] is True
    assert calls["n"] == 0, "cached trace must not call vendors"


def test_trace_refresh_bypasses_cache(anon, monkeypatch):
    monkeypatch.setattr(svc.settings, "rapidapi_key", "")
    monkeypatch.setattr(svc.settings, "rapidapi_host", "")
    monkeypatch.setattr(svc.settings, "rapidapi_challan_host", "")
    assert anon.get("/api/vehicle/MH12AB0001/trace").status_code == 200
    r = anon.get("/api/vehicle/MH12AB0001/trace?refresh=true")
    assert r.status_code == 200
    assert r.json()["meta"]["cached"] is False


def test_trace_stale_cache_refetches(anon, monkeypatch):
    from datetime import datetime, timedelta

    from app.db import SessionLocal
    from app.models import VehicleTraceCache

    monkeypatch.setattr(svc.settings, "rapidapi_key", "")
    monkeypatch.setattr(svc.settings, "rapidapi_host", "")
    monkeypatch.setattr(svc.settings, "rapidapi_challan_host", "")
    assert anon.get("/api/vehicle/DL01C1234/trace").status_code == 200
    db = SessionLocal()
    try:
        row = db.get(VehicleTraceCache, "DL01C1234")
        assert row is not None
        row.updated_at = datetime.utcnow() - timedelta(days=2)
        db.commit()
    finally:
        db.close()
    calls = {"n": 0}

    async def counting_rc(plate):
        calls["n"] += 1
        return {"ok": True, "mocked": True, "payload": svc.mock_rc(plate)}

    async def counting_ch(plate):
        calls["n"] += 1
        return {"ok": True, "mocked": True, "payload": svc.mock_challans(plate)}

    monkeypatch.setattr(svc, "fetch_rc", counting_rc)
    monkeypatch.setattr(svc, "fetch_challans", counting_ch)
    r = anon.get("/api/vehicle/DL01C1234/trace")
    assert r.status_code == 200
    assert r.json()["meta"]["cached"] is False
    assert calls["n"] == 2


def test_trace_invalid_plate(anon):
    r = anon.get("/api/vehicle/NOPE!!/trace")
    assert r.status_code == 422
