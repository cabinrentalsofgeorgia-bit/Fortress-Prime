"""Sovereign Fast Quote pricing service."""

from __future__ import annotations

import operator
import structlog
from collections import OrderedDict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable
from uuid import UUID

from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.financial_primitives import Fee, PropertyFee, PropertyTax, Tax
from backend.models.learned_rule import LearnedRule
from backend.models.pricing import QuoteLineItem, QuoteRequest, QuoteResponse
from backend.models.pricing_override import PricingOverride
from backend.models.property import Property
from backend.services.quote_builder import QuoteBuilderError, build_local_rent_quote
from backend.services.sovereign_yield_authority import SovereignYieldAuthority

_learned_rules_logger = structlog.get_logger("learned_rules_engine")


TWO_PLACES = Decimal("0.01")
ONE_HUNDRED = Decimal("100.00")

# Processing Fee rules — verified against Streamline vault data (2026):
#   Non-VRBO:  6% of taxable base (rent + cleaning + party fees)
#   VRBO/HA:   $59.95 flat cap  ("Processing Fee all but HA/VRBO" in Streamline)
# The storefront checkout only handles non-VRBO bookings; VRBO reservations
# arrive via Streamline (booking_source='HA-OLB') and are capped server-side.
PROCESSING_FEE_RATE = Decimal("6.000")
PROCESSING_FEE_VRBO_CAP = Decimal("59.95")
_VRBO_SOURCES = frozenset(["ha-olb", "vrbo", "homeaway", "ha"])


def calculate_processing_fee(taxable_base: Decimal, booking_source: str | None = None) -> Decimal:
    """Return the correct Processing Fee given taxable base and booking source.

    Non-VRBO: 6% of taxable base (no cap).
    VRBO/HA:  min(6% of taxable_base, $59.95) — but in practice Streamline
              applies the cap before the reservation reaches us.
    """
    raw = _to_money(taxable_base * PROCESSING_FEE_RATE / ONE_HUNDRED)
    if (booking_source or "").lower().strip() in _VRBO_SOURCES:
        return min(raw, PROCESSING_FEE_VRBO_CAP)
    return raw


# Fees excluded from the taxable base used for Processing Fee and County/State Tax.
# ADW and DOT Tax are non-taxable per Streamline invoice structure.
_NONTAXABLE_FEE_PATTERNS = frozenset(["damage waiver", "dot tax"])


def _is_nontaxable_fee(name: str) -> bool:
    lower = (name or "").lower()
    return any(p in lower for p in _NONTAXABLE_FEE_PATTERNS)


def _is_dot_tax_fee(name: str) -> bool:
    return "dot tax" in (name or "").lower()


class PricingError(ValueError):
    """Raised when a quote request cannot be satisfied."""


def _to_money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


