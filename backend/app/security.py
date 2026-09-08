"""Role-based access control and the audit trail.

Three roles, ordered. A route needs a minimum role; anything at or above it
passes.

    viewer    read-only — dashboards, search, exports
    operator  viewer + acknowledge alerts, start/stop analytics, edit watchlist
    admin     operator + camera registry changes, grid sync, demo controls

Enforcement is middleware rather than per-route dependencies: every mutating
request to /api is checked in one place, so a new router cannot accidentally
ship unprotected. Reads stay open when AUTH_ENFORCE_READS is false, which is
the sandbox default so dashboards work without a login.
"""

import json
import logging
from datetime import datetime, timedelta

import jwt

from .config import settings

log = logging.getLogger("sentinel.security")

ROLES = ("viewer", "operator", "admin")


def rank(role: str) -> int:
    try:
        return ROLES.index(role)
    except ValueError:
        return -1


def users() -> dict[str, tuple[str, str]]:
    """username -> (password, role). Sourced from settings so deployments can
    override without touching code. A real deployment swaps this for the
    department's directory (LDAP/AD) behind the same interface."""
    out = {}
    if settings.admin_username:
        out[settings.admin_username] = (settings.admin_password, "admin")
    if settings.operator_username:
        out[settings.operator_username] = (settings.operator_password, "operator")
    if settings.viewer_username:
        out[settings.viewer_username] = (settings.viewer_password, "viewer")
    return out


def authenticate(username: str, password: str) -> str | None:
    """Return the role on success, None otherwise."""
    entry = users().get(username)
    if entry is None:
        return None
    expected, role = entry
    # constant-ish time compare; passwords here are short config values
    if len(password) != len(expected):
        return None
    if sum(a != b for a, b in zip(password, expected)):
        return None
    return role


def issue_token(username: str, role: str) -> str:
    return jwt.encode(
        {
            "sub": username,
            "role": role,
            "exp": datetime.utcnow() + timedelta(hours=settings.token_ttl_hours),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def claims_from_header(header: str | None) -> dict | None:
    if not header or not header.lower().startswith("bearer "):
        return None
    return decode_token(header.split(" ", 1)[1].strip())


# --- what each path prefix costs -------------------------------------------
# Longest matching prefix wins. Anything not listed falls back to OPERATOR for
# mutations, so a new endpoint is protected by default rather than open.

MUTATION_ROLES = {
    "/api/auth": None,               # login must be reachable unauthenticated
    "/api/cameras": "admin",
    "/api/demo": "admin",
    "/api/streams": "operator",
    "/api/watchlist": "operator",
    "/api/alerts": "operator",
    "/api/copilot": "operator",
    "/api/sightings": "operator",
}

DEFAULT_MUTATION_ROLE = "operator"


def required_role(path: str) -> str | None:
    best, best_len = DEFAULT_MUTATION_ROLE, -1
    for prefix, role in MUTATION_ROLES.items():
        if path.startswith(prefix) and len(prefix) > best_len:
            best, best_len = role, len(prefix)
    return best


def audit(db, *, user: str, role: str, action: str, target: str,
          status: int, detail: dict | None = None) -> None:
    """Append to the audit trail. Never raises — an audit failure must not take
    down the request it is recording."""
    from .models import AuditLog
    try:
        db.add(AuditLog(
            ts=datetime.utcnow(), username=user or "anonymous", role=role or "",
            action=action, target=target[:300], status=status,
            detail=json.dumps(detail, default=str)[:1000] if detail else "",
        ))
        db.commit()
    except Exception:
        log.exception("audit write failed for %s %s", action, target)
