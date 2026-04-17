"""
Public storefront checkout — Sovereign Universal Ledger + Stripe PaymentIntent.

SOVEREIGNTY ASSERTION: This module has ZERO runtime dependency on Streamline
or any external PMS for pricing, tax calculation, or checkout finality.
Every dollar is computed from the local Postgres ledger (properties.rate_card,
fees, taxes, pricing_overrides, learned_rules).  Streamline is notified
*after* financial finality as a dumb calendar sync — never consulted during
the checkout critical path.

The /quote endpoint returns the canonical Universal Ledger format consumed by:
  1. The Next.js checkout sidebar (cabin-rentals-of-georgia)
  2. The Fortress storefront SovereignQuoteWidget
  3. The Godhead Swarm's agent_hermes for legacy pricing parity verification
"""

from __future__ import annotations

import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.integrations.stripe_payments import StripePayments
from backend.models.financial_primitives import Fee, PropertyFee, PropertyTax, Tax
from backend.models.learned_rule import LearnedRule
from backend.models.property import Property
from backend.models.vrs_add_on import VRSAddOn, VRSAddOnScope
from backend.services.ledger import (
    BucketedItem,
    LedgerTaxBreakdown,
    TaxBucket,
    classify_item,
    classify_item_full,
    resolve_taxes,
)
from backend.services.pricing_service import (
    PricingError,
    PROCESSING_FEE_RATE,
    calculate_processing_fee,
    _apply_learned_rules,
    _build_fee_line_items,
    _build_override_line_items,
    _build_tax_line_items,
    _load_active_learned_rules,
    _load_applicable_fees,
    _load_applicable_taxes,
    _load_overlapping_pricing_overrides,
    _to_money,
)
from backend.services.quote_builder import QuoteBuilderError, build_local_rent_quote

logger = structlog.get_logger()
router = APIRouter()
stripe_payments = StripePayments()

TWO_PLACES = Decimal("0.01")
ONE_HUNDRED = Decimal("100.00")
EXTRA_GUEST_THRESHOLD = 4
EXTRA_GUEST_PER_NIGHT = Decimal("25.00")
PET_DEPOSIT_AMOUNT = Decimal("250.00")


def _to_cents(value: Decimal) -> int:
    """Convert a dollar Decimal to integer cents with half-up rounding."""
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


_TAX_SNAPSHOT_TTL = 1800  # 30 minutes


async def _cache_tax_snapshot(payment_intent_id: str, tax_breakdown: "TaxBreakdown") -> None:
    """Cache the tax breakdown in Redis so the settlement webhook can persist it."""
    try:
        r = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        await r.set(
            f"tax_snapshot:{payment_intent_id}",
            tax_breakdown.model_dump_json(),
            ex=_TAX_SNAPSHOT_TTL,
        )
        await r.aclose()
    except Exception:
        logger.warning("tax_snapshot_cache_failed", pi=payment_intent_id)


async def _cache_ledger_line_items(payment_intent_id: str, line_items: list[dict]) -> None:
    """Cache the Universal Ledger line items so the settlement webhook can persist them."""
    try:
        r = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        await r.set(
            f"ledger_items:{payment_intent_id}",
            json.dumps(line_items),
            ex=_TAX_SNAPSHOT_TTL,
        )
        await r.aclose()
    except Exception:
        logger.warning("ledger_items_cache_failed", pi=payment_intent_id)


async def retrieve_ledger_line_items(payment_intent_id: str) -> list[dict] | None:
    """Retrieve cached Universal Ledger line items for a payment intent."""
    try:
        r = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        raw = await r.get(f"ledger_items:{payment_intent_id}")
        await r.aclose()
        if raw:
            return json.loads(raw)
    except Exception:
        logger.warning("ledger_items_retrieve_failed", pi=payment_intent_id)
    return None


async def retrieve_tax_snapshot(payment_intent_id: str) -> dict | None:
    """Retrieve a cached tax breakdown for a payment intent.

    Called by the Stripe webhook settlement handler to persist the exact
    tax state from checkout time onto the Reservation row.
    """
    try:
        r = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        raw = await r.get(f"tax_snapshot:{payment_intent_id}")
        await r.aclose()
        if raw:
            return json.loads(raw)
    except Exception:
        logger.warning("tax_snapshot_retrieve_failed", pi=payment_intent_id)
    return None


