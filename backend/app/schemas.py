from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Money = Annotated[int, Field(ge=1, le=100_000_000, description="Amount in cents")]
SplitType = Literal["equal", "exact", "shares"]

CATEGORIES = [
    "food",
    "groceries",
    "accommodation",
    "transport",
    "activities",
    "drinks",
    "shopping",
    "other",
]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth -------------------------------------------------------------------


class GroupCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=72)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    admin_name: str = Field(min_length=1, max_length=60)

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, v: str) -> str:
        return v.upper()


class LoginRequest(BaseModel):
    group_slug: str = Field(min_length=1, max_length=140)
    password: str = Field(min_length=1, max_length=72)
    display_name: str = Field(min_length=1, max_length=60)
    # Sent back by a returning device to prove it owns the claimed name.
    device_id: str | None = Field(default=None, max_length=64)


class MemberOut(ORMModel):
    id: uuid.UUID
    display_name: str
    is_admin: bool
    color: str
    created_at: datetime


class GroupOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    currency: str
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    device_id: str
    member: MemberOut
    group: GroupOut


# --- expenses ---------------------------------------------------------------


class ShareInput(BaseModel):
    member_id: uuid.UUID
    # Required for split_type="exact" (cents), for "shares" it is the weight.
    value: int = Field(ge=0, le=100_000_000)


class ExpenseCreate(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount_cents: Money
    payer_id: uuid.UUID
    expense_date: date
    category: str = "other"
    note: str | None = Field(default=None, max_length=2000)
    split_type: SplitType = "equal"
    # For "equal": who takes part. For "exact"/"shares": the values per member.
    participant_ids: list[uuid.UUID] = Field(default_factory=list)
    shares: list[ShareInput] = Field(default_factory=list)

    @field_validator("category")
    @classmethod
    def known_category(cls, v: str) -> str:
        return v if v in CATEGORIES else "other"


class ExpenseUpdate(ExpenseCreate):
    pass


class ShareOut(BaseModel):
    member_id: uuid.UUID
    display_name: str
    amount_cents: int
    weight: int


class ReceiptOut(ORMModel):
    id: uuid.UUID
    original_filename: str | None
    content_type: str
    size_bytes: int
    uploaded_by_id: uuid.UUID
    created_at: datetime


class ExpenseOut(BaseModel):
    id: uuid.UUID
    description: str
    amount_cents: int
    currency: str
    category: str
    expense_date: date
    note: str | None
    split_type: str
    payer_id: uuid.UUID
    payer_name: str
    created_by_id: uuid.UUID
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    shares: list[ShareOut]
    receipts: list[ReceiptOut]


# --- balances & settlements -------------------------------------------------


class BalanceOut(BaseModel):
    member_id: uuid.UUID
    display_name: str
    color: str
    # Positive: gets money back. Negative: owes money.
    net_cents: int
    paid_cents: int
    share_cents: int


class TransferOut(BaseModel):
    from_member_id: uuid.UUID
    from_name: str
    to_member_id: uuid.UUID
    to_name: str
    amount_cents: int


class BalanceSummary(BaseModel):
    currency: str
    total_spent_cents: int
    balances: list[BalanceOut]
    suggested_transfers: list[TransferOut]


class SettlementCreate(BaseModel):
    from_member_id: uuid.UUID
    to_member_id: uuid.UUID
    amount_cents: Money
    note: str | None = Field(default=None, max_length=200)


class SettlementOut(BaseModel):
    id: uuid.UUID
    from_member_id: uuid.UUID
    from_name: str
    to_member_id: uuid.UUID
    to_name: str
    amount_cents: int
    note: str | None
    created_at: datetime


class AuditLogOut(BaseModel):
    id: uuid.UUID
    member_name: str | None
    action: str
    entity_type: str
    summary: str | None
    created_at: datetime
