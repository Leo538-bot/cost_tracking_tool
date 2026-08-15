from __future__ import annotations

import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from .config import settings

# bcrypt silently truncates at 72 bytes; reject longer input instead of pretending.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError("password too long")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except ValueError:
        return False


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def create_access_token(*, member_id: uuid.UUID, group_id: uuid.UUID, device_id: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(member_id),
        "gid": str(group_id),
        "did": device_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.session_days)).timestamp()),
        "jti": secrets.token_urlsafe(8),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError on any tampering, expiry or malformed input."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def new_device_id() -> str:
    return secrets.token_urlsafe(24)


# Ambiguous characters are left out so the key can be copied off a handwritten
# note without 0/O or 1/I/l guesswork.
_RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_RECOVERY_GROUPS = 4
_RECOVERY_GROUP_LEN = 4


def generate_recovery_key() -> str:
    """A one-off emergency key, e.g. 'K7QM-3XPD-9WRT-BFHS' (~79 bits)."""
    groups = [
        "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_GROUP_LEN))
        for _ in range(_RECOVERY_GROUPS)
    ]
    return "-".join(groups)


def normalise_recovery_key(raw: str) -> str:
    """Accept what people actually type: lower case, spaces, missing dashes."""
    cleaned = "".join(ch for ch in raw.upper() if ch.isalnum())
    if len(cleaned) != _RECOVERY_GROUPS * _RECOVERY_GROUP_LEN:
        return cleaned
    return "-".join(
        cleaned[i : i + _RECOVERY_GROUP_LEN]
        for i in range(0, len(cleaned), _RECOVERY_GROUP_LEN)
    )
