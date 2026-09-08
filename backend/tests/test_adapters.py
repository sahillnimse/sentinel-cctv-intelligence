"""Federation adapters.

The contract matters more than any single adapter: every registered adapter
must describe itself, discover without raising, and produce cameras that map
cleanly onto the registry. That is what lets a new vendor be added without
touching anything else.
"""

import pytest

from app import adapters
from app.adapters.base import DiscoveredCamera
from app.adapters.rtsp import _parse_sources


class TestRegistry:
    def test_expected_adapters_registered(self):
        keys = {a["key"] for a in adapters.describe()}
        assert {"sentinel-grid", "onvif", "rtsp", "local-media"} <= keys

    def test_describe_reports_required_fields(self):
        for a in adapters.describe():
            assert a["key"] and a["label"] and a["vendor"]
            assert isinstance(a["protocols"], list) and a["protocols"]
            assert isinstance(a["configured"], bool)

    def test_get_unknown_returns_none(self):
        assert adapters.get("no-such-vendor") is None

    def test_discover_unknown_raises(self):
        with pytest.raises(KeyError):
            adapters.discover("no-such-vendor")

    def test_every_adapter_discovers_without_raising(self):
        for a in adapters.all_adapters():
            result = a.discover()
            assert isinstance(result, list)
            assert all(isinstance(c, DiscoveredCamera) for c in result)


class TestDiscoveredCamera:
    def test_maps_onto_registry_columns(self):
        cam = DiscoveredCamera(external_id="cam01", name="Gate",
                               rtsp_url="rtsp://x/1", latitude=23.0, longitude=72.0)
        fields = cam.as_camera_fields()
        assert fields["external_id"] == "cam01"
        assert fields["rtsp_url"] == "rtsp://x/1"
        # An adapter that knows no department must not write an empty one.
        assert fields["department"] == "Unassigned"

    def test_department_preserved_when_known(self):
        cam = DiscoveredCamera(external_id="c", name="n", department="GSRTC")
        assert cam.as_camera_fields()["department"] == "GSRTC"


class TestSentinelGrid:
    def test_falls_back_to_documented_range(self):
        cams = adapters.get("sentinel-grid").discover()
        assert len(cams) == 30
        assert cams[0].external_id == "cam01"
        assert cams[-1].external_id == "cam30"

    def test_every_camera_has_all_three_protocols(self):
        for cam in adapters.get("sentinel-grid").discover():
            assert cam.rtsp_url.startswith("rtsp://")
            assert "index.m3u8" in cam.hls_url
            assert cam.whep_url.endswith("/whep")

    def test_rtsp_uses_the_documented_path_shape(self):
        cam = adapters.get("sentinel-grid").discover()[0]
        assert cam.rtsp_url.endswith("/stream/cam01")


class TestRtspSourceParsing:
    def test_named_pairs(self):
        assert _parse_sources("Gate 1=rtsp://a/1,Gate 2=rtsp://b/2") == [
            ("Gate 1", "rtsp://a/1"), ("Gate 2", "rtsp://b/2")]

    def test_bare_url_gets_a_name(self):
        parsed = _parse_sources("rtsp://host/ch1")
        assert len(parsed) == 1
        assert parsed[0][1] == "rtsp://host/ch1"
        assert parsed[0][0]

    def test_blank_and_whitespace_ignored(self):
        assert _parse_sources("") == []
        assert _parse_sources("  ,  , ") == []

    def test_whitespace_trimmed(self):
        assert _parse_sources("  A = rtsp://x/1  ") == [("A", "rtsp://x/1")]


class TestLocalMedia:
    def test_unconfigured_discovers_nothing(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "local_media_dir", "")
        assert adapters.get("local-media").discover() == []

    def test_missing_directory_is_not_configured(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "local_media_dir", "/no/such/path")
        assert adapters.get("local-media").configured() is False

    def test_finds_video_files(self, tmp_path, monkeypatch):
        from app.config import settings
        (tmp_path / "a.mp4").write_bytes(b"x")
        (tmp_path / "b.mkv").write_bytes(b"x")
        (tmp_path / "notes.txt").write_text("ignore me")
        monkeypatch.setattr(settings, "local_media_dir", str(tmp_path))

        cams = adapters.get("local-media").discover()
        assert len(cams) == 2
        assert {c.name for c in cams} == {"File a", "File b"}
        assert all(c.camera_type == "File" for c in cams)

    def test_probe_reflects_existence(self, tmp_path, monkeypatch):
        from app.config import settings
        (tmp_path / "a.mp4").write_bytes(b"x")
        monkeypatch.setattr(settings, "local_media_dir", str(tmp_path))
        adapter = adapters.get("local-media")
        cam = adapter.discover()[0]
        assert adapter.probe(cam) is True
        cam.rtsp_url = str(tmp_path / "gone.mp4")
        assert adapter.probe(cam) is False


class TestOnvifDisabled:
    def test_discovery_off_by_default(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "onvif_discovery_enabled", False)
        # No multicast traffic when disabled.
        assert adapters.get("onvif").discover() == []
