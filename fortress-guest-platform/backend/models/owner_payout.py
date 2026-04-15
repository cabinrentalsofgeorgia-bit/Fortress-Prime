"""
Owner payout models.

Two tables:
  owner_payout_accounts   — one row per enrolled owner+property pair.
                            Created when an owner accepts their invite.
  owner_statement_sends   — audit log of every statement email generated.
                            One row per statement run per property.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.core.database import Base


class OwnerPayoutAccount(Base):
    """
    Enrolled property owner.  One row per (owner, property) pair.
    Created when the owner accepts their invite and completes Stripe onboarding.

    commission_rate is stored as a decimal fraction (0.3000 = 30%).
    It must be set at invite time — there is no default.
    """

    __tablename__ = "owner_payout_accounts"
    __table_args__ = (
        UniqueConstraint("property_id", name="uq_owner_payout_accounts_property_id"),
        UniqueConstraint("stripe_account_id", name="uq_owner_payout_accounts_stripe_account_id"),
        CheckConstraint(
            "commission_rate >= 0 AND commission_rate <= 0.5000",
            name="chk_opa_commission_rate",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    property_id = Column(String(100), nullable=False, index=True)
    owner_name = Column(String(255), nullable=False)
    owner_middle_name = Column(String(100), nullable=True)   # G.6: Streamline middle name
    owner_email = Column(String(255), nullable=True, index=True)
    stripe_account_id = Column(String(255), nullable=True)
    account_status = Column(
        String(64),
        nullable=False,
        default="onboarding",
        server_default="onboarding",
    )
    # Management commission rate as a decimal fraction (e.g. 0.3000 for 30%).
    # NOT NULL — must be set at invite creation. No default.
    commission_rate = Column(Numeric(5, 4), nullable=False)
    # Streamline's integer owner ID, used for the monthly statement comparison.
    # Nullable — not all owners have a Streamline account.
    streamline_owner_id = Column(Integer, nullable=True, index=True)

    # Owner mailing address — populated at invite time, used in PDF statements.
    # Nullable until real owners are enrolled (test rows legitimately have NULL).
    mailing_address_line1 = Column(String(255), nullable=True)
    mailing_address_line2 = Column(String(255), nullable=True)
    mailing_address_city = Column(String(100), nullable=True)
    mailing_address_state = Column(String(50), nullable=True)
    mailing_address_postal_code = Column(String(20), nullable=True)
    mailing_address_country = Column(String(50), nullable=True, server_default="USA")

    instant_payout = Column(Boolean, nullable=False, default=False, server_default="false")
    payout_schedule = Column(String(20), nullable=False, default="manual", server_default="manual")
    payout_day_of_week = Column(Integer, nullable=True)
    payout_day_of_month = Column(Integer, nullable=True)
    last_payout_at = Column(TIMESTAMP(timezone=True), nullable=True)
    next_scheduled_payout = Column(TIMESTAMP(timezone=True), nullable=True)
    minimum_payout_threshold = Column(Numeric(10, 2), nullable=False, default=100.00)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    # One account → many statement records
    statement_sends = relationship(
        "OwnerStatementSend",
        back_populates="owner_payout_account",
        order_by="OwnerStatementSend.created_at",
    )

    @property
    def mailing_address_display(self) -> str:
        """
        Single-line mailing address string matching Streamline's PDF format.

        Returns empty string when all address fields are NULL (test rows,
        or real rows before backfill completes).

        Format:  "{line1}[ {line2}] {city}, {state} {postal_code}"
        All components on one line; line2 included only when not blank.

        Examples:
            "PO Box 982 Morganton, GA 30560"
            "2300 Riverchase Center Birmingham, AL 35244"
            "100 Oak St Suite 4 Blue Ridge, GA 30513"
        """
        if not self.mailing_address_line1:
            return ""

        parts: list[str] = [self.mailing_address_line1]
        if self.mailing_address_line2:
            parts.append(self.mailing_address_line2)

        city = self.mailing_address_city or ""
        state = self.mailing_address_state or ""
        postal = self.mailing_address_postal_code or ""
        city_state_zip = ", ".join(filter(None, [city, f"{state} {postal}".strip()]))
        if city_state_zip:
            parts.append(city_state_zip)

        return " ".join(parts)

    @property
    def is_enrolled(self) -> bool:
        """True if the owner has completed Stripe onboarding."""
        return bool(self.stripe_account_id) and self.account_status in (
            "pending_kyc", "active", "restricted"
        )

    def __repr__(self) -> str:
        return (
            f"<OwnerPayoutAccount id={self.id} "
            f"owner={self.owner_name!r} rate={self.commission_rate}>"
        )


class OwnerStatementSend(Base):
    """
    Permanent audit record for every statement email generated.

    Written at send time with sent_at=NULL, then updated to sent_at=now()
    once the email is confirmed delivered.  If anything fails, error_message
    is populated and sent_at stays NULL.
    """

    __tablename__ = "owner_statement_sends"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    owner_payout_account_id = Column(
        BigInteger,
        ForeignKey("owner_payout_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    property_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    statement_period_start = Column(Date, nullable=False)
    statement_period_end = Column(Date, nullable=False)

    # Set to the actual send timestamp once the email is delivered.
    sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    sent_to_email = Column(String(255), nullable=True)

    # Crog-VRS computed total (net to owner)
    crog_total_amount = Column(Numeric(12, 2), nullable=True)
    # Streamline reported total (net to owner), or NULL if unavailable
    streamline_total_amount = Column(Numeric(12, 2), nullable=True)

    # Which figure was sent to the owner
    source_used = Column(String(20), nullable=True)   # 'crog' | 'streamline' | 'failed'

    # How the two figures compared
    comparison_status = Column(String(30), nullable=True)  # 'match' | 'mismatch' | ...
    comparison_diff_cents = Column(Integer, nullable=True)

    # SMTP message ID returned by the mail server (for debugging bounces)
    email_message_id = Column(String(255), nullable=True)

    # Populated if anything failed during the send pipeline
    error_message = Column(Text, nullable=True)

    # True when this row was created by the manual test endpoint
    is_test = Column(Boolean, nullable=False, default=False, server_default="false")

    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    owner_payout_account = relationship(
        "OwnerPayoutAccount",
        back_populates="statement_sends",
    )

    def __repr__(self) -> str:
        return (
            f"<OwnerStatementSend id={self.id} "
            f"opa={self.owner_payout_account_id} "
            f"period={self.statement_period_start}..{self.statement_period_end} "
            f"status={self.comparison_status!r}>"
        )