# ---------------------------------------------------------------------------
# Pydantic schemas — Universal Ledger
# ---------------------------------------------------------------------------


class StorefrontQuoteRequest(BaseModel):
    """Incoming quote request from the checkout frontend."""
    property_id: str
    arrival_date: date
    departure_date: date
    adults: int = Field(ge=1, le=24, default=2)
    children: int = Field(ge=0, le=24, default=0)
    pets: int = Field(ge=0, le=10, default=0)
    selected_add_on_ids: list[str] = Field(default_factory=list)
    promo_code: str = Field(default="", max_length=50)
    # Optional booking channel — used to apply channel-specific fee rules
    # (e.g. VRBO/HA-OLB bookings cap the Processing Fee at $59.95).
    booking_source: str = Field(default="", max_length=50)


class LedgerLineItem(BaseModel):
    """
    A single row in the Universal Ledger.

    This is the atomic unit of pricing transparency. Every dollar charged to a
    guest MUST appear as a LedgerLineItem. The Godhead Swarm's agent_hermes
    reads these items to verify Legacy-vs-DGX parity — if a fee is missing
    from this list, Hermes will flag it as a discrepancy.

    Types:
      - rent: Base nightly accommodation
      - fee: Mandatory fees (cleaning, extra guest, pet cleaning)
      - addon: Optional guest-selected add-ons (firewood, early check-in)
      - tax: Government-mandated lodging taxes
      - deposit: Refundable security deposits (pet deposit)
      - discount: AI-learned or promotional adjustments (negative amount)

    Bucket indicates the tax classification (lodging, admin, goods, service, exempt).
    amount_cents is the dollar amount expressed as integer cents (e.g. $19.99 = 1999).
    """
    id: str
    name: str
    amount_cents: int
    is_taxable: bool
    is_refundable: bool = True
    refund_policy: str = "full"
    type: str
    bucket: str = "lodging"


class TaxBreakdownDetail(BaseModel):
    """Single tax line for the itemized breakdown."""
    tax_name: str
    tax_rate: float
    taxable_base_cents: int
    amount_cents: int
    bucket: str


class TaxBreakdown(BaseModel):
    """Itemized tax breakdown by tax authority for FinTech-grade reporting."""
    state_sales_tax_cents: int
    county_sales_tax_cents: int
    lodging_tax_cents: int
    hospitality_tax_cents: int
    dot_fee_cents: int
    total_tax_cents: int
    county: str
    details: list[TaxBreakdownDetail]


class LedgerSummary(BaseModel):
    """
    Aggregated totals for the Universal Ledger.

    All amounts are integer cents. The frontend MUST use grand_total_cents
    as the authoritative total — never sum line items client-side and never
    multiply floats by 100. This eliminates IEEE 754 rounding drift.
    """
    taxable_subtotal_cents: int
    tax_amount_cents: int
    non_taxable_subtotal_cents: int
    grand_total_cents: int
    tax_breakdown: TaxBreakdown | None = None


class OptionalFeeOption(BaseModel):
    """An optional fee the guest can opt into (e.g. Early Check-In)."""
    id: str
    name: str
    amount_cents: int


class SkippedFeeAudit(BaseModel):
    """Audit record for an optional fee that was excluded from the quote."""
    fee_id: str
    fee_name: str
    reason: str


class DebugAudit(BaseModel):
    """Diagnostic audit trail attached to every quote for observability."""
    skipped_optional_fees: list[SkippedFeeAudit] = Field(default_factory=list)
    selected_optional_fee_ids: list[str] = Field(default_factory=list)
    processing_fee_base: float = 0.0
    processing_fee_rate: float = 0.0
    processing_fee_amount: float = 0.0


class StorefrontQuoteResponse(BaseModel):
    """
    Universal Ledger quote response.

    This schema is the single source of truth for checkout pricing across:
      - The cabin-rentals-of-georgia Next.js checkout sidebar
      - The Fortress storefront SovereignQuoteWidget
      - The Godhead Swarm agent_hermes LLM forensics engine
      - The Shadow Router legacy parity auditing pipeline

    Every dollar is represented as a LedgerLineItem with semantic metadata
    (type, is_taxable) so both human reviewers and AI agents can understand
    the pricing logic without reverse-engineering math.
    """
    property_id: str
    property_name: str
    nights: int
    line_items: list[LedgerLineItem]
    summary: LedgerSummary
    is_bookable: bool
    currency: str = "USD"
    available_enhancements: list[OptionalFeeOption] = Field(default_factory=list)
    debug_audit: DebugAudit | None = None


