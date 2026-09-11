"""Sign-in, sign-out, and the audit trail.

Credentials are checked against the users table. The three env-var logins now
only seed the first accounts on an empty database; see security.bootstrap_users.
"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import AuditLog, User
from ..schemas import LoginIn
from ..security import (COOKIE_NAME, authenticate, claims_from_request,
                        decode_token, issue_token)

log = logging.getLogger("sentinel.auth")

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)

_LOCKOUT_AFTER = 8
_LOCKOUT_SECONDS = 60
_LOCKOUT_MAX_TRACKED = 2000
_failures: dict[str, list[float]] = {}


def _prune_failures(now: float) -> None:
    """Drop expired entries so a spray of invented usernames cannot grow this
    map without bound. Only touched on the failure path."""
    if len(_failures) < _LOCKOUT_MAX_TRACKED:
        return
    window = now - _LOCKOUT_SECONDS
    for key in [k for k, hits in _failures.items() if not any(t >= window for t in hits)]:
        _failures.pop(key, None)


def _locked(username: str) -> bool:
    window = time.time() - _LOCKOUT_SECONDS
    hits = [t for t in _failures.get(username, []) if t >= window]
    if hits:
        _failures[username] = hits
    else:
        _failures.pop(username, None)
    return len(hits) >= _LOCKOUT_AFTER


def _note_failure(username: str) -> None:
    now = time.time()
    _prune_failures(now)
    _failures.setdefault(username, []).append(now)


def _clear_failures(username: str) -> None:
    _failures.pop(username, None)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME, token,
        httponly=True,
        # Only sent over HTTPS when the deployment says it is behind TLS. Left
        # off in local development, where the console is served over plain HTTP
        # and a secure cookie would simply never be sent.
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
        max_age=int(settings.token_ttl_hours * 3600),
    )


def issue_session(user: User, db: Session, *, response: Response | None = None,
                  note: str = "") -> dict:
    """Mint a token for this account and record the sign-in.

    Shared with the password-change route, which re-issues a session because
    changing a password bumps token_version and would otherwise sign the caller
    out of the request they are in the middle of making.
    """
    token = issue_token(user.username, user.role, uid=user.id,
                        token_version=user.token_version)
    if response is not None:
        _set_session_cookie(response, token)
    payload = {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "username": user.username,
        "full_name": user.full_name,
        "must_change_password": user.must_change_password,
    }
    if note:
        payload["note"] = note
    return payload


@router.post("/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    key = (body.username or "").strip().lower()
    if key and _locked(key):
        db.add(AuditLog(username=body.username, role="", action="POST",
                        target="/api/auth/login", status=429, detail="lockout"))
        db.commit()
        raise HTTPException(status_code=429,
                            detail="Too many failed logins — try again shortly")

    user = authenticate(db, key, body.password)
    if user is None:
        _note_failure(key or body.username)
        db.add(AuditLog(username=body.username, role="", action="POST",
                        target="/api/auth/login", status=401,
                        detail="bad credentials"))
        db.commit()
        # One message for wrong password, unknown user and disabled account.
        # Distinguishing them tells an attacker which usernames are real.
        raise HTTPException(status_code=401, detail="Invalid credentials")

    _clear_failures(key)
    user.last_login_at = __import__("datetime").datetime.utcnow()
    db.add(AuditLog(username=user.username, role=user.role, action="POST",
                    target="/api/auth/login", status=200))
    db.commit()
    db.refresh(user)
    return issue_session(user, db, response=response)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db),
       creds: HTTPAuthorizationCredentials = Depends(bearer)):
    claims = claims_from_request(request)
    if claims is None and creds is not None:
        claims = decode_token(creds.credentials)
    if claims is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    out = {"username": claims.get("sub"), "role": claims.get("role"),
           "exp": claims.get("exp")}
    user = None
    if claims.get("uid") is not None:
        user = db.get(User, claims["uid"])
    if user is None:
        user = db.query(User).filter(User.username == claims.get("sub", "")).first()
    if user is not None:
        out.update(full_name=user.full_name, badge_no=user.badge_no,
                   must_change_password=user.must_change_password,
                   last_login_at=user.last_login_at)
    return out


@router.get("/audit")
def audit_trail(limit: int = 200, db: Session = Depends(get_db)):
    rows = db.query(AuditLog).order_by(AuditLog.ts.desc()).limit(min(limit, 1000)).all()
    return [{"id": r.id, "ts": r.ts, "username": r.username, "role": r.role,
             "action": r.action, "target": r.target, "status": r.status,
             "detail": r.detail} for r in rows]


def current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    """Dependency for routes that want the caller's identity. Blanket
    enforcement of mutations happens in the middleware, not here."""
    if creds is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    claims = decode_token(creds.credentials)
    if claims is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return claims
