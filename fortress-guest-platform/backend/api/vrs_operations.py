from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from html import escape
from typing import Any, Literal
from uuid import UUID

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import require_operator_manager_admin
from backend.models import Guest, GuestQuote, GuestQuoteStatus, Property, Reservation, ReservationHold
from backend.models.openshell_audit import OpenShellAuditLog
from backend.models.parity_audit import ParityAudit
from backend.services.email_service import is_email_configured, send_email
from backend.services.hold_service import create_inventory_hold
from backend.services.reservation_engine import ReservationEngine
from backend.models.staff import StaffUser
from backend.services.openshell_audit import record_audit_event

router = APIRouter()
reservation_engine = ReservationEngine()

CONTROL_TOWER_BLOCKED_CAPABILITIES = [
    "create_hold_without_staff_approval",
    "create_payment_intent_without_staff_approval",
    "convert_hold_to_reservation",
    "charge_or_refund_payment",
    "write_streamline",
    "publish_public_content",
    "change_cloudflare_dns_or_tunnel",
    "mutate_legacy_drupal_or_aws",
]
PROOF_LANE_ALLOWED_EMAIL_DOMAINS = {
    "cabin-rentals-of-georgia.com",
    "crog-ai.com",
    "garyknight.com",
}


@router.get("/operations/ping")
async def vrs_operations_ping():
    return {"status": "ok", "service": "vrs_operations"}


class QuoteBookingRecord(BaseModel):
    id: str
    kind: Literal["quote", "hold", "reservation", "parity"]
    title: str
    status: str
    property_id: str | None = None
    property_name: str | None = None
    guest_label: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    total_amount: float | None = None
    payment_state: str | None = None
    parity_status: str | None = None
    stop_level: Literal["clear", "inspect", "stop"]
    stop_reason: str
    href: str
    created_at: str | None = None
    updated_at: str | None = None
    assigned_to: str | None = None
    escalated: bool = False
    reviewed: bool = False
    dismissed: bool = False
    last_action: str | None = None
    last_action_by: str | None = None
    last_action_at: str | None = None
    last_note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuoteBookingSafeguard(BaseModel):
    id: str
    label: str
    status: Literal["locked", "clear", "attention"]
    detail: str
    href: str | None = None


class QuoteBookingControlTowerResponse(BaseModel):
    summary: dict[str, int]
    safeguards: list[QuoteBookingSafeguard]
    quotes: list[QuoteBookingRecord]
    holds: list[QuoteBookingRecord]
    reservations: list[QuoteBookingRecord]
    parity_audits: list[QuoteBookingRecord]
    generated_at: str


class QuoteBookingActionRequest(BaseModel):
    action: Literal["claim", "mark_reviewed", "escalate", "dismiss", "note"]
    note: str | None = Field(default=None, max_length=1000)
    assignee: str | None = Field(default=None, max_length=320)


class QuoteBookingActionResponse(BaseModel):
    ok: bool
    kind: str
    id: str
    action: str
    audit_id: str | None = None
    audit_hash: str | None = None
    message: str


class QuoteBookingSendRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class QuoteBookingSendResponse(BaseModel):
    ok: bool
    quote_id: str
    guest_email: str
    audit_id: str | None = None
    audit_hash: str | None = None
    message: str


class QuoteBookingHoldRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class QuoteBookingHoldResponse(BaseModel):
    ok: bool
    quote_id: str
    hold_id: str
    expires_at: str
    audit_id: str | None = None
    audit_hash: str | None = None
    message: str


class QuoteBookingReservationRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class QuoteBookingReservationResponse(BaseModel):
    ok: bool
    quote_id: str
    hold_id: str
    reservation_id: str
    confirmation_code: str
    audit_id: str | None = None
    audit_hash: str | None = None
    message: str


class QuoteBookingProofLaneRequest(BaseModel):
    guest_email: str | None = Field(default=None, max_length=320)
    property_id: UUID | None = None
    amount_cents: int = Field(default=100, ge=50, le=5000)
    mark_reviewed: bool = True