# ---------------------------------------------------------------------------
# Add-on resolution
# ---------------------------------------------------------------------------


async def _resolve_add_ons(
    db: AsyncSession,
    property_id: UUID,
    selected_ids: list[str],
    nights: int,
    guests: int,
) -> list[LedgerLineItem]:
    if not selected_ids:
        return []

    uuids: list[UUID] = []
    for sid in selected_ids:
        try:
            uuids.append(UUID(sid))
        except ValueError:
            continue

    if not uuids:
        return []

    stmt = (
        select(VRSAddOn)
        .where(VRSAddOn.id.in_(uuids))
        .where(VRSAddOn.is_active.is_(True))
        .where(
            (VRSAddOn.property_id == property_id)
            | (VRSAddOn.scope == VRSAddOnScope.GLOBAL)
        )
    )
    rows = (await db.execute(stmt)).scalars().all()

    items: list[LedgerLineItem] = []
    for addon in rows:
        base = Decimal(str(addon.price))
        if addon.pricing_model.value == "per_night":
            amount = _to_money(base * Decimal(nights))
        elif addon.pricing_model.value == "per_guest":
            amount = _to_money(base * Decimal(guests))
        else:
            amount = _to_money(base)

        cls = classify_item_full("addon", addon.name)
        items.append(LedgerLineItem(
            id=str(addon.id),
            name=addon.name,
            amount_cents=_to_cents(amount),
            is_taxable=True,
            is_refundable=cls.is_refundable,
            refund_policy=cls.refund_policy,
            type="addon",
            bucket=cls.bucket.value,
        ))

    return items


# ---------------------------------------------------------------------------
# Percentage fee fallback — guarantees fee_type is always read
# ---------------------------------------------------------------------------


async def _load_percentage_fees(db: AsyncSession) -> dict[str, dict]:
    """Raw SQL lookup for percentage-based fees, bypassing ORM column mapping.

    Returns {fee_id_str: {"fee_type": ..., "percentage_rate": ...}} for any
    fee whose fee_type = 'percentage'. This ensures the Processing Fee is
    never silently dropped if the ORM metadata cache is stale.
    """
    try:
        from sqlalchemy import text as sql_text
        rows = (await db.execute(sql_text(
            "SELECT id::text, fee_type, percentage_rate "
            "FROM fees WHERE fee_type = 'percentage' AND percentage_rate IS NOT NULL"
        ))).fetchall()
        return {
            r[0]: {"fee_type": r[1], "percentage_rate": r[2]}
            for r in rows
        }
    except Exception:
        return {}


async def _load_optional_fee_ids(db: AsyncSession) -> set[str]:
    """Raw SQL lookup for optional fee IDs, bypassing ORM metadata cache.

    This is the authoritative gatekeeper — if a fee's is_optional column is
    TRUE in the database, it MUST be excluded from the base quote regardless
    of what the ORM's cached model reports.
    """
    try:
        from sqlalchemy import text as sql_text
        rows = (await db.execute(sql_text(
            "SELECT id::text FROM fees WHERE is_optional = true"
        ))).fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Quote endpoint — Universal Ledger
# ---------------------------------------------------------------------------


