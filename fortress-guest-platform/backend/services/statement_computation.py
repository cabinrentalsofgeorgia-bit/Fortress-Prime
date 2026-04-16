"""
Statement Computation Service
==============================
Computes a per-property owner statement from local Crog-VRS data.

Entry point:
    compute_owner_statement(db, owner_payout_account_id, period_start, period_end)
        → StatementResult

The commission rate is ALWAYS read from owner_payout_accounts.commission_rate for
the row being computed.  It is never a parameter default, never pulled from config,
and never hardcoded.

This service is the single source of truth for "what the Crog-VRS ledger says" and
is compared against Streamline's GetMonthEndStatement in Phase 3.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import timedelta
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.owner_charge import OwnerCharge, OwnerChargeType  # noqa: F401 (OwnerChargeType used in charge loop)
from backend.models.property import Property
from backend.models.reservation import Reservation
from backend.services.ledger import (
    BucketedItem,
    TaxBucket,
    calculate_owner_payout,
)

logger = structlog.get_logger(service="statement_computation")


# ── Error types ───────────────────────────────────────────────────────────────

class StatementComputationError(Exception):
    """Raised when compute_owner_statement cannot produce a result.

    `code` is one of:
        'not_found'            — no owner_payout_accounts row for this id
        'not_enrolled'         — row exists but stripe_account_id is NULL (invite not accepted)
        'no_commission_rate'   — commission_rate is NULL (should be impossible post-migration)
        'property_not_found'   — property_id in the payout account is a valid UUID but no
                                 matching row exists in the properties table
        'property_not_renting' — property exists but renting_state != 'active'
                                 (pre_launch, paused, or offboarded)
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ── Output models ─────────────────────────────────────────────────────────────

class StatementLineItem(BaseModel):
    """One reservation's contribution to the statement."""
    reservation_id: str
    confirmation_code: str
    check_in: date
    check_out: date
    nights: int
    description: str              # "{property_name} — {guest_name}"
    gross_amount: Decimal         # commissionable gross attributable to THIS period
    # True when this reservation straddles a period boundary and only a
    # portion of its revenue is attributed here. Phase E uses this for the
    # asterisk footnote in the PDF, matching Streamline's format.
    crosses_period_boundary: bool = False
    pass_through_total: Decimal   # cleaning, ADW, taxes — not in commission base
    commission_amount: Decimal    # management commission (gross × rate)
    cc_processing_fee: Decimal    # CC processing fee
    net_to_owner: Decimal         # gross - commission - cc_processing_fee
    # H.1: Streamline reservation type code (STA, POS, …)
    # Source: streamline_financial_detail->>'type_id' mapped via _SL_TYPE_CODES.
    reservation_type: str = ""

    class Config:
        json_encoders = {Decimal: str}


# ── Streamline reservation type code mapping (H.1) ───────────────────────────
# Source: streamline_financial_detail.type_id observed in March 2026 data.
# Extend when new codes appear.
_SL_TYPE_CODES: dict[str, str] = {
    "2": "STA",   # Standard/Stay
    "7": "POS",   # Point of Sale / online booking
}


class OwnerChargeLineItem(BaseModel):
    """One owner charge entry in the statement."""
    posting_date: date
    transaction_type: str              # raw enum value
    transaction_type_display: str      # human-readable name
    description: str
    amount: Decimal                    # positive = expense/charge, negative = credit
    reference_id: Optional[str] = None

    class Config:
        json_encoders = {Decimal: str}


