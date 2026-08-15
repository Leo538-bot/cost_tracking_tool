from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import CurrentUser, get_group_member, require_admin, write_audit
from ..models import Expense, ExpenseShare, Settlement
from ..security import generate_recovery_key, hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


class PasswordChange(BaseModel):
    new_password: str = Field(min_length=8, max_length=72)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_group_password(
    payload: PasswordChange,
    request: Request,
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Rotate the shared password, e.g. after someone leaves the trip.

    Existing sessions keep working -- tokens are tied to the device, not the password.
    """
    user.group.password_hash = hash_password(payload.new_password)
    write_audit(
        db,
        request=request,
        user=user,
        action="group.password_change",
        entity_type="group",
        entity_id=user.group.id,
        summary="Gruppen-Passwort geändert",
    )
    db.commit()


class RecoveryKeyOut(BaseModel):
    recovery_key: str


@router.post("/recovery-key", response_model=RecoveryKeyOut)
def regenerate_recovery_key(
    request: Request,
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Issue a fresh emergency key, invalidating the previous one.

    Use this when the old key was lost, or after it has been shown to someone who
    should not keep it. The value is returned once and only its hash is stored.
    """
    key = generate_recovery_key()
    user.group.recovery_key_hash = hash_password(key)
    user.group.recovery_key_set_at = func.now()
    write_audit(
        db,
        request=request,
        user=user,
        action="group.recovery_key_reset",
        entity_type="group",
        entity_id=user.group.id,
        summary="Neuer Notfall-Schlüssel erzeugt (alter ist ungültig)",
    )
    db.commit()
    return RecoveryKeyOut(recovery_key=key)


@router.post("/members/{member_id}/release", status_code=status.HTTP_204_NO_CONTENT)
def release_member_device(
    member_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Unbind a name from its device so a new phone can claim it.

    This is the recovery path for a lost or wiped phone. It invalidates the old
    device's token, so only one device holds a name at a time.
    """
    member = get_group_member(db, user.group.id, member_id)
    member.device_id = None
    write_audit(
        db,
        request=request,
        user=user,
        action="member.release",
        entity_type="member",
        entity_id=member.id,
        summary=f"Gerätebindung von {member.display_name} aufgehoben",
    )
    db.commit()


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    member_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Remove someone who never took part in any cost.

    Members referenced by an expense or a settlement are kept, because deleting them
    would silently rewrite the group's history.
    """
    member = get_group_member(db, user.group.id, member_id)
    if member.id == user.member.id:
        raise HTTPException(400, "Du kannst dich nicht selbst entfernen.")

    referenced = db.scalar(
        select(Expense.id).where(
            (Expense.payer_id == member.id) | (Expense.created_by_id == member.id)
        )
    ) or db.scalar(
        select(ExpenseShare.id).where(ExpenseShare.member_id == member.id)
    ) or db.scalar(
        select(Settlement.id).where(
            (Settlement.from_member_id == member.id)
            | (Settlement.to_member_id == member.id)
            | (Settlement.created_by_id == member.id)
        )
    )
    if referenced is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{member.display_name} kommt in Ausgaben vor und kann nicht entfernt werden.",
        )

    name = member.display_name
    db.delete(member)
    write_audit(
        db,
        request=request,
        user=user,
        action="member.remove",
        entity_type="member",
        entity_id=member_id,
        summary=f"{name} aus der Gruppe entfernt",
    )
    db.commit()
