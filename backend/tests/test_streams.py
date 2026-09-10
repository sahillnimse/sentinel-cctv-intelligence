"""Which cameras come up, and what the operator is told about the ones that don't.

The live wall showed a fraction of the grid for two separate reasons, so both
are pinned here: the autostart cap read 0 as "none" when an operator setting it
meant "all", and every selection filtered on rtsp_url alone even though the
worker falls back to hls_url.

start_worker is stubbed throughout. These tests are about which camera ids get
picked and what the response says, and a real worker opens a socket to whatever
URL the fixture invented.
"""

import pytest
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import Camera, has_stream
from tests.conftest import auth_header

CAMERAS = (
    # name,                  rtsp,                        hls
    ("sel-rtsp", "rtsp://example.invalid/a", ""),
    ("sel-hls-only", "", "https://example.invalid/a.m3u8"),
    ("sel-registry-only", "", ""),
)


@pytest.fixture
def cams(app_client):
    """RTSP, HLS-only, and a registry entry with no stream at all.

    Depends on app_client because the schema is created by the app's lifespan,
    not by this module.
    """
    db = SessionLocal()
    try:
        db.execute(delete(Camera).where(Camera.department == "TestSel"))
        db.commit()
        for name, rtsp, hls in CAMERAS:
            db.add(Camera(name=name, rtsp_url=rtsp, hls_url=hls, department="TestSel"))
        db.commit()
        ids = {c.name: c.id for c in
               db.scalars(select(Camera).where(Camera.department == "TestSel")).all()}
        yield ids
    finally:
        # Bulk delete rather than ORM deletes: nothing here needs cascade, and a
        # session that has been holding these rows across a request can no
        # longer agree with the database about them.
        db.execute(delete(Camera).where(Camera.department == "TestSel"))
        db.commit()
        db.close()


@pytest.fixture
def started(monkeypatch):
    """Record start_worker calls instead of spawning decoder threads.

    Returns the list of camera ids the endpoint asked to start. The stub answers
    True once per id and False afterwards, which is what the real one does for a
    worker that is already running.
    """
    calls: list[int] = []

    def fake_start(camera_id: int) -> bool:
        first = camera_id not in calls
        calls.append(camera_id)
        return first

    monkeypatch.setattr("app.routers.streams.start_worker", fake_start)
    return calls


class TestStreamableSelection:
    def test_has_stream_accepts_rtsp_or_hls(self, cams):
        """The worker tries rtsp then falls back to hls, so selection must take
        either. Filtering on rtsp_url alone left HLS-only cameras permanently
        dark on the live wall with no way to start them."""
        db = SessionLocal()
        try:
            picked = {c.name for c in db.scalars(
                select(Camera).where(has_stream(), Camera.department == "TestSel")).all()}
        finally:
            db.close()
        assert picked == {"sel-rtsp", "sel-hls-only"}


class TestAutostartCap:
    """The cap reads as: negative all, zero none, positive a limit."""

    @staticmethod
    def _selected(cap: int, eligible: int = 35) -> list[int]:
        ids = list(range(1, eligible + 1))
        if cap == 0:
            return []
        return ids[:cap] if cap > 0 else ids

    def test_zero_starts_nothing(self):
        """0 is the test suite's setting and reads naturally as "no limit". It
        is the opposite, and it is what leaves every tile idle."""
        assert self._selected(0) == []

    def test_negative_starts_every_streamable_camera(self):
        assert len(self._selected(-1)) == 35

    def test_positive_caps(self):
        assert len(self._selected(30)) == 30

    def test_cap_above_supply_is_not_an_error(self):
        assert len(self._selected(100)) == 35


class TestStartEndpoints:
    def test_start_rejects_a_camera_with_no_stream(self, app_client, cams, started):
        """A registry entry has nothing to decode. This used to report success,
        spawn a thread that exited on its first line, and leave the operator
        pressing Start with no feedback and no change."""
        h = auth_header(app_client, "operator", "operator123")
        r = app_client.post(f"/api/streams/{cams['sel-registry-only']}/start", headers=h)
        assert r.status_code == 409
        assert "no RTSP or HLS" in r.json()["detail"]
        assert started == []

    def test_start_accepts_an_hls_only_camera(self, app_client, cams, started):
        h = auth_header(app_client, "operator", "operator123")
        r = app_client.post(f"/api/streams/{cams['sel-hls-only']}/start", headers=h)
        assert r.status_code == 200
        assert started == [cams["sel-hls-only"]]

    def test_start_all_starts_hls_only_cameras_too(self, app_client, cams, started):
        h = auth_header(app_client, "operator", "operator123")
        body = app_client.post("/api/streams/start-all", headers=h).json()
        assert cams["sel-hls-only"] in body["started"]
        assert cams["sel-rtsp"] in body["started"]
        assert cams["sel-registry-only"] not in body["started"]

    def test_start_all_reports_every_outcome(self, app_client, cams, started):
        """Reporting only newly started ids made a second press look like a
        failure and said nothing about cameras that can never stream."""
        h = auth_header(app_client, "operator", "operator123")
        body = app_client.post("/api/streams/start-all", headers=h).json()

        for key in ("started", "already_running", "no_stream",
                    "total_with_url", "total_cameras"):
            assert key in body, f"start-all response is missing {key}"

        assert cams["sel-registry-only"] in body["no_stream"]
        # Every camera is accounted for exactly once, under one heading.
        assert body["total_with_url"] + len(body["no_stream"]) == body["total_cameras"]
        assert len(body["started"]) + len(body["already_running"]) == body["total_with_url"]

    def test_start_all_is_idempotent(self, app_client, cams, started):
        """A second press must report the grid as already running, not as a
        no-op with an empty result the UI cannot explain."""
        h = auth_header(app_client, "operator", "operator123")
        first = app_client.post("/api/streams/start-all", headers=h).json()
        second = app_client.post("/api/streams/start-all", headers=h).json()
        assert first["started"]
        assert second["started"] == []
        assert len(second["already_running"]) == second["total_with_url"]

    def test_start_all_needs_operator(self, app_client, started):
        h = auth_header(app_client, "viewer", "viewer123")
        assert app_client.post("/api/streams/start-all", headers=h).status_code == 403
        assert started == []
