"""
VRS Command & Control adjudication API.

Surfaces HELD conflict-resolution cases from the operational deliberation ledger
and lets an operator inspect live council context before overriding dispatch.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import require_operator_manager_admin
from backend.models.guest import Guest
from backend.models.message import Message
from backend.models.operational_deliberation_log import OperationalDeliberationLog
from backend.models.property import Property
from backend.models.reservation import Reservation
from backend.models.staff import StaffUser
from backend.services.crog_concierge_engine import run_guest_send_sms, run_guest_triage

router = APIRouter()

_SEND_THRESHOLD = 0.8


class OverrideDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str | None = Field(default=None, max_length=1600)
    consensus_conviction: float | None = Field(default=None, ge=0.0, le=1.0)
    minimum_conviction: float = Field(default=0.0, ge=0.0, le=1.0)


def _payload_dict(log: OperationalDeliberationLog) -> dict[str, Any]:
    return log.payload_json if isinstance(log.payload_json, dict) else {}


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _conviction(payload: dict[str, Any]) -> float:
    conflict = payload.get("conflict_resolution") or {}
    triage = payload.get("triage") or {}
    value = conflict.get("consensus_conviction", triage.get("consensus_conviction", 0.0))
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _signal(payload: dict[str, Any]) -> str:
    conflict = payload.get("conflict_resolution") or {}
    triage = payload.get("triage") or {}
    return str(conflict.get("consensus_signal") or triage.get("consensus_signal") or "NEUTRAL")


def _hold_reason(payload: dict[str, Any], dispatched: bool) -> str:
    if dispatched:
        return "dispatched"
    conviction = _conviction(payload)
    signal = _signal(payload).upper()
    if conviction < _SEND_THRESHOLD:
        return "below_send_threshold"
    if signal in {"CAUTION", "CRITICAL_RISK", "ERROR"}:
        return "human_review_required"
    return "operator_override_required"


def _status(payload: dict[str, Any], dispatched: bool) -> str:
    return "dispatched" if dispatched else "held"


def _guest_summary(guest: Guest | None) -> dict[str, Any] | None:
    if guest is None:
        return None
    return {
        "id": str(guest.id),
        "full_name": guest.full_name,
        "phone_number": guest.phone_number,
        "email": guest.email,
    }


def _reservation_summary(reservation: Reservation | None) -> dict[str, Any] | None:
    if reservation is None:
        return None
    return {
        "id": str(reservation.id),
        "confirmation_code": reservation.confirmation_code,
        "status": reservation.status,
        "check_in_date": _to_iso(reservation.check_in_date),
        "check_out_date": _to_iso(reservation.check_out_date),
    }


def _property_summary(prop: Property | None) -> dict[str, Any] | None:
    if prop is None:
        return None
    return {
        "id": str(prop.id),
        "name": prop.name,
        "slug": prop.slug,
    }


def _message_summary(message: Message | None) -> dict[str, Any] | None:
    if message is None:
        return None
    return {
        "id": str(message.id),
        "direction": message.direction,
        "status": message.status,
        "body": message.body,
        "created_at": _to_iso(message.created_at),
    }


def _looks_like_test_artifact(
    payload: dict[str, Any],
    guest: Guest | None,
    reservation: Reservation | None,
    message: Message | None,
) -> bool:
    seed_meta = payload.get("seed_metadata") or {}
    if str(seed_meta.get("source") or "").strip().lower() == "cursor_seed":
        return True

    guest_email = (getattr(guest, "email", None) or "").strip().lower()
    if guest_email.endswith("@fortress-prime.local") or "e2e" in guest_email:
        return True

    special_requests = (getattr(reservation, "special_requests", None) or "").strip().lower()
    if "[targeted e2e test]" in special_requests or "session=" in special_requests:
        return True

    body = (getattr(message, "body", None) or "").strip().lower()
    if "manage_concierge_pilot.py" in body or "verification probe" in body:
        return True

    return False


async def _resolve_context(
    db: AsyncSession,
    log: OperationalDeliberationLog,
) -> tuple[Guest | None, Reservation | None, Property | None, Message | None]:
    message = await db.get(Message, log.message_id) if log.message_id else None
    guest = await db.get(Guest, log.guest_id) if log.guest_id else None
    reservation = await db.get(Reservation, log.reservation_id) if log.reservation_id else None
    prop = await db.get(Property, log.property_id) if log.property_id else None

    if reservation is not None and guest is None and reservation.guest_id:
        guest = await db.get(Guest, reservation.guest_id)
    if reservation is not None and prop is None and reservation.property_id:
        prop = await db.get(Property, reservation.property_id)
    if message is not None and guest is None and message.guest_id:
        guest = await db.get(Guest, message.guest_id)
    if message is not None and reservation is None and message.reservation_id:
        reservation = await db.get(Reservation, message.reservation_id)
        if reservation is not None and prop is None and reservation.property_id:
            prop = await db.get(Property, reservation.property_id)
    if message is None:
        message = await _find_anchor_message(
            db,
            guest=guest,
            reservation=reservation,
            created_at=log.created_at,
        )
        if message is not None:
            if guest is None and message.guest_id:
                guest = await db.get(Guest, message.guest_id)
            if reservation is None and message.reservation_id:
                reservation = await db.get(Reservation, message.reservation_id)
                if reservation is not None and prop is None and reservation.property_id:
                    prop = await db.get(Property, reservation.property_id)

    return guest, reservation, prop, message


async def _dispatched_sessions(db: AsyncSession) -> set[str]:
    result = await db.execute(
        select(OperationalDeliberationLog.session_id).where(
            OperationalDeliberationLog.verdict_type == "guest_send_sms"
        )
    )
    return {row[0] for row in result.all() if row and row[0]}


async def _find_anchor_message(
    db: AsyncSession,
    *,
    guest: Guest | None,
    reservation: Reservation | None,
    created_at: Any,
) -> Message | None:
    time_filters = []
    if created_at is not None:
        time_filters.append(Message.created_at <= created_at)

    if reservation is not None:
        result = await db.execute(
            select(Message)
            .where(
                and_(
                    Message.reservation_id == reservation.id,
                    Message.direction == "inbound",
                    *time_filters,
                )
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        match = result.scalars().first()
        if match is not None:
            return match

    if guest is not None:
        result = await db.execute(
            select(Message)
            .where(
                and_(
                    Message.guest_id == guest.id,
                    Message.direction == "inbound",
                    *time_filters,
                )
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        match = result.scalars().first()
        if match is not None:
            return match

    return None


async def _compute_live_triage(
    db: AsyncSession,
    *,
    guest: Guest | None,
    reservation: Reservation | None,
    message: Message | None,
) -> dict[str, Any] | None:
    inbound_message = (message.body or "").strip() if message is not None else ""
    if not inbound_message:
        return None
    if guest is None and reservation is None and message is None:
        return None

    try:
        return await run_guest_triage(
            db,
            guest_id=guest.id if guest is not None else None,
            reservation_id=reservation.id if reservation is not None else None,
            message_id=message.id if message is not None else None,
            guest_phone=guest.phone_number if guest is not None else None,
            inbound_message=inbound_message,
            trigger_type="VRS_C2_LIVE_TRIAGE",
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unavailable",
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
        }


async def _queue_item(
    db: AsyncSession,
    log: OperationalDeliberationLog,
    *,
    dispatched_sessions: set[str],
) -> dict[str, Any]:
    payload = _payload_dict(log)
    dispatched = log.session_id in dispatched_sessions
    guest, reservation, prop, message = await _resolve_context(db, log)
    conflict = payload.get("conflict_resolution") or {}
    triage = payload.get("triage") or {}
    field_reality = payload.get("field_reality") or {}

    return {
        "id": str(log.id),
        "session_id": log.session_id,
        "verdict_type": log.verdict_type,
        "status": _status(payload, dispatched),
        "hold_reason": _hold_reason(payload, dispatched),
        "created_at": _to_iso(log.created_at),
        "consensus_signal": _signal(payload),
        "consensus_conviction": _conviction(payload),
        "complaint_legitimacy": conflict.get("complaint_legitimacy"),
        "corrective_scheduling": conflict.get("corrective_scheduling"),
        "escalation_level": triage.get("escalation_level"),
        "departments_implicated": conflict.get("departments_implicated")
        or triage.get("departments_implicated")
        or [],
        "guest": _guest_summary(guest),
        "reservation": _reservation_summary(reservation),
        "property": _property_summary(prop),
        "message": _message_summary(message),
        "inbound_message": (message.body or "") if message is not None else None,
        "field_reality": field_reality,
        "_is_test_artifact": _looks_like_test_artifact(payload, guest, reservation, message),
    }


async def _load_conflict_log(db: AsyncSession, adjudication_id: UUID) -> OperationalDeliberationLog:
    log = await db.get(OperationalDeliberationLog, adjudication_id)
    if log is None or log.verdict_type != "guest_resolve_conflict":
        raise HTTPException(status_code=404, detail="Adjudication not found")
    return log


async def _detail_payload(
    db: AsyncSession,
    log: OperationalDeliberationLog,
    *,
    dispatched_sessions: set[str] | None = None,
) -> dict[str, Any]:
    sessions = dispatched_sessions if dispatched_sessions is not None else await _dispatched_sessions(db)
    item = await _queue_item(db, log, dispatched_sessions=sessions)
    item.pop("_is_test_artifact", None)
    guest, reservation, prop, message = await _resolve_context(db, log)
    payload = _payload_dict(log)
    live_triage = await _compute_live_triage(
        db,
        guest=guest,
        reservation=reservation,
        message=message,
    )

    item["ledger_payload"] = payload
    item["live_triage"] = live_triage
    item["draft_reply"] = (
        ((live_triage or {}).get("draft_reply") or {}).get("text")
        if isinstance(live_triage, dict)
        else None
    )
    item["council"] = (
        (live_triage or {}).get("council")
        if isinstance(live_triage, dict) and "council" in live_triage
        else None
    )
    item["recommended_actions"] = (
        (live_triage or {}).get("recommended_actions")
        if isinstance(live_triage, dict) and "recommended_actions" in live_triage
        else payload.get("conflict_resolution", {}).get("departments_implicated", [])
    )
    return item


@router.get("/queue")
async def list_vrs_queue(
    limit: int = Query(default=25, ge=1, le=100),
    held_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_operator_manager_admin),
):
    dispatched_sessions = await _dispatched_sessions(db)
    raw_limit = min(max(limit * 4, limit), 200)
    result = await db.execute(
        select(OperationalDeliberationLog)
        .where(OperationalDeliberationLog.verdict_type == "guest_resolve_conflict")
        .order_by(OperationalDeliberationLog.created_at.desc())
        .limit(raw_limit)
    )
    rows = result.scalars().all()

    items: list[dict[str, Any]] = []
    held_count = 0
    dispatched_count = 0
    for log in rows:
        item = await _queue_item(db, log, dispatched_sessions=dispatched_sessions)
        if item.get("_is_test_artifact"):
            continue
        if item["status"] == "held":
            held_count += 1
        else:
            dispatched_count += 1
        if held_only and item["status"] != "held":
            continue
        item.pop("_is_test_artifact", None)
        items.append(item)
        if len(items) >= limit:
            break

    payload = {
        "items": items,
        "summary": {
            "held": held_count,
            "dispatched": dispatched_count,
            "total_scanned": len(rows),
        },
    }
    return payload


@router.post("/sync")
async def sync_vrs_queue(
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_operator_manager_admin),
):
    payload = await list_vrs_queue(limit=limit, held_only=True, db=db, _user=_user)
    payload["synced"] = True
    return payload


@router.get("/adjudications/{adjudication_id}")
async def get_vrs_adjudication(
    adjudication_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_operator_manager_admin),
):
    log = await _load_conflict_log(db, adjudication_id)
    return await _detail_payload(db, log)


@router.post("/adjudications/{adjudication_id}/override-dispatch")
async def override_vrs_dispatch(
    adjudication_id: UUID,
    body: OverrideDispatchRequest,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_operator_manager_admin),
):
    log = await _load_conflict_log(db, adjudication_id)
    dispatched_sessions = await _dispatched_sessions(db)
    if log.session_id in dispatched_sessions:
        raise HTTPException(status_code=409, detail="Adjudication already dispatched")

    guest, reservation, _prop, _message = await _resolve_context(db, log)
    detail = await _detail_payload(db, log, dispatched_sessions=dispatched_sessions)
    payload = _payload_dict(log)

    draft_body = (body.body or "").strip() or str(detail.get("draft_reply") or "").strip()
    if not draft_body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Override dispatch requires a message body",
        )

    conviction = body.consensus_conviction
    if conviction is None:
        conviction = _conviction(payload)

    try:
        dispatch = await run_guest_send_sms(
            db,
            guest_id=guest.id if guest is not None else None,
            reservation_id=reservation.id if reservation is not None else None,
            guest_phone=guest.phone_number if guest is not None else None,
            body=draft_body,
            consensus_conviction=conviction,
            minimum_conviction=body.minimum_conviction,
            session_id=log.session_id,
            source_workflow="vrs_command_center_override",
            trigger_type=f"VRS_COMMAND_CENTER_OVERRIDE:{user.role}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:500]) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)[:500]) from exc

    return {
        "status": "dispatched",
        "operator": {
            "id": str(user.id),
            "email": user.email,
            "role": user.role,
        },
        "dispatch": dispatch,
        "adjudication": await _detail_payload(db, log),
    }
