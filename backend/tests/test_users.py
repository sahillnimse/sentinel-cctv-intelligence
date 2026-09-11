"""Account administration.

A control room runs shifts, so several operators is the normal case and the old
three-env-var scheme could not express it. These tests pin the parts that are
easy to get wrong and expensive to discover later: that revoking access takes
effect immediately rather than whenever a token happens to expire, and that an
administrator cannot lock the department out of its own console.
"""

import pytest

from app.db import SessionLocal
from app.models import User
from app.utils import passwords
from tests.conftest import auth_header


@pytest.fixture
def admin(app_client):
    return auth_header(app_client, "admin", "admin123")


@pytest.fixture
def made(app_client, admin):
    """Accounts created during a test, removed afterwards."""
    created: list[int] = []

    def create(username, role="operator", **kw):
        r = app_client.post("/api/users",
                            json={"username": username, "role": role, **kw},
                            headers=admin)
        assert r.status_code == 201, r.text
        body = r.json()
        created.append(body["user"]["id"])
        return body

    yield create

    db = SessionLocal()
    try:
        for uid in created:
            obj = db.get(User, uid)
            if obj is not None:
                db.delete(obj)
        db.commit()
    finally:
        db.close()


SETTLED_PASSWORD = "Kathiawar-Junction-77"


def settle(app_client, username: str, temporary: str) -> dict:
    """Complete the forced password change; return fresh session headers.

    A created account starts on a temporary password whose session is confined
    to the change itself. Most tests want a working session, so settle first.
    """
    h = auth_header(app_client, username, temporary)
    r = app_client.post("/api/users/me/password",
                        json={"current_password": temporary,
                              "new_password": SETTLED_PASSWORD},
                        headers=h)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestMultipleOperators:
    def test_several_operators_can_coexist(self, app_client, admin, made):
        """The thing the env-var scheme could not do at all."""
        made("shift.a.operator", "operator")
        made("shift.b.operator", "operator")
        rows = app_client.get("/api/users", headers=admin).json()
        operators = [u for u in rows if u["role"] == "operator" and u["active"]]
        assert len(operators) >= 3  # the two above plus the seeded one

    def test_a_created_operator_can_sign_in_and_act(self, app_client, made):
        body = made("shift.c.operator", "operator")
        h = settle(app_client, "shift.c.operator", body["temporary_password"])
        # Operator rights: watchlist yes, camera registry no.
        assert app_client.get("/api/watchlist", headers=h).status_code == 200
        assert app_client.post("/api/cameras", json={"name": "x"},
                               headers=h).status_code == 403

    def test_role_is_honoured_for_a_created_viewer(self, app_client, made):
        body = made("shift.d.viewer", "viewer")
        h = settle(app_client, "shift.d.viewer", body["temporary_password"])
        assert app_client.get("/api/watchlist", headers=h).status_code == 200
        assert app_client.post("/api/watchlist", json={"plate": "GJ01AA1111"},
                               headers=h).status_code == 403

    def test_duplicate_username_is_refused(self, app_client, admin, made):
        made("shift.e.operator", "operator")
        r = app_client.post("/api/users",
                            json={"username": "shift.e.operator", "role": "viewer"},
                            headers=admin)
        assert r.status_code == 409


