from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import CurrentUser, get_current_user, write_audit
from ..models import Expense, Receipt
from ..schemas import ReceiptOut
from ..storage import (
    ALLOWED_CONTENT_TYPES,
    ReceiptError,
    delete_receipt_files,
    resolve_path,
    store_receipt,
)

router = APIRouter(prefix="/api", tags=["receipts"])


def _load_expense(db: Session, expense_id: uuid.UUID, user: CurrentUser) -> Expense:
    expense = db.scalar(
        select(Expense).where(Expense.id == expense_id, Expense.group_id == user.group.id)
    )
    if expense is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ausgabe nicht gefunden.")
    return expense


@router.post(
    "/expenses/{expense_id}/receipts",
    response_model=ReceiptOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_receipt(
    expense_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expense = _load_expense(db, expense_id, user)

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Bitte ein Foto hochladen (JPEG, PNG, WebP oder HEIC).",
        )

    raw = await file.read()
    try:
        file_path, thumb_path, size = store_receipt(raw, expense.id)
    except ReceiptError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    receipt = Receipt(
        expense_id=expense.id,
        file_path=file_path,
        thumb_path=thumb_path,
        original_filename=(file.filename or None),
        content_type="image/jpeg",
        size_bytes=size,
        uploaded_by_id=user.member.id,
    )
    db.add(receipt)
    write_audit(
        db,
        request=request,
        user=user,
        action="receipt.upload",
        entity_type="receipt",
        entity_id=expense.id,
        summary=f"Kassenzettel zu '{expense.description}' hochgeladen",
    )
    db.commit()
    db.refresh(receipt)
    return ReceiptOut.model_validate(receipt)


@router.get("/receipts/{receipt_id}")
def get_receipt_image(
    receipt_id: uuid.UUID,
    thumb: bool = False,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve a receipt image, but only to members of the group it belongs to."""
    receipt = db.scalar(
        select(Receipt)
        .join(Expense, Receipt.expense_id == Expense.id)
        .where(Receipt.id == receipt_id, Expense.group_id == user.group.id)
    )
    if receipt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kassenzettel nicht gefunden.")

    try:
        path = resolve_path(receipt.thumb_path if thumb else receipt.file_path)
    except ReceiptError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Datei nicht gefunden.") from exc

    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Datei nicht gefunden.")

    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": f"private, max-age={60 * 60 * 24}"},
    )


@router.delete("/receipts/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt(
    receipt_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    receipt = db.scalar(
        select(Receipt)
        .join(Expense, Receipt.expense_id == Expense.id)
        .where(Receipt.id == receipt_id, Expense.group_id == user.group.id)
    )
    if receipt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kassenzettel nicht gefunden.")

    if receipt.uploaded_by_id != user.member.id and not user.member.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Nur wer den Beleg hochgeladen hat oder der Admin darf ihn löschen.",
        )

    delete_receipt_files(receipt.file_path, receipt.thumb_path)
    db.delete(receipt)
    write_audit(
        db,
        request=request,
        user=user,
        action="receipt.delete",
        entity_type="receipt",
        entity_id=receipt_id,
        summary="Kassenzettel gelöscht",
    )
    db.commit()


@router.get("/config/upload-limits")
def upload_limits(user: CurrentUser = Depends(get_current_user)):
    return {
        "max_bytes": settings.max_upload_bytes,
        "allowed_types": sorted(ALLOWED_CONTENT_TYPES),
    }
