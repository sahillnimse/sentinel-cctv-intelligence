"""Shared test setup.

`app.config.settings` is built once at import time, so the first module to
import the app fixes DATABASE_URL for the whole process. Test modules that each
set their own env var therefore silently shared one database, and whichever ran
second saw the other's rows. Setting it here, before anything imports the app,
makes the sharing explicit.

The consequence for test authors: the database is shared, so assert on rows you
created rather than on global totals.
"""

import os
import tempfile

import pytest

_TMPDIR = tempfile.mkdtemp(prefix="sentinel-tests-")

os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMPDIR}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough-for-hs256-ok")
os.environ.setdefault("AUTOSTART_MAX_CAMERAS", "0")
os.environ.setdefault("DEMO_SIMULATE", "false")
os.environ.setdefault("DETECTION_RETENTION_MIN", "0")   # no pruning mid-test
# Pin the read policy. Without this the suite inherits it from a developer's
# gitignored .env, so the same commit passes on one machine and fails on a
# clean checkout. Sandbox mode here; the shipped default is asserted separately.
os.environ.setdefault("AUTH_ENFORCE_READS", "false")


@pytest.fixture(scope="session")
def app_client():
    """One TestClient for the whole session, since the app is a singleton."""
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        # The seeded starter accounts use the shipped default passwords, which
        # fail the password policy, so they are flagged must_change_password.
        # In production that flag confines the session until the password is
        # changed. Here the seeded accounts stand in for established accounts
        # with real passwords, so settle the flag once at startup; the forced
        # path itself is covered by dedicated tests using created accounts.
        from app.db import SessionLocal
        from app.models import User
        db = SessionLocal()
        try:
            for row in db.query(User).filter(
                    User.created_by == "system-bootstrap").all():
                row.must_change_password = False
            db.commit()
        finally:
            db.close()
        yield c


def auth_header(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def anon(app_client):
    """A client with no credentials at all.

    Login sets an httpOnly cookie and TestClient keeps a cookie jar, so after
    any test signs in the shared client stays authenticated. Tests asserting
    unauthenticated behaviour must start from a clean jar or they silently
    assert nothing.
    """
    app_client.cookies.clear()
    try:
        yield app_client
    finally:
        # Nothing to restore: every other test authenticates with an explicit
        # Authorization header rather than relying on the jar.
        app_client.cookies.clear()
