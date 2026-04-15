"""
OwnerBalancePeriod — one row per owner per calendar statement period.

The row carries the running ledger balance forward: its opening_balance equals
the closing_balance of the prior period for the same owner.  If no prior period
exists (the owner's first statement ever, or after a backfill), opening_balance
is set to zero.

The database enforces the ledger equation via a CHECK constraint:
    closing_balance = opening_balance
                    + total_revenue
                    - total_commission
                    - total_charges
                    - total_payments
                    + total_owner_income

Any code that writes to this table must maintain this invariant.
"""
from __future__ import annotations

from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    Enum as SqlEnum,
    ForeignKey,
    Numeric,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.core.database import Base


class StatementPeriodStatus(str, PyEnum):
    """Lifecycle states for an owner balance period / statement."""
    DRAFT            = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED         = "approved"
    PAID             = "paid"
    EMAILED          = "emailed"
    VOIDED           = "voided"


_STATUS_ENUM = SqlEnum(
    "draft", "pending_approval", "approved", "paid", "emailed", "voided",
    name="statement_period_status",
    create_constraint=False,  # type already created by migration d1e2f3a4b5c6
)


class OwnerBalancePeriod(Base):
    """Per-owner per-period ledger row."""

    __tablename__ = "owner_balance_periods"
    __table_args__ = (
        UniqueConstraint(
            "owner_payout_account_id", "period_start", "period_end",
            name="uq_obp_owner_period",
        ),
        CheckConstraint("period_end > period_start", name="chk_obp_period_order"),
        CheckConstraint(
            "closing_balance = opening_balance"
            " + total_revenue"
            " - total_commission"
            " - total_charges"
            " - total_payments"
            " + total_owner_income",
            name="chk_obp_ledger_equation",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    owner_payout_account_id = Column(
        BigInteger,
        ForeignKey("owner_payout_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    period_start = Column(Date, nullable=False)
    period_end   = Column(Date, nullable=False)

    opening_balance = Column(Numeric(12, 2), nullable=False)
    closing_balance = Column(Numeric(12, 2), nullable=False)

    total_revenue      = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    total_commission   = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    total_charges      = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    total_payments     = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    total_owner_income = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")

    status = Column(
        _STATUS_ENUM,
        nullable=False,
        default=StatementPeriodStatus.DRAFT.value,
        server_default="draft",
    )

    created_at  = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at  = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    approved_at = Column(TIMESTAMP(timezone=True), nullable=True)
    approved_by = Column(String(255), nullable=True)
    paid_at     = Column(TIMESTAMP(timezone=True), nullable=True)
    paid_by     = Column(String(255), nullable=True)
    emailed_at  = Column(TIMESTAMP(timezone=True), nullable=True)
    voided_at   = Column(TIMESTAMP(timezone=True), nullable=True)
    voided_by   = Column(String(255), nullable=True)
    notes       = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<OwnerBalancePeriod id={self.id} "
            f"opa={self.owner_payout_account_id} "
            f"period={self.period_start}..{self.period_end} "
            f"status={self.status!r} "
            f"closing={self.closing_balance}>"
        )
