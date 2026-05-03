from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import require_operator_manager_admin
from backend.models import Guest, GuestQuote, GuestQuoteStatus, Property, Reservation, ReservationHold
from backend.models.openshell_audit import OpenShellAuditLog
from backend.models.parity_audit import ParityAudit
from backend.models.staff import StaffUser
from backend.services.openshell_audit import record_audit_event

router = APIRouter()


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
) -> tuple[int, int]:
    if not quote.property_id or not quote.check_in or not quote.check_out:
        return 0, 0

    hold_count = await _count(
        db,
        select(func.count())
        .select_from(ReservationHold)
        .where(
            ReservationHold.property_id == quote.property_id,
            ReservationHold.status == "active",
            ReservationHold.expires_at >= now,
            ReservationHold.check_in_date < quote.check_out,
            ReservationHold.check_out_date > quote.check_in,
        ),
    )
    reservation_count = await _count(
        db,
        select(func.count())
        .select_from(Reservation)
        .where(
            Reservation.property_id == quote.property_id,
            Reservation.status.notin_(["cancelled", "canceled", "no_show"]),
            Reservation.check_in_date < quote.check_out,
            Reservation.check_out_date > quote.check_in,
        ),
    )
    return hold_count, reservation_count


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
    hold_conflicts, reservation_conflicts = await _quote_overlap_counts(db, quote, now)
    payment_ready = bool(quote.stripe_payment_link_id or quote.stripe_payment_link_url)
    parity_status = _quote_parity_status(quote)
    parity_upper = parity_status.upper()
    parity_passed = parity_upper in {"MATCH", "PASS", "PASSED", "CLEAR"}
    parity_missing = parity_upper in {"", "NONE", "NULL", "NOT_CHECKED", "UNKNOWN"}
    parity_drift = not parity_passed and not parity_missing

    checks = [
        _check(
            "Expiration",
            "fail" if is_expired else "pass",
            f"Expires {quote.expires_at.isoformat()}" if quote.expires_at else "No expiration timestamp found.",
        ),
        _check(
            "Availability",
            "fail" if (not has_stay or hold_conflicts or reservation_conflicts) else "pass",
            (
                f"{hold_conflicts} active hold conflict(s), {reservation_conflicts} reservation conflict(s)."
                if has_stay
                else "Property and stay dates are required."
            ),
        ),
        _check(
            "Stripe handoff",
            "pass" if payment_ready else "fail",
            "Payment link is attached." if payment_ready else "No Stripe payment link is attached.",
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
                payment_state="payment_link_created" if quote.stripe_payment_link_id else "no_payment_link",
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
            label="Read-only first pass",
            status="locked",
            detail="This surface cannot send quotes, create holds, charge cards, issue refunds, or write to Streamline.",
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
        "blocked_capabilities": [
            "send_guest_quote",
            "create_checkout_hold",
            "charge_or_refund_payment",
            "write_streamline",
            "publish_public_content",
        ],
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
