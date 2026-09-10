"""RBAC and the audit trail.

The point of these is that a route added later cannot quietly ship without
protection: enforcement lives in one middleware and defaults to operator, so
an unlisted path is closed rather than open.
"""

import pytest

from app.security import (DEFAULT_MUTATION_ROLE, authenticate, decode_token,
                          issue_token, claims_from_header, rank, required_role)


class TestRoleRanking:
    def test_order(self):
        assert rank("viewer") < rank("operator") < rank("admin")

    def test_unknown_role_ranks_below_everything(self):
        assert rank("nonsense") < rank("viewer")

    def test_empty_role_is_not_a_viewer(self):
        assert rank("") < rank("viewer")


class TestAuthenticate:
    def test_valid_admin(self):
        assert authenticate("admin", "admin123") == "admin"

    def test_valid_viewer(self):
        assert authenticate("viewer", "viewer123") == "viewer"

    def test_wrong_password(self):
        assert authenticate("admin", "wrong") is None

    def test_unknown_user(self):
        assert authenticate("nobody", "admin123") is None

    def test_empty_password(self):
        assert authenticate("admin", "") is None


class TestTokens:
    def test_roundtrip(self):
        claims = decode_token(issue_token("admin", "admin"))
        assert claims is not None
        assert claims["sub"] == "admin"
        assert claims["role"] == "admin"

    def test_garbage_rejected(self):
        assert decode_token("not.a.token") is None

    def test_tampered_rejected(self):
        token = issue_token("viewer", "viewer")
        assert decode_token(token[:-4] + "AAAA") is None

    def test_header_parsing(self):
        token = issue_token("op", "operator")
        assert claims_from_header(f"Bearer {token}")["role"] == "operator"

    @pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer", "token abc"])
    def test_bad_headers_rejected(self, header):
        assert claims_from_header(header) is None


class TestRequiredRole:
    @pytest.mark.parametrize("path,expected", [
        ("/api/cameras", "admin"),
        ("/api/cameras/12", "admin"),
        ("/api/cameras/sync-grid", "admin"),
        ("/api/demo/seed", "admin"),
        ("/api/watchlist", "operator"),
        ("/api/alerts/3/ack", "operator"),
        ("/api/streams/1/start", "operator"),
    ])
    def test_known_paths(self, path, expected):
        assert required_role(path) == expected

    def test_login_is_open(self):
        assert required_role("/api/auth") is None

    def test_unlisted_path_defaults_closed(self):
        # A router added later is protected without anyone remembering to.
        assert required_role("/api/something-new") == DEFAULT_MUTATION_ROLE

    def test_longest_prefix_wins(self):
        assert required_role("/api/cameras/anything/deep") == "admin"


class TestReadRoles:
    def test_audit_needs_admin(self):
        from app.security import required_read_role
        assert required_read_role("/api/auth/audit") == "admin"

    def test_most_reads_are_public(self):
        from app.security import required_read_role
        for path in ("/api/cameras", "/api/alerts", "/api/analytics/summary",
                     "/api/auth/me", "/api/fleet/health"):
            assert required_read_role(path) is None, path


class TestRedactUrl:
    @pytest.mark.parametrize("raw,expected", [
        ("rtsp://user:pass@host:8554/stream/cam01",
         "rtsp://***@host:8554/stream/cam01"),
        ("rtsp://host:8554/stream/cam01",
         "rtsp://host:8554/stream/cam01"),
        ("https://cctv.corp8.cloud/cam01/index.m3u8",
         "https://cctv.corp8.cloud/cam01/index.m3u8"),
        ("could not open rtsp://user:pass@host/stream/cam01",
         "could not open rtsp://***@host/stream/cam01"),
        ("", ""),
        (None, None),
    ])
    def test_redaction(self, raw, expected):
        from app.utils import redact_url
        assert redact_url(raw) == expected


class TestShippedDefaults:
    """Guard the defaults a clean checkout ships with.

    These are read off the Settings class, not the running instance, so a
    developer's .env cannot make them look right when they are not.
    """

    def test_reads_are_enforced_by_default(self):
        from app.config import Settings
        assert Settings.model_fields["auth_enforce_reads"].default is True,             "a fresh deployment must require auth for reads"

    def test_token_lifetime_is_bounded(self):
        from app.config import Settings
        assert 0 < Settings.model_fields["token_ttl_hours"].default <= 24

    def test_default_passwords_are_flagged_not_silent(self):
        # config warns when the shipped passwords are still in use; that
        # warning is the only thing standing between a demo and a deployment.
        import warnings

        from app.config import Settings
        assert Settings.model_fields["admin_password"].default == "admin123"
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            import importlib

            import app.config
            importlib.reload(app.config)
        assert any("Default role passwords" in str(w.message) for w in caught)
