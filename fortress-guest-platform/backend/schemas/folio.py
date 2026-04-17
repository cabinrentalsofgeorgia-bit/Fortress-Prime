"""
Reservation Folio — Strict Pydantic Data Contracts
====================================================
These models act as the bouncer between dirty legacy data (Streamline,
RueBaRue, Stripe) and the frontend.  Every Optional field has a safe
default.  Validators coerce common legacy quirks (null amounts → 0,
missing dates → None) so the frontend NEVER receives unexpected shapes.

All monetary fields are integer cents (e.g. $19.99 → 1999) to eliminate
IEEE 754 floating-point drift in trust accounting pipelines.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def _dollars_to_cents(v: Any) -> int:
    """Coerce a dollar amount (float, str, Decimal, None) to integer cents."""
    if v is None:
        return 0
    try:
        return int((Decimal(str(v)) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    except Exception:
        return 0


class FolioGuest(BaseModel):
    """Guest profile — contact and loyalty data."""

    id: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone_number: str = ""
    address_line1: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""
    loyalty_tier: str = ""
    lifetime_stays: int = 0
    lifetime_revenue: float = 0.0
    vip_status: Optional[str] = None
    stripe_customer_id: Optional[str] = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or "Unknown Guest"

    @field_validator("lifetime_revenue", mode="before")
    @classmethod
    def _coerce_revenue(cls, v: Any) -> float:
        if v is None:
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0


class FolioStay(BaseModel):
    """Core reservation / stay details."""

    id: str = ""
    confirmation_code: str = ""
    property_id: str = ""
    property_name: str = ""
    property_address: str = ""
    check_in_date: Optional[date] = None
    check_out_date: Optional[date] = None
    nights: int = 0
    num_guests: int = 0
    num_adults: Optional[int] = None
    num_children: Optional[int] = None
    num_pets: int = 0
    status: str = "unknown"
    booking_source: str = ""
    access_code: Optional[str] = None
    access_code_type: str = ""
    access_code_location: str = ""
    wifi_ssid: str = ""
    wifi_password: str = ""
    special_requests: str = ""
    internal_notes: str = ""
    streamline_notes: Optional[List[Dict[str, Any]]] = None

    @model_validator(mode="after")
    def _derive_nights(self) -> "FolioStay":
        if self.nights == 0 and self.check_in_date and self.check_out_date:
            self.nights = (self.check_out_date - self.check_in_date).days
        return self


class FolioLineItem(BaseModel):
    """A single line on the financial folio (fee, tax, payment, charge)."""

    label: str
    amount_cents: int = 0
    category: str = "fee"  # fee | tax | payment | adjustment | deposit

    @field_validator("amount_cents", mode="before")
    @classmethod
    def _coerce_amount(cls, v: Any) -> int:
        return _dollars_to_cents(v)


class FolioSecurityDeposit(BaseModel):
    """Security deposit authorization state for a reservation."""

    is_required: bool = False
    amount_cents: int = 50000
    status: str = "none"  # none | scheduled | authorized | captured | released
    stripe_payment_intent: Optional[str] = None
    updated_at: Optional[str] = None

    @field_validator("amount_cents", mode="before")
    @classmethod
    def _coerce_deposit(cls, v: Any) -> int:
        if v is None:
            return 50000
        result = _dollars_to_cents(v)
        return result if result > 0 else 50000

    @property
    def system_flag(self) -> Optional[str]:
        """Amber flag when deposit is required but not yet actioned."""
        if self.is_required and self.status == "none":
            return "DEPOSIT PENDING"
        return None


class FolioFinancials(BaseModel):
    """Complete financial picture for a reservation.

    All monetary fields are integer cents (e.g. $500.00 → 50000).
    The ``_coerce_money_cents`` validator accepts legacy dollar-amount
    inputs (float / str / Decimal) and converts them to cents via
    ``_dollars_to_cents``, so existing callers passing dollar values
    continue to work during the migration.
    """

    total_amount_cents: int = 0
    paid_amount_cents: int = 0
    balance_due_cents: int = 0
    nightly_rate_cents: int = 0
    cleaning_fee_cents: int = 0
    pet_fee_cents: int = 0
    damage_waiver_fee_cents: int = 0
    service_fee_cents: int = 0
    tax_amount_cents: int = 0
    currency: str = "USD"
    line_items: List[FolioLineItem] = Field(default_factory=list)
    price_breakdown: Optional[Dict[str, Any]] = None
    streamline_financial_detail: Optional[Dict[str, Any]] = None
    security_deposit: FolioSecurityDeposit = Field(default_factory=FolioSecurityDeposit)

    @field_validator(
        "total_amount_cents",
        "paid_amount_cents",
        "balance_due_cents",
        "nightly_rate_cents",
        "cleaning_fee_cents",
        "pet_fee_cents",
        "damage_waiver_fee_cents",
        "service_fee_cents",
        "tax_amount_cents",
        mode="before",
    )
    @classmethod
    def _coerce_money_cents(cls, v: Any) -> int:
        return _dollars_to_cents(v)

    @model_validator(mode="after")
    def _build_line_items(self) -> "FolioFinancials":
        if not self.line_items:
            items: List[FolioLineItem] = []
            if self.nightly_rate_cents > 0:
                items.append(FolioLineItem(label="Nightly Rate", amount_cents=self.nightly_rate_cents, category="fee"))
            if self.cleaning_fee_cents > 0:
                items.append(FolioLineItem(label="Cleaning Fee", amount_cents=self.cleaning_fee_cents, category="fee"))
            if self.pet_fee_cents > 0:
                items.append(FolioLineItem(label="Pet Fee", amount_cents=self.pet_fee_cents, category="fee"))
            if self.damage_waiver_fee_cents > 0:
                items.append(FolioLineItem(label="Damage Waiver", amount_cents=self.damage_waiver_fee_cents, category="fee"))
            if self.service_fee_cents > 0:
                items.append(FolioLineItem(label="Service Fee", amount_cents=self.service_fee_cents, category="fee"))
            if self.tax_amount_cents > 0:
                items.append(FolioLineItem(label="Taxes", amount_cents=self.tax_amount_cents, category="tax"))
            if self.paid_amount_cents > 0:
                items.append(FolioLineItem(label="Payment Received", amount_cents=-self.paid_amount_cents, category="payment"))
            self.line_items = items
        return self


class FolioMessage(BaseModel):
    """A communication record (SMS, email, auto-response)."""

    id: str = ""
    direction: str = ""  # inbound | outbound
    body: str = ""
    status: str = ""
    phone_from: str = ""
    phone_to: str = ""
    channel: str = "sms"  # sms | email | ruebarue
    is_auto_response: bool = False
    intent: Optional[str] = None
    sentiment: Optional[str] = None
    created_at: Optional[str] = None


class FolioWorkOrder(BaseModel):
    """Maintenance / work order linked to the stay."""

    id: str = ""
    ticket_number: Optional[str] = None
    title: str = ""
    category: Optional[str] = None
    priority: Optional[str] = None
    status: str = "open"
    description: str = ""
    created_at: Optional[str] = None


class FolioDamageClaim(BaseModel):
    """Damage claim record."""

    id: str = ""
    claim_number: Optional[str] = None
    damage_description: str = ""
    estimated_cost: float = 0.0
    status: str = "open"
    has_legal_draft: bool = False
    created_at: Optional[str] = None

    @field_validator("estimated_cost", mode="before")
    @classmethod
    def _coerce_cost(cls, v: Any) -> float:
        if v is None:
            return 0.0
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            return 0.0


class FolioAgreement(BaseModel):
    """Rental agreement status."""

    id: str = ""
    status: str = ""
    signed_at: Optional[str] = None
    signer_name: str = ""
    agreement_type: str = ""
    has_content: bool = False


class FolioLifecycle(BaseModel):
    """Communication lifecycle tracker — which automated messages have been sent."""

    pre_arrival_sent: bool = False
    digital_guide_sent: bool = False
    access_info_sent: bool = False
    mid_stay_checkin_sent: bool = False
    checkout_reminder_sent: bool = False
    post_stay_followup_sent: bool = False


class ReservationFolio(BaseModel):
    """
    Master folio — the single source of truth for a reservation.
    Aggregates data from Streamline (PMS), native DB, Stripe, and RueBaRue.
    Every field has a safe default so the frontend never crashes.
    """

    guest: FolioGuest = Field(default_factory=FolioGuest)
    stay: FolioStay = Field(default_factory=FolioStay)
    financials: FolioFinancials = Field(default_factory=FolioFinancials)
    messages: List[FolioMessage] = Field(default_factory=list)
    work_orders: List[FolioWorkOrder] = Field(default_factory=list)
    damage_claims: List[FolioDamageClaim] = Field(default_factory=list)
    agreement: Optional[FolioAgreement] = None
    lifecycle: FolioLifecycle = Field(default_factory=FolioLifecycle)

    aggregation_errors: List[str] = Field(
        default_factory=list,
        description="Non-fatal errors during aggregation (e.g. RueBaRue timeout). "
        "Populated so the UI can show partial-data warnings.",
    )