class StatementResult(BaseModel):
    """
    Result of compute_owner_statement().

    commission_rate is the fractional form read directly from
    owner_payout_accounts.commission_rate (e.g. Decimal("0.3000") for 30%).

    source is always 'crog' here. Phase 3 wraps this in a comparison against
    Streamline's GetMonthEndStatement.
    """
    owner_payout_account_id: int
    owner_name: str
    owner_email: Optional[str]
    property_id: str              # VARCHAR form stored in owner_payout_accounts
    property_name: str
    period_start: date
    period_end: date

    # Rate read from DB — the only source of truth
    commission_rate: Decimal      # fraction: 0.3000 = 30%
    commission_rate_percent: Decimal  # display: 30.00

    line_items: list[StatementLineItem] = Field(default_factory=list)
    owner_charges: list[OwnerChargeLineItem] = Field(default_factory=list)

    total_gross: Decimal = Decimal("0.00")
    total_pass_through: Decimal = Decimal("0.00")
    total_commission: Decimal = Decimal("0.00")
    total_cc_processing: Decimal = Decimal("0.00")
    total_net_to_owner: Decimal = Decimal("0.00")
    total_charges: Decimal = Decimal("0.00")   # sum of all owner_charges amounts

    reservation_count: int = 0
    currency: str = "USD"
    source: str = "crog"

    class Config:
        json_encoders = {Decimal: str}


# ── Period allocation ────────────────────────────────────────────────────────

def allocate_reservation_to_period(
    reservation: "Reservation",
    period_start: date,
    period_end: date,
) -> "tuple[Decimal, bool]":
    """
    Return (fraction_of_gross, crosses_period_boundary) for a reservation.

    `fraction_of_gross` is the Decimal fraction (0–1) of the reservation's
    commissionable gross that falls within [period_start, period_end].
    Multiply this by the total gross to get the period-attributable amount.

    `crosses_period_boundary` is True when the reservation spans across the
    period boundary (check_in before period_start or check_out after
    period_end+1 day), so the PDF renderer can add the asterisk footnote.

    Rules:
    - A reservation entirely within the period: fraction = 1.
    - A reservation entirely outside the period: fraction = 0.
    - A reservation straddling a boundary: proportional by night count.
    - Zero-night reservations (check_in == check_out): fraction = 0.

    Uses only Decimal arithmetic — no float at any step.
    """
    check_in = reservation.check_in_date
    check_out = reservation.check_out_date

    total_nights = (check_out - check_in).days
    if total_nights <= 0:
        return Decimal("0"), False

    # Nights that fall inside the period.
    # A night "belongs" to the period if it starts on or after period_start
    # and before period_end+1 (i.e., the checkout day is not counted).
    effective_start = max(check_in, period_start)
    effective_end = min(check_out, period_end + timedelta(days=1))

    if effective_end <= effective_start:
        return Decimal("0"), False

    nights_in_period = (effective_end - effective_start).days

    crosses = check_in < period_start or check_out > period_end

    if nights_in_period >= total_nights:
        return Decimal("1"), crosses

    fraction = Decimal(nights_in_period) / Decimal(total_nights)
    return fraction, True   # split → always crosses boundary


# ── Internal helpers ──────────────────────────────────────────────────────────

