from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import CurrentUser, get_current_user, get_group_member, write_audit
from ..models import Expense, ExpenseShare, Member
from ..schemas import ExpenseCreate, ExpenseOut, ExpenseUpdate, ReceiptOut, ShareOut
from ..splitting import split_by_weights, split_equally, validate_exact_split

router = APIRouter(prefix="/api/expenses", tags=["expenses"])


def serialize_expense(expense: Expense, currency: str) -> ExpenseOut:
    return ExpenseOut(
        id=expense.id,
        description=expense.description,
        amount_cents=expense.amount_cents,
        currency=currency,
        category=expense.category,
        expense_date=expense.expense_date,
        note=expense.note,
        split_type=expense.split_type,
        payer_id=expense.payer_id,
        payer_name=expense.payer.display_name,
        created_by_id=expense.created_by_id,
        created_by_name=expense.created_by.display_name,
        created_at=expense.created_at,
        updated_at=expense.updated_at,
        shares=[
            ShareOut(
                member_id=s.member_id,
                display_name=s.member.display_name,
                amount_cents=s.amount_cents,
                weight=s.weight,
            )
            for s in sorted(expense.shares, key=lambda s: s.member.display_name.casefold())
        ],
        receipts=[ReceiptOut.model_validate(r) for r in expense.receipts],
    )


def _build_shares(
    db: Session, group_id: uuid.UUID, payload: ExpenseCreate
) -> list[tuple[uuid.UUID, int, int]]:
    """Resolve the requested split into (member_id, amount_cents, weight) rows."""
    if payload.split_type == "equal":
        ids = payload.participant_ids
        if not ids:
            raise HTTPException(400, "Bitte mindestens eine Person auswählen.")
        if len(set(ids)) != len(ids):
            raise HTTPException(400, "Eine Person wurde doppelt ausgewählt.")
        for member_id in ids:
            get_group_member(db, group_id, member_id)
        amounts = split_equally(payload.amount_cents, list(ids))
        return [(mid, amount, 1) for mid, amount in amounts.items()]

    if not payload.shares:
        raise HTTPException(400, "Für diese Aufteilung fehlen die Beträge.")
    seen = {s.member_id for s in payload.shares}
    if len(seen) != len(payload.shares):
        raise HTTPException(400, "Eine Person wurde doppelt ausgewählt.")
    for share in payload.shares:
        get_group_member(db, group_id, share.member_id)

    if payload.split_type == "exact":
        amounts = {s.member_id: s.value for s in payload.shares}
        try:
            validate_exact_split(payload.amount_cents, amounts)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return [(mid, amount, 1) for mid, amount in amounts.items()]

    weights = {s.member_id: s.value for s in payload.shares if s.value > 0}
    if not weights:
        raise HTTPException(400, "Mindestens ein Anteil muss größer als 0 sein.")
    try:
        amounts = split_by_weights(payload.amount_cents, weights)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return [(mid, amounts[mid], weights[mid]) for mid in weights]


@router.get("", response_model=list[ExpenseOut])
def list_expenses(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    category: str | None = None,
    member_id: uuid.UUID | None = None,
):
    stmt = select(Expense).where(Expense.group_id == user.group.id)
    if category:
        stmt = stmt.where(Expense.category == category)
    if member_id:
        # Anything this person is involved in, as payer or as debtor.
        stmt = stmt.where(
            (Expense.payer_id == member_id)
            | Expense.id.in_(
                select(ExpenseShare.expense_id).where(ExpenseShare.member_id == member_id)
            )
        )

    stmt = stmt.order_by(Expense.expense_date.desc(), Expense.created_at.desc())
    expenses = db.scalars(stmt.limit(limit).offset(offset)).all()
    return [serialize_expense(e, user.group.currency) for e in expenses]


