"""
OwnerCharge model — manual expense/credit entries against an owner's account.

Charges are entered by staff (typically Barbara Knight) and posted to a specific
date. They reduce (or increase, if negative) the owner's statement closing balance.

Positive amount = expense/charge to owner (reduces owner balance).
Negative amount = credit to owner (increases owner balance).
Zero amount = not allowed; use void instead.

Once a statement period is approved/paid/emailed, charges inside that period
are locked from editing or voiding. Use credit_from_management in a later
period to correct errors.
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
)
from sqlalchemy.sql import func

from backend.core.database import Base


class OwnerChargeType(str, PyEnum):
    """
    Transaction types for owner charges.

    Starter set of 17 values from Streamline's owner charge workflow.
    See NOTES.md for the deliberate exclusions and how to add new types.
    """
    CLEANING_FEE               = "cleaning_fee"
    MAINTENANCE                = "maintenance"
    MANAGEMENT_FEE             = "management_fee"
    SUPPLIES                   = "supplies"
    LANDSCAPING                = "landscaping"
    LINEN                      = "linen"
    ELECTRIC_BILL              = "electric_bill"
    HOUSEKEEPER_PAY            = "housekeeper_pay"
    ADVERTISING_FEE            = "advertising_fee"
    THIRD_PARTY_OTA_COMMISSION = "third_party_ota_commission"
    TRAVEL_AGENT_FEE           = "travel_agent_fee"
    CREDIT_CARD_DISPUTE        = "credit_card_dispute"
    FEDERAL_TAX_WITHHOLDING    = "federal_tax_withholding"
    ADJUST_OWNER_REVENUE       = "adjust_owner_revenue"
    CREDIT_FROM_MANAGEMENT     = "credit_from_management"
    PAY_TO_OLD_OWNER           = "pay_to_old_owner"
    MISC_GUEST_CHARGES         = "misc_guest_charges"

    @property
    def display_name(self) -> str:
        """Human-readable name for UI display and statement PDFs."""
        return _DISPLAY_NAMES[self]


# Human-readable names for each charge type (for admin form and PDF)
_DISPLAY_NAMES: dict[OwnerChargeType, str] = {
    OwnerChargeType.CLEANING_FEE:               "Cleaning Fee",
    OwnerChargeType.MAINTENANCE:                "Maintenance",
    OwnerChargeType.MANAGEMENT_FEE:             "Management Fee",
    OwnerChargeType.SUPPLIES:                   "Supplies",
    OwnerChargeType.LANDSCAPING:                "Landscaping",
    OwnerChargeType.LINEN:                      "Linen",
    OwnerChargeType.ELECTRIC_BILL:              "Electric Bill",
    OwnerChargeType.HOUSEKEEPER_PAY:            "Housekeeper Pay",
    OwnerChargeType.ADVERTISING_FEE:            "Advertising Fee",
    OwnerChargeType.THIRD_PARTY_OTA_COMMISSION: "3rd Party OTA Commission",
    OwnerChargeType.TRAVEL_AGENT_FEE:           "Travel Agent Fee",
    OwnerChargeType.CREDIT_CARD_DISPUTE:        "Credit Card Dispute",
    OwnerChargeType.FEDERAL_TAX_WITHHOLDING:    "Federal Tax Withholding",
    OwnerChargeType.ADJUST_OWNER_REVENUE:       "Adjust Owner Revenue",
    OwnerChargeType.CREDIT_FROM_MANAGEMENT:     "Credit From Management",
    OwnerChargeType.PAY_TO_OLD_OWNER:           "Pay To Old Owner",
    OwnerChargeType.MISC_GUEST_CHARGES:         "Miscellaneous Guest Charges",
}

_CHARGE_TYPE_ENUM = SqlEnum(
    *[t.value for t in OwnerChargeType],
    name="owner_charge_type_enum",
    create_constraint=False,  # type created by migration c9e2f4a7b1d3
)


class OwnerCharge(Base):
    """Manual expense or credit entry against an owner's account."""

    __tablename__ = "owner_charges"
    __table_args__ = (
        CheckConstraint("amount != 0", name="chk_oc_amount_not_zero"),
        CheckConstraint("description != ''", name="chk_oc_description_not_empty"),
        CheckConstraint(
            "(voided_at IS NULL AND voided_by IS NULL) "
            "OR (voided_at IS NOT NULL AND voided_by IS NOT NULL)",
            name="chk_oc_void_pair",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    owner_payout_account_id = Column(
        BigInteger,
        ForeignKey("owner_payout_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    posting_date    = Column(Date, nullable=False, index=True)
    transaction_type = Column(_CHARGE_TYPE_ENUM, nullable=False)
    description     = Column(String(500), nullable=False)
    amount          = Column(Numeric(12, 2), nullable=False)  # +ve = charge, -ve = credit
    reference_id    = Column(String(100), nullable=True)
    originating_work_order_id = Column(BigInteger, nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    created_by = Column(String(255), nullable=False)

    voided_at  = Column(TIMESTAMP(timezone=True), nullable=True)
    voided_by  = Column(String(255), nullable=True)
    void_reason = Column(Text, nullable=True)

    @property
    def is_voided(self) -> bool:
        return self.voided_at is not None

    @property
    def transaction_type_display(self) -> str:
        try:
            return OwnerChargeType(self.transaction_type).display_name
        except ValueError:
            return str(self.transaction_type)

    def __repr__(self) -> str:
        return (
            f"<OwnerCharge id={self.id} "
            f"opa={self.owner_payout_account_id} "
            f"date={self.posting_date} "
            f"type={self.transaction_type} "
            f"amount={self.amount}>"
        )
