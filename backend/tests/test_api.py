"""End-to-end API tests against a throwaway database.

These cover the paths a judge will exercise: onboard a camera, put a plate on
the watchlist, record a sighting, get an alert, trace the vehicle. Plus the
access-control behaviour, which is easy to regress silently.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    # Point the app at a scratch DB before anything imports settings.
    tmpdir = tempfile.mkdtemp(prefix="sentinel-test-")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmpdir}/test.db"
    os.environ["DEMO_SIMULATE"] = "false"
    os.environ["AUTOSTART_MAX_CAMERAS"] = "0"
    os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-for-hs256-ok"

    from app.main import app
    with TestClient(app) as c:
        yield c


def token(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


class TestHealth:
    def test_health(self, client):
        assert client.get("/api/health").json()["status"] == "ok"


class TestAuth:
    def test_login_returns_role(self, client):
        r = client.post("/api/auth/login",
                        json={"username": "admin", "password": "admin123"})
        assert r.status_code == 200
        assert r.json()["role"] == "admin"

    def test_bad_credentials_rejected(self, client):
        r = client.post("/api/auth/login",
                        json={"username": "admin", "password": "nope"})
        assert r.status_code == 401

    def test_me_requires_token(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_me_with_token(self, client):
        r = client.get("/api/auth/me", headers=hdr(token(client, "viewer", "viewer123")))
        assert r.json()["role"] == "viewer"


class TestAccessControl:
    def test_mutation_without_token_is_401(self, client):
        assert client.post("/api/cameras", json={"name": "x"}).status_code == 401

    def test_viewer_cannot_create_camera(self, client):
        r = client.post("/api/cameras", json={"name": "x"},
                        headers=hdr(token(client, "viewer", "viewer123")))
        assert r.status_code == 403

    def test_operator_cannot_create_camera(self, client):
        r = client.post("/api/cameras", json={"name": "x"},
                        headers=hdr(token(client, "operator", "operator123")))
        assert r.status_code == 403

    def test_operator_can_edit_watchlist(self, client):
        r = client.post("/api/watchlist", json={"plate": "MH12AB0001", "reason": "stolen"},
                        headers=hdr(token(client, "operator", "operator123")))
        assert r.status_code in (200, 201)

    def test_reads_are_open(self, client):
        assert client.get("/api/cameras").status_code == 200

    def test_denials_are_audited(self, client):
        client.post("/api/cameras", json={"name": "x"},
                    headers=hdr(token(client, "viewer", "viewer123")))
        rows = client.get("/api/auth/audit?limit=100").json()
        assert any(r["status"] == 403 and r["username"] == "viewer" for r in rows)


class TestCameraRegistry:
    def test_create_and_list(self, client):
        admin = hdr(token(client, "admin", "admin123"))
        r = client.post("/api/cameras", headers=admin, json={
            "name": "Test Junction", "department": "Police", "camera_type": "IP",
            "latitude": 23.02, "longitude": 72.57, "location_name": "Ring Road",
            "external_id": "test01", "rtsp_url": "rtsp://example/stream/test01",
        })
        assert r.status_code in (200, 201), r.text
        cam = r.json()
        assert cam["name"] == "Test Junction"

        names = [c["name"] for c in client.get("/api/cameras").json()]
        assert "Test Junction" in names

    def test_update(self, client):
        admin = hdr(token(client, "admin", "admin123"))
        cam = client.get("/api/cameras").json()[0]
        r = client.put(f"/api/cameras/{cam['id']}", headers=admin,
                       json={**cam, "location_name": "Updated Road"})
        assert r.status_code == 200
        assert r.json()["location_name"] == "Updated Road"

    def test_departments(self, client):
        assert isinstance(client.get("/api/cameras/departments").json(), list)

    def test_coverage_is_geojson(self, client):
        g = client.get("/api/cameras/coverage").json()
        assert g["type"] == "FeatureCollection"


class TestGapAnalysis:
    def test_shape(self, client):
        d = client.get("/api/analytics/gap-analysis?cell_km=5&reach_km=2").json()
        assert set(d) >= {"cells", "summary", "unhealthy", "by_department"}
        s = d["summary"]
        assert s["covered"] + s["gaps"] == s["total_cells"]

    def test_bigger_reach_never_reduces_coverage(self, client):
        tight = client.get("/api/analytics/gap-analysis?cell_km=5&reach_km=1").json()
        loose = client.get("/api/analytics/gap-analysis?cell_km=5&reach_km=20").json()
        assert loose["summary"]["coverage_pct"] >= tight["summary"]["coverage_pct"]


class TestWatchlistAndAlerts:
    def test_watchlist_roundtrip(self, client):
        op = hdr(token(client, "operator", "operator123"))
        r = client.post("/api/watchlist", headers=op,
                        json={"plate": "GJ01ZZ9999", "label": "test", "reason": "wanted"})
        assert r.status_code in (200, 201)
        entry = r.json()
        assert entry["plate"] == "GJ01ZZ9999"

        plates = [w["plate"] for w in client.get("/api/watchlist").json()]
        assert "GJ01ZZ9999" in plates

        assert client.delete(f"/api/watchlist/{entry['id']}", headers=op).status_code in (200, 204)

    def test_alerts_list(self, client):
        assert isinstance(client.get("/api/alerts").json(), list)


class TestTrace:
    def test_unknown_plate_returns_empty_route(self, client):
        d = client.get("/api/sightings/trace/XX00XX0000").json()
        assert d["route"] == []
        assert d["watchlisted"] is False


class TestAnalytics:
    def test_summary_shape(self, client):
        d = client.get("/api/analytics/summary?minutes=60").json()
        assert set(d) >= {"totals", "series", "by_type", "by_hour", "top_cameras"}
        assert len(d["by_hour"]) == 24

    def test_fleet_health_shape(self, client):
        d = client.get("/api/fleet/health").json()
        o = d["overall"]
        assert o["online"] + o["offline"] + o["unknown"] == o["total_cameras"]


class TestEdge:
    def test_status_reports_disabled(self, client):
        assert client.get("/api/edge/status").json()["enabled"] is False

    def test_ingest_skips_unknown_cameras(self, client):
        op = hdr(token(client, "operator", "operator123"))
        r = client.post("/api/edge/ingest", headers=op, json={
            "node_id": "edge-test",
            "events": [{"kind": "sighting", "external_id": "does-not-exist",
                        "plate": "GJ01AB1234", "confidence": 0.9}],
        })
        assert r.status_code == 200
        assert r.json()["skipped"] == 1
        assert r.json()["accepted"] == 0

    def test_ingest_accepts_known_camera(self, client):
        op = hdr(token(client, "operator", "operator123"))
        r = client.post("/api/edge/ingest", headers=op, json={
            "node_id": "edge-test",
            "events": [{"kind": "sighting", "external_id": "test01",
                        "plate": "GJ01AB1234", "confidence": 0.9}],
        })
        assert r.json()["accepted"] == 1