async def _load_overlapping_pricing_overrides(
    db: AsyncSession,
    property_id: UUID,
    check_in: date,
    check_out: date,
) -> list[PricingOverride]:
    stmt = (
        select(PricingOverride)
        .where(PricingOverride.property_id == property_id)
        .where(PricingOverride.start_date < check_out)
        .where(PricingOverride.end_date >= check_in)
        .order_by(PricingOverride.start_date.asc(), PricingOverride.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def _load_applicable_taxes(
    db: AsyncSession,
    property_id: UUID,
) -> list[Tax]:
    stmt = (
        select(Tax)
        .join(PropertyTax, PropertyTax.tax_id == Tax.id)
        .where(PropertyTax.property_id == property_id)
        .where(PropertyTax.is_active.is_(True))
        .where(Tax.is_active.is_(True))
        .order_by(Tax.name.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def _load_applicable_fees(
    db: AsyncSession,
    property_id: UUID,
) -> list[Fee]:
    stmt = (
        select(Fee)
        .join(PropertyFee, PropertyFee.fee_id == Fee.id)
        .where(PropertyFee.property_id == property_id)
        .where(PropertyFee.is_active.is_(True))
        .where(Fee.is_active.is_(True))
        .order_by(Fee.name.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def _load_optional_fee_ids(db: AsyncSession) -> set[str]:
    """Raw SQL lookup for optional fee IDs, bypassing ORM metadata cache.

    If a fee's ``is_optional`` column is TRUE in the database, it MUST be
    excluded from the base quote unless its UUID appears in
    ``selected_optional_ids`` — same gatekeeper rule as ``storefront_checkout``.
    """
    try:
        rows = (
            await db.execute(
                sql_text("SELECT id::text FROM fees WHERE is_optional = true")
            )
        ).fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()


def _fee_name_matches_check_in_out_intercept(name: str | None) -> bool:
    """Mirror storefront_checkout hard-intercept for early/late check-in/out."""
    fee_name_lower = (name or "").lower()
    return (
        "check-in" in fee_name_lower
        or "check-out" in fee_name_lower
        or "early" in fee_name_lower
        or "late" in fee_name_lower
    )


def _matching_override_for_night(
    stay_date: date,
    overrides: Iterable[PricingOverride],
) -> PricingOverride | None:
    match: PricingOverride | None = None
    for override in overrides:
        if override.start_date <= stay_date <= override.end_date:
            if match is not None and match.id != override.id:
                raise PricingError(
                    f"Conflicting pricing overrides found for {stay_date.isoformat()}"
                )
            match = override
    return match


def _build_override_line_items(
    nightly_breakdown: Iterable[tuple[date, Decimal]],
    overrides: list[PricingOverride],
) -> tuple[list[QuoteLineItem], Decimal]:
    applied_amounts: "OrderedDict[str, tuple[PricingOverride, Decimal]]" = OrderedDict()
    total_adjustment = Decimal("0.00")

    for stay_date, nightly_rate in nightly_breakdown:
        override = _matching_override_for_night(stay_date, overrides)
        if override is None:
            continue
        adjustment_ratio = Decimal(str(override.adjustment_percentage)) / ONE_HUNDRED
        nightly_adjustment = _to_money(nightly_rate * adjustment_ratio)
        current_override, current_amount = applied_amounts.get(
            str(override.id),
            (override, Decimal("0.00")),
        )
        applied_amounts[str(override.id)] = (
            current_override,
            current_amount + nightly_adjustment,
        )
        total_adjustment += nightly_adjustment

    line_items: list[QuoteLineItem] = []
    for override, amount in applied_amounts.values():
        rounded_amount = _to_money(amount)
        adjustment_percentage = _to_money(Decimal(str(override.adjustment_percentage)))
        if rounded_amount == Decimal("0.00"):
            continue
        line_items.append(
            QuoteLineItem(
                description=(
                    "Yield Adjustment Discount "
                    f"({adjustment_percentage}% {override.start_date.isoformat()} to {override.end_date.isoformat()})"
                    if rounded_amount < 0
                    else "Yield Adjustment Premium "
                    f"(+{adjustment_percentage}% {override.start_date.isoformat()} to {override.end_date.isoformat()})"
                ),
                amount=rounded_amount,
                type="discount" if rounded_amount < 0 else "fee",
            )
        )

    return line_items, _to_money(total_adjustment)


def _build_fee_line_items(
    *,
    pets: int,
    fees: list[Fee],
    base_rent: Decimal = Decimal("0.00"),
    nights: int = 1,
    pct_fee_cache: dict[str, dict] | None = None,
    selected_optional_ids: set[str] | None = None,
    optional_fee_ids: set[str] | None = None,
) -> tuple[list[QuoteLineItem], Decimal, Decimal]:
    """Two-pass fee builder: flat fees first, then percentage fees on taxable base.

    The Processing Fee (percentage type) is calculated on the taxable base:
    (base_rent + cleaning + party fees). ADW and DOT Tax are excluded from the
    taxable base, matching Streamline's exact invoice structure.
    DOT Tax flat_amount is a per-night rate multiplied by nights.
    Optional fees are excluded unless their ID is in selected_optional_ids.
    The optional_fee_ids set (from raw SQL) takes precedence over ORM attributes
    to prevent metadata-cache leaks.

    Returns (line_items, total_fees, taxable_flat_total).
    """
    opt_ids = optional_fee_ids or set()
    # Mandatory ledger rows: exclude optional (DB + ORM), pet-only rows used when
    # pets>0, and check-in/out lines handled by the hard-intercept below.
    standard_fees = [
        fee for fee in fees
        if not bool(fee.is_pet_fee)
        and str(fee.id) not in opt_ids
        and not getattr(fee, "is_optional", False)
        and not _fee_name_matches_check_in_out_intercept(fee.name)
    ]
    if not standard_fees:
        raise PricingError("Property fee ledger is missing")

    cache = pct_fee_cache or {}
    selected_opt = selected_optional_ids or set()
    line_items: list[QuoteLineItem] = []
    total_fees = Decimal("0.00")
    flat_fee_total = Decimal("0.00")
    taxable_flat_total = Decimal("0.00")
    deferred_pct_fees: list[tuple] = []

    # Pass 1 — flat fees (Cleaning, ADW, etc.; optional fees only if selected)
    for fee in fees:
        if bool(fee.is_pet_fee) and pets < 1:
            continue

        fee_id_str = str(fee.id)

        # Hard intercept: Streamline-style early/late check-in/out must never be
        # mandatory; only include when explicitly selected (matches storefront).
        if _fee_name_matches_check_in_out_intercept(fee.name):
            if fee_id_str not in selected_opt:
                continue

        is_optional = fee_id_str in opt_ids or getattr(fee, "is_optional", False)
        if is_optional and fee_id_str not in selected_opt:
            continue

        fee_type = getattr(fee, "fee_type", None)
        pct_rate = getattr(fee, "percentage_rate", None)

        if fee_type is None and str(fee.id) in cache:
            fee_type = cache[str(fee.id)]["fee_type"]
            pct_rate = cache[str(fee.id)]["percentage_rate"]

        fee_type = fee_type or "flat"

        if fee_type == "percentage" and pct_rate is not None:
            deferred_pct_fees.append((fee, Decimal(str(pct_rate))))
            continue

        raw_amount = Decimal(str(fee.flat_amount))
        if _is_dot_tax_fee(fee.name):
            amount = _to_money(raw_amount * nights)
        else:
            amount = _to_money(raw_amount)
        if amount == Decimal("0.00"):
            continue
        total_fees += amount
        flat_fee_total += amount
        if not _is_nontaxable_fee(fee.name):
            taxable_flat_total += amount
        line_items.append(
            QuoteLineItem(
                description=fee.name,
                amount=amount,
                type="fee",
            )
        )

    # Pass 2 — percentage fees on taxable base only (rent + cleaning + party fees).
    # ADW and DOT Tax are excluded from pct_base per Streamline invoice structure.
    pct_base = base_rent + taxable_flat_total
    for fee, rate in deferred_pct_fees:
        amount = _to_money(pct_base * rate / ONE_HUNDRED)
        if amount == Decimal("0.00"):
            continue
        total_fees += amount
        line_items.append(
            QuoteLineItem(
                description=fee.name,
                amount=amount,
                type="fee",
            )
        )

    return line_items, _to_money(total_fees), _to_money(taxable_flat_total)


def _build_tax_line_items(
    *,
    tax_base: Decimal,
    taxes: list[Tax],
) -> tuple[list[QuoteLineItem], Decimal]:
    if not taxes:
        raise PricingError("Property tax ledger is missing")

    line_items: list[QuoteLineItem] = []
    total_taxes = Decimal("0.00")
    for tax in taxes:
        rate = Decimal(str(tax.percentage_rate))
        tax_amount = _to_money(tax_base * (rate / ONE_HUNDRED))
        if tax_amount == Decimal("0.00"):
            continue
        total_taxes += tax_amount
        line_items.append(
            QuoteLineItem(
                description=tax.name,
                amount=tax_amount,
                type="tax",
            )
        )
    return line_items, _to_money(total_taxes)


_CONDITION_OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


def _evaluate_trigger_condition(
    condition: dict,
    context: dict,
) -> bool:
    """
    Evaluate a learned rule's trigger_condition against request context.

    Condition format: {"field": "op value"} e.g. {"days_to_arrival": ">30", "pets": ">0"}
    Empty condition = always matches (global rule).
    """
    if not condition:
        return True

    for field, expr in condition.items():
        actual = context.get(field)
        if actual is None:
            return False

        expr_str = str(expr).strip()
        matched_op = None
        for op_str in sorted(_CONDITION_OPS, key=len, reverse=True):
            if expr_str.startswith(op_str):
                matched_op = op_str
                break

        if matched_op is None:
            try:
                return float(actual) == float(expr_str)
            except (ValueError, TypeError):
                return False

        threshold_str = expr_str[len(matched_op):].strip()
        try:
            return _CONDITION_OPS[matched_op](float(actual), float(threshold_str))
        except (ValueError, TypeError):
            return False

    return True


async def _load_active_learned_rules(
    db: AsyncSession,
    property_id: UUID,
) -> list[LearnedRule]:
    stmt = (
        select(LearnedRule)
        .where(LearnedRule.status == "active")
        .where(
            (LearnedRule.property_id == property_id)
            | (LearnedRule.property_id.is_(None))
        )
        .order_by(LearnedRule.confidence_score.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


def _apply_learned_rules(
    rules: list[LearnedRule],
    subtotal: Decimal,
    context: dict,
) -> tuple[list[QuoteLineItem], Decimal]:
    line_items: list[QuoteLineItem] = []
    total_adjustment = Decimal("0.00")

    for rule in rules:
        if not _evaluate_trigger_condition(rule.trigger_condition or {}, context):
            continue

        if rule.adjustment_type == "flat_fee":
            amount = _to_money(Decimal(str(rule.adjustment_value)))
        elif rule.adjustment_type == "percentage":
            amount = _to_money(subtotal * Decimal(str(rule.adjustment_value)))
        else:
            continue

        if amount == Decimal("0.00"):
            continue

        total_adjustment += amount
        display_name = (rule.rule_name or "learned_adjustment").replace("_", " ").title()
        line_items.append(
            QuoteLineItem(
                description=f"{display_name} (AI Learned)",
                amount=amount,
                type="discount" if amount < 0 else "fee",
            )
        )

        _learned_rules_logger.info(
            "learned_rule_applied",
            rule_id=str(rule.id),
            rule_name=rule.rule_name,
            adjustment=float(amount),
            confidence=rule.confidence_score,
        )

    return line_items, _to_money(total_adjustment)


async def calculate_fast_quote(
    request: QuoteRequest,
    db: AsyncSession,
) -> QuoteResponse:
    nights = (request.check_out - request.check_in).days
    if nights < 1:
        raise PricingError("check_out must be after check_in")

    property_record = await db.get(Property, request.property_id)
    if property_record is None or not property_record.is_active:
        raise PricingError("Property not found")

    yield_violations = await SovereignYieldAuthority.validate_stay_constraints(
        db,
        request.property_id,
        request.check_in,
        request.check_out,
    )
    if yield_violations:
        raise PricingError("; ".join(yield_violations))

    total_guests = request.adults + request.children
    is_bookable = total_guests <= int(property_record.max_guests or 0)
    try:
        rent_quote = await build_local_rent_quote(
            request.property_id,
            request.check_in,
            request.check_out,
            db,
        )
    except QuoteBuilderError as exc:
        raise PricingError(str(exc)) from exc

    fees = await _load_applicable_fees(db, request.property_id)
    taxes = await _load_applicable_taxes(db, request.property_id)
    overrides = await _load_overlapping_pricing_overrides(
        db,
        request.property_id,
        request.check_in,
        request.check_out,
    )
    override_line_items, total_adjustment = _build_override_line_items(
        rent_quote.nightly_breakdown,
        overrides,
    )
    adjusted_rent = _to_money(rent_quote.rent + total_adjustment)
    optional_fee_ids = await _load_optional_fee_ids(db)
    fee_line_items, total_fees, taxable_flat_fee_total = _build_fee_line_items(
        pets=request.pets,
        fees=fees,
        base_rent=adjusted_rent,
        nights=nights,
        optional_fee_ids=optional_fee_ids,
        selected_optional_ids=set(request.selected_add_on_ids),
    )

    # --- Godhead Phase 3: Self-Healing Learned Rules ---
    learned_rules = await _load_active_learned_rules(db, request.property_id)
    days_to_arrival = (request.check_in - date.today()).days
    rule_context = {
        "days_to_arrival": days_to_arrival,
        "nights": nights,
        "guests": total_guests,
        "adults": request.adults,
        "children": request.children,
        "pets": request.pets,
    }
    pre_tax_subtotal = _to_money(adjusted_rent + total_fees)
    learned_line_items, learned_adjustment = _apply_learned_rules(
        learned_rules,
        pre_tax_subtotal,
        rule_context,
    )
    pre_tax_subtotal = _to_money(pre_tax_subtotal + learned_adjustment)

    # Tax base = rent + cleaning + party fees only.
    # ADW, DOT Tax, and Processing Fee are excluded per Streamline invoice structure.
    tax_base = _to_money(adjusted_rent + taxable_flat_fee_total)
    tax_line_items, total_tax_amount = _build_tax_line_items(
        tax_base=tax_base,
        taxes=taxes,
    )
    total_amount = _to_money(pre_tax_subtotal + total_tax_amount)

    nightly_rate = (rent_quote.rent / Decimal(nights)).quantize(TWO_PLACES) if nights else Decimal("0.00")
    line_items = [
        QuoteLineItem(
            description=f"{nights} night stay @ ${nightly_rate} / night",
            amount=rent_quote.rent,
            type="rent",
        ),
        *override_line_items,
        *fee_line_items,
        *learned_line_items,
        *tax_line_items,
    ]

    return QuoteResponse(
        property_id=property_record.id,
        currency="USD",
        line_items=line_items,
        total_amount=total_amount,
        is_bookable=is_bookable,
    )
