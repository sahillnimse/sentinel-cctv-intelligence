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