def _bucketed_items_from_reservation(res: Reservation) -> list[BucketedItem]:
    """Build BucketedItems from a Reservation ORM row.

    Mirrors _build_bucketed_items_from_reservation in admin_statements.py.
    This is intentionally a private helper — callers use compute_owner_statement.

    Fix G.5 (2026-04-15):
      - Fix 1: nightly_rate is the TOTAL base rent for the booking period
        (Streamline price_breakdown.price_nightly stores the booking total,
        not the per-night rate). Do NOT multiply by nights_count.
      - Fix 2: Parse streamline_financial_detail.required_fees JSON and
        classify additional commissionable items (pet fees, extra-guest /
        additional-party fees) that have no dedicated DB column.
        Classification policy (strict — extend only at Gary's direction):
          COMMISSIONABLE: name contains "pet", "additional person",
            "additional party", "extra guest", or "extra person" (case-insensitive)
          PASS-THROUGH: everything else (cleaning, ADW, processing, DOT, etc.)
          MALFORMED: missing name / value, or non-numeric value →
            log WARNING, treat as pass-through (safe default)
    """
    items: list[BucketedItem] = []

    # ── Fix 1: use nightly_rate directly (it stores TOTAL base rent, not per-night) ──
    nightly_rate = Decimal(str(res.nightly_rate or 0))
    rent = nightly_rate if nightly_rate > 0 else Decimal(str(res.total_amount or 0))
    if rent > 0:
        items.append(BucketedItem(name="Base Rent", amount=rent,
                                  item_type="rent", bucket=TaxBucket.LODGING))

    cleaning = Decimal(str(res.cleaning_fee or 0))
    if cleaning > 0:
        items.append(BucketedItem(name="Cleaning Fee", amount=cleaning,
                                  item_type="fee", bucket=TaxBucket.LODGING))

    pet_fee = Decimal(str(res.pet_fee or 0))
    if pet_fee > 0:
        items.append(BucketedItem(name="Pet Fee", amount=pet_fee,
                                  item_type="fee", bucket=TaxBucket.LODGING))

    adw = Decimal(str(res.damage_waiver_fee or 0))
    if adw > 0:
        items.append(BucketedItem(name="Accidental Damage Waiver", amount=adw,
                                  item_type="fee", bucket=TaxBucket.ADMIN))

    svc = Decimal(str(res.service_fee or 0))
    if svc > 0:
        items.append(BucketedItem(name="Processing Fee", amount=svc,
                                  item_type="fee", bucket=TaxBucket.ADMIN))

    tax = Decimal(str(res.tax_amount or 0))
    if tax > 0:
        items.append(BucketedItem(name="Taxes", amount=tax,
                                  item_type="tax", bucket=TaxBucket.LODGING))

    # ── Fix 2: parse required_fees from streamline_financial_detail JSON ──────
    # Commissionable keywords (extra-guest / additional-party surcharges).
    # Streamline is the source of truth for classification; CROG's job is parity,
    # not opinion. Pet fees removed in G.5.1 — Streamline treats them as
    # pass-through (verified against March 2026 Fallen Timber Lodge statements).
    _COMMISSIONABLE_PATTERNS = (
        "additional person",
        "additional party",
        "extra guest",
        "extra person",
    )

    fin_detail = res.streamline_financial_detail
    if isinstance(fin_detail, dict) and not fin_detail.get("_stale"):
        raw_fees = fin_detail.get("required_fees")
        if isinstance(raw_fees, list):
            for entry in raw_fees:
                # Validate structure — malformed → warning + pass-through
                if not isinstance(entry, dict):
                    logger.warning(
                        "required_fees_entry_not_dict",
                        reservation_confirmation_code=res.confirmation_code,
                        raw_entry=entry,
                        classified_as="pass-through",
                        match_rule="malformed-not-dict",
                    )
                    continue

                fee_name = entry.get("name")
                fee_value = entry.get("value")

                if not isinstance(fee_name, str) or not fee_name.strip():
                    logger.warning(
                        "required_fees_entry_missing_name",
                        reservation_confirmation_code=res.confirmation_code,
                        raw_entry=entry,
                        classified_as="pass-through",
                        match_rule="malformed-missing-name",
                    )
                    continue

                try:
                    fee_amount = Decimal(str(fee_value))
                except Exception:
                    logger.warning(
                        "required_fees_entry_non_numeric_value",
                        reservation_confirmation_code=res.confirmation_code,
                        fee_name=fee_name,
                        raw_value=fee_value,
                        classified_as="pass-through",
                        match_rule="malformed-non-numeric-value",
                    )
                    continue

                if fee_amount <= 0:
                    # Zero / negative fees are uncommon and non-commissionable
                    continue

                name_lower = fee_name.strip().lower()
                matched_rule = None
                for pattern in _COMMISSIONABLE_PATTERNS:
                    if pattern in name_lower:
                        matched_rule = pattern
                        break

                if matched_rule is not None:
                    logger.info(
                        "required_fees_classified",
                        reservation_confirmation_code=res.confirmation_code,
                        fee_name=fee_name,
                        fee_value=float(fee_amount),
                        classified_as="commissionable",
                        match_rule=matched_rule,
                    )
                    items.append(BucketedItem(
                        name=fee_name.strip(),
                        amount=fee_amount,
                        item_type="addon",
                        bucket=TaxBucket.LODGING,
                    ))
                else:
                    logger.info(
                        "required_fees_classified",
                        reservation_confirmation_code=res.confirmation_code,
                        fee_name=fee_name,
                        fee_value=float(fee_amount),
                        classified_as="pass-through",
                        match_rule="default-pass-through",
                    )
                    # Pass-through items from required_fees are already accounted
                    # for in the dedicated columns (cleaning_fee, damage_waiver_fee,
                    # service_fee, tax_amount). Do NOT double-count them.
                    # The loop is for commissionable items only; pass-through entries
                    # here are logged for audit but not added to items.

    return items


