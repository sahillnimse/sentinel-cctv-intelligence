from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog
from ..schemas import LoginIn, TokenOut
from ..security import authenticate, decode_token, issue_token

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    role = authenticate(body.username, body.password)
    if role is None:
        # Failed logins are worth recording; brute force shows up here.
        db.add(AuditLog(username=body.username, role="", action="POST",
                        target="/api/auth/login", status=401, detail="bad credentials"))
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    db.add(AuditLog(username=body.username, role=role, action="POST",
                    target="/api/auth/login", status=200))
    db.commit()
    return TokenOut(access_token=issue_token(body.username, role), role=role)


@router.get("/me")
def me(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    if creds is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    claims = decode_token(creds.credentials)
    if claims is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
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
