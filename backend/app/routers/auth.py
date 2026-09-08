from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import AuditLog
from ..schemas import LoginIn, TokenOut
from ..security import (COOKIE_NAME, authenticate, claims_from_request,
                        decode_token, issue_token)

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)

_LOCKOUT_AFTER = 8
_LOCKOUT_SECONDS = 60
_failures: dict[str, list[float]] = {}


def _locked(username: str) -> bool:
    import time
    window = time.time() - _LOCKOUT_SECONDS
    hits = [t for t in _failures.get(username, []) if t >= window]
    _failures[username] = hits
    return len(hits) >= _LOCKOUT_AFTER


def _note_failure(username: str) -> None:
    import time
    _failures.setdefault(username, []).append(time.time())


def _clear_failures(username: str) -> None:
    _failures.pop(username, None)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME, token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=int(settings.token_ttl_hours * 3600),
    )


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    key = (body.username or "").strip().lower()
    if key and _locked(key):
        db.add(AuditLog(username=body.username, role="", action="POST",
                        target="/api/auth/login", status=429, detail="lockout"))
        db.commit()
        raise HTTPException(status_code=429, detail="Too many failed logins — try again shortly")
    role = authenticate(body.username, body.password)
    if role is None:
        _note_failure(key or body.username)
        db.add(AuditLog(username=body.username, role="", action="POST",
                        target="/api/auth/login", status=401, detail="bad credentials"))
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _clear_failures(key)
    db.add(AuditLog(username=body.username, role=role, action="POST",
                    target="/api/auth/login", status=200))
    db.commit()
    token = issue_token(body.username, role)
    _set_session_cookie(response, token)
    return TokenOut(access_token=token, role=role)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request, creds: HTTPAuthorizationCredentials = Depends(bearer)):
    claims = claims_from_request(request)
    if claims is None and creds is not None:
        claims = decode_token(creds.credentials)
    if claims is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"username": claims.get("sub"), "role": claims.get("role"),
            "exp": claims.get("exp")}


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
