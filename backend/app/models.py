from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Group(Base):
    """A trip. Everything else hangs off this."""

    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), nullable=False, unique=True, index=True)
    # bcrypt hash of the shared group password.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # bcrypt hash of the emergency recovery key. Shown to the creator exactly once
    # and never again -- only its hash lives here. Nullable so a trip created
    # before this feature existed keeps working until an admin generates one.
    recovery_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recovery_key_set_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    members: Mapped[list[Member]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    expenses: Mapped[list[Expense]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    settlements: Mapped[list[Settlement]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class Member(Base):
    """One participant of a trip.

    The group password alone does not identify anyone, so a name is claimed by the
    first device that logs in with it and is pinned to that device from then on.
    """

    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("group_id", "name_key", name="uq_member_name_per_group"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(60), nullable=False)
    # Case-folded name, used for the uniqueness constraint so "Leo" == "leo".
    name_key: Mapped[str] = mapped_column(String(60), nullable=False)
    # Device that claimed this name. Later logins must present the same id.
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#6366f1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    group: Mapped[Group] = relationship(back_populates="members")


class Expense(Base):
    """A single cost, paid by one member, owed by one or more members."""

    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    # Money is stored in minor units (cents) so splitting never loses a rounding penny.
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "equal" | "exact" | "shares"
    split_type: Mapped[str] = mapped_column(String(10), nullable=False, default="equal")

    created_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    group: Mapped[Group] = relationship(back_populates="expenses")
    payer: Mapped[Member] = relationship(foreign_keys=[payer_id])
    created_by: Mapped[Member] = relationship(foreign_keys=[created_by_id])
    shares: Mapped[list[ExpenseShare]] = relationship(
        back_populates="expense", cascade="all, delete-orphan", lazy="selectin"
    )
    receipts: Mapped[list[Receipt]] = relationship(
        back_populates="expense", cascade="all, delete-orphan", lazy="selectin"
    )


class ExpenseShare(Base):
    """How much of an expense a single member owes."""

    __tablename__ = "expense_shares"
    __table_args__ = (UniqueConstraint("expense_id", "member_id", name="uq_share_per_member"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    expense_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Only meaningful for split_type="shares" (e.g. a couple counts as 2).
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    expense: Mapped[Expense] = relationship(back_populates="shares")
    member: Mapped[Member] = relationship()


class Receipt(Base):
    """An uploaded photo of a paper receipt, attached to an expense."""

    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    expense_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Paths are relative to settings.upload_dir so the volume can be moved.
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    thumb_path: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str] = mapped_column(String(60), nullable=False, default="image/jpeg")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    expense: Mapped[Expense] = relationship(back_populates="receipts")
    uploaded_by: Mapped[Member] = relationship()


class Settlement(Base):
    """A real-world repayment ("I gave Anna 20 EUR in cash")."""

    __tablename__ = "settlements"

    id: Mapped[uuid.UUID] = _uuid_pk()
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT"), nullable=False
    )
    to_member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    group: Mapped[Group] = relationship(back_populates="settlements")
    from_member: Mapped[Member] = relationship(foreign_keys=[from_member_id])
    to_member: Mapped[Member] = relationship(foreign_keys=[to_member_id])


class AuditLog(Base):
    """Append-only trail of who changed what, from which device."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    member_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    member: Mapped[Member | None] = relationship()
