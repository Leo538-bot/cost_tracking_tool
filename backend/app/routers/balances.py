from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import CurrentUser, get_current_user, get_group_member, write_audit
from ..models import AuditLog, Expense, Member, Settlement
from ..schemas import (
    AuditLogOut,
    BalanceOut,
    BalanceSummary,
    SettlementCreate,
    SettlementOut,
    TransferOut,
)
from ..splitting import compute_balances, simplify_debts

router = APIRouter(prefix="/api", tags=["balances"])


@router.get("/balances", response_model=BalanceSummary)
def get_balances(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Who owes whom, and the shortest set of payments that clears it."""
    group = user.group
    members = db.scalars(
        select(Member).where(Member.group_id == group.id).order_by(Member.created_at)
    ).all()
    by_id = {m.id: m for m in members}

    expenses = db.scalars(select(Expense).where(Expense.group_id == group.id)).all()
    settlements = db.scalars(select(Settlement).where(Settlement.group_id == group.id)).all()

    paid: dict[uuid.UUID, int] = dict.fromkeys(by_id, 0)
    owed: dict[uuid.UUID, int] = dict.fromkeys(by_id, 0)
    expense_tuples = []
    for expense in expenses:
        shares = {s.member_id: s.amount_cents for s in expense.shares}
        expense_tuples.append((expense.payer_id, expense.amount_cents, shares))
        paid[expense.payer_id] = paid.get(expense.payer_id, 0) + expense.amount_cents
        for member_id, amount in shares.items():
            owed[member_id] = owed.get(member_id, 0) + amount

    balances = compute_balances(
        expenses=expense_tuples,
        settlements=[(s.from_member_id, s.to_member_id, s.amount_cents) for s in settlements],
        member_ids=list(by_id),
    )
    transfers = simplify_debts(balances)

    return BalanceSummary(
        currency=group.currency,
        total_spent_cents=sum(e.amount_cents for e in expenses),
        balances=[
            BalanceOut(
                member_id=m.id,
                display_name=m.display_name,
                color=m.color,
                net_cents=balances.get(m.id, 0),
                paid_cents=paid.get(m.id, 0),
                share_cents=owed.get(m.id, 0),
            )
            for m in members
        ],
        suggested_transfers=[
            TransferOut(
                from_member_id=t.from_member_id,
                from_name=by_id[t.from_member_id].display_name,
                to_member_id=t.to_member_id,
                to_name=by_id[t.to_member_id].display_name,
                amount_cents=t.amount_cents,
            )
            for t in transfers
        ],
    )


@router.get("/settlements", response_model=list[SettlementOut])
def list_settlements(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settlements = db.scalars(
        select(Settlement)
        .where(Settlement.group_id == user.group.id)
        .order_by(Settlement.created_at.desc())
    ).all()
    return [
        SettlementOut(
            id=s.id,
            from_member_id=s.from_member_id,
            from_name=s.from_member.display_name,
            to_member_id=s.to_member_id,
            to_name=s.to_member.display_name,
            amount_cents=s.amount_cents,
            note=s.note,
            created_at=s.created_at,
        )
        for s in settlements
    ]


@router.post("/settlements", response_model=SettlementOut, status_code=status.HTTP_201_CREATED)
def create_settlement(
    payload: SettlementCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record that cash actually changed hands."""
    if payload.from_member_id == payload.to_member_id:
        raise HTTPException(400, "Sender und Empfänger müssen unterschiedlich sein.")

    sender = get_group_member(db, user.group.id, payload.from_member_id)
    receiver = get_group_member(db, user.group.id, payload.to_member_id)

    settlement = Settlement(
        group_id=user.group.id,
        from_member_id=sender.id,
        to_member_id=receiver.id,
        amount_cents=payload.amount_cents,
        note=payload.note,
        created_by_id=user.member.id,
    )
    db.add(settlement)
    write_audit(
        db,
        request=request,
        user=user,
        action="settlement.create",
        entity_type="settlement",
        summary=(
            f"{sender.display_name} → {receiver.display_name}: "
            f"{payload.amount_cents / 100:.2f} {user.group.currency}"
        ),
    )
    db.commit()
    db.refresh(settlement)

    return SettlementOut(
        id=settlement.id,
        from_member_id=sender.id,
        from_name=sender.display_name,
        to_member_id=receiver.id,
        to_name=receiver.display_name,
        amount_cents=settlement.amount_cents,
        note=settlement.note,
        created_at=settlement.created_at,
    )


@router.delete("/settlements/{settlement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_settlement(
    settlement_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settlement = db.scalar(
        select(Settlement).where(
            Settlement.id == settlement_id, Settlement.group_id == user.group.id
        )
    )
    if settlement is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zahlung nicht gefunden.")
    if settlement.created_by_id != user.member.id and not user.member.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Dazu fehlt dir die Berechtigung.")

    db.delete(settlement)
    write_audit(
        db,
        request=request,
        user=user,
        action="settlement.delete",
        entity_type="settlement",
        summary="Rückzahlung gelöscht",
    )
    db.commit()


@router.get("/activity", response_model=list[AuditLogOut])
def get_activity(
    limit: int = 50,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Recent changes, so the group can see who did what."""
    logs = db.scalars(
        select(AuditLog)
        .where(AuditLog.group_id == user.group.id)
        .order_by(AuditLog.created_at.desc())
        .limit(min(max(limit, 1), 200))
    ).all()
    return [
        AuditLogOut(
            id=log.id,
            member_name=log.member.display_name if log.member else None,
            action=log.action,
            entity_type=log.entity_type,
            summary=log.summary,
            created_at=log.created_at,
        )
        for log in logs
    ]
