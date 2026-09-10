"""Role-based access control and the audit trail.

Three roles, ordered. A route needs a minimum role; anything at or above it
passes.

    viewer    read-only — dashboards, search, exports
    operator  viewer + acknowledge alerts, start/stop analytics, edit watchlist
    admin     operator + camera registry changes, grid sync, demo controls

Enforcement is middleware rather than per-route dependencies: every mutating
request to /api is checked in one place, so a new router cannot accidentally
ship unprotected. Reads require a token when AUTH_ENFORCE_READS is true
(the deployment default). Set it false only for a closed sandbox.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta

import jwt

from .config import settings

log = logging.getLogger("sentinel.security")

ROLES = ("viewer", "operator", "admin")
COOKIE_NAME = "sentinel_token"
# Compared against when the username does not exist, so a miss costs the same
# PBKDF2 work as a hit and cannot be timed apart.
_DUMMY_HASH = (
    "pbkdf2_sha256$600000$AAAAAAAAAAAAAAAAAAAAAA==$"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)


def rank(role: str) -> int:
    try:
        return ROLES.index(role)
    except ValueError:
        return -1


def bootstrap_users() -> dict[str, tuple[str, str]]:
    """username -> (password, role) for the accounts seeded on an empty database.

    These are the env-var logins the app used to authenticate against directly.
    They now exist only to create the first admin, so a fresh deployment is
    reachable. Everything after that is managed in the users table.
    """
    out = {}
    if settings.admin_username:
        out[settings.admin_username] = (settings.admin_password, "admin")
    if settings.operator_username:
        out[settings.operator_username] = (settings.operator_password, "operator")
    if settings.viewer_username:
        out[settings.viewer_username] = (settings.viewer_password, "viewer")
    return out


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def const_eq(left: str, right: str) -> bool:
    """Length-independent comparison via SHA-256, then a digest compare."""
    return hmac.compare_digest(_digest(left), _digest(right))


def authenticate(db, username: str, password: str):
    """Return the User on success, None otherwise.

    Runs the hash comparison even when the username is unknown. Skipping it
    would make a miss measurably faster than a hit and turn the login endpoint
    into a username oracle.

    An inactive account fails exactly like a wrong password: telling the caller
    "this account is disabled" confirms the account exists.
    """
    from .models import User
    from .utils import passwords

    user = db.query(User).filter(User.username == username).first()
    stored = user.password_hash if user is not None else _DUMMY_HASH
    matched = passwords.verify(password, stored)
    if user is None or not matched or not user.active:
        return None

    # Opportunistic upgrade: raising the work factor takes effect on next login
    # rather than needing a forced reset for everyone.
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
        db.commit()
    return user


def issue_token(username: str, role: str, *, uid: int | None = None,
                token_version: int = 1) -> str:
    """Sign a session token.

    Carries the user id and their token_version so a session can be revoked
    before it expires. A stateless JWT is otherwise valid until TOKEN_TTL_HOURS
    elapses, which would mean a terminated officer keeps their console for the
    rest of the shift.
    """
    return jwt.encode(
        {
            "sub": username,
            "role": role,
            "uid": uid,
            "ver": token_version,
            "exp": datetime.utcnow() + timedelta(hours=settings.token_ttl_hours),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def session_is_current(db, claims: dict | None) -> bool:
    """Is the account behind these claims still entitled to this session?

    Checked on every authenticated request. Three ways a still-unexpired token
    stops being valid: the account was deactivated, its role changed, or its
    password was reset. Each bumps token_version.

    Tokens minted before this field existed carry no uid. Those are accepted on
    username alone so a deployment upgrading in place does not log everyone out
    mid-shift, and they age out at their own expiry.
    """
    from .models import User

    if not claims:
        return False
    if claims.get("sub") == "edge":  # shared ingest token, not a user account
        return True

    uid = claims.get("uid")
    if uid is None:
        user = db.query(User).filter(User.username == claims.get("sub", "")).first()
        return user is None or user.active

    user = db.get(User, uid)
    if user is None or not user.active:
        return False
    if claims.get("ver", 1) != user.token_version:
        return False
    return claims.get("role") == user.role


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def claims_from_header(header: str | None) -> dict | None:
    if not header or not header.lower().startswith("bearer "):
        return None
    return decode_token(header.split(" ", 1)[1].strip())


def bearer_secret(header: str | None) -> str | None:
    if not header or not header.lower().startswith("bearer "):
        return None
    token = header.split(" ", 1)[1].strip()
    return token or None


def edge_token_ok(header: str | None) -> bool:
    """True when the caller presented the shared EDGE_TOKEN (not a JWT)."""
    expected = settings.edge_token
    got = bearer_secret(header)
    if not expected or not got:
        return False
    return const_eq(got, expected)


def claims_from_request(request) -> dict | None:
    claims = claims_from_header(request.headers.get("authorization"))
    if claims is not None:
        return claims
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    return decode_token(raw)


def is_public(path: str) -> bool:
    if path == "/api/health" or path.startswith("/api/health/"):
        return True
    if path.startswith("/api/auth/login") or path.startswith("/api/auth/logout"):
        return True
    return False


# --- what each path prefix costs -------------------------------------------
# Longest matching prefix wins. Anything not listed falls back to OPERATOR for
# mutations, so a new endpoint is protected by default rather than open.

MUTATION_ROLES = {
    "/api/auth": None,               # login/logout must be reachable unauthenticated
    "/api/cameras": "admin",
    "/api/demo": "admin",
    "/api/streams": "operator",
    "/api/watchlist": "operator",
    "/api/alerts": "operator",
    "/api/copilot": "operator",
    "/api/sightings": "operator",
    "/api/adapters": "admin",
    "/api/users": "admin",
    # Changing your own password must stay reachable by whoever is logged in,
    # including a viewer, and including an account forced to change it.
    "/api/users/me/password": "viewer",
}

DEFAULT_MUTATION_ROLE = "operator"

# Extra minimum roles for sensitive reads, applied even when AUTH_ENFORCE_READS
# is false. The audit trail names operators and failed logins.
READ_ROLES = {
    "/api/auth/audit": "admin",
    "/api/users": "admin",
}


def required_role(path: str) -> str | None:
    best, best_len = DEFAULT_MUTATION_ROLE, -1
    for prefix, role in MUTATION_ROLES.items():
        if path.startswith(prefix) and len(prefix) > best_len:
            best, best_len = role, len(prefix)
    return best


def required_read_role(path: str) -> str | None:
    """Minimum role to READ this path, or None when the global read policy applies."""
    best, best_len = None, -1
    for prefix, role in READ_ROLES.items():
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