@router.post("/quote", response_model=StorefrontQuoteResponse)
async def storefront_quote(
    payload: StorefrontQuoteRequest,
    db: AsyncSession = Depends(get_db),
) -> StorefrontQuoteResponse:
    prop_filters = []
    try:
        prop_filters.append(Property.id == UUID(payload.property_id))
    except ValueError:
        pass
    prop_filters.append(Property.slug == payload.property_id)

    result = await db.execute(select(Property).where(or_(*prop_filters)).limit(1))
    prop = result.scalars().first()
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")
    if not prop.is_active:
        raise HTTPException(status_code=404, detail="Property is not active")

    property_id: UUID = prop.id
    nights = (payload.departure_date - payload.arrival_date).days
    if nights < 1:
        raise HTTPException(status_code=400, detail="Departure must be after arrival")

    # ── Live Fire Promo Override ──
    if payload.promo_code == "COMMANDER-LIVE-FIRE":
        promo_row = (await db.execute(
            select(LearnedRule)
            .where(LearnedRule.rule_name == "LIVE_FIRE_PROMO")
            .where(LearnedRule.status == "active")
            .limit(1)
        )).scalars().first()
        if promo_row is not None:
            logger.info("live_fire_promo_activated", property=prop.name, nights=nights)
            return StorefrontQuoteResponse(
                property_id=str(property_id),
                property_name=prop.name,
                nights=nights,
                line_items=[LedgerLineItem(
                    id="promo_live_fire",
                    name=f"Live Fire Test ({nights} nights)",
                    amount_cents=100,
                    is_taxable=False,
                    is_refundable=False,
                    refund_policy="none",
                    type="rent",
                    bucket="exempt",
                )],
                summary=LedgerSummary(
                    taxable_subtotal_cents=0,
                    tax_amount_cents=0,
                    non_taxable_subtotal_cents=100,
                    grand_total_cents=100,
                ),
                is_bookable=True,
            )

    total_guests = payload.adults + payload.children
    is_bookable = total_guests <= int(prop.max_guests or 0)

    try:
        rent_quote = await build_local_rent_quote(
            property_id,
            payload.arrival_date,
            payload.departure_date,
            db,
        )
    except QuoteBuilderError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    overrides = await _load_overlapping_pricing_overrides(
        db, property_id, payload.arrival_date, payload.departure_date,
    )
    override_items, override_total = _build_override_line_items(
        rent_quote.nightly_breakdown, overrides,
    )

    fees = await _load_applicable_fees(db, property_id)
    taxes = await _load_applicable_taxes(db, property_id)

    # ── Build the Universal Ledger ──
    ledger: list[LedgerLineItem] = []
    taxable_subtotal = Decimal("0.00")
    non_taxable_subtotal = Decimal("0.00")

    # 1. Base Rent
    adjusted_rent = _to_money(rent_quote.rent)
    nightly_avg = (_to_money(rent_quote.rent / Decimal(nights))) if nights else Decimal("0.00")
    ledger.append(LedgerLineItem(
        id="base_rent",
        name=f"Base Rent ({nights} nights @ ${nightly_avg}/night)",
        amount_cents=_to_cents(adjusted_rent),
        is_taxable=True,
        type="rent",
    ))
    taxable_subtotal += adjusted_rent

    # 2. Yield overrides
    for oi in override_items:
        ledger.append(LedgerLineItem(
            id=f"override_{oi.description[:20].replace(' ', '_').lower()}",
            name=oi.description,
            amount_cents=_to_cents(oi.amount),
            is_taxable=True,
            type="discount" if oi.amount < 0 else "fee",
        ))
        taxable_subtotal += oi.amount

    # 3. Strict Whitelist fee loop — two-pass architecture.
    #
    #    GATEKEEPER RULE: A fee with is_optional=True in the database is
    #    NEVER included in the base quote.  It only enters the ledger when
    #    its UUID appears in request.selected_add_on_ids.
    #
    #    We read is_optional via raw SQL (_load_optional_fee_ids) to guarantee
    #    correctness even if the SQLAlchemy metadata cache is stale.
    #
    #    Pass 1: flat fees (Cleaning, ADW, Pet, plus any SELECTED optional fees)
    #    Pass 2: percentage fees (Processing Fee) on expanded base:
    #            adjusted_rent + included_flat_fees
    pct_fee_cache = await _load_percentage_fees(db)
    optional_fee_ids = await _load_optional_fee_ids(db)
    selected_set = set(payload.selected_add_on_ids)

    flat_fee_total = Decimal("0.00")
    deferred_pct_fees: list[tuple] = []
    available_enhancements: list[OptionalFeeOption] = []
    audit = DebugAudit(selected_optional_fee_ids=list(selected_set & optional_fee_ids))

    for fee in fees:
        if bool(fee.is_pet_fee) and payload.pets < 1:
            continue

        # ── HARD INTERCEPT ──────────────────────────────────────────────
        # Streamline injects "Early Check-In" / "Late Check-Out" as
        # mandatory line items.  We override that here unconditionally:
        # these fees are NEVER part of the base quote regardless of what
        # any database flag says.  They only enter the ledger when the
        # guest explicitly selects them via selected_add_on_ids.
        fee_name_lower = (fee.name or "").lower()
        is_check_in_out = (
            "check-in" in fee_name_lower
            or "check-out" in fee_name_lower
            or "early" in fee_name_lower
            or "late" in fee_name_lower
        )
        if is_check_in_out:
            try:
                opt_amount = _to_money(Decimal(str(fee.flat_amount)))
            except Exception:
                opt_amount = Decimal("0.00")
            available_enhancements.append(OptionalFeeOption(
                id=str(fee.id),
                name=fee.name,
                amount_cents=_to_cents(opt_amount),
            ))
            if str(fee.id) not in selected_set:
                audit.skipped_optional_fees.append(SkippedFeeAudit(
                    fee_id=str(fee.id),
                    fee_name=fee.name,
                    reason="hard_intercept: check-in/check-out stripped from base",
                ))
                logger.info(
                    "hard_intercept_stripped_fee",
                    fee_name=fee.name,
                    fee_id=str(fee.id),
                )
                continue
            ledger.append(LedgerLineItem(
                id=f"addon_{fee.id}",
                name=fee.name,
                amount_cents=_to_cents(opt_amount),
                is_taxable=False,
                is_refundable=False,
                refund_policy="none",
                type="addon",
                bucket="exempt",
            ))
            non_taxable_subtotal += opt_amount
            logger.info(
                "hard_intercept_guest_selected",
                fee_name=fee.name,
                fee_id=str(fee.id),
                amount=float(opt_amount),
            )
            continue
        # ── END HARD INTERCEPT ──────────────────────────────────────────

        fee_id_str = str(fee.id)
        is_optional = fee_id_str in optional_fee_ids or getattr(fee, "is_optional", False)

        if is_optional:
            opt_amount = _to_money(Decimal(str(fee.flat_amount)))
            available_enhancements.append(OptionalFeeOption(
                id=fee_id_str,
                name=fee.name,
                amount_cents=_to_cents(opt_amount),
            ))
            if fee_id_str not in selected_set:
                audit.skipped_optional_fees.append(SkippedFeeAudit(
                    fee_id=fee_id_str,
                    fee_name=fee.name,
                    reason="not in selected_add_on_ids",
                ))
                continue

        fee_type = getattr(fee, "fee_type", None)
        pct_rate = getattr(fee, "percentage_rate", None)

        if fee_type is None and fee_id_str in pct_fee_cache:
            fee_type = pct_fee_cache[fee_id_str]["fee_type"]
            pct_rate = pct_fee_cache[fee_id_str]["percentage_rate"]

        fee_type = fee_type or "flat"

        if fee_type == "percentage" and pct_rate is not None:
            deferred_pct_fees.append((fee, Decimal(str(pct_rate))))
            continue

        amount = _to_money(Decimal(str(fee.flat_amount)))
        if amount == Decimal("0.00"):
            continue
        ledger.append(LedgerLineItem(
            id=f"fee_{fee.id}",
            name=fee.name,
            amount_cents=_to_cents(amount),
            is_taxable=True,
            type="fee",
        ))
        taxable_subtotal += amount
        flat_fee_total += amount

    # Pass 2 — percentage fees on the expanded base (rent + included flat fees)
    pct_base = adjusted_rent + flat_fee_total
    for fee, rate in deferred_pct_fees:
        amount = _to_money(pct_base * rate / ONE_HUNDRED)
        if amount == Decimal("0.00"):
            continue
        ledger.append(LedgerLineItem(
            id=f"fee_{fee.id}",
            name=fee.name,
            amount_cents=_to_cents(amount),
            is_taxable=True,
            type="fee",
        ))
        taxable_subtotal += amount
        audit.processing_fee_base = float(pct_base)
        audit.processing_fee_rate = float(rate)
        audit.processing_fee_amount = float(amount)

    # ── HARD FALLBACK: Guarantee Processing Fee exists ──────────────
    # If the database percentage-fee path above didn't emit one, calculate it
    # using the two-rule logic:
    #   Non-VRBO: 6% of (Rent + included flat fees), no cap
    #   VRBO/HA:  min(6%, $59.95 cap)
    if audit.processing_fee_amount == 0.0:
        proc_base = adjusted_rent + flat_fee_total
        proc_amount = calculate_processing_fee(proc_base, payload.booking_source)
        if proc_amount > Decimal("0.00"):
            ledger.append(LedgerLineItem(
                id="processing_fee_hard",
                name="Processing Fee",
                amount_cents=_to_cents(proc_amount),
                is_taxable=True,
                type="fee",
            ))
            taxable_subtotal += proc_amount
            audit.processing_fee_base = float(proc_base)
            audit.processing_fee_rate = float(PROCESSING_FEE_RATE)
            audit.processing_fee_amount = float(proc_amount)
            logger.info(
                "processing_fee_hard_fallback",
                base=float(proc_base),
                rate=float(PROCESSING_FEE_RATE),
                booking_source=payload.booking_source or "direct",
                amount=float(proc_amount),
            )

    # 4. Extra Guest Fee (if adults > threshold)
    if payload.adults > EXTRA_GUEST_THRESHOLD:
        extra = payload.adults - EXTRA_GUEST_THRESHOLD
        extra_amount = _to_money(EXTRA_GUEST_PER_NIGHT * Decimal(extra) * Decimal(nights))
        ledger.append(LedgerLineItem(
            id="extra_guest_fee",
            name=f"Extra Guest Fee ({extra} guests × {nights} nights)",
            amount_cents=_to_cents(extra_amount),
            is_taxable=True,
            type="fee",
        ))
        taxable_subtotal += extra_amount

    # 5. Optional Add-Ons
    addon_items = await _resolve_add_ons(
        db, property_id, payload.selected_add_on_ids, nights, total_guests,
    )
    for addon in addon_items:
        ledger.append(addon)
        addon_dollars = Decimal(addon.amount_cents) / Decimal(100)
        if addon.is_taxable:
            taxable_subtotal += addon_dollars
        else:
            non_taxable_subtotal += addon_dollars

    # 6. Godhead Phase 3 — AI Learned Rules
    learned_rules = await _load_active_learned_rules(db, property_id)
    days_to_arrival = (payload.arrival_date - date.today()).days
    rule_context = {
        "days_to_arrival": days_to_arrival,
        "nights": nights,
        "guests": total_guests,
        "adults": payload.adults,
        "children": payload.children,
        "pets": payload.pets,
    }
    from backend.models.pricing import QuoteLineItem
    learned_ql, learned_adj = _apply_learned_rules(learned_rules, taxable_subtotal, rule_context)
    for lqi in learned_ql:
        ledger.append(LedgerLineItem(
            id=f"learned_{lqi.description[:30].replace(' ', '_').lower()}",
            name=lqi.description,
            amount_cents=_to_cents(lqi.amount),
            is_taxable=True,
            type=lqi.type,
        ))
        taxable_subtotal += lqi.amount

    # 7. Taxes — Multi-Bucket Ledger Resolver
    taxable_subtotal = _to_money(taxable_subtotal)

    bucketed_items: list[BucketedItem] = []
    for li in ledger:
        cls = classify_item_full(li.type, li.name)
        li.bucket = cls.bucket.value
        li.is_refundable = cls.is_refundable
        li.refund_policy = cls.refund_policy
        bucketed_items.append(BucketedItem(
            name=li.name,
            amount=Decimal(li.amount_cents) / Decimal(100),
            item_type=li.type,
            bucket=cls.bucket,
        ))

    county_name: str | None = getattr(prop, "county", None)
    tax_result: LedgerTaxBreakdown = resolve_taxes(bucketed_items, county_name, nights)
    total_tax = tax_result.total_tax

    for detail in tax_result.details:
        if detail.amount == Decimal("0.00"):
            continue
        ledger.append(LedgerLineItem(
            id=f"tax_{detail.tax_name[:30].replace(' ', '_').lower()}",
            name=detail.tax_name,
            amount_cents=_to_cents(detail.amount),
            is_taxable=False,
            is_refundable=False,
            refund_policy="follows_base",
            type="tax",
            bucket="tax",
        ))

    resolved_county = (county_name or "Fannin").strip().title()
    tax_breakdown = TaxBreakdown(
        state_sales_tax_cents=_to_cents(tax_result.state_sales_tax),
        county_sales_tax_cents=_to_cents(tax_result.county_sales_tax),
        lodging_tax_cents=_to_cents(tax_result.lodging_tax),
        hospitality_tax_cents=_to_cents(tax_result.hospitality_tax),
        dot_fee_cents=_to_cents(tax_result.dot_fee),
        total_tax_cents=_to_cents(tax_result.total_tax),
        county=resolved_county,
        details=[
            TaxBreakdownDetail(
                tax_name=d.tax_name,
                tax_rate=float(d.tax_rate),
                taxable_base_cents=_to_cents(d.taxable_base),
                amount_cents=_to_cents(d.amount),
                bucket=d.bucket.value,
            )
            for d in tax_result.details
            if d.amount > Decimal("0.00")
        ],
    )

    # 8. Pet Deposit (non-taxable, refundable)
    if payload.pets > 0:
        ledger.append(LedgerLineItem(
            id="pet_deposit",
            name="Refundable Pet Deposit",
            amount_cents=_to_cents(PET_DEPOSIT_AMOUNT),
            is_taxable=False,
            is_refundable=True,
            refund_policy="full",
            type="deposit",
            bucket="exempt",
        ))
        non_taxable_subtotal += PET_DEPOSIT_AMOUNT

    non_taxable_subtotal = _to_money(non_taxable_subtotal)
    grand_total = _to_money(taxable_subtotal + total_tax + non_taxable_subtotal)

    logger.info(
        "storefront_quote_generated",
        property=prop.name,
        nights=nights,
        line_item_count=len(ledger),
        grand_total=float(grand_total),
    )

    return StorefrontQuoteResponse(
        property_id=str(property_id),
        property_name=prop.name,
        nights=nights,
        line_items=ledger,
        summary=LedgerSummary(
            taxable_subtotal_cents=_to_cents(taxable_subtotal),
            tax_amount_cents=_to_cents(total_tax),
            non_taxable_subtotal_cents=_to_cents(non_taxable_subtotal),
            grand_total_cents=_to_cents(grand_total),
            tax_breakdown=tax_breakdown,
        ),
        available_enhancements=available_enhancements,
        debug_audit=audit,
        is_bookable=is_bookable,
    )


