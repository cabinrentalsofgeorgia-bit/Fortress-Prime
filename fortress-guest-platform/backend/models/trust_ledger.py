"""
Double-entry trust ledger gated by swarm governance decisions.
"""
from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.core.time import utc_now

# Import swarm_governance before TrustTransaction so TrustDecision exists in the
# registry when SQLAlchemy resolves the string relationship (avoids mapper init failure).
from backend.models import swarm_governance as _swarm_governance  # noqa: F401


def _enum_column(enum_cls: type[enum.Enum], name: str) -> SqlEnum:
    return SqlEnum(
        enum_cls,
        name=name,
        native_enum=False,
        validate_strings=True,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
    )


class TrustAccountType(str, enum.Enum):
    ASSET = "asset"
    LIABILITY = "liability"


class TrustLedgerEntryType(str, enum.Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class TrustAccount(Base):
    """Ledger account available for deterministic trust postings."""

    __tablename__ = "trust_accounts"
    __table_args__ = (
        UniqueConstraint("name", name="uq_trust_accounts_name"),
        Index("ix_trust_accounts_type_name", "type", "name"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    type: Mapped[TrustAccountType] = mapped_column(
        _enum_column(TrustAccountType, "trust_account_type"),
        nullable=False,
        index=True,
    )

    entries: Mapped[list[TrustLedgerEntry]] = relationship(
        "TrustLedgerEntry",
        back_populates="account",
    )


class TrustTransaction(Base):
    """Authorized financial transaction tied back to a trust decision."""

    __tablename__ = "trust_transactions"
    __table_args__ = (
        UniqueConstraint(
            "streamline_event_id",
            name="uq_trust_transactions_streamline_event_id",
        ),
        UniqueConstraint("signature", name="uq_trust_transactions_signature"),
        Index("ix_trust_transactions_decision_timestamp", "decision_id", "timestamp"),
        Index("ix_trust_transactions_previous_signature", "previous_signature"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    streamline_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("trust_decisions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("now()"),
        index=True,
    )
    signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)

    decision: Mapped["TrustDecision"] = relationship(
        "TrustDecision",
        back_populates="transactions",
    )
    entries: Mapped[list[TrustLedgerEntry]] = relationship(
        "TrustLedgerEntry",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )


class TrustLedgerEntry(Base):
    """Individual debit or credit line item within a trust transaction."""

    __tablename__ = "trust_ledger_entries"
    __table_args__ = (
        CheckConstraint(
            "amount_cents > 0",
            name="ck_trust_ledger_entries_amount_positive",
        ),
        Index("ix_trust_ledger_entries_transaction_id", "transaction_id"),
        Index("ix_trust_ledger_entries_account_id", "account_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    transaction_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("trust_transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("trust_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_type: Mapped[TrustLedgerEntryType] = mapped_column(
        _enum_column(TrustLedgerEntryType, "trust_ledger_entry_type"),
        nullable=False,
        index=True,
    )

    transaction: Mapped[TrustTransaction] = relationship("TrustTransaction", back_populates="entries")
    account: Mapped[TrustAccount] = relationship("TrustAccount", back_populates="entries")

