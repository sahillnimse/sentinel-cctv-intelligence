"""Account administration.

Who can sign in to the console, at what level, and how that is revoked.

Access is admin-only, enforced in the RBAC middleware by the /api/users prefix
rather than per-route here, with one exception: changing your own password is
reachable by any signed-in account, including one that is being forced to
change it.

Two rules run through the whole module.

Accounts are deactivated, never deleted. The audit trail attributes actions by
username, so deleting the row orphans the record of everything that person did.

An admin cannot lock the department out. You cannot deactivate or demote
yourself, and the last active admin cannot be removed by any route, because
recovering from that needs database access nobody has at 3am.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import (PasswordChange, TempPasswordOut, UserCreate, UserOut,
                       UserUpdate)
from ..security import ROLES, audit, claims_from_request
from ..utils import passwords

log = logging.getLogger("sentinel.users")

router = APIRouter(prefix="/users", tags=["users"])

MIN_USERNAME = 3
MAX_USERNAME = 100


def _caller(request: Request) -> dict:
    return claims_from_request(request) or {}


def _normalise_username(raw: str) -> str:
    name = (raw or "").strip().lower()
    if len(name) < MIN_USERNAME or len(name) > MAX_USERNAME:
        raise HTTPException(
            400, f"Username must be {MIN_USERNAME}-{MAX_USERNAME} characters")
    if not all(c.isalnum() or c in "._-" for c in name):
        raise HTTPException(
            400, "Username may contain letters, digits, dot, underscore and hyphen only")
    return name


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(ROLES)}")
    return role


def _active_admins(db: Session, *, excluding: int | None = None) -> int:
    q = db.query(func.count(User.id)).filter(User.role == "admin", User.active.is_(True))
    if excluding is not None:
        q = q.filter(User.id != excluding)
    return q.scalar() or 0


def _guard_last_admin(db: Session, target: User, *, new_role: str | None = None,
                      new_active: bool | None = None) -> None:
    """Refuse a change that would leave no active admin."""
    still_admin = (new_role or target.role) == "admin"
    still_active = target.active if new_active is None else new_active
    if still_admin and still_active:
        return
    if target.role == "admin" and target.active and _active_admins(db, excluding=target.id) == 0:
        raise HTTPException(
            409, "This is the last active administrator — promote another "
                 "account to admin before changing this one")


def _guard_not_self(caller: dict, target: User, action: str) -> None:
    if caller.get("uid") == target.id or caller.get("sub") == target.username:
        raise HTTPException(
            409, f"You cannot {action} your own account — ask another administrator")


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    """Every account, active and not. Deactivated accounts stay visible so an
    admin can see who used to have access and when they last signed in."""
    return db.query(User).order_by(User.active.desc(), User.username).all()


@router.post("", response_model=TempPasswordOut, status_code=201)
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db)):
    """Create an account. The temporary password is returned exactly once."""
    caller = _caller(request)
    username = _normalise_username(body.username)
    role = _check_role(body.role)

    if db.query(User).filter(User.username == username).first() is not None:
        raise HTTPException(409, f"Username '{username}' is already taken")

    if body.password:
        problem = passwords.policy_error(body.password, username=username)
        if problem:
            raise HTTPException(400, problem)
        secret, forced = body.password, False
    else:
        secret, forced = passwords.generate(), True

    user = User(
        username=username,
        password_hash=passwords.hash_password(secret),
        role=role,
        full_name=(body.full_name or "").strip(),
        badge_no=(body.badge_no or "").strip(),
        active=True,
        must_change_password=True if forced else False,
        created_by=caller.get("sub", ""),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    audit(db, user=caller.get("sub", ""), role=caller.get("role", ""),
          action="POST", target="/api/users", status=201,
          detail={"created": username, "role": role})
    log.info("account created: %s (%s) by %s", username, role, caller.get("sub", ""))
    return TempPasswordOut(user=UserOut.model_validate(user), temporary_password=secret)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, request: Request,
                db: Session = Depends(get_db)):
    """Change role, name, badge or active state."""
    caller = _caller(request)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")

    changes: dict = {}

    if body.role is not None and body.role != user.role:
        _check_role(body.role)
        _guard_not_self(caller, user, "change the role of")
        _guard_last_admin(db, user, new_role=body.role)
        changes["role"] = f"{user.role} -> {body.role}"
        user.role = body.role
        # The old token carries the old role. Force a fresh sign-in rather than
        # letting a demoted account keep admin claims until its token expires.
        user.token_version += 1

    if body.active is not None and body.active != user.active:
        _guard_not_self(caller, user, "deactivate")
        _guard_last_admin(db, user, new_active=body.active)
        changes["active"] = f"{user.active} -> {body.active}"
        user.active = body.active
        # Revokes every session this account currently holds.
        user.token_version += 1

    if body.full_name is not None and body.full_name.strip() != user.full_name:
        changes["full_name"] = True
        user.full_name = body.full_name.strip()

    if body.badge_no is not None and body.badge_no.strip() != user.badge_no:
        changes["badge_no"] = True
        user.badge_no = body.badge_no.strip()

    if not changes:
        return user

    db.commit()
    db.refresh(user)
    audit(db, user=caller.get("sub", ""), role=caller.get("role", ""),
          action="PATCH", target=f"/api/users/{user_id}", status=200,
          detail={"target": user.username, **changes})
    return user


@router.delete("/{user_id}")
def deactivate_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    """Revoke access. Deactivates rather than deleting, and ends any live
    session immediately."""
    caller = _caller(request)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    _guard_not_self(caller, user, "deactivate")
    _guard_last_admin(db, user, new_active=False)

    if user.active:
        user.active = False
        user.token_version += 1
        db.commit()

    audit(db, user=caller.get("sub", ""), role=caller.get("role", ""),
          action="DELETE", target=f"/api/users/{user_id}", status=200,
          detail={"deactivated": user.username})
    log.info("account deactivated: %s by %s", user.username, caller.get("sub", ""))
    return {"deactivated": user.username, "id": user.id,
            "note": "Account retained for audit history; sessions revoked."}


@router.post("/{user_id}/reset-password", response_model=TempPasswordOut)
def reset_password(user_id: int, request: Request, db: Session = Depends(get_db)):
    """Issue a new temporary password and end the account's live sessions.

    An admin never sees or sets the existing password; there is no route that
    reveals one, because the stored form is a one-way hash.
    """
    caller = _caller(request)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")

    secret = passwords.generate()
    user.password_hash = passwords.hash_password(secret)
    user.must_change_password = True
    # A reset is usually a response to a suspected compromise, so existing
    # sessions must not survive it.
    user.token_version += 1
    db.commit()
    db.refresh(user)

    audit(db, user=caller.get("sub", ""), role=caller.get("role", ""),
          action="POST", target=f"/api/users/{user_id}/reset-password", status=200,
          detail={"target": user.username})
    log.info("password reset for %s by %s", user.username, caller.get("sub", ""))
    return TempPasswordOut(user=UserOut.model_validate(user), temporary_password=secret)


@router.post("/me/password")
def change_own_password(body: PasswordChange, request: Request,
                        db: Session = Depends(get_db)):
    """Change your own password. Requires the current one."""
    caller = _caller(request)
    if not caller:
        raise HTTPException(401, "Not authenticated")

    user = None
    if caller.get("uid") is not None:
        user = db.get(User, caller["uid"])
    if user is None:
        user = db.query(User).filter(User.username == caller.get("sub", "")).first()
    if user is None:
        raise HTTPException(404, "Account not found")

    if not passwords.verify(body.current_password, user.password_hash):
        audit(db, user=user.username, role=user.role, action="POST",
              target="/api/users/me/password", status=401,
              detail={"reason": "current password incorrect"})
        raise HTTPException(401, "Current password is incorrect")

    problem = passwords.policy_error(body.new_password, username=user.username)
    if problem:
        raise HTTPException(400, problem)
    if passwords.verify(body.new_password, user.password_hash):
        raise HTTPException(400, "New password must be different from the current one")

    user.password_hash = passwords.hash_password(body.new_password)
    user.must_change_password = False
    # Every other session for this account is signed out. If the reason for the
    # change is that someone else knows the old password, leaving their session
    # alive defeats the point. The caller gets a fresh token below.
    user.token_version += 1
    db.commit()
    db.refresh(user)

    audit(db, user=user.username, role=user.role, action="POST",
          target="/api/users/me/password", status=200)

    from ..routers.auth import issue_session
    return issue_session(user, db, note="Password changed. Other sessions signed out.")


@router.get("/me", response_model=UserOut)
def me(request: Request, db: Session = Depends(get_db)):
    """The signed-in account's own profile."""
    caller = _caller(request)
    if not caller:
        raise HTTPException(401, "Not authenticated")
    user = None
    if caller.get("uid") is not None:
        user = db.get(User, caller["uid"])
    if user is None:
        user = db.query(User).filter(User.username == caller.get("sub", "")).first()
    if user is None:
        raise HTTPException(404, "Account not found")
    return user