# ---------------------------------------------------------------------------
# Checkout (Stripe PaymentIntent) — now uses Universal Ledger internally
# ---------------------------------------------------------------------------


class CheckoutPayload(BaseModel):
    property_id: str
    arrival_date: date
    departure_date: date
    adults: int = Field(ge=1, le=24, default=2)
    children: int = Field(ge=0, le=24, default=0)
    pets: int = Field(ge=0, le=10, default=0)
    selected_add_on_ids: list[str] = Field(default_factory=list)
    promo_code: str = Field(default="", max_length=50)
    total_cents: int | None = None
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=20)
    address: str = Field(max_length=255, default="")
    city: str = Field(max_length=100, default="")
    state: str = Field(max_length=50, default="")
    zip_code: str = Field(max_length=20, default="")


class CheckoutResponse(BaseModel):
    status: str
    client_secret: str
    payment_intent_id: str
    amount_cents: int
    property_name: str
    nights: int


@router.post("/process", response_model=CheckoutResponse)
async def process_checkout(
    payload: CheckoutPayload,
    db: AsyncSession = Depends(get_db),
) -> CheckoutResponse:
    quote_req = StorefrontQuoteRequest(
        property_id=payload.property_id,
        arrival_date=payload.arrival_date,
        departure_date=payload.departure_date,
        adults=payload.adults,
        children=payload.children,
        pets=payload.pets,
        selected_add_on_ids=payload.selected_add_on_ids,
        promo_code=payload.promo_code,
    )
    ledger_quote = await storefront_quote(quote_req, db)
    amount_cents = ledger_quote.summary.grand_total_cents

    if amount_cents < 100:
        raise HTTPException(status_code=422, detail="Quote total is below minimum")

    guest_name = f"{payload.first_name} {payload.last_name}"

    logger.info(
        "storefront_checkout_initiated",
        property=ledger_quote.property_name,
        guest=guest_name,
        email=payload.email,
        nights=ledger_quote.nights,
        amount_cents=amount_cents,
    )

    try:
        intent = await stripe_payments.create_payment_intent(
            amount_cents=amount_cents,
            reservation_id=f"STOREFRONT-{payload.property_id}-{payload.arrival_date}",
            guest_email=payload.email,
            guest_name=guest_name,
            property_name=ledger_quote.property_name,
            extra_metadata={
                "property_id": ledger_quote.property_id,
                "arrival": str(payload.arrival_date),
                "departure": str(payload.departure_date),
                "adults": str(payload.adults),
                "children": str(payload.children),
                "pets": str(payload.pets),
                "phone": payload.phone,
                "source": "storefront_checkout",
            },
        )
    except Exception as e:
        logger.error("stripe_payment_intent_failed", error=str(e))
        raise HTTPException(status_code=502, detail="Payment processing unavailable")

    if ledger_quote.summary.tax_breakdown:
        await _cache_tax_snapshot(
            intent["payment_intent_id"],
            ledger_quote.summary.tax_breakdown,
        )

    await _cache_ledger_line_items(
        intent["payment_intent_id"],
        [li.model_dump() for li in ledger_quote.line_items],
    )

    return CheckoutResponse(
        status="payment_intent_created",
        client_secret=intent["client_secret"],
        payment_intent_id=intent["payment_intent_id"],
        amount_cents=amount_cents,
        property_name=ledger_quote.property_name,
        nights=ledger_quote.nights,
    )