@router.post("", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payer = get_group_member(db, user.group.id, payload.payer_id)
    share_rows = _build_shares(db, user.group.id, payload)

    expense = Expense(
        group_id=user.group.id,
        payer_id=payer.id,
        description=payload.description.strip(),
        amount_cents=payload.amount_cents,
        category=payload.category,
        expense_date=payload.expense_date,
        note=payload.note,
        split_type=payload.split_type,
        created_by_id=user.member.id,
    )
    db.add(expense)
    db.flush()

    for member_id, amount, weight in share_rows:
        db.add(
            ExpenseShare(
                expense_id=expense.id, member_id=member_id, amount_cents=amount, weight=weight
            )
        )

    write_audit(
        db,
        request=request,
        user=user,
        action="expense.create",
        entity_type="expense",
        entity_id=expense.id,
        summary=f"{expense.description} ({expense.amount_cents / 100:.2f} {user.group.currency})",
    )
    db.commit()
    db.refresh(expense)
    return serialize_expense(expense, user.group.currency)


def _load_editable(
    db: Session, expense_id: uuid.UUID, user: CurrentUser, action: str
) -> Expense:
    expense = db.scalar(
        select(Expense).where(Expense.id == expense_id, Expense.group_id == user.group.id)
    )
    if expense is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ausgabe nicht gefunden.")
    # You own what you entered; the admin can fix anything.
    if expense.created_by_id != user.member.id and not user.member.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Nur {expense.created_by.display_name} oder der Admin darf diesen Eintrag {action}.",
        )
    return expense


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(
    expense_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expense = db.scalar(
        select(Expense).where(Expense.id == expense_id, Expense.group_id == user.group.id)
    )
    if expense is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ausgabe nicht gefunden.")
    return serialize_expense(expense, user.group.currency)


@router.put("/{expense_id}", response_model=ExpenseOut)
def update_expense(
    expense_id: uuid.UUID,
    payload: ExpenseUpdate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expense = _load_editable(db, expense_id, user, "ändern")
    payer = get_group_member(db, user.group.id, payload.payer_id)
    share_rows = _build_shares(db, user.group.id, payload)

    expense.payer_id = payer.id
    expense.description = payload.description.strip()
    expense.amount_cents = payload.amount_cents
    expense.category = payload.category
    expense.expense_date = payload.expense_date
    expense.note = payload.note
    expense.split_type = payload.split_type

    for share in list(expense.shares):
        db.delete(share)
    db.flush()

    for member_id, amount, weight in share_rows:
        db.add(
            ExpenseShare(
                expense_id=expense.id, member_id=member_id, amount_cents=amount, weight=weight
            )
        )

    write_audit(
        db,
        request=request,
        user=user,
        action="expense.update",
        entity_type="expense",
        entity_id=expense.id,
        summary=f"{expense.description} geändert",
    )
    db.commit()
    db.refresh(expense)
    return serialize_expense(expense, user.group.currency)


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    expense_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expense = _load_editable(db, expense_id, user, "löschen")
    summary = f"{expense.description} ({expense.amount_cents / 100:.2f} {user.group.currency})"

    # Receipt files are cleaned up by the storage layer via the same relative paths.
    from ..storage import delete_receipt_files

    for receipt in expense.receipts:
        delete_receipt_files(receipt.file_path, receipt.thumb_path)

    db.delete(expense)
    write_audit(
        db,
        request=request,
        user=user,
        action="expense.delete",
        entity_type="expense",
        entity_id=expense_id,
        summary=f"{summary} gelöscht",
    )
    db.commit()


member_router = APIRouter(prefix="/api/members", tags=["members"])


@member_router.get("")
def list_members(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    members = db.scalars(
        select(Member).where(Member.group_id == user.group.id).order_by(Member.created_at)
    ).all()
    return [
        {
            "id": str(m.id),
            "display_name": m.display_name,
            "is_admin": m.is_admin,
            "color": m.color,
            "is_you": m.id == user.member.id,
            "device_bound": m.device_id is not None,
        }
        for m in members
    ]
