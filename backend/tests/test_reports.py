"""Session-wide reports and operational endpoints.

The detection report is a named submission deliverable: the government-feed
demonstration must be accompanied by an output report of detected vehicles and
plates with timestamps. It has to be right, and it has to be openable.
"""

import csv
import io
import os
import tempfile
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    tmpdir = tempfile.mkdtemp(prefix="sentinel-reports-")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmpdir}/r.db"
    os.environ["AUTOSTART_MAX_CAMERAS"] = "0"
    os.environ["DEMO_SIMULATE"] = "false"
    os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-for-hs256-ok"

    from app.db import SessionLocal
    from app.main import app
    from app.models import Camera, Sighting, VehicleDetection

    with TestClient(app) as c:
        db = SessionLocal()
        cam = Camera(name="Ring Road", department="Police", external_id="t01",
                     latitude=23.02, longitude=72.57, location_name="Junction 4",
                     rtsp_url="rtsp://x/1")
        db.add(cam)
        db.commit()

        now = datetime.utcnow()
        for i, plate in enumerate(["GJ01AB1234", "GJ01AB1234", "MH12XY9999"]):
            db.add(Sighting(camera_id=cam.id, plate=plate, plate_raw=plate,
                            confidence=0.9 - i * 0.05,
                            ts=now - timedelta(minutes=i * 5), snapshot=f"{i}.jpg"))
        for i in range(5):
            db.add(VehicleDetection(camera_id=cam.id, vehicle_type="car",
                                    plate="GJ01AB1234" if i < 2 else "",
                                    ts=now - timedelta(minutes=i)))
        db.commit()
        db.close()
        yield c


def parse_csv(text_body: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text_body)))


class TestDetectionReport:
    def test_summary_totals(self, client):
        d = client.get("/api/reports/detections").json()
        t = d["totals"]
        assert t["plate_reads"] == 3
        assert t["distinct_plates"] == 2
        assert t["vehicle_detections"] == 5

    def test_plates_carry_first_and_last_seen(self, client):
        d = client.get("/api/reports/detections").json()
        entry = next(p for p in d["plates"] if p["plate"] == "GJ01AB1234")
        assert entry["reads"] == 2
        assert entry["first_seen"] <= entry["last_seen"]

    def test_plates_ordered_by_first_sighting(self, client):
        d = client.get("/api/reports/detections").json()
        firsts = [p["first_seen"] for p in d["plates"]]
        assert firsts == sorted(firsts)

    def test_window_filter_narrows_the_report(self, client):
        wide = client.get("/api/reports/detections").json()
        narrow = client.get("/api/reports/detections?minutes=1").json()
        assert narrow["totals"]["plate_reads"] <= wide["totals"]["plate_reads"]


class TestCsvExports:
    def test_detections_csv_has_required_columns(self, client):
        r = client.get("/api/reports/detections.csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        assert "attachment" in r.headers["content-disposition"]

        rows = parse_csv(r.text)
        assert len(rows) == 3
        # The deliverable is "detected vehicles and plates with timestamps".
        for column in ("timestamp_utc", "plate", "camera_name", "confidence"):
            assert column in rows[0], f"missing {column}"
        assert all(row["timestamp_utc"] for row in rows)
        assert all(row["plate"] for row in rows)

    def test_detections_csv_resolves_camera_metadata(self, client):
        rows = parse_csv(client.get("/api/reports/detections.csv").text)
        assert rows[0]["camera_name"] == "Ring Road"
        assert rows[0]["department"] == "Police"
        assert rows[0]["location"] == "Junction 4"

    def test_vehicles_csv_includes_unreadable_plates(self, client):
        rows = parse_csv(client.get("/api/reports/vehicles.csv").text)
        assert len(rows) == 5
        # The denominator matters: an evaluator checking plate yield needs the
        # vehicles whose plate could not be read.
        assert any(row["plate"] == "" for row in rows)

    def test_plates_only_filter(self, client):
        rows = parse_csv(client.get("/api/reports/detections.csv?plates_only=true").text)
        assert all(row["plate"] for row in rows)

    def test_registry_csv_round_trips_the_import_shape(self, client):
        rows = parse_csv(client.get("/api/reports/registry.csv").text)
        assert len(rows) == 1
        for column in ("external_id", "name", "department", "latitude",
                       "longitude", "rtsp_url"):
            assert column in rows[0], f"missing {column}"
        assert rows[0]["name"] == "Ring Road"

    def test_empty_window_still_returns_a_valid_file(self, client):
        r = client.get("/api/reports/detections.csv?since=2099-01-01T00:00:00")
        assert r.status_code == 200
        rows = parse_csv(r.text)
        assert rows == []          # header only, not an error


class TestOps:
    def test_readiness_reports_every_dependency(self, client):
        r = client.get("/api/health/ready")
        assert r.status_code in (200, 503)
        d = r.json()
        assert set(d["checks"]) == {"database", "disk", "analytics", "edge"}
        assert d["status"] in ("ready", "degraded")

    def test_readiness_is_green_in_a_healthy_process(self, client):
        r = client.get("/api/health/ready")
        assert r.status_code == 200, r.text
        assert r.json()["checks"]["database"]["ok"] is True

    def test_liveness_stays_shallow(self, client):
        # Liveness must not depend on the database, or a DB outage restarts
        # every node instead of just marking them unready.
        assert client.get("/api/health").json()["status"] == "ok"

    def test_metrics_is_prometheus_text(self, client):
        r = client.get("/api/metrics")
        assert r.status_code == 200
        assert "text/plain" in r.headers["content-type"]
        body = r.text
        for metric in ("sentinel_uptime_seconds", "sentinel_cameras",
                       "sentinel_alerts_open", "sentinel_models_loaded"):
            assert f"# TYPE {metric}" in body or metric in body

    def test_every_metric_is_documented(self, client):
        body = client.get("/api/metrics").text
        helps = {l.split()[2] for l in body.splitlines() if l.startswith("# HELP")}
        emitted = {l.split()[0].split("{")[0] for l in body.splitlines()
                   if l and not l.startswith("#")}
        assert emitted <= helps, f"undocumented metrics: {emitted - helps}"

    def test_camera_counts_add_up(self, client):
        body = client.get("/api/metrics").text
        counts = [int(l.rsplit(" ", 1)[1]) for l in body.splitlines()
                  if l.startswith("sentinel_cameras{")]
        assert sum(counts) == len(client.get("/api/cameras").json())