@router.get("/stripe-key")
async def get_storefront_stripe_key() -> dict:
    key = settings.stripe_publishable_key
    if not key:
        raise HTTPException(503, "Stripe is not configured")
    return {"publishable_key": key}


@router.get("/addons")
async def get_property_addons(
    property_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    prop_uuid: UUID | None = None
    try:
        prop_uuid = UUID(property_id)
    except ValueError:
        result = await db.execute(
            select(Property).where(Property.slug == property_id).limit(1)
        )
        prop = result.scalars().first()
        if prop:
            prop_uuid = prop.id

    if prop_uuid is None:
        return []

    stmt = (
        select(VRSAddOn)
        .where(VRSAddOn.is_active.is_(True))
        .where(
            (VRSAddOn.property_id == prop_uuid)
            | (VRSAddOn.scope == VRSAddOnScope.GLOBAL)
        )
        .order_by(VRSAddOn.name)
    )
    rows = (await db.execute(stmt)).scalars().all()

    return [
        {
            "id": str(addon.id),
            "name": addon.name,
            "description": addon.description or "",
            "price": float(addon.price),
            "pricing_model": addon.pricing_model.value if addon.pricing_model else "flat_fee",
            "scope": addon.scope.value if addon.scope else "global",
        }
        for addon in rows
    ]


class ConfirmationResponse(BaseModel):
    status: str
    confirmation_code: str | None = None
    property_name: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    nights: int | None = None
    guest_name: str | None = None
    total_amount: float | None = None
    payment_intent_id: str


@router.get("/confirmation/{payment_intent_id}", response_model=ConfirmationResponse)
async def get_confirmation(
    payment_intent_id: str,
    db: AsyncSession = Depends(get_db),
) -> ConfirmationResponse:
    from sqlalchemy import text as sql_text
    from backend.models.reservation import Reservation
    from backend.models.property import Property as Prop

    row = await db.execute(
        sql_text(
            "SELECT id, confirmation_code, property_id, check_in_date, check_out_date, "
            "guest_name, total_amount, status "
            "FROM reservations "
            "WHERE price_breakdown->>'stripe_payment_intent_id' = :pi "
            "LIMIT 1"
        ),
        {"pi": payment_intent_id},
    )
    res = row.fetchone()

    if res is None:
        stripe_client = StripePayments()
        try:
            pi_status = stripe_client.retrieve_payment_intent_status(payment_intent_id)
        except Exception:
            pi_status = "unknown"

        return ConfirmationResponse(
            status=f"processing ({pi_status})",
            payment_intent_id=payment_intent_id,
        )

    prop = await db.get(Prop, res.property_id)
    nights = (res.check_out_date - res.check_in_date).days if res.check_in_date and res.check_out_date else None

    return ConfirmationResponse(
        status=res.status,
        confirmation_code=res.confirmation_code,
        property_name=prop.name if prop else None,
        check_in=res.check_in_date.isoformat() if res.check_in_date else None,
        check_out=res.check_out_date.isoformat() if res.check_out_date else None,
        nights=nights,
        guest_name=res.guest_name,
        total_amount=float(res.total_amount) if res.total_amount else None,
        payment_intent_id=payment_intent_id,
    )