class QuoteBookingProofLaneResponse(BaseModel):
    ok: bool
    quote: QuoteBookingRecord
    audit_id: str | None = None
    audit_hash: str | None = None
    stripe_mode: Literal["test"]
    message: str


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _money(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _uuid(value: UUID | str | None) -> str | None:
    return str(value) if value is not None else None


def _guest_name(first_name: str | None, last_name: str | None, fallback: str | None = None) -> str | None:
    name = f"{first_name or ''} {last_name or ''}".strip()
    return name or fallback


def _money_decimal_from_cents(amount_cents: int) -> Decimal:
    return (Decimal(amount_cents) / Decimal("100")).quantize(Decimal("0.01"))


def _display_money(value: Any) -> str:
    money = _money(value)
    if money is None:
        return "the quoted total"
    return f"${money:,.2f}"


def _display_date(value: Any) -> str:
    if value is None:
        return "TBD"
    if hasattr(value, "strftime"):
        return value.strftime("%b %-d, %Y")
    return str(value)


def _quote_guest_names(quote: GuestQuote) -> tuple[str, str]:
    guest_name = (quote.guest_name or "").strip()
    parts = guest_name.split()
    if not parts:
        return "Guest", "Quote"
    if len(parts) == 1:
        return parts[0][:100], "Quote"
    return parts[0][:100], " ".join(parts[1:])[:100]


def _stripe_secret_mode() -> Literal["test", "live", "unknown"]:
    key = settings.stripe_secret_key or ""
    if key.startswith("sk_test_"):
        return "test"
    if key.startswith("sk_live_"):
        return "live"
    return "unknown"


def _resolve_proof_lane_email(current_user: StaffUser, requested_email: str | None) -> str:
    email = (requested_email or current_user.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="A staff/test email is required for proof lane quotes")

    domain = email.rsplit("@", 1)[-1]
    current_user_email = (current_user.email or "").strip().lower()
    if email == current_user_email or domain in PROOF_LANE_ALLOWED_EMAIL_DOMAINS:
        return email

    raise HTTPException(status_code=422, detail="Proof lane quotes can only be sent to staff/test email domains")


async def _resolve_proof_lane_property(db: AsyncSession, property_id: UUID | None) -> Property:
    if property_id:
        prop = await db.get(Property, property_id)
        if prop is None:
            raise HTTPException(status_code=404, detail="Proof lane property not found")
        return prop

    result = await db.execute(
        select(Property).where(Property.is_active.is_(True)).order_by(Property.name.asc()).limit(1)
    )
    prop = result.scalar_one_or_none()
    if prop is None:
        raise HTTPException(status_code=422, detail="No active property is available for the proof lane")
    return prop


def _create_proof_lane_payment_link(
    *,
    quote_id: str,
    amount_cents: int,
    property_id: str,
    property_name: str,
    guest_email: str,
) -> dict[str, Any]:
    if _stripe_secret_mode() != "test":
        raise HTTPException(status_code=423, detail="Proof lane payment links require Stripe test mode")
    stripe.api_key = settings.stripe_secret_key
    if not stripe.api_key:
        raise HTTPException(status_code=503, detail="Stripe is not configured")

    product = stripe.Product.create(
        name=f"CROG-VRS Proof Lane - {property_name}",
        description="Internal CROG-VRS quote-to-booking proof lane. Stripe test mode only.",
        metadata={
            "type": "crog_vrs_proof_lane",
            "quote_id": quote_id,
            "property_id": property_id,
            "safe_internal_only": "true",
        },
    )
    price = stripe.Price.create(
        product=product.id,
        unit_amount=amount_cents,
        currency="usd",
    )
    link = stripe.PaymentLink.create(
        line_items=[{"price": price.id, "quantity": 1}],
        payment_method_types=["card"],
        metadata={
            "type": "crog_vrs_proof_lane",
            "quote_id": quote_id,
            "property_id": property_id,
            "guest_email": guest_email,
            "safe_internal_only": "true",
        },
    )
    return {
        "payment_link_url": link.url,
        "payment_link_id": link.id,
        "product_id": product.id,
        "price_id": price.id,
    }


def _hold_stop_level(hold: ReservationHold, now: datetime) -> tuple[Literal["clear", "inspect", "stop"], str]:
    status = (hold.status or "").lower()
    if status == "active" and hold.expires_at and hold.expires_at < now:
        return "stop", "Active hold is past its expiration window."
    if status == "active" and not hold.payment_intent_id:
        return "inspect", "Active hold has no Stripe PaymentIntent attached."
    if status == "converted":
        return "clear", "Hold converted into a local reservation."
    if status == "expired":
        return "inspect", "Hold expired before conversion."
    return "inspect", "Hold requires staff review before any guest or payment action."


def _quote_stop_level(quote: GuestQuote, now_naive: datetime) -> tuple[Literal["clear", "inspect", "stop"], str]:
    status = str(quote.status or "").lower()
    if status == GuestQuoteStatus.PENDING and quote.expires_at and quote.expires_at < now_naive:
        return "stop", "Pending quote is expired; do not send or reuse."
    if status == GuestQuoteStatus.ACCEPTED:
        return "clear", "Guest accepted this quote; verify hold/reservation conversion."
    if status == GuestQuoteStatus.PENDING:
        return "inspect", "Guest-facing quote delivery remains staff-approved."
    if status == GuestQuoteStatus.EXPIRED:
        return "inspect", "Expired quote retained for audit and replay context."
    return "inspect", "Quote status needs staff review."


def _quote_parity_status(quote: GuestQuote) -> str:
    snapshot = quote.source_snapshot if isinstance(quote.source_snapshot, dict) else {}
    raw = (
        snapshot.get("parity_status")
        or snapshot.get("drift_status")
        or snapshot.get("quote_parity_status")
        or "not_checked"
    )
    return str(raw or "not_checked")


def _check(label: str, status: str, detail: str) -> dict[str, str]:
    return {"label": label, "status": status, "detail": detail}


async def _quote_overlap_counts(
    db: AsyncSession,
    quote: GuestQuote,
    now: datetime,
) -> tuple[int, int, int, int]:
    if not quote.property_id or not quote.check_in or not quote.check_out:
        return 0, 0, 0, 0

    hold_rows = await db.execute(
        select(ReservationHold.id, ReservationHold.quote_snapshot)
        .where(
            ReservationHold.property_id == quote.property_id,
            ReservationHold.status == "active",
            ReservationHold.expires_at >= now,
            ReservationHold.check_in_date < quote.check_out,
            ReservationHold.check_out_date > quote.check_in,
        ),
    )
    own_hold_count = 0
    other_hold_count = 0
    for _hold_id, quote_snapshot in hold_rows.all():
        snapshot = quote_snapshot if isinstance(quote_snapshot, dict) else {}
        if str(snapshot.get("quote_ref") or "") == str(quote.id):
            own_hold_count += 1
        else:
            other_hold_count += 1

    reservation_rows = await db.execute(
        select(Reservation.id, Reservation.price_breakdown)
        .where(
            Reservation.property_id == quote.property_id,
            Reservation.status.notin_(["cancelled", "canceled", "no_show"]),
            Reservation.check_in_date < quote.check_out,
            Reservation.check_out_date > quote.check_in,
        ),
    )
    own_reservation_count = 0
    other_reservation_count = 0
    for _reservation_id, price_breakdown in reservation_rows.all():
        breakdown = price_breakdown if isinstance(price_breakdown, dict) else {}
        if str(breakdown.get("quote_ref") or "") == str(quote.id):
            own_reservation_count += 1
        else:
            other_reservation_count += 1

    return other_hold_count, other_reservation_count, own_hold_count, own_reservation_count


async def _quote_readiness_machine_state(
    db: AsyncSession,
    quote: GuestQuote,
    now: datetime,
    now_naive: datetime,
) -> dict[str, Any]:
    status = str(quote.status or "").lower()
    is_expired = bool(
        status == GuestQuoteStatus.EXPIRED
        or (status == GuestQuoteStatus.PENDING and quote.expires_at and quote.expires_at < now_naive)
    )
    has_stay = bool(quote.property_id and quote.check_in and quote.check_out)
    (
        hold_conflicts,
        reservation_conflicts,
        own_hold_count,
        own_reservation_count,
    ) = await _quote_overlap_counts(db, quote, now)
    payment_ready = bool((quote.stripe_payment_link_url or "").strip())
    parity_status = _quote_parity_status(quote)
    parity_upper = parity_status.upper()
    parity_passed = parity_upper in {"MATCH", "PASS", "PASSED", "CLEAR"}
    parity_missing = parity_upper in {"", "NONE", "NULL", "NOT_CHECKED", "UNKNOWN"}
    parity_drift = not parity_passed and not parity_missing
    availability_check_status = (
        "fail"
        if (not has_stay or hold_conflicts or reservation_conflicts)
        else "watch"
        if own_hold_count or own_reservation_count
        else "pass"
    )
    if not has_stay:
        availability_detail = "Property and stay dates are required."
    elif hold_conflicts or reservation_conflicts:
        availability_detail = f"{hold_conflicts} active hold conflict(s), {reservation_conflicts} reservation conflict(s)."
    elif own_reservation_count:
        availability_detail = f"{own_reservation_count} local reservation already exists for this quote."
    elif own_hold_count:
        availability_detail = f"{own_hold_count} active local hold already exists for this quote."
    else:
        availability_detail = "Availability is clear."

    checks = [
        _check(
            "Expiration",
            "fail" if is_expired else "pass",
            f"Expires {quote.expires_at.isoformat()}" if quote.expires_at else "No expiration timestamp found.",
        ),
        _check(
            "Availability",
            availability_check_status,
            availability_detail,
        ),
        _check(
            "Stripe handoff",
            "pass" if payment_ready else "fail",
            "Guest checkout payment link is attached." if payment_ready else "No guest checkout payment link is attached.",
        ),
        _check(
            "Streamline parity",
            "pass" if parity_passed else "fail" if parity_drift else "watch",
            f"Parity status: {parity_status}.",
        ),
    ]

    if is_expired:
        state = "expired"
        reasons = ["Quote is expired and cannot be sent or reused."]
    elif status != GuestQuoteStatus.PENDING:
        state = "blocked"
        reasons = [f"Quote status is {status}; send workflow only handles pending quotes."]
    elif not has_stay or hold_conflicts or reservation_conflicts:
        state = "hold_conflict"
        reasons = ["Availability is blocked by missing stay data or an overlapping hold/reservation."]
    elif own_reservation_count:
        state = "local_reservation_created"
        reasons = ["A staff-approved local reservation already exists for this quote."]
    elif own_hold_count:
        state = "local_hold_created"
        reasons = ["A staff-approved local checkout hold already exists for this quote."]
    elif not payment_ready:
        state = "missing_payment_handoff"
        reasons = ["Stripe payment handoff is missing."]
    elif parity_drift:
        state = "parity_drift"
        reasons = [f"Streamline parity is {parity_status}."]
    elif parity_missing:
        state = "parity_missing"
        reasons = ["Streamline parity has not been verified."]
    else:
        state = "machine_ready"
        reasons = ["Expiration, availability, payment handoff, and parity checks passed."]

    return {
        "readiness_machine_state": state,
        "readiness_reasons": reasons,
        "readiness_checks": checks,
        "hold_conflicts": hold_conflicts,
        "reservation_conflicts": reservation_conflicts,
        "local_hold_count": own_hold_count,
        "local_reservation_count": own_reservation_count,
        "parity_status": parity_status,
    }


def _finalize_quote_readiness(quotes: list[QuoteBookingRecord]) -> dict[str, int]:
    counts = {
        "ready_quotes": 0,
        "blocked_quotes": 0,
        "expired_quotes": 0,
        "parity_drift_quotes": 0,
        "parity_missing_quotes": 0,
        "missing_payment_handoff_quotes": 0,
        "hold_conflict_quotes": 0,
        "local_hold_created_quotes": 0,
        "local_reservation_created_quotes": 0,
        "quotes_needing_staff_approval": 0,
    }
    stop_states = {
        "blocked",
        "expired",
        "parity_drift",
        "parity_missing",
        "missing_payment_handoff",
        "hold_conflict",
    }

    for record in quotes:
        machine_state = str(record.metadata.get("readiness_machine_state") or "blocked")
        reasons = list(record.metadata.get("readiness_reasons") or [])
        if machine_state == "machine_ready":
            if record.reviewed:
                state = "ready"
                label = "Ready"
                reasons = ["All readiness checks passed and staff approval is recorded."]
                record.stop_level = "clear"
                record.stop_reason = "Quote is ready for a controlled guest-send workflow."
            else:
                state = "needs_staff_approval"
                label = "Needs Approval"
                reasons = ["Staff approval has not been recorded."]
                record.stop_level = "inspect"
                record.stop_reason = "Quote passes machine checks but still needs staff approval."
        else:
            state = machine_state
            label = state.replace("_", " ").title()
            record.stop_level = "stop" if state in stop_states else "inspect"
            record.stop_reason = reasons[0] if reasons else "Quote readiness is blocked."

        record.metadata["readiness_state"] = state
        record.metadata["readiness_label"] = label
        record.metadata["readiness_reasons"] = reasons

        if state == "ready":
            counts["ready_quotes"] += 1
        if state in stop_states:
            counts["blocked_quotes"] += 1
        if state == "expired":
            counts["expired_quotes"] += 1
        if state == "parity_drift":
            counts["parity_drift_quotes"] += 1
        if state == "parity_missing":
            counts["parity_missing_quotes"] += 1
        if state == "missing_payment_handoff":
            counts["missing_payment_handoff_quotes"] += 1
        if state == "hold_conflict":
            counts["hold_conflict_quotes"] += 1
        if state == "local_hold_created":
            counts["local_hold_created_quotes"] += 1
        if state == "local_reservation_created":
            counts["local_reservation_created_quotes"] += 1
        if state == "needs_staff_approval":
            counts["quotes_needing_staff_approval"] += 1

    return counts


def _reservation_stop_level(reservation: Reservation) -> tuple[Literal["clear", "inspect", "stop"], str]:
    if not reservation.streamline_reservation_id:
        return "inspect", "Local reservation has not been linked to a Streamline reservation id."
    if reservation.balance_due and _money(reservation.balance_due) not in (None, 0.0):
        return "inspect", "Reservation still shows a balance due."
    return "clear", "Local reservation and Streamline reference are present."


def _parity_stop_level(audit: ParityAudit) -> tuple[Literal["clear", "inspect", "stop"], str]:
    status = str(audit.status or "").upper()
    if status == "MATCH":
        return "clear", "Local ledger total matches Streamline."
    if status == "MINOR_DRIFT":
        return "inspect", "Minor quote drift needs staff review before repeating the pattern."
    return "stop", "Critical quote drift blocks autonomous quote-to-booking promotion."


async def _count(db: AsyncSession, stmt: Any) -> int:
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


def _control_resource_id(kind: str, item_id: str) -> str:
    return f"{kind}:{item_id}"


async def _apply_control_audits(db: AsyncSession, records: list[QuoteBookingRecord]) -> None:
    if not records:
        return

    by_resource_id = {_control_resource_id(record.kind, record.id): record for record in records}
    result = await db.execute(
        select(OpenShellAuditLog)
        .where(
            OpenShellAuditLog.resource_type == "quote_booking_control_item",
            OpenShellAuditLog.tool_name == "quote_booking_control_tower",
            OpenShellAuditLog.resource_id.in_(list(by_resource_id)),
        )
        .order_by(OpenShellAuditLog.created_at.asc())
        .limit(2000)
    )

    for audit in result.scalars().all():
        record = by_resource_id.get(audit.resource_id or "")
        if record is None:
            continue

        action = (audit.action or "").removeprefix("quote_booking.")
        metadata = audit.metadata_json or {}
        if action == "claim":
            record.assigned_to = str(metadata.get("assignee") or audit.actor_email or "")
        elif action == "escalate":
            record.escalated = True
        elif action == "mark_reviewed":
            record.reviewed = True
        elif action == "dismiss":
            record.dismissed = True
        elif action == "send_guest_quote":
            record.metadata["guest_quote_sent"] = True
        elif action == "create_local_hold":
            record.metadata["local_hold_created"] = True
            if metadata.get("hold_id"):
                record.metadata["local_hold_id"] = str(metadata.get("hold_id"))
        elif action == "convert_local_reservation":
            record.metadata["local_reservation_created"] = True
            if metadata.get("reservation_id"):
                record.metadata["local_reservation_id"] = str(metadata.get("reservation_id"))
            if metadata.get("confirmation_code"):
                record.metadata["confirmation_code"] = str(metadata.get("confirmation_code"))

        note = metadata.get("note")
        if isinstance(note, str) and note.strip():
            record.last_note = note.strip()

        record.last_action = action
        record.last_action_by = audit.actor_email
        record.last_action_at = _iso(audit.created_at)


def _parse_uuid(item_id: str) -> UUID:
    try:
        return UUID(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid Control Tower item id") from exc


async def _load_control_item(db: AsyncSession, kind: str, item_id: str):
    normalized = kind.strip().lower()
    model_by_kind = {
        "quote": GuestQuote,
        "hold": ReservationHold,
        "reservation": Reservation,
        "parity": ParityAudit,
    }
    model = model_by_kind.get(normalized)
    if model is None:
        raise HTTPException(status_code=404, detail="Unknown Control Tower item kind")

    row = await db.get(model, _parse_uuid(item_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Control Tower item not found")
    return normalized, row


async def _quote_control_record(
    db: AsyncSession,
    quote: GuestQuote,
    now: datetime,
    now_naive: datetime,
) -> QuoteBookingRecord:
    property_name: str | None = None
    property_slug: str | None = None
    if quote.property_id:
        property_record = await db.get(Property, quote.property_id)
        if property_record:
            property_name = property_record.name
            property_slug = property_record.slug

    stop_level, stop_reason = _quote_stop_level(quote, now_naive)
    readiness_metadata = await _quote_readiness_machine_state(db, quote, now, now_naive)
    title = property_name or quote.target_property_id or "Guest quote"
    record = QuoteBookingRecord(
        id=str(quote.id),
        kind="quote",
        title=title,
        status=str(quote.status),
        property_id=_uuid(quote.property_id) or quote.target_property_id,
        property_name=property_name or quote.target_property_id,
        guest_label=quote.guest_email or quote.guest_name,
        check_in=_iso(quote.check_in),
        check_out=_iso(quote.check_out),
        total_amount=_money(quote.total_amount),
        payment_state="payment_link_created" if quote.stripe_payment_link_url else "no_payment_link",
        parity_status=str(readiness_metadata.get("parity_status") or "not_checked"),
        stop_level=stop_level,
        stop_reason=stop_reason,
        href="/vrs/quotes",
        created_at=_iso(quote.created_at),
        updated_at=_iso(quote.updated_at),
        metadata={
            "campaign": quote.campaign,
            "property_slug": property_slug,
            "stripe_payment_link_id": quote.stripe_payment_link_id,
            "expires_at": _iso(quote.expires_at),
            **readiness_metadata,
        },
    )
    await _apply_control_audits(db, [record])
    _finalize_quote_readiness([record])
    return record


def _build_guest_quote_email(quote: GuestQuote, record: QuoteBookingRecord, payment_url: str) -> tuple[str, str, str]:
    property_name = record.property_name or record.title or "your selected cabin"
    amount = _display_money(quote.total_amount)
    check_in = _display_date(quote.check_in)
    check_out = _display_date(quote.check_out)
    nights = f"{quote.nights} night{'s' if quote.nights != 1 else ''}" if quote.nights else "your stay"
    subject = f"Your Cabin Rentals of Georgia quote for {property_name}"

    safe_property_name = escape(property_name)
    safe_amount = escape(amount)
    safe_check_in = escape(check_in)
    safe_check_out = escape(check_out)
    safe_nights = escape(nights)
    safe_payment_url = escape(payment_url, quote=True)

    html_body = f"""
<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#18181b;">
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
      <tr>
        <td align="center" style="padding:32px 16px;">
          <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="max-width:600px;background:#ffffff;border:1px solid #e4e4e7;border-radius:12px;overflow:hidden;">
            <tr>
              <td style="background:#18181b;padding:24px 28px;">
                <h1 style="margin:0;color:#ffffff;font-size:20px;font-weight:600;">Cabin Rentals of Georgia</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:28px;">
                <p style="margin:0 0 16px;font-size:16px;line-height:1.6;">Your cabin quote is ready.</p>
                <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin:0 0 24px;border-collapse:collapse;">
                  <tr><td style="padding:8px 0;color:#71717a;">Cabin</td><td style="padding:8px 0;text-align:right;font-weight:600;">{safe_property_name}</td></tr>
                  <tr><td style="padding:8px 0;color:#71717a;">Stay</td><td style="padding:8px 0;text-align:right;font-weight:600;">{safe_check_in} to {safe_check_out}</td></tr>
                  <tr><td style="padding:8px 0;color:#71717a;">Length</td><td style="padding:8px 0;text-align:right;font-weight:600;">{safe_nights}</td></tr>
                  <tr><td style="padding:8px 0;color:#71717a;">Total</td><td style="padding:8px 0;text-align:right;font-weight:700;">{safe_amount}</td></tr>
                </table>
                <p style="margin:0 0 24px;color:#52525b;font-size:15px;line-height:1.6;">Use the secure checkout link below to review and reserve the cabin.</p>
                <p style="margin:0 0 24px;">
                  <a href="{safe_payment_url}" style="display:inline-block;background:#18181b;color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:8px;font-weight:600;">Review and reserve</a>
                </p>
                <p style="margin:0;color:#71717a;font-size:13px;line-height:1.6;">If the button does not open, copy and paste this link into your browser:<br><a href="{safe_payment_url}" style="color:#2563eb;word-break:break-all;">{safe_payment_url}</a></p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    text_body = (
        "Your Cabin Rentals of Georgia quote is ready.\n\n"
        f"Cabin: {property_name}\n"
        f"Stay: {check_in} to {check_out}\n"
        f"Length: {nights}\n"
        f"Total: {amount}\n\n"
        f"Review and reserve: {payment_url}\n"
    )
    return subject, html_body, text_body


async def _record_quote_send_audit(
    *,
    db: AsyncSession,
    current_user: StaffUser,
    quote: GuestQuote,
    record: QuoteBookingRecord | None,
    outcome: str,
    note: str | None,
    detail: str,
) -> OpenShellAuditLog | None:
    readiness_state = None
    readiness_reasons: list[str] = []
    if record is not None:
        readiness_state = str(record.metadata.get("readiness_state") or "")
        readiness_reasons = [
            str(item)
            for item in (record.metadata.get("readiness_reasons") or [])
            if isinstance(item, str)
        ]

    return await record_audit_event(
        db=db,
        actor_id=str(current_user.id),
        actor_email=current_user.email,
        action="quote_booking.send_guest_quote",
        resource_type="quote_booking_control_item",
        resource_id=_control_resource_id("quote", str(quote.id)),
        purpose="Controlled staff-approved guest quote send.",
        tool_name="quote_booking_control_tower",
        redaction_status="metadata_only",
        model_route="human_staff",
        outcome=outcome,
        metadata_json={
            "quote_id": str(quote.id),
            "guest_email": quote.guest_email,
            "property_name": record.property_name if record else None,
            "total_amount": _money(quote.total_amount),
            "readiness_state": readiness_state,
            "readiness_reasons": readiness_reasons,
            "note": note,
            "detail": detail,
            "safe_send_only": True,
            "blocked_capabilities": CONTROL_TOWER_BLOCKED_CAPABILITIES,
        },
    )


async def _record_quote_hold_audit(
    *,
    db: AsyncSession,
    current_user: StaffUser,
    quote: GuestQuote,
    record: QuoteBookingRecord | None,
    outcome: str,
    note: str | None,
    detail: str,
    hold_id: str | None = None,
) -> OpenShellAuditLog | None:
    readiness_state = None
    readiness_reasons: list[str] = []
    if record is not None:
        readiness_state = str(record.metadata.get("readiness_state") or "")
        readiness_reasons = [
            str(item)
            for item in (record.metadata.get("readiness_reasons") or [])
            if isinstance(item, str)
        ]

    return await record_audit_event(
        db=db,
        actor_id=str(current_user.id),
        actor_email=current_user.email,
        action="quote_booking.create_local_hold",
        resource_type="quote_booking_control_item",
        resource_id=_control_resource_id("quote", str(quote.id)),
        purpose="Staff-approved local checkout hold from a ready guest quote.",
        tool_name="quote_booking_control_tower",
        redaction_status="metadata_only",
        model_route="human_staff",
        outcome=outcome,
        metadata_json={
            "quote_id": str(quote.id),
            "hold_id": hold_id,
            "guest_email": quote.guest_email,
            "property_id": str(quote.property_id) if quote.property_id else None,
            "total_amount": _money(quote.total_amount),
            "readiness_state": readiness_state,
            "readiness_reasons": readiness_reasons,
            "note": note,
            "detail": detail,
            "local_hold_only": True,
            "payment_intent_created": False,
            "payment_captured": False,
            "streamline_write": "blocked",
            "legacy_storefront": "untouched",
            "blocked_capabilities": CONTROL_TOWER_BLOCKED_CAPABILITIES,
        },
    )


async def _record_quote_reservation_audit(
    *,
    db: AsyncSession,
    current_user: StaffUser,
    quote: GuestQuote,
    record: QuoteBookingRecord | None,
    outcome: str,
    note: str | None,
    detail: str,
    hold_id: str | None = None,
    reservation_id: str | None = None,
    confirmation_code: str | None = None,
) -> OpenShellAuditLog | None:
    readiness_state = None
    readiness_reasons: list[str] = []
    if record is not None:
        readiness_state = str(record.metadata.get("readiness_state") or "")
        readiness_reasons = [
            str(item)
            for item in (record.metadata.get("readiness_reasons") or [])
            if isinstance(item, str)
        ]

    return await record_audit_event(
        db=db,
        actor_id=str(current_user.id),
        actor_email=current_user.email,
        action="quote_booking.convert_local_reservation",
        resource_type="quote_booking_control_item",
        resource_id=_control_resource_id("quote", str(quote.id)),
        purpose="Staff-approved local reservation conversion from a local quote hold.",
        tool_name="quote_booking_control_tower",
        redaction_status="metadata_only",
        model_route="human_staff",
        outcome=outcome,
        metadata_json={
            "quote_id": str(quote.id),
            "hold_id": hold_id,
            "reservation_id": reservation_id,
            "confirmation_code": confirmation_code,
            "guest_email": quote.guest_email,
            "property_id": str(quote.property_id) if quote.property_id else None,
            "total_amount": _money(quote.total_amount),
            "readiness_state": readiness_state,
            "readiness_reasons": readiness_reasons,
            "note": note,
            "detail": detail,
            "local_reservation_only": True,
            "reservation_status": "pending_payment",
            "payment_intent_created": False,
            "payment_captured": False,
            "streamline_write": "blocked",
            "legacy_storefront": "untouched",
            "blocked_capabilities": CONTROL_TOWER_BLOCKED_CAPABILITIES,
        },
    )


async def _find_active_quote_hold(db: AsyncSession, quote: GuestQuote) -> ReservationHold | None:
    if not quote.property_id or not quote.check_in or not quote.check_out:
        return None
    result = await db.execute(
        select(ReservationHold)
        .where(
            ReservationHold.property_id == quote.property_id,
            ReservationHold.status == "active",
            ReservationHold.check_in_date == quote.check_in,
            ReservationHold.check_out_date == quote.check_out,
            ReservationHold.expires_at >= datetime.now(timezone.utc),
        )
        .order_by(desc(ReservationHold.created_at))
        .limit(20)
    )
    for hold in result.scalars().all():
        snapshot = hold.quote_snapshot if isinstance(hold.quote_snapshot, dict) else {}
        if str(snapshot.get("quote_ref") or "") == str(quote.id):
            return hold
    return None


@router.get(
    "/quote-booking/control-tower",
    response_model=QuoteBookingControlTowerResponse,
    dependencies=[Depends(require_operator_manager_admin)],
)
async def quote_booking_control_tower(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> QuoteBookingControlTowerResponse:
    """Read-only internal quote-to-booking posture from existing CROG-VRS ledgers."""
    now = datetime.now(timezone.utc)
    now_naive = datetime.utcnow()
    day_ago = now - timedelta(days=1)
    day_ago_naive = now_naive - timedelta(days=1)

    pending_quotes = await _count(
        db,
        select(func.count()).select_from(GuestQuote).where(GuestQuote.status == GuestQuoteStatus.PENDING),
    )
    expired_pending_quotes = await _count(
        db,
        select(func.count())
        .select_from(GuestQuote)
        .where(
            or_(
                GuestQuote.status == GuestQuoteStatus.EXPIRED,
                and_(GuestQuote.status == GuestQuoteStatus.PENDING, GuestQuote.expires_at < now_naive),
            )
        ),
    )
    accepted_quotes_24h = await _count(
        db,
        select(func.count())
        .select_from(GuestQuote)
        .where(GuestQuote.status == GuestQuoteStatus.ACCEPTED, GuestQuote.accepted_at >= day_ago_naive),
    )
    active_holds = await _count(
        db,
        select(func.count()).select_from(ReservationHold).where(ReservationHold.status == "active"),
    )
    stale_active_holds = await _count(
        db,
        select(func.count())
        .select_from(ReservationHold)
        .where(ReservationHold.status == "active", ReservationHold.expires_at < now),
    )
    converted_holds_24h = await _count(
        db,
        select(func.count())
        .select_from(ReservationHold)
        .where(ReservationHold.status == "converted", ReservationHold.updated_at >= day_ago),
    )
    direct_reservations_24h = await _count(
        db,
        select(func.count())
        .select_from(Reservation)
        .where(Reservation.created_at >= day_ago),
    )
    parity_drifts_24h = await _count(
        db,
        select(func.count())
        .select_from(ParityAudit)
        .where(ParityAudit.created_at >= day_ago, func.upper(ParityAudit.status) != "MATCH"),
    )

    quote_rows = await db.execute(
        select(GuestQuote, Property.name, Property.slug)
        .outerjoin(Property, GuestQuote.property_id == Property.id)
        .order_by(desc(GuestQuote.created_at))
        .limit(limit)
    )
    quotes: list[QuoteBookingRecord] = []
    for quote, property_name, property_slug in quote_rows.all():
        stop_level, stop_reason = _quote_stop_level(quote, now_naive)
        readiness_metadata = await _quote_readiness_machine_state(db, quote, now, now_naive)
        title = property_name or quote.target_property_id or "Guest quote"
        quotes.append(
            QuoteBookingRecord(
                id=str(quote.id),
                kind="quote",
                title=title,
                status=str(quote.status),
                property_id=_uuid(quote.property_id) or quote.target_property_id,
                property_name=property_name or quote.target_property_id,
                guest_label=quote.guest_email or quote.guest_name,
                check_in=_iso(quote.check_in),
                check_out=_iso(quote.check_out),
                total_amount=_money(quote.total_amount),
                payment_state="payment_link_created" if quote.stripe_payment_link_url else "no_payment_link",
                parity_status=str(readiness_metadata.get("parity_status") or "not_checked"),
                stop_level=stop_level,
                stop_reason=stop_reason,
                href="/vrs/quotes",
                created_at=_iso(quote.created_at),
                updated_at=_iso(quote.updated_at),
                metadata={
                    "campaign": quote.campaign,
                    "property_slug": property_slug,
                    "stripe_payment_link_id": quote.stripe_payment_link_id,
                    "expires_at": _iso(quote.expires_at),
                    **readiness_metadata,
                },
            )
        )

    hold_rows = await db.execute(
        select(ReservationHold, Property.name, Guest.email, Guest.first_name, Guest.last_name)
        .outerjoin(Property, ReservationHold.property_id == Property.id)
        .outerjoin(Guest, ReservationHold.guest_id == Guest.id)
        .order_by(desc(ReservationHold.created_at))
        .limit(limit)
    )
    holds: list[QuoteBookingRecord] = []
    for hold, property_name, guest_email, first_name, last_name in hold_rows.all():
        stop_level, stop_reason = _hold_stop_level(hold, now)
        holds.append(
            QuoteBookingRecord(
                id=str(hold.id),
                kind="hold",
                title=property_name or "Checkout hold",
                status=str(hold.status),
                property_id=_uuid(hold.property_id),
                property_name=property_name,
                guest_label=_guest_name(first_name, last_name, guest_email),
                check_in=_iso(hold.check_in_date),
                check_out=_iso(hold.check_out_date),
                total_amount=_money(hold.amount_total),
                payment_state="payment_intent_attached" if hold.payment_intent_id else "no_payment_intent",
                parity_status=None,
                stop_level=stop_level,
                stop_reason=stop_reason,
                href="/command/quote-control",
                created_at=_iso(hold.created_at),
                updated_at=_iso(hold.updated_at),
                metadata={
                    "session_id": hold.session_id,
                    "payment_intent_id": hold.payment_intent_id,
                    "converted_reservation_id": _uuid(hold.converted_reservation_id),
                    "expires_at": _iso(hold.expires_at),
                },
            )
        )

    reservation_rows = await db.execute(
        select(Reservation, Property.name)
        .outerjoin(Property, Reservation.property_id == Property.id)
        .order_by(desc(Reservation.created_at))
        .limit(limit)
    )
    reservations: list[QuoteBookingRecord] = []
    for reservation, property_name in reservation_rows.all():
        stop_level, stop_reason = _reservation_stop_level(reservation)
        reservations.append(
            QuoteBookingRecord(
                id=str(reservation.id),
                kind="reservation",
                title=reservation.confirmation_code,
                status=str(reservation.status),
                property_id=_uuid(reservation.property_id),
                property_name=property_name,
                guest_label=reservation.guest_email or reservation.guest_name,
                check_in=_iso(reservation.check_in_date),
                check_out=_iso(reservation.check_out_date),
                total_amount=_money(reservation.total_amount),
                payment_state="paid" if _money(reservation.balance_due) in (None, 0.0) else "balance_due",
                parity_status="streamline_linked" if reservation.streamline_reservation_id else "streamline_pending",
                stop_level=stop_level,
                stop_reason=stop_reason,
                href=f"/reservations?search={reservation.confirmation_code}",
                created_at=_iso(reservation.created_at),
                updated_at=_iso(reservation.updated_at),
                metadata={
                    "booking_source": reservation.booking_source,
                    "streamline_reservation_id": reservation.streamline_reservation_id,
                    "balance_due": _money(reservation.balance_due),
                },
            )
        )

    parity_rows = await db.execute(
        select(ParityAudit, Reservation.confirmation_code, Property.name)
        .outerjoin(Reservation, ParityAudit.reservation_id == Reservation.id)
        .outerjoin(Property, Reservation.property_id == Property.id)
        .order_by(desc(ParityAudit.created_at))
        .limit(limit)
    )
    parity_audits: list[QuoteBookingRecord] = []
    for audit, confirmation_code, property_name in parity_rows.all():
        stop_level, stop_reason = _parity_stop_level(audit)
        parity_audits.append(
            QuoteBookingRecord(
                id=str(audit.id),
                kind="parity",
                title=confirmation_code or audit.confirmation_id,
                status=str(audit.status),
                property_name=property_name,
                total_amount=_money(audit.local_total),
                payment_state=None,
                parity_status=str(audit.status),
                stop_level=stop_level,
                stop_reason=stop_reason,
                href="/command/checkout-parity",
                created_at=_iso(audit.created_at),
                metadata={
                    "reservation_id": str(audit.reservation_id),
                    "confirmation_id": audit.confirmation_id,
                    "streamline_total": _money(audit.streamline_total),
                    "delta": _money(audit.delta),
                },
            )
        )

    summary = {
        "pending_quotes": pending_quotes,
        "expired_pending_quotes": expired_pending_quotes,
        "accepted_quotes_24h": accepted_quotes_24h,
        "active_holds": active_holds,
        "stale_active_holds": stale_active_holds,
        "converted_holds_24h": converted_holds_24h,
        "direct_reservations_24h": direct_reservations_24h,
        "parity_drifts_24h": parity_drifts_24h,
    }

    all_records = [*quotes, *holds, *reservations, *parity_audits]
    await _apply_control_audits(db, all_records)
    readiness_summary = _finalize_quote_readiness(quotes)
    hard_stops = sum(1 for row in all_records if row.stop_level == "stop")
    inspection_items = sum(1 for row in all_records if row.stop_level == "inspect")
    assigned_items = sum(1 for row in all_records if row.assigned_to)
    escalated_items = sum(1 for row in all_records if row.escalated)
    reviewed_items = sum(1 for row in all_records if row.reviewed)
    dismissed_items = sum(1 for row in all_records if row.dismissed)
    summary.update(
        {
            **readiness_summary,
            "hard_stops": hard_stops,
            "inspection_items": inspection_items,
            "assigned_items": assigned_items,
            "escalated_items": escalated_items,
            "reviewed_items": reviewed_items,
            "dismissed_items": dismissed_items,
        }
    )

    safeguards = [
        QuoteBookingSafeguard(
            id="staff_auth",
            label="Internal staff boundary",
            status="locked",
            detail="Control Tower data is served only from the staff API path and requires an authenticated CROG operator.",
            href="/command/settings/staff",
        ),
        QuoteBookingSafeguard(
            id="read_only",
            label="Controlled send only",
            status="locked",
            detail="Only readiness-approved quote emails can be sent. Holds, charges, refunds, Streamline writes, public content, DNS, and tunnels stay locked.",
            href="/ai-engine",
        ),
        QuoteBookingSafeguard(
            id="quote_readiness",
            label="Quote readiness gate",
            status=(
                "attention"
                if summary.get("blocked_quotes", 0) or summary.get("quotes_needing_staff_approval", 0)
                else "clear"
            ),
            detail=(
                f"{summary.get('ready_quotes', 0)} ready, "
                f"{summary.get('quotes_needing_staff_approval', 0)} need staff approval, "
                f"{summary.get('blocked_quotes', 0)} blocked."
            ),
            href="/command/quote-control",
        ),
        QuoteBookingSafeguard(
            id="legacy_boundary",
            label="Legacy storefront untouched",
            status="locked",
            detail="No DNS, Cloudflare tunnel, AWS, Drupal, or public-domain controls are wired to this endpoint.",
            href=None,
        ),
        QuoteBookingSafeguard(
            id="parity_gate",
            label="Parity hard stop",
            status="attention" if parity_drifts_24h else "clear",
            detail=(
                f"{parity_drifts_24h} quote parity drift"
                f"{'' if parity_drifts_24h == 1 else 's'} detected in the last 24 hours."
            ),
            href="/command/checkout-parity",
        ),
        QuoteBookingSafeguard(
            id="hold_freshness",
            label="Hold freshness gate",
            status="attention" if stale_active_holds else "clear",
            detail=(
                f"{stale_active_holds} active checkout hold"
                f"{'' if stale_active_holds == 1 else 's'} past expiration."
            ),
            href="/command/quote-control",
        ),
    ]

    return QuoteBookingControlTowerResponse(
        summary=summary,
        safeguards=safeguards,
        quotes=quotes,
        holds=holds,
        reservations=reservations,
        parity_audits=parity_audits,
        generated_at=now.isoformat(),
    )


@router.post(
    "/quote-booking/control-tower/proof-lane/test-quote",
    response_model=QuoteBookingProofLaneResponse,
)
async def quote_booking_proof_lane_test_quote(
    body: QuoteBookingProofLaneRequest,
    db: AsyncSession = Depends(get_db),
    current_user: StaffUser = Depends(require_operator_manager_admin),
) -> QuoteBookingProofLaneResponse:
    """Create a Stripe-test, staff-only quote for proving the guarded send lane."""
    if _stripe_secret_mode() != "test":
        raise HTTPException(status_code=423, detail="Proof lane is locked unless Stripe is in test mode")

    guest_email = _resolve_proof_lane_email(current_user, body.guest_email)
    prop = await _resolve_proof_lane_property(db, body.property_id)
    amount = _money_decimal_from_cents(body.amount_cents)
    check_in = date.today() + timedelta(days=90)
    check_out = check_in + timedelta(days=2)
    now_naive = datetime.utcnow()

    quote = GuestQuote(
        target_property_id=str(prop.id),
        property_id=prop.id,
        guest_name="CROG-VRS Proof Lane",
        guest_email=guest_email,
        guest_phone="proof-lane",
        check_in=check_in,
        check_out=check_out,
        nights=2,
        adults=2,
        children=0,
        pets=0,
        base_rent=amount,
        taxes=Decimal("0.00"),
        fees=Decimal("0.00"),
        total_amount=amount,
        base_price=float(amount),
        ai_adjusted_price=float(amount),
        sovereign_narrative="Internal CROG-VRS proof lane test quote. Stripe test mode only.",
        campaign="proof_lane_test",
        target_keyword="internal-proof-lane",
        quote_breakdown={
            "base_rent": str(amount),
            "taxes": "0.00",
            "fees": "0.00",
            "total": str(amount),
            "pricing_source": "proof_lane_test",
            "nightly_breakdown": [
                {"date": check_in.isoformat(), "rate": str((amount / 2).quantize(Decimal("0.01")))},
                {"date": (check_in + timedelta(days=1)).isoformat(), "rate": str((amount / 2).quantize(Decimal("0.01")))},
            ],
        },
        source_snapshot={
            "parity_status": "MATCH",
            "quote_parity_status": "MATCH",
            "proof_lane": True,
            "safe_internal_only": True,
            "stripe_mode": "test",
            "streamline_write": "blocked",
            "legacy_storefront": "untouched",
            "cloudflare_dns_or_tunnel": "untouched",
        },
        expires_at=now_naive + timedelta(hours=48),
        status=GuestQuoteStatus.PENDING,
    )
    db.add(quote)
    await db.flush()

    try:
        link_result = await asyncio.to_thread(
            _create_proof_lane_payment_link,
            quote_id=str(quote.id),
            amount_cents=body.amount_cents,
            property_id=str(prop.id),
            property_name=prop.name,
            guest_email=guest_email,
        )
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Stripe test payment link failed: {str(exc)[:160]}") from exc

    quote.stripe_payment_link_url = str(link_result["payment_link_url"])
    quote.stripe_payment_link_id = str(link_result["payment_link_id"])
    await db.commit()
    await db.refresh(quote)

    audit = await record_audit_event(
        db=db,
        actor_id=str(current_user.id),
        actor_email=current_user.email,
        action="quote_booking.proof_lane_test_quote_created",
        resource_type="quote_booking_control_item",
        resource_id=_control_resource_id("quote", str(quote.id)),
        purpose="Create a safe internal quote-to-booking proof lane test quote.",
        tool_name="quote_booking_control_tower",
        redaction_status="metadata_only",
        model_route="human_staff",
        outcome="success",
        metadata_json={
            "quote_id": str(quote.id),
            "guest_email": guest_email,
            "property_id": str(prop.id),
            "property_name": prop.name,
            "amount_cents": body.amount_cents,
            "stripe_mode": "test",
            "safe_internal_only": True,
            "blocked_capabilities": CONTROL_TOWER_BLOCKED_CAPABILITIES,
        },
    )

    if body.mark_reviewed:
        await record_audit_event(
            db=db,
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            action="quote_booking.mark_reviewed",
            resource_type="quote_booking_control_item",
            resource_id=_control_resource_id("quote", str(quote.id)),
            purpose="Staff approval for an internal proof lane test quote.",
            tool_name="quote_booking_control_tower",
            redaction_status="metadata_only",
            model_route="human_staff",
            outcome="success",
            metadata_json={
                "kind": "quote",
                "item_id": str(quote.id),
                "action": "mark_reviewed",
                "note": "Proof lane test quote approved by staff action.",
                "safe_action_only": True,
                "proof_lane": True,
                "blocked_capabilities": CONTROL_TOWER_BLOCKED_CAPABILITIES,
            },
        )

    record = await _quote_control_record(db, quote, datetime.now(timezone.utc), datetime.utcnow())
    return QuoteBookingProofLaneResponse(
        ok=True,
        quote=record,
        audit_id=str(audit.id) if audit else None,
        audit_hash=audit.entry_hash if audit else None,
        stripe_mode="test",
        message="Proof lane test quote created in Stripe test mode and reviewed. It is eligible for the controlled internal send workflow only.",
    )


@router.post(
    "/quote-booking/control-tower/quote/{quote_id}/create-hold",
    response_model=QuoteBookingHoldResponse,
)
async def quote_booking_control_create_hold(
    quote_id: UUID,
    body: QuoteBookingHoldRequest,
    db: AsyncSession = Depends(get_db),
    current_user: StaffUser = Depends(require_operator_manager_admin),
) -> QuoteBookingHoldResponse:
    """Create a local inventory hold from a sent, ready quote. No payment capture or Streamline write."""
    quote = await db.get(GuestQuote, quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="Guest quote not found")

    note = (body.note or "").strip() or None
    record = await _quote_control_record(db, quote, datetime.now(timezone.utc), datetime.utcnow())
    readiness_state = str(record.metadata.get("readiness_state") or "blocked")
    if readiness_state != "ready":
        await _record_quote_hold_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="blocked",
            note=note,
            detail=f"Readiness gate refused local hold: {readiness_state}.",
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Quote is not ready for a local hold.",
                "readiness_state": readiness_state,
                "readiness_reasons": record.metadata.get("readiness_reasons") or [],
            },
        )

    if not record.metadata.get("guest_quote_sent"):
        await _record_quote_hold_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="blocked",
            note=note,
            detail="Guest quote has not been sent through the controlled workflow.",
        )
        raise HTTPException(status_code=409, detail="Send the quote before creating a local checkout hold")

    if not quote.property_id or not quote.check_in or not quote.check_out:
        await _record_quote_hold_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="blocked",
            note=note,
            detail="Quote is missing property or stay dates.",
        )
        raise HTTPException(status_code=422, detail="Quote is missing property or stay dates")

    guest_email = (quote.guest_email or "").strip()
    if not guest_email or "@" not in guest_email:
        await _record_quote_hold_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="blocked",
            note=note,
            detail="Guest email is missing or invalid.",
        )
        raise HTTPException(status_code=422, detail="Guest email is missing or invalid")

    first_name, last_name = _quote_guest_names(quote)
    guest_phone = (quote.guest_phone or "").strip() or f"quote-{str(quote.id)[:8]}"
    guest = (
        await db.execute(select(Guest).where(Guest.email == guest_email))
    ).scalar_one_or_none()
    if guest is None:
        guest = (
            await db.execute(select(Guest).where(Guest.phone_number == guest_phone))
        ).scalar_one_or_none()
    if guest is None:
        guest = Guest(
            email=guest_email,
            first_name=first_name,
            last_name=last_name,
            phone=guest_phone,
        )
        db.add(guest)
        await db.flush()
    else:
        guest.email = guest_email
        guest.first_name = first_name
        guest.last_name = last_name
        guest.phone = guest_phone

    quote_snapshot = {
        "quote_ref": str(quote.id),
        "source": "quote_booking_control_tower",
        "quote_breakdown": quote.quote_breakdown or {},
        "source_snapshot": quote.source_snapshot or {},
        "total": str(quote.total_amount or "0.00"),
        "payment_link_id": quote.stripe_payment_link_id,
        "payment_link_url_present": bool(quote.stripe_payment_link_url),
        "payment_intent_created": False,
        "streamline_write": "blocked",
        "legacy_storefront": "untouched",
    }
    try:
        hold = await create_inventory_hold(
            db,
            property_id=quote.property_id,
            check_in=quote.check_in,
            check_out=quote.check_out,
            session_id=f"quote-control-{quote.id}",
            guest_id=guest.id,
            num_guests=max(1, int((quote.adults or 0) + (quote.children or 0))),
            amount_total=quote.total_amount,
            quote_snapshot=quote_snapshot,
            special_requests=note or f"Created from controlled CROG-VRS quote {quote.id}.",
        )
        await db.commit()
        await db.refresh(hold)
    except HTTPException as exc:
        await db.rollback()
        await _record_quote_hold_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="blocked",
            note=note,
            detail=str(exc.detail),
        )
        raise
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        await _record_quote_hold_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="failure",
            note=note,
            detail=f"Local hold creation failed: {str(exc)[:160]}",
        )
        raise HTTPException(status_code=500, detail="Local hold creation failed") from exc

    audit = await _record_quote_hold_audit(
        db=db,
        current_user=current_user,
        quote=quote,
        record=record,
        outcome="success",
        note=note,
        detail="Local checkout hold created without payment capture or Streamline write.",
        hold_id=str(hold.id),
    )
    return QuoteBookingHoldResponse(
        ok=True,
        quote_id=str(quote.id),
        hold_id=str(hold.id),
        expires_at=hold.expires_at.isoformat(),
        audit_id=str(audit.id) if audit else None,
        audit_hash=audit.entry_hash if audit else None,
        message="Local checkout hold created. No card was charged, no PaymentIntent was created, no Streamline write occurred, and the legacy site was untouched.",
    )


@router.post(
    "/quote-booking/control-tower/quote/{quote_id}/convert-hold",
    response_model=QuoteBookingReservationResponse,
)
async def quote_booking_control_convert_hold(
    quote_id: UUID,
    body: QuoteBookingReservationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: StaffUser = Depends(require_operator_manager_admin),
) -> QuoteBookingReservationResponse:
    """Convert a staff-created local hold into a local pending-payment reservation."""
    quote = await db.get(GuestQuote, quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="Guest quote not found")

    note = (body.note or "").strip() or None
    record = await _quote_control_record(db, quote, datetime.now(timezone.utc), datetime.utcnow())
    readiness_state = str(record.metadata.get("readiness_state") or "blocked")
    if readiness_state != "local_hold_created":
        await _record_quote_reservation_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="blocked",
            note=note,
            detail=f"Conversion requires a staff-created local hold; current state is {readiness_state}.",
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Quote does not have an active local hold to convert.",
                "readiness_state": readiness_state,
                "readiness_reasons": record.metadata.get("readiness_reasons") or [],
            },
        )

    hold = await _find_active_quote_hold(db, quote)
    if hold is None:
        await _record_quote_reservation_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="blocked",
            note=note,
            detail="No active local hold exists for this quote.",
        )
        raise HTTPException(status_code=409, detail="No active local hold exists for this quote")

    guest = await db.get(Guest, hold.guest_id) if hold.guest_id else None
    if guest is None:
        await _record_quote_reservation_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="blocked",
            note=note,
            hold_id=str(hold.id),
            detail="Local hold has no guest ledger row.",
        )
        raise HTTPException(status_code=422, detail="Local hold has no guest ledger row")

    total_amount = Decimal(str(quote.total_amount or hold.amount_total or "0.00"))
    nights = max(1, (hold.check_out_date - hold.check_in_date).days)
    guest_name = _guest_name(guest.first_name, guest.last_name, quote.guest_name) or "Guest Quote"
    conversion_note = (
        f"CROG-VRS quote-control conversion from quote {quote.id} and hold {hold.id}. "
        "Pending payment; no Stripe capture and no Streamline write."
    )
    if note:
        conversion_note = f"{conversion_note} Staff note: {note}"

    try:
        reservation = await reservation_engine.create_reservation(
            db,
            {
                "guest_id": guest.id,
                "property_id": hold.property_id,
                "check_in_date": hold.check_in_date,
                "check_out_date": hold.check_out_date,
                "num_guests": hold.num_guests,
                "num_adults": quote.adults,
                "num_children": quote.children,
                "booking_source": "crog_vrs_quote_control",
                "total_amount": total_amount,
                "internal_notes": conversion_note,
                "exclude_hold_id": hold.id,
            },
        )
        reservation.status = "pending_payment"
        reservation.guest_email = guest.email or quote.guest_email or ""
        reservation.guest_name = guest_name
        reservation.guest_phone = guest.phone or quote.guest_phone
        reservation.num_pets = quote.pets or 0
        reservation.nights_count = nights
        reservation.nightly_rate = (Decimal(str(quote.base_rent or "0.00")) / Decimal(nights)).quantize(Decimal("0.01"))
        reservation.cleaning_fee = Decimal("0.00")
        reservation.service_fee = Decimal(str(quote.fees or "0.00"))
        reservation.tax_amount = Decimal(str(quote.taxes or "0.00"))
        reservation.price_breakdown = {
            "quote_ref": str(quote.id),
            "hold_ref": str(hold.id),
            "source": "quote_booking_control_tower",
            "quote_breakdown": quote.quote_breakdown or {},
            "source_snapshot": quote.source_snapshot or {},
            "base_rent": str(quote.base_rent or "0.00"),
            "fees": str(quote.fees or "0.00"),
            "taxes": str(quote.taxes or "0.00"),
            "total": str(total_amount),
            "payment_intent_created": False,
            "payment_captured": False,
            "streamline_write": "blocked",
            "legacy_storefront": "untouched",
        }
        reservation.paid_amount = Decimal("0.00")
        reservation.balance_due = total_amount
        reservation.streamline_reservation_id = None

        hold.status = "converted"
        hold.converted_reservation_id = reservation.id
        hold.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(reservation)
        await db.refresh(hold)
    except ValueError as exc:
        await db.rollback()
        await _record_quote_reservation_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="blocked",
            note=note,
            hold_id=str(hold.id),
            detail=str(exc),
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        await _record_quote_reservation_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="failure",
            note=note,
            hold_id=str(hold.id),
            detail=f"Local reservation conversion failed: {str(exc)[:160]}",
        )
        raise HTTPException(status_code=500, detail="Local reservation conversion failed") from exc

    audit = await _record_quote_reservation_audit(
        db=db,
        current_user=current_user,
        quote=quote,
        record=record,
        outcome="success",
        note=note,
        detail="Local pending-payment reservation created without payment capture or Streamline write.",
        hold_id=str(hold.id),
        reservation_id=str(reservation.id),
        confirmation_code=reservation.confirmation_code,
    )
    return QuoteBookingReservationResponse(
        ok=True,
        quote_id=str(quote.id),
        hold_id=str(hold.id),
        reservation_id=str(reservation.id),
        confirmation_code=reservation.confirmation_code,
        audit_id=str(audit.id) if audit else None,
        audit_hash=audit.entry_hash if audit else None,
        message="Local pending-payment reservation created. No card was charged, no PaymentIntent was created, no Streamline write occurred, and the legacy site was untouched.",
    )


@router.post(
    "/quote-booking/control-tower/quote/{quote_id}/send",
    response_model=QuoteBookingSendResponse,
)
async def quote_booking_control_send_quote(
    quote_id: UUID,
    body: QuoteBookingSendRequest,
    db: AsyncSession = Depends(get_db),
    current_user: StaffUser = Depends(require_operator_manager_admin),
) -> QuoteBookingSendResponse:
    """Send one staff-approved quote email after the server-side readiness gate passes."""
    quote = await db.get(GuestQuote, quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="Guest quote not found")

    note = (body.note or "").strip() or None
    now = datetime.now(timezone.utc)
    now_naive = datetime.utcnow()
    record = await _quote_control_record(db, quote, now, now_naive)
    readiness_state = str(record.metadata.get("readiness_state") or "blocked")
    if readiness_state != "ready":
        await _record_quote_send_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="blocked",
            note=note,
            detail=f"Readiness gate refused send: {readiness_state}.",
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Quote is not ready to send.",
                "readiness_state": readiness_state,
                "readiness_reasons": record.metadata.get("readiness_reasons") or [],
            },
        )

    guest_email = (quote.guest_email or "").strip()
    if not guest_email or "@" not in guest_email:
        await _record_quote_send_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="blocked",
            note=note,
            detail="Guest email is missing or invalid.",
        )
        raise HTTPException(status_code=422, detail="Guest email is missing or invalid")

    payment_url = (quote.stripe_payment_link_url or "").strip()
    if not payment_url:
        await _record_quote_send_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="blocked",
            note=note,
            detail="Guest checkout payment link is missing.",
        )
        raise HTTPException(status_code=409, detail="Guest checkout payment link is missing")

    if not is_email_configured():
        audit = await _record_quote_send_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="failure",
            note=note,
            detail="SMTP email delivery is not configured.",
        )
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Email delivery is not configured.",
                "audit_id": str(audit.id) if audit else None,
            },
        )

    subject, html_body, text_body = _build_guest_quote_email(quote, record, payment_url)
    sent = await asyncio.to_thread(
        send_email,
        to=guest_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )
    if not sent:
        audit = await _record_quote_send_audit(
            db=db,
            current_user=current_user,
            quote=quote,
            record=record,
            outcome="failure",
            note=note,
            detail="SMTP provider returned a send failure.",
        )
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Quote email dispatch failed.",
                "audit_id": str(audit.id) if audit else None,
            },
        )

    audit = await _record_quote_send_audit(
        db=db,
        current_user=current_user,
        quote=quote,
        record=record,
        outcome="success",
        note=note,
        detail="Quote email sent to guest through controlled staff workflow.",
    )
    return QuoteBookingSendResponse(
        ok=True,
        quote_id=str(quote.id),
        guest_email=guest_email,
        audit_id=str(audit.id) if audit else None,
        audit_hash=audit.entry_hash if audit else None,
        message="Quote sent to guest. Source booking, payment, public site, DNS, Cloudflare, and Streamline records were not changed.",
    )


@router.post(
    "/quote-booking/control-tower/{kind}/{item_id}/action",
    response_model=QuoteBookingActionResponse,
)
async def quote_booking_control_action(
    kind: str,
    item_id: str,
    body: QuoteBookingActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: StaffUser = Depends(require_operator_manager_admin),
) -> QuoteBookingActionResponse:
    """Record a safe staff action for a Control Tower item without mutating source ledgers."""
    normalized_kind, row = await _load_control_item(db, kind, item_id)
    assignee = (body.assignee or current_user.email or "").strip() if body.action == "claim" else None
    note = (body.note or "").strip() or None
    resource_id = _control_resource_id(normalized_kind, item_id)
    metadata = {
        "kind": normalized_kind,
        "item_id": item_id,
        "action": body.action,
        "assignee": assignee,
        "note": note,
        "source_status": str(getattr(row, "status", "") or ""),
        "safe_action_only": True,
        "blocked_capabilities": ["send_guest_quote_without_readiness_approval", *CONTROL_TOWER_BLOCKED_CAPABILITIES],
    }
    audit = await record_audit_event(
        db=db,
        actor_id=str(current_user.id),
        actor_email=current_user.email,
        action=f"quote_booking.{body.action}",
        resource_type="quote_booking_control_item",
        resource_id=resource_id,
        purpose="Staff triage action on quote-to-booking Control Tower item.",
        tool_name="quote_booking_control_tower",
        redaction_status="metadata_only",
        model_route="human_staff",
        outcome="success",
        metadata_json=metadata,
    )
    action_labels = {
        "claim": "claimed",
        "mark_reviewed": "marked reviewed",
        "escalate": "escalated",
        "dismiss": "dismissed",
        "note": "noted",
    }
    return QuoteBookingActionResponse(
        ok=True,
        kind=normalized_kind,
        id=item_id,
        action=body.action,
        audit_id=str(audit.id) if audit else None,
        audit_hash=audit.entry_hash if audit else None,
        message=f"Control Tower item {action_labels[body.action]}. No source booking, payment, quote, or Streamline record was changed.",
    )