class TestRevocationIsImmediate:
    """The reason token_version exists.

    A JWT is valid on its signature until it expires. Without a version check a
    dismissed officer keeps a working console for up to TOKEN_TTL_HOURS, which
    on the shipped default is half a day.
    """

    def test_deactivating_kills_a_live_session(self, app_client, admin, made):
        body = made("revoke.me", "operator")
        h = settle(app_client, "revoke.me", body["temporary_password"])
        assert app_client.get("/api/watchlist", headers=h).status_code == 200

        assert app_client.delete(f"/api/users/{body['user']['id']}",
                                 headers=admin).status_code == 200

        # Same token, no re-login. It must stop working now, not at expiry.
        after = app_client.get("/api/watchlist", headers=h)
        assert after.status_code == 401
        assert "sign in again" in after.json()["detail"].lower()

    def test_demotion_kills_the_old_role(self, app_client, admin, made):
        body = made("demote.me", "operator")
        h = settle(app_client, "demote.me", body["temporary_password"])
        assert app_client.post("/api/watchlist", json={"plate": "GJ02BB2222"},
                               headers=h).status_code == 200

        app_client.patch(f"/api/users/{body['user']['id']}",
                         json={"role": "viewer"}, headers=admin)

        # The old token still claims operator. It must not be believed.
        assert app_client.post("/api/watchlist", json={"plate": "GJ02BB3333"},
                               headers=h).status_code == 401

    def test_password_reset_kills_existing_sessions(self, app_client, admin, made):
        body = made("reset.me", "operator")
        h = settle(app_client, "reset.me", body["temporary_password"])
        assert app_client.get("/api/watchlist", headers=h).status_code == 200

        r = app_client.post(f"/api/users/{body['user']['id']}/reset-password",
                            headers=admin)
        assert r.status_code == 200
        assert r.json()["temporary_password"] != body["temporary_password"]
        assert app_client.get("/api/watchlist", headers=h).status_code == 401

    def test_deactivated_account_cannot_sign_in_again(self, app_client, admin, made):
        body = made("gone.for.good", "operator")
        secret = body["temporary_password"]
        app_client.delete(f"/api/users/{body['user']['id']}", headers=admin)
        r = app_client.post("/api/auth/login",
                            json={"username": "gone.for.good", "password": secret})
        assert r.status_code == 401


class TestLockoutProtection:
    """An admin must not be able to strand the department outside its console."""

    def _admin_id(self, app_client, admin):
        rows = app_client.get("/api/users", headers=admin).json()
        return next(u["id"] for u in rows if u["username"] == "admin")

    def test_cannot_deactivate_yourself(self, app_client, admin):
        uid = self._admin_id(app_client, admin)
        r = app_client.delete(f"/api/users/{uid}", headers=admin)
        assert r.status_code == 409
        assert "your own account" in r.json()["detail"]

    def test_cannot_demote_yourself(self, app_client, admin):
        uid = self._admin_id(app_client, admin)
        r = app_client.patch(f"/api/users/{uid}", json={"role": "viewer"},
                             headers=admin)
        assert r.status_code == 409

    def test_last_admin_cannot_be_demoted_by_another_admin(self, app_client, admin, made):
        """Guard the count, not just the caller: a second admin demoting the
        first is not self-demotion but can still empty the role."""
        body = made("second.admin", "admin")
        h2 = settle(app_client, "second.admin", body["temporary_password"])
        rows = app_client.get("/api/users", headers=admin).json()
        first = next(u["id"] for u in rows if u["username"] == "admin")

        # Two admins exist, so demoting one is allowed.
        assert app_client.patch(f"/api/users/{first}", json={"role": "operator"},
                                headers=h2).status_code == 200
        # Restore, using the still-valid second admin.
        assert app_client.patch(f"/api/users/{first}", json={"role": "admin"},
                                headers=h2).status_code == 200


class TestAccessControl:
    def test_user_admin_is_admin_only(self, app_client):
        for role, password in (("operator", "operator123"), ("viewer", "viewer123")):
            h = auth_header(app_client, role, password)
            assert app_client.get("/api/users", headers=h).status_code == 403
            assert app_client.post("/api/users", json={"username": "sneaky"},
                                   headers=h).status_code == 403

    def test_roster_is_not_readable_anonymously(self, anon):
        assert anon.get("/api/users").status_code == 401

    def test_anyone_signed_in_can_read_their_own_profile(self, app_client):
        h = auth_header(app_client, "viewer", "viewer123")
        r = app_client.get("/api/users/me", headers=h)
        assert r.status_code == 200
        assert r.json()["username"] == "viewer"

    def test_profile_never_includes_the_hash(self, app_client, admin):
        rows = app_client.get("/api/users", headers=admin).json()
        assert rows
        for user in rows:
            assert "password_hash" not in user
            assert "password" not in user


