"""Snapshot path resolution.

Snapshot filenames come out of a database column and are joined onto the
snapshot directory before being read and hashed. A row carrying `../../` would
otherwise read files outside that directory and put their digest into an
evidence export, so the guard is the thing standing between a bad row and
arbitrary file reads.
"""

import pytest

from app.config import settings
from app.utils.files import snapshot_path


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "snapshot_dir", tmp_path)
    f = tmp_path / "veh_cam01_123.jpg"
    f.write_bytes(b"jpeg")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "deep.jpg").write_bytes(b"jpeg")
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("not yours")
    return tmp_path


class TestAccepts:
    def test_plain_filename(self, snapshot):
        assert snapshot_path("veh_cam01_123.jpg") == snapshot / "veh_cam01_123.jpg"

    def test_nested_filename(self, snapshot):
        assert snapshot_path("nested/deep.jpg") == snapshot / "nested" / "deep.jpg"

    def test_windows_separators(self, snapshot):
        assert snapshot_path("nested\\deep.jpg") == snapshot / "nested" / "deep.jpg"


class TestRejects:
    @pytest.mark.parametrize("name", [None, "", "   ".strip()])
    def test_empty(self, snapshot, name):
        assert snapshot_path(name) is None

    def test_missing_file(self, snapshot):
        assert snapshot_path("does-not-exist.jpg") is None

    @pytest.mark.parametrize("name", [
        "../secret.txt",
        "../../secret.txt",
        "nested/../../secret.txt",
        "..\\secret.txt",
    ])
    def test_traversal(self, snapshot, name):
        assert snapshot_path(name) is None, f"escaped the snapshot directory: {name}"

    def test_absolute_path(self, snapshot):
        outside = snapshot.parent / "secret.txt"
        assert snapshot_path(str(outside)) is None

    def test_directory_is_not_a_file(self, snapshot):
        assert snapshot_path("nested") is None


class TestEvidenceUsesTheGuard:
    def test_hash_of_a_traversal_name_is_empty(self, snapshot):
        from app.routers.evidence import file_sha256
        # A real digest here would mean the export leaked a file's contents.
        assert file_sha256("../secret.txt") == ""

    def test_hash_of_a_real_snapshot_works(self, snapshot):
        from app.routers.evidence import file_sha256
        digest = file_sha256("veh_cam01_123.jpg")
        assert len(digest) == 64
