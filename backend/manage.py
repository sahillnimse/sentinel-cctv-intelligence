"""Offline account recovery.

The console deliberately refuses to let an administrator strand the department:
you cannot revoke or demote yourself, and the last active admin cannot be
removed. Those rules stop the common accidents, but they do not help when
nobody knows the admin password any more — a forgotten password, someone
leaving, a reset that was never written down.

Recovering from that needs a path that does not require being signed in, so it
lives here rather than in the API. Running it requires shell access to the
server and the database file, which is the access boundary this relies on.

Every action is written to the audit trail as "console" so it is visible
alongside the rest, and never looks like the account did it to itself.

    python manage.py list
    python manage.py reset-password <username>
    python manage.py create-admin <username>
    python manage.py activate <username>
"""

import sys
from datetime import datetime

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from app.db import SessionLocal          # noqa: E402
from app.models import AuditLog, User    # noqa: E402
from app.utils import passwords          # noqa: E402


def _audit(db, action: str, target: str, detail: str) -> None:
    db.add(AuditLog(ts=datetime.utcnow(), username="console", role="admin",
                    action=action, target=target, status=200, detail=detail))


def _find(db, username: str) -> User:
    user = db.query(User).filter(User.username == username.strip().lower()).first()
    if user is None:
        sys.exit(f"No account named {username!r}. Run 'python manage.py list'.")
    return user


def cmd_list(db, _args) -> None:
    users = db.query(User).order_by(User.active.desc(), User.username).all()
    if not users:
        print("No accounts. The server seeds them from .env on first start.")
        return
    print(f"{'username':<24}{'role':<12}{'status':<12}{'last sign-in'}")
    print("-" * 74)
    for u in users:
        status = "active" if u.active else "revoked"
        if u.active and u.must_change_password:
            status = "must reset"
        seen = u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else "never"
        print(f"{u.username:<24}{u.role:<12}{status:<12}{seen}")


def cmd_reset_password(db, args) -> None:
    if not args:
        sys.exit("usage: python manage.py reset-password <username>")
    user = _find(db, args[0])
    secret = passwords.generate()
    user.password_hash = passwords.hash_password(secret)
    user.must_change_password = True
    user.active = True
    # Ends any session the account still holds, on the assumption that a
    # password nobody knew may have been known by someone else.
    user.token_version += 1
    _audit(db, "RESET", f"user:{user.username}", "password reset from console")
    db.commit()
    print(f"\n  {user.username} -> {secret}\n")
    print("Shown once. Sign in with it and the console will require a new one.")


def cmd_create_admin(db, args) -> None:
    if not args:
        sys.exit("usage: python manage.py create-admin <username>")
    name = args[0].strip().lower()
    if db.query(User).filter(User.username == name).first() is not None:
        sys.exit(f"{name!r} already exists. Use reset-password instead.")
    secret = passwords.generate()
    db.add(User(username=name, password_hash=passwords.hash_password(secret),
                role="admin", full_name="Recovery administrator", active=True,
                must_change_password=True, created_by="console"))
    _audit(db, "CREATE", f"user:{name}", "admin created from console")
    db.commit()
    print(f"\n  {name} -> {secret}\n")
    print("Shown once. Sign in with it and the console will require a new one.")


def cmd_activate(db, args) -> None:
    if not args:
        sys.exit("usage: python manage.py activate <username>")
    user = _find(db, args[0])
    user.active = True
    user.token_version += 1
    _audit(db, "ACTIVATE", f"user:{user.username}", "reactivated from console")
    db.commit()
    print(f"{user.username} is active again.")


COMMANDS = {
    "list": cmd_list,
    "reset-password": cmd_reset_password,
    "create-admin": cmd_create_admin,
    "activate": cmd_activate,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    db = SessionLocal()
    try:
        COMMANDS[sys.argv[1]](db, sys.argv[2:])
    finally:
        db.close()


if __name__ == "__main__":
    main()
