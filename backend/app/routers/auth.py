from datetime import datetime, timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import settings
from ..schemas import LoginIn, TokenOut

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn):
    if body.username != settings.admin_username or body.password != settings.admin_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = jwt.encode(
        {"sub": body.username, "role": "admin", "exp": datetime.utcnow() + timedelta(hours=12)},
        settings.jwt_secret,
        algorithm="HS256",
    )
    return TokenOut(access_token=token)


def current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    """Dependency for routes you want to protect. Not applied globally in dev."""
    if creds is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
