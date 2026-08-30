from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slugify import slugify
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import rate_limit
from ..database import get_db
from ..deps import CurrentUser, client_ip, get_current_user
from ..models import AuditLog, Group, Member
from ..schemas import AuthResponse, GroupCreate, GroupOut, LoginRequest, MemberOut
from ..security import (
    constant_time_equals,
    create_access_token,
    generate_recovery_key,
    hash_password,
    new_device_id,
    normalise_recovery_key,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Distinct, readable on white, colour-blind friendly enough for a small group.
MEMBER_COLORS = [
    "#6366f1",
    "#ec4899",
    "#f59e0b",
    "#10b981",
    "#3b82f6",
    "#8b5cf6",
    "#ef4444",
    "#14b8a6",
    "#f97316",
    "#84cc16",
]


def _unique_slug(db: Session, name: str) -> str:
    base = slugify(name)[:120] or "trip"
    candidate = base
    while db.scalar(select(Group.id).where(Group.slug == candidate)) is not None:
        candidate = f"{base}-{secrets.token_hex(2)}"
    return candidate


def _pick_color(db: Session, group_id) -> str:
    used = db.scalars(select(Member.color).where(Member.group_id == group_id)).all()
    for color in MEMBER_COLORS:
        if color not in used:
            return color
    return secrets.choice(MEMBER_COLORS)


@router.post("/groups", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreate, request: Request, db: Session = Depends(get_db)):
    """Create a trip and log the creator in as its admin.

    The recovery key returned here is the only time it is ever visible.
    """
    recovery_key = generate_recovery_key()
    group = Group(
        name=payload.name.strip(),
        slug=_unique_slug(db, payload.name),
        password_hash=hash_password(payload.password),
        recovery_key_hash=hash_password(recovery_key),
        recovery_key_set_at=func.now(),
        currency=payload.currency,
    )
    db.add(group)
    db.flush()

    display_name = payload.admin_name.strip()
    device_id = new_device_id()
    admin = Member(
        group_id=group.id,
        display_name=display_name,
        name_key=display_name.casefold(),
        device_id=device_id,
        is_admin=True,
        color=MEMBER_COLORS[0],
        last_seen_at=func.now(),
    )
    db.add(admin)
    db.flush()

    db.add(
        AuditLog(
            group_id=group.id,
            member_id=admin.id,
            action="group.create",
            entity_type="group",
            entity_id=group.id,
            summary=f"Gruppe '{group.name}' angelegt",
            device_id=device_id,
            ip_address=client_ip(request),
        )
    )
    db.commit()
    db.refresh(group)
    db.refresh(admin)

    token = create_access_token(member_id=admin.id, group_id=group.id, device_id=device_id)
    return AuthResponse(
        access_token=token,
        device_id=device_id,
        member=MemberOut.model_validate(admin),
        group=GroupOut.model_validate(group),
        recovery_key=recovery_key,
    )


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Join a trip with the shared password, claiming or resuming a name.

    A name belongs to the first device that claims it. Returning devices send the
    device_id they were given; anyone else asking for that name is refused.
    """
    caller_ip = client_ip(request)
    limiter_key = f"{caller_ip}:{payload.group_slug}"
    using_recovery = bool(payload.recovery_key and payload.recovery_key.strip())

    if using_recovery:
        allowed, retry_after = rate_limit.check_and_record(
            f"recovery:{limiter_key}",
            max_attempts=rate_limit.RECOVERY_MAX_ATTEMPTS,
            window_seconds=rate_limit.RECOVERY_WINDOW_SECONDS,
        )
    else:
        allowed, retry_after = rate_limit.check_and_record(limiter_key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Zu viele Fehlversuche. Bitte später erneut probieren.",
            headers={"Retry-After": str(retry_after)},
        )

    group = db.scalar(select(Group).where(Group.slug == payload.group_slug.strip().lower()))

    # Same generic error whether the group or the password was wrong, so the
    # endpoint cannot be used to enumerate existing trips.
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Gruppe oder Passwort stimmt nicht.",
    )
    if group is None or not verify_password(payload.password, group.password_hash):
        raise invalid

    display_name = payload.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="Bitte einen Namen angeben.")

    member = db.scalar(
        select(Member).where(
            Member.group_id == group.id, Member.name_key == display_name.casefold()
        )
    )

    issued_recovery_key: str | None = None

    if using_recovery:
        # Emergency path: the phone that held this name is gone for good.
        if group.recovery_key_hash is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Für diese Reise ist kein Notfall-Schlüssel hinterlegt.",
            )
        if not verify_password(
            normalise_recovery_key(payload.recovery_key or ""), group.recovery_key_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Der Notfall-Schlüssel stimmt nicht.",
            )
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"In dieser Reise gibt es niemanden mit dem Namen '{display_name}'. "
                    "Der Notfall-Schlüssel stellt nur bestehende Namen wieder her."
                ),
            )

        device_id = new_device_id()
        member.device_id = device_id
        # Reaching for the emergency key means admin access is broken, so the
        # recovered member becomes admin -- otherwise the trip stays leaderless.
        member.is_admin = True

        # Burn the used key immediately and hand out a fresh one, so a key that
        # was written down and passed around cannot be replayed.
        issued_recovery_key = generate_recovery_key()
        group.recovery_key_hash = hash_password(issued_recovery_key)
        group.recovery_key_set_at = func.now()

        action = "member.recover"
        summary = f"{display_name} wurde per Notfall-Schlüssel wiederhergestellt"
    elif member is None:
        device_id = new_device_id()
        member = Member(
            group_id=group.id,
            display_name=display_name,
            name_key=display_name.casefold(),
            device_id=device_id,
            is_admin=False,
            color=_pick_color(db, group.id),
        )
        db.add(member)
        action = "member.join"
        summary = f"{display_name} ist der Gruppe beigetreten"
    elif member.device_id is None:
        # Admin released the name; the next device to log in takes it over.
        device_id = new_device_id()
        member.device_id = device_id
        action = "member.rebind"
        summary = f"{display_name} wurde auf einem neuen Gerät angemeldet"
    elif payload.device_id and constant_time_equals(member.device_id, payload.device_id):
        device_id = member.device_id
        action = "member.login"
        summary = f"{display_name} hat sich angemeldet"
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Der Name '{display_name}' gehört bereits zu einem anderen Gerät. "
                "Wähle einen anderen Namen, oder lass ihn vom Admin freigeben."
            ),
        )

    member.last_seen_at = func.now()
    db.flush()
    db.add(
        AuditLog(
            group_id=group.id,
            member_id=member.id,
            action=action,
            entity_type="member",
            entity_id=member.id,
            summary=summary,
            device_id=device_id,
            ip_address=caller_ip,
        )
    )
    db.commit()
    db.refresh(member)

    rate_limit.clear(limiter_key)
    if using_recovery:
        rate_limit.clear(f"recovery:{limiter_key}")

    token = create_access_token(member_id=member.id, group_id=group.id, device_id=device_id)
    return AuthResponse(
        access_token=token,
        device_id=device_id,
        member=MemberOut.model_validate(member),
        group=GroupOut.model_validate(group),
        recovery_key=issued_recovery_key,
    )


@router.get("/me", response_model=AuthResponse)
def me(user: CurrentUser = Depends(get_current_user)):
    """Re-validate a stored token on app start."""
    token = create_access_token(
        member_id=user.member.id, group_id=user.group.id, device_id=user.device_id
    )
    return AuthResponse(
        access_token=token,
        device_id=user.device_id,
        member=MemberOut.model_validate(user.member),
        group=GroupOut.model_validate(user.group),
    )
