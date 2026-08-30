from __future__ import annotations

import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import AuditLog, Group, Member
from .security import constant_time_equals, decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Nicht angemeldet oder Sitzung abgelaufen.",
    headers={"WWW-Authenticate": "Bearer"},
)


def client_ip(request: Request) -> str:
    """The visitor's address, as reported by the reverse proxy.

    The proxy overwrites this header on every request, and the API port is not
    published, so a caller cannot spoof it by sending one. If the header is
    unset -- running the API directly, say -- fall back to the socket peer.
    """
    if settings.client_ip_header:
        forwarded = request.headers.get(settings.client_ip_header)
        if forwarded:
            # Take the first entry: proxies append, so the client is leftmost.
            candidate = forwarded.split(",")[0].strip()
            if candidate:
                return candidate[:45]
    return request.client.host if request.client else "unknown"


@dataclass
class CurrentUser:
    member: Member
    group: Group
    device_id: str


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if credentials is None:
        raise CREDENTIALS_ERROR

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise CREDENTIALS_ERROR from None

    try:
        member_id = uuid.UUID(payload["sub"])
        group_id = uuid.UUID(payload["gid"])
        device_id = str(payload["did"])
    except (KeyError, ValueError, TypeError):
        raise CREDENTIALS_ERROR from None

    member = db.get(Member, member_id)
    if member is None or member.group_id != group_id:
        raise CREDENTIALS_ERROR

    # A token stays valid only for the device that claimed the name. If the member
    # was re-bound to another device, older tokens stop working.
    if member.device_id is None or not constant_time_equals(member.device_id, device_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Dieser Name ist inzwischen an ein anderes Gerät gebunden.",
        )

    group = db.get(Group, group_id)
    if group is None:
        raise CREDENTIALS_ERROR

    request.state.member_id = member.id
    return CurrentUser(member=member, group=group, device_id=device_id)


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.member.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur der Gruppen-Admin darf das.",
        )
    return user


def get_group_member(db: Session, group_id: uuid.UUID, member_id: uuid.UUID) -> Member:
    """Load a member, refusing ids that belong to some other group."""
    member = db.scalar(select(Member).where(Member.id == member_id, Member.group_id == group_id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unbekanntes Gruppenmitglied.",
        )
    return member


def write_audit(
    db: Session,
    *,
    request: Request,
    user: CurrentUser,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    summary: str | None = None,
) -> None:
    db.add(
        AuditLog(
            group_id=user.group.id,
            member_id=user.member.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
            device_id=user.device_id,
            ip_address=client_ip(request),
        )
    )