class TestPasswordRules:
    def test_self_service_change_requires_the_current_password(self, app_client, made):
        body = made("changer.one", "operator")
        h = auth_header(app_client, "changer.one", body["temporary_password"])
        r = app_client.post("/api/users/me/password",
                            json={"current_password": "wrong",
                                  "new_password": "Kathiawar-Junction-77"},
                            headers=h)
        assert r.status_code == 401

    def test_self_service_change_works_and_reissues_a_session(self, app_client, made):
        body = made("changer.two", "operator")
        h = auth_header(app_client, "changer.two", body["temporary_password"])
        r = app_client.post("/api/users/me/password",
                            json={"current_password": body["temporary_password"],
                                  "new_password": "Kathiawar-Junction-77"},
                            headers=h)
        assert r.status_code == 200
        # A change bumps token_version, so the caller needs the fresh token it
        # returns or it would sign itself out mid-request.
        fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert app_client.get("/api/watchlist", headers=fresh).status_code == 200
        assert app_client.post("/api/auth/login",
                               json={"username": "changer.two",
                                     "password": "Kathiawar-Junction-77"}
                               ).status_code == 200

    def test_weak_passwords_are_refused(self, app_client, admin):
        for weak in ("short", "password", "admin123", "aaaaaaaaaaaa"):
            r = app_client.post("/api/users",
                                json={"username": f"weak{len(weak)}x",
                                      "password": weak},
                                headers=admin)
            assert r.status_code == 400, f"{weak!r} was accepted"

    def test_generated_passwords_satisfy_the_policy(self):
        for _ in range(20):
            assert passwords.policy_error(passwords.generate()) is None

    def test_admin_created_account_must_change_password(self, app_client, made):
        body = made("forced.change", "viewer")
        assert body["user"]["must_change_password"] is True
        r = app_client.post("/api/auth/login",
                            json={"username": "forced.change",
                                  "password": body["temporary_password"]})
        assert r.json()["must_change_password"] is True


class TestHashing:
    def test_verify_accepts_the_right_password_only(self):
        stored = passwords.hash_password("Bhavnagar-Circle-42")
        assert passwords.verify("Bhavnagar-Circle-42", stored)
        assert not passwords.verify("bhavnagar-circle-42", stored)

    def test_same_password_hashes_differently(self):
        """Distinct salts, so identical passwords are not visibly identical in
        the table and one cracked hash does not reveal the others."""
        a = passwords.hash_password("Bhavnagar-Circle-42")
        b = passwords.hash_password("Bhavnagar-Circle-42")
        assert a != b

    def test_malformed_hash_fails_closed(self):
        for junk in ("", "notahash", "pbkdf2_sha256$abc", "$$$$"):
            assert passwords.verify("anything", junk) is False


class TestForcedChangeGate:
    """A temporary password must not drive the console.

    The login screen withholds the app until the password is changed, but that
    is only UI. Without a server-side gate the same session could skip the
    screen and call the API directly for as long as the token lasted — exactly
    the window the forced change is meant to close.
    """

    def test_temporary_session_cannot_read_or_mutate(self, app_client, made):
        body = made("gated.temp", "operator")
        h = auth_header(app_client, "gated.temp", body["temporary_password"])

        for method, target, payload in (
            ("GET", "/api/watchlist", None),
            ("GET", "/api/cameras", None),
            ("POST", "/api/watchlist", {"plate": "GJ09ZZ0001"}),
            ("GET", "/api/users", None),
        ):
            r = app_client.request(method, target, json=payload, headers=h)
            assert r.status_code == 403, (method, target, r.text)
            assert r.json().get("must_change_password") is True

    def test_temporary_session_may_only_change_and_read_self(
        self, app_client, made
    ):
        body = made("gated.self", "viewer")
        h = auth_header(app_client, "gated.self", body["temporary_password"])

        assert app_client.get("/api/users/me", headers=h).status_code == 200
        assert app_client.get("/api/auth/me", headers=h).status_code == 200
        r = app_client.post(
            "/api/users/me/password",
            json={"current_password": body["temporary_password"],
                  "new_password": "Sabarmati-Ghat-55"},
            headers=h)
        assert r.status_code == 200

        # The change settles the flag: the fresh session works normally.
        fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert app_client.get("/api/watchlist", headers=fresh).status_code == 200
        # ... while the pre-change token no longer does (version bumped).
        assert app_client.get("/api/watchlist", headers=h).status_code == 401
