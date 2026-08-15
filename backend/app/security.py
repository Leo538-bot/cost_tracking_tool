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