# ── Charges helper (shared by main path and fake-property early return) ──────

async def _fetch_charges(
    db: AsyncSession,
    owner_payout_account_id: int,
    period_start: date,
    period_end: date,
) -> "tuple[list[OwnerChargeLineItem], Decimal]":
    """Fetch non-voided owner charges and return (line_items, total)."""
    result = await db.execute(
        select(OwnerCharge)
        .where(
            OwnerCharge.owner_payout_account_id == owner_payout_account_id,
            OwnerCharge.posting_date >= period_start,
            OwnerCharge.posting_date <= period_end,
            OwnerCharge.voided_at.is_(None),
        )
        .order_by(OwnerCharge.posting_date.asc(), OwnerCharge.created_at.asc())
    )
    charges = result.scalars().all()

    items: list[OwnerChargeLineItem] = []
    total = Decimal("0.00")
    for ch in charges:
        try:
            display = OwnerChargeType(ch.transaction_type).display_name
        except ValueError:
            display = str(ch.transaction_type)
        items.append(OwnerChargeLineItem(
            posting_date=ch.posting_date,
            transaction_type=str(ch.transaction_type),
            transaction_type_display=display,
            description=ch.description,
            amount=Decimal(str(ch.amount)),
            reference_id=ch.reference_id,
        ))
        total += Decimal(str(ch.amount))
    return items, total


# ── Main entry point ──────────────────────────────────────────────────────────

