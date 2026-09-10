"""Password hashing and policy.

PBKDF2-HMAC-SHA256 from the standard library rather than bcrypt or argon2.
Three reasons: no compiled dependency to get onto a departmental machine, the
algorithm is FIPS-approved which matters for government procurement, and the
work factor is stored per hash so it can be raised later without invalidating
existing passwords.

Stored form:  pbkdf2_sha256$<iterations>$<salt_b64>$<derived_b64>

Everything the rest of the app needs is verify() and hash_password(). Nothing
outside this module should see a plaintext password, and nothing anywhere
should log one.
"""

import base64
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000  # OWASP guidance for PBKDF2-HMAC-SHA256
SALT_BYTES = 16
DERIVED_BYTES = 32

MIN_LENGTH = 10
# A password nobody should be able to set, whatever the policy says. These are
# the first guesses in any credential-stuffing run against an Indian police
# deployment, and the shipped defaults are on the list precisely because an
# operator creating accounts will reach for them.
_FORBIDDEN = {
    "password", "password1", "passw0rd", "12345678", "123456789", "1234567890",
    "qwertyuiop", "admin123", "operator123", "viewer123", "sentinel", "sentinel123",
    "gujarat123", "police123", "changeme", "letmein123", "welcome123",
}


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                  iterations, dklen=DERIVED_BYTES)
    return f"{ALGORITHM}${iterations}${_b64(salt)}${_b64(derived)}"


def verify(password: str, stored: str) -> bool:
    """Constant-time check of a candidate password against a stored hash.

    Returns False rather than raising on a malformed hash: a corrupt row must
    fail the login, not 500 the endpoint and tell the caller the row exists.
    """
    try:
        algorithm, iterations, salt_b64, derived_b64 = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                      _unb64(salt_b64), int(iterations),
                                      dklen=len(_unb64(derived_b64)))
        return hmac.compare_digest(derived, _unb64(derived_b64))
    except (ValueError, TypeError, base64.binascii.Error):
        return False


def needs_rehash(stored: str) -> bool:
    """True when a stored hash was made with a weaker work factor than current.

    Lets ITERATIONS be raised over time: the next successful login re-hashes at
    the new cost, so old accounts catch up without a forced reset.
    """
    try:
        algorithm, iterations, _, _ = stored.split("$")
        return algorithm != ALGORITHM or int(iterations) < ITERATIONS
    except ValueError:
        return True


def policy_error(password: str, *, username: str = "") -> str | None:
    """Why this password is unacceptable, or None if it is fine.

    Deliberately short. A long rule list pushes people towards one predictable
    pattern that satisfies every rule, and length is what actually helps.
    """
    if len(password) < MIN_LENGTH:
        return f"Password must be at least {MIN_LENGTH} characters"
    if password.lower() in _FORBIDDEN:
        return "That password is too common — choose something unpredictable"
    if username and password.lower() == username.lower():
        return "Password must not be the username"
    if len(set(password)) < 4:
        return "Password must use at least 4 different characters"
    return None


def generate(length: int = 14) -> str:
    """A temporary password for an admin-created or admin-reset account.

    Excludes characters that are misread off a screen or over a phone, since
    these get handed to a person verbally or on paper.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        if policy_error(candidate) is None:
            return candidate
