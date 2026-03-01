"""
Reservation Folio — Strict Pydantic Data Contracts
====================================================
These models act as the bouncer between dirty legacy data (Streamline,
RueBaRue, Stripe) and the frontend.  Every Optional field has a safe
default.  Validators coerce common legacy quirks (null amounts → 0.0,
missing dates → None) so the frontend NEVER receives unexpected shapes.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


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
    amount: float = 0.0
    category: str = "fee"  # fee | tax | payment | adjustment | deposit

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, v: Any) -> float:
        if v is None:
            return 0.0
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            return 0.0


class FolioSecurityDeposit(BaseModel):
    """Security deposit authorization state for a reservation."""

    is_required: bool = False
    amount: float = 500.00
    status: str = "none"  # none | scheduled | authorized | captured | released
    stripe_payment_intent: Optional[str] = None
    updated_at: Optional[str] = None

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_deposit(cls, v: Any) -> float:
        if v is None:
            return 500.00
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            return 500.00

    @property
    def system_flag(self) -> Optional[str]:
        """Amber flag when deposit is required but not yet actioned."""
        if self.is_required and self.status == "none":
            return "DEPOSIT PENDING"
        return None


class FolioFinancials(BaseModel):
    """Complete financial picture for a reservation."""

    total_amount: float = 0.0
    paid_amount: float = 0.0
    balance_due: float = 0.0
    nightly_rate: float = 0.0
    cleaning_fee: float = 0.0
    pet_fee: float = 0.0
    damage_waiver_fee: float = 0.0
    service_fee: float = 0.0
    tax_amount: float = 0.0
    currency: str = "USD"
    line_items: List[FolioLineItem] = Field(default_factory=list)
    price_breakdown: Optional[Dict[str, Any]] = None
    streamline_financial_detail: Optional[Dict[str, Any]] = None
    security_deposit: FolioSecurityDeposit = Field(default_factory=FolioSecurityDeposit)

    @field_validator(
        "total_amount",
        "paid_amount",
        "balance_due",
        "nightly_rate",
        "cleaning_fee",
        "pet_fee",
        "damage_waiver_fee",
        "service_fee",
        "tax_amount",
        mode="before",
    )
    @classmethod
    def _coerce_money(cls, v: Any) -> float:
        if v is None:
            return 0.0
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            return 0.0

    @model_validator(mode="after")
    def _build_line_items(self) -> "FolioFinancials":
        if not self.line_items:
            items: List[FolioLineItem] = []
            if self.nightly_rate > 0:
                items.append(FolioLineItem(label="Nightly Rate", amount=self.nightly_rate, category="fee"))
            if self.cleaning_fee > 0:
                items.append(FolioLineItem(label="Cleaning Fee", amount=self.cleaning_fee, category="fee"))
            if self.pet_fee > 0:
                items.append(FolioLineItem(label="Pet Fee", amount=self.pet_fee, category="fee"))
            if self.damage_waiver_fee > 0:
                items.append(FolioLineItem(label="Damage Waiver", amount=self.damage_waiver_fee, category="fee"))
            if self.service_fee > 0:
                items.append(FolioLineItem(label="Service Fee", amount=self.service_fee, category="fee"))
            if self.tax_amount > 0:
                items.append(FolioLineItem(label="Taxes", amount=self.tax_amount, category="tax"))
            if self.paid_amount > 0:
                items.append(FolioLineItem(label="Payment Received", amount=-self.paid_amount, category="payment"))
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