async def compute_owner_statement(
    db: AsyncSession,
    owner_payout_account_id: int,
    period_start: date,
    period_end: date,
) -> StatementResult:
    """
    Compute an owner statement from Crog-VRS data.

    commission_rate is read from owner_payout_accounts.commission_rate for the
    given owner_payout_account_id.  It is never defaulted or hardcoded.

    Raises StatementComputationError for:
        'not_found'          — no row for owner_payout_account_id
        'not_enrolled'       — row exists but stripe_account_id is NULL
        'no_commission_rate' — commission_rate is NULL (impossible post-migration,
                               but defended against explicitly)

    Returns a StatementResult with empty line_items and zero totals if the owner
    had no qualifying reservations in the period (this is NOT an error).
    """
    # ── Step 1: Load the payout account row ──────────────────────────────────
    opa_row = await db.execute(
        text("""
            SELECT id, property_id, owner_name, owner_email,
                   stripe_account_id, commission_rate, account_status
            FROM owner_payout_accounts
            WHERE id = :opa_id
        """),
        {"opa_id": owner_payout_account_id},
    )
    opa = opa_row.fetchone()

    if opa is None:
        raise StatementComputationError(
            code="not_found",
            message=(
                f"No owner_payout_accounts row found for id={owner_payout_account_id}. "
                "Check that the owner has been invited and has accepted."
            ),
        )

    if not opa.stripe_account_id:
        raise StatementComputationError(
            code="not_enrolled",
            message=(
                f"Owner '{opa.owner_name}' (payout_account_id={owner_payout_account_id}) "
                "has not completed Stripe onboarding — stripe_account_id is NULL. "
                "The owner must click their invite link and connect their bank account."
            ),
        )

    if opa.commission_rate is None:
        raise StatementComputationError(
            code="no_commission_rate",
            message=(
                f"Owner '{opa.owner_name}' (payout_account_id={owner_payout_account_id}) "
                "has a NULL commission_rate, which should be impossible after the "
                "Phase 1.5 migration. Check the database for this row."
            ),
        )

    commission_rate = Decimal(str(opa.commission_rate))
    commission_rate_percent = (commission_rate * 100).quantize(Decimal("0.0001"))
    property_id_str: str = opa.property_id

    # ── Step 2: Resolve the property record (for name and UUID) ──────────────
    # owner_payout_accounts.property_id is VARCHAR; properties.id is UUID.
    try:
        property_uuid = _uuid.UUID(property_id_str)
    except ValueError:
        # Fake/test property_id (e.g. "test-prop-abc123") — no real property row.
        # Still compute charges (they only need owner_payout_account_id).
        logger.warning(
            "statement_no_property_record",
            owner_payout_account_id=owner_payout_account_id,
            property_id=property_id_str,
        )
        charge_items, total_charges = await _fetch_charges(
            db, owner_payout_account_id, period_start, period_end
        )
        return StatementResult(
            owner_payout_account_id=owner_payout_account_id,
            owner_name=opa.owner_name or "",
            owner_email=opa.owner_email,
            property_id=property_id_str,
            property_name=property_id_str,
            period_start=period_start,
            period_end=period_end,
            commission_rate=commission_rate,
            commission_rate_percent=commission_rate_percent,
            owner_charges=charge_items,
            total_charges=total_charges,
        )

    prop_result = await db.execute(
        select(Property).where(Property.id == property_uuid)
    )
    prop = prop_result.scalar_one_or_none()
    if prop is None:
        raise StatementComputationError(
            code="property_not_found",
            message=(
                f"Property UUID {property_id_str!r} is referenced by "
                f"owner_payout_accounts.id={owner_payout_account_id} "
                f"but no matching row exists in the properties table. "
                "Check that the property has not been deactivated or deleted."
            ),
        )

    # Only 'active' properties generate owner statements.
    # pre_launch / paused / offboarded properties are explicitly excluded.
    renting_state = getattr(prop, "renting_state", "active")
    if renting_state != "active":
        raise StatementComputationError(
            code="property_not_renting",
            message=(
                f"Property {prop.name!r} (id={property_id_str}) has "
                f"renting_state={renting_state!r}. Only 'active' properties "
                "generate owner statements. Change the property's renting_state "
                "to 'active' when it begins renting."
            ),
        )

    property_name = prop.name

    # ── Step 3: Query reservations for this property in the period ────────────
    # Include reservations that CHECK IN within the period OR that straddle
    # the period start (check_in before period_start but check_out after it).
    # Owner bookings (is_owner_booking=True) contribute $0 — excluded here.
    res_result = await db.execute(
        select(Reservation)
        .where(and_(
            Reservation.property_id == property_uuid,
            Reservation.check_in_date < (period_end + timedelta(days=1)),
            Reservation.check_out_date > period_start,
            Reservation.status.in_(["confirmed", "checked_in", "checked_out", "completed"]),
            Reservation.is_owner_booking.is_(False),
        ))
        .order_by(Reservation.check_in_date.asc())
    )
    reservations = res_result.scalars().all()

    # ── Step 4: Compute per-reservation payouts using the DB commission_rate ──
    line_items: list[StatementLineItem] = []
    total_gross = Decimal("0.00")
    total_pass_through = Decimal("0.00")
    total_commission = Decimal("0.00")
    total_cc = Decimal("0.00")
    total_net = Decimal("0.00")

    for res in reservations:
        items = _bucketed_items_from_reservation(res)

        # commission_rate comes from the DB — never from a default, never hardcoded.
        payout = calculate_owner_payout(items, commission_rate=commission_rate_percent)

        # Allocate proportionally when the reservation straddles a period boundary.
        fraction, crosses = allocate_reservation_to_period(res, period_start, period_end)

        if fraction <= Decimal("0"):
            continue  # reservation is entirely outside this period

        # Apply fraction to all financial figures
        period_gross      = (payout.gross_revenue      * fraction).quantize(Decimal("0.01"))
        period_pass       = (payout.pass_through_total * fraction).quantize(Decimal("0.01"))
        period_commission = (payout.commission_amount  * fraction).quantize(Decimal("0.01"))
        period_net        = (payout.net_owner_payout   * fraction).quantize(Decimal("0.01"))

        nights = res.nights_count or (res.check_out_date - res.check_in_date).days
        guest_name = getattr(res, "guest_name", "") or ""
        description = f"{property_name}" + (f" — {guest_name}" if guest_name else "")

        # Extract Streamline type code from financial detail JSON (H.1)
        fin = res.streamline_financial_detail or {}
        type_id_raw = str(fin.get("type_id", "") or "").strip()
        res_type = _SL_TYPE_CODES.get(type_id_raw, "")

        line_items.append(StatementLineItem(
            reservation_id=str(res.id),
            confirmation_code=res.confirmation_code or "",
            check_in=res.check_in_date,
            check_out=res.check_out_date,
            nights=nights,
            description=description,
            gross_amount=period_gross,
            pass_through_total=period_pass,
            commission_amount=period_commission,
            cc_processing_fee=Decimal("0.00"),
            net_to_owner=period_net,
            crosses_period_boundary=crosses,
            reservation_type=res_type,
        ))

        total_gross += period_gross
        total_pass_through += period_pass
        total_commission += period_commission
        total_net += period_net

    # ── Step 5: Load non-voided owner charges for this account+period ────────
    charge_line_items, total_charges = await _fetch_charges(
        db, owner_payout_account_id, period_start, period_end
    )

    logger.info(
        "owner_statement_computed",
        owner_payout_account_id=owner_payout_account_id,
        property_id=property_id_str,
        period=f"{period_start} to {period_end}",
        reservations=len(line_items),
        charges=len(charge_line_items),
        commission_rate_pct=float(commission_rate_percent),
        total_net=float(total_net),
    )

    return StatementResult(
        owner_payout_account_id=owner_payout_account_id,
        owner_name=opa.owner_name or "",
        owner_email=opa.owner_email,
        property_id=property_id_str,
        property_name=property_name,
        period_start=period_start,
        period_end=period_end,
        commission_rate=commission_rate,
        commission_rate_percent=commission_rate_percent,
        line_items=line_items,
        owner_charges=charge_line_items,
        total_gross=total_gross,
        total_pass_through=total_pass_through,
        total_commission=total_commission,
        total_cc_processing=total_cc,
        total_net_to_owner=total_net,
        total_charges=total_charges,
        reservation_count=len(line_items),
    )


# ── What-if helper (used by admin_statements.py only) ─────────────────────────

def _apply_rate_override(result: StatementResult, rate_percent: Decimal) -> StatementResult:
    """
    Recompute a StatementResult with a different commission rate.

    Used ONLY by the admin what-if endpoint (commission_rate_override).
    Does NOT touch owner_payout_accounts. Returns a new StatementResult with
    source='crog_what_if' so callers can distinguish it from the real number.
    """
    from backend.services.ledger import _money  # type: ignore[attr-defined]

    new_items: list[StatementLineItem] = []
    total_gross = Decimal("0.00")
    total_commission = Decimal("0.00")
    total_cc = Decimal("0.00")
    total_net = Decimal("0.00")

    for li in result.line_items:
        adj_commission = _money(li.gross_amount * rate_percent / Decimal("100"))
        adj_net = _money(li.gross_amount - adj_commission - li.cc_processing_fee)
        new_items.append(StatementLineItem(
            reservation_id=li.reservation_id,
            confirmation_code=li.confirmation_code,
            check_in=li.check_in,
            check_out=li.check_out,
            nights=li.nights,
            description=li.description,
            gross_amount=li.gross_amount,
            pass_through_total=li.pass_through_total,
            commission_amount=adj_commission,
            cc_processing_fee=li.cc_processing_fee,
            net_to_owner=adj_net,
        ))
        total_gross += li.gross_amount
        total_commission += adj_commission
        total_cc += li.cc_processing_fee
        total_net += adj_net

    return result.model_copy(update={
        "commission_rate": rate_percent / Decimal("100"),
        "commission_rate_percent": rate_percent,
        "line_items": new_items,
        "total_gross": total_gross,
        "total_commission": total_commission,
        "total_cc_processing": total_cc,
        "total_net_to_owner": total_net,
        "source": "crog_what_if",
    })
