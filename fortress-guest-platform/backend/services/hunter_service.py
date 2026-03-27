"""
Reactivation Hunter queue sweep.

Target Alpha: abandoned quotes / checkout sessions stale for >= 2 hours.
Target Bravo: orphaned active holds past checkout TTL with no PaymentIntent.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.async_job import AsyncJobRun
from backend.models.guest import Guest
from backend.models.hunter import HunterQueueEntry, HunterRun
from backend.models.hunter_recovery_op import HunterRecoveryOp, HunterRecoveryOpStatus
from backend.models.property import Property
from backend.models.recovery_parity_comparison import RecoveryParityComparison
from backend.models.reservation_hold import ReservationHold
from backend.models.rue_bar_rue_legacy_recovery_template import RueBaRueLegacyRecoveryTemplate
from backend.models.storefront_intent import StorefrontIntentEvent
from backend.services.async_jobs import enqueue_async_job
from backend.services.concierge_recovery_parity import (
    _pick_legacy_template,
    _render_legacy_body,
    _render_sovereign_recovery_body,
    _SafeFormatDict,
    compute_recovery_dedupe_hash,
)
from backend.services.enticer_swarm_service import get_concierge_book_url
from backend.services.funnel_analytics_service import build_funnel_hq_payload
from backend.services.hold_service import HOLD_TTL_MINUTES
from backend.services.openshell_audit import record_audit_event

_HEX_SESSION_FP = re.compile(r"^[0-9a-f]{64}$")
_SYNTHETIC_EMAIL_DOMAINS = frozenset({"example.com", "crog-ai.com"})
_SYNTHETIC_IDENTITY_MARKERS = (
    "test",
    "smoke",
    "shadow",
    "manual",
    "dedicated",
    "synthetic",
    "sample",
    "demo",
)


@dataclass(frozen=True)
class HunterCandidate:
    session_fp: str
    property_id: UUID | None
    reservation_id: UUID | None
    guest_phone: str | None
    guest_email: str | None
    campaign: str
    payload: dict[str, Any]
    score: int


def _session_pepper() -> bytes:
    pepper = (settings.audit_log_signing_key or "").strip().encode()
    return pepper or b"fortress-dev-storefront-intent-pepper"


def _normalize_session_fp(raw_session: str | None) -> str:
    raw = str(raw_session or "").strip().lower()
    if not raw:
        return ""
    if _HEX_SESSION_FP.fullmatch(raw):
        return raw
    return hmac.new(_session_pepper(), raw.encode("utf-8"), hashlib.sha256).hexdigest()


def _iso_or_none(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value) if value is not None else None


def _score_target_alpha(intent_score_estimate: Any) -> int:
    try:
        numeric = float(intent_score_estimate or 0.0)
    except (TypeError, ValueError):
        numeric = 0.0
    return max(10, min(100, int(round(numeric * 20))))


def _candidate_payload(base: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in base.items() if value is not None}


def _normalize_email(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    return raw or None


def _normalize_phone(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw or None


def _humanize_slug(value: str | None) -> str | None:
    slug = str(value or "").strip().lower()
    if not slug:
        return None
    return " ".join(part.capitalize() for part in slug.split("-") if part)


def _parse_cart_value(value: Any) -> Decimal | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("$", "").replace(",", "")
    try:
        return Decimal(normalized).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _candidate_cart_id(candidate: HunterCandidate) -> str:
    payload = candidate.payload or {}
    for key in ("cart_id", "quote_id", "hold_id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return candidate.session_fp


def _candidate_guest_name(candidate: HunterCandidate) -> str | None:
    return str((candidate.payload or {}).get("guest_display_name") or "").strip() or None


def _candidate_cabin_name(candidate: HunterCandidate) -> str | None:
    payload = candidate.payload or {}
    return (
        str(payload.get("cabin_name") or payload.get("property_name") or "").strip()
        or _humanize_slug(payload.get("property_slug"))
    )


def _candidate_cart_value(candidate: HunterCandidate) -> Decimal | None:
    payload = candidate.payload or {}
    return _parse_cart_value(payload.get("cart_value"))


def _candidate_draft_context(candidate: HunterCandidate) -> dict[str, Any]:
    payload = candidate.payload or {}
    return _candidate_payload(
        {
            "cart_id": _candidate_cart_id(candidate),
            "session_fp": candidate.session_fp,
            "guest_name": _candidate_guest_name(candidate),
            "guest_email": candidate.guest_email,
            "guest_phone": candidate.guest_phone,
            "cabin_name": _candidate_cabin_name(candidate),
            "property_slug": payload.get("property_slug"),
            "campaign": candidate.campaign,
            "friction_label": payload.get("friction_label"),
            "drop_off_point": payload.get("drop_off_point"),
            "check_in": payload.get("check_in"),
            "check_out": payload.get("check_out"),
            "adults": payload.get("adults"),
            "children": payload.get("children"),
            "pets": payload.get("pets"),
            "cart_value": str(_candidate_cart_value(candidate)) if _candidate_cart_value(candidate) is not None else None,
            "source_domain": "cabin-rentals-of-georgia.com",
        }
    )


def _contains_synthetic_marker(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in _SYNTHETIC_IDENTITY_MARKERS)


def _is_synthetic_identity(*, guest_email: str | None, guest_display_name: Any) -> bool:
    email = _normalize_email(guest_email)
    if email:
        local_part, _, domain = email.partition("@")
        if domain in _SYNTHETIC_EMAIL_DOMAINS:
            return True
        if _contains_synthetic_marker(local_part):
            return True
    return _contains_synthetic_marker(guest_display_name)


def _has_recovery_contact_channel(*, guest_email: str | None, guest_phone: str | None) -> bool:
    return bool(_normalize_email(guest_email) or _normalize_phone(guest_phone))


async def _load_hunter_entry(db: AsyncSession, session_fp: str) -> HunterQueueEntry | None:
    return (
        await db.execute(
            select(HunterQueueEntry).where(HunterQueueEntry.session_fp == session_fp).limit(1)
        )
    ).scalar_one_or_none()


async def _load_hunter_recovery_op(db: AsyncSession, recovery_op_id: UUID) -> HunterRecoveryOp | None:
    return await db.get(HunterRecoveryOp, recovery_op_id)


async def _latest_recovery_meta_by_session(
    db: AsyncSession,
    session_fp: str,
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(StorefrontIntentEvent.meta)
            .where(StorefrontIntentEvent.session_fp == session_fp)
            .order_by(StorefrontIntentEvent.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row if isinstance(row, dict) else {}


async def _property_ids_by_slug(
    db: AsyncSession,
    slugs: set[str],
) -> dict[str, UUID]:
    if not slugs:
        return {}
    rows = (
        await db.execute(
            select(Property.slug, Property.id).where(Property.slug.in_(sorted(slugs)))
        )
    ).all()
    return {str(slug): property_id for slug, property_id in rows}


async def _collect_target_alpha_candidates(
    db: AsyncSession,
    *,
    limit: int,
) -> list[HunterCandidate]:
    funnel = await build_funnel_hq_payload(
        db,
        recovery_limit=limit,
        stale_after_hours=2,
        min_stale_minutes=120,
    )
    recovery_rows = funnel.get("recovery") if isinstance(funnel.get("recovery"), list) else []
    property_ids = await _property_ids_by_slug(
        db,
        {
            str(row.get("property_slug")).strip().lower()
            for row in recovery_rows
            if isinstance(row, dict) and row.get("property_slug")
        },
    )

    candidates: list[HunterCandidate] = []
    for row in recovery_rows:
        if not isinstance(row, dict):
            continue
        session_fp = _normalize_session_fp(str(row.get("session_fp") or ""))
        if not session_fp:
            continue
        guest_email = _normalize_email(row.get("guest_email"))
        guest_phone = _normalize_phone(row.get("guest_phone"))
        guest_display_name = row.get("guest_display_name")
        if not _has_recovery_contact_channel(guest_email=guest_email, guest_phone=guest_phone):
            continue
        if _is_synthetic_identity(guest_email=guest_email, guest_display_name=guest_display_name):
            continue

        property_slug_raw = row.get("property_slug")
        property_slug = (
            str(property_slug_raw).strip().lower() if property_slug_raw is not None else None
        )
        payload = _candidate_payload(
            {
                "prey_class": "abandoned_quote",
                "source": "storefront_intent",
                "cart_id": row.get("cart_id") or row.get("quote_id"),
                "quote_id": row.get("quote_id"),
                "drop_off_point": row.get("drop_off_point") or row.get("deepest_funnel_stage"),
                "drop_off_point_label": row.get("drop_off_point_label"),
                "friction_label": row.get("friction_label"),
                "last_event_type": row.get("last_event_type"),
                "last_seen_at": _iso_or_none(row.get("last_seen_at")),
                "session_fp_suffix": row.get("session_fp_suffix"),
                "property_slug": property_slug,
                "guest_display_name": guest_display_name,
                "linked_guest_id": str(row.get("linked_guest_id")) if row.get("linked_guest_id") else None,
                "intent_score_estimate": row.get("intent_score_estimate"),
                "check_in": row.get("check_in"),
                "check_out": row.get("check_out"),
                "adults": row.get("adults"),
                "children": row.get("children"),
                "pets": row.get("pets"),
                "cart_value": row.get("cart_value"),
            }
        )
        candidates.append(
            HunterCandidate(
                session_fp=session_fp,
                property_id=property_ids.get(property_slug) if property_slug else None,
                reservation_id=None,
                guest_phone=guest_phone,
                guest_email=guest_email,
                campaign="abandoned_quote",
                payload=payload,
                score=_score_target_alpha(row.get("intent_score_estimate")),
            )
        )
    return candidates


async def _collect_target_bravo_candidates(
    db: AsyncSession,
    *,
    limit: int,
) -> list[HunterCandidate]:
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=HOLD_TTL_MINUTES)
    stmt = (
        select(ReservationHold)
        .where(
            ReservationHold.status == "active",
            ReservationHold.payment_intent_id.is_(None),
            ReservationHold.created_at <= stale_before,
        )
        .order_by(ReservationHold.created_at.asc())
        .limit(limit)
    )
    holds = list((await db.execute(stmt)).scalars().all())

    candidates: list[HunterCandidate] = []
    for hold in holds:
        session_fp = _normalize_session_fp(hold.session_id)
        if not session_fp:
            continue

        guest: Guest | None = hold.guest
        guest_email = _normalize_email(guest.email if guest is not None else None)
        guest_phone = _normalize_phone(guest.phone if guest is not None else None)
        guest_display_name = guest.full_name if guest is not None else None
        if not _has_recovery_contact_channel(guest_email=guest_email, guest_phone=guest_phone):
            continue
        if _is_synthetic_identity(guest_email=guest_email, guest_display_name=guest_display_name):
            continue
        property_slug = hold.property.slug if hold.property is not None else None
        payload = _candidate_payload(
            {
                "prey_class": "orphaned_hold",
                "source": "reservation_holds",
                "hold_id": str(hold.id),
                "property_slug": property_slug,
                "guest_id": str(hold.guest_id) if hold.guest_id else None,
                "guest_display_name": guest_display_name,
                "hold_status": hold.status,
                "created_at": _iso_or_none(hold.created_at),
                "expires_at": _iso_or_none(hold.expires_at),
                "friction_label": "Hold created without payment intent",
                "timeout_minutes": HOLD_TTL_MINUTES,
                "check_in_date": hold.check_in_date.isoformat() if hold.check_in_date else None,
                "check_out_date": hold.check_out_date.isoformat() if hold.check_out_date else None,
            }
        )
        candidates.append(
            HunterCandidate(
                session_fp=session_fp,
                property_id=hold.property_id,
                reservation_id=None,
                guest_phone=guest_phone,
                guest_email=guest_email,
                campaign="orphaned_hold",
                payload=payload,
                score=100,
            )
        )
    return candidates


def _merge_candidates(candidates: list[HunterCandidate]) -> list[HunterCandidate]:
    merged: dict[str, HunterCandidate] = {}
    for candidate in candidates:
        existing = merged.get(candidate.session_fp)
        if existing is None or candidate.score >= existing.score:
            merged[candidate.session_fp] = candidate
    return list(merged.values())


async def _upsert_candidates(
    db: AsyncSession,
    candidates: list[HunterCandidate],
) -> tuple[int, int]:
    if not candidates:
        return (0, 0)

    session_fps = [candidate.session_fp for candidate in candidates]
    existing_session_fps = set(
        (await db.execute(select(HunterQueueEntry.session_fp).where(HunterQueueEntry.session_fp.in_(session_fps))))
        .scalars()
        .all()
    )

    values = [
        {
            "session_fp": candidate.session_fp,
            "property_id": candidate.property_id,
            "reservation_id": candidate.reservation_id,
            "guest_phone": candidate.guest_phone,
            "guest_email": candidate.guest_email,
            "campaign": candidate.campaign,
            "payload": candidate.payload,
            "score": candidate.score,
            "status": "queued",
            "last_error": None,
        }
        for candidate in candidates
    ]

    insert_stmt = pg_insert(HunterQueueEntry).values(values)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[HunterQueueEntry.session_fp],
        set_={
            "property_id": insert_stmt.excluded.property_id,
            "reservation_id": insert_stmt.excluded.reservation_id,
            "guest_phone": insert_stmt.excluded.guest_phone,
            "guest_email": insert_stmt.excluded.guest_email,
            "campaign": insert_stmt.excluded.campaign,
            "payload": insert_stmt.excluded.payload,
            "score": insert_stmt.excluded.score,
            "status": case(
                (HunterQueueEntry.status == "processing", HunterQueueEntry.status),
                else_="queued",
            ),
            "last_error": None,
            "updated_at": func.now(),
        },
    )
    await db.execute(upsert_stmt)
    return (len(candidates) - len(existing_session_fps), len(existing_session_fps))


async def _active_recovery_ops_by_cart_id(
    db: AsyncSession,
    cart_ids: list[str],
) -> dict[str, HunterRecoveryOp]:
    if not cart_ids:
        return {}
    rows = (
        await db.execute(
            select(HunterRecoveryOp)
            .where(HunterRecoveryOp.cart_id.in_(cart_ids))
            .where(
                HunterRecoveryOp.status.in_(
                    (
                        HunterRecoveryOpStatus.QUEUED,
                        HunterRecoveryOpStatus.EXECUTING,
                        HunterRecoveryOpStatus.DRAFT_READY,
                    )
                )
            )
            .order_by(HunterRecoveryOp.created_at.desc())
        )
    ).scalars().all()
    active: dict[str, HunterRecoveryOp] = {}
    for row in rows:
        if row.cart_id not in active:
            active[row.cart_id] = row
    return active


async def _inflight_recovery_job_ids(
    db: AsyncSession,
    recovery_op_ids: list[UUID],
) -> set[str]:
    if not recovery_op_ids:
        return set()
    rows = (
        await db.execute(
            select(AsyncJobRun.payload_json)
            .where(AsyncJobRun.job_name == "hunter_recovery_draft")
            .where(AsyncJobRun.status.in_(("queued", "running")))
        )
    ).scalars().all()
    target_ids = {str(value) for value in recovery_op_ids}
    inflight: set[str] = set()
    for payload in rows:
        if not isinstance(payload, dict):
            continue
        recovery_op_id = str(payload.get("recovery_op_id") or "").strip()
        if recovery_op_id and recovery_op_id in target_ids:
            inflight.add(recovery_op_id)
    return inflight


async def _stage_recovery_ops(
    db: AsyncSession,
    *,
    candidates: list[HunterCandidate],
    requested_by: str,
) -> dict[str, int]:
    alpha_candidates = [candidate for candidate in candidates if candidate.campaign == "abandoned_quote"]
    if not alpha_candidates:
        return {"created_count": 0, "updated_count": 0, "enqueued_count": 0}

    cart_ids = [_candidate_cart_id(candidate) for candidate in alpha_candidates]
    active_ops = await _active_recovery_ops_by_cart_id(db, cart_ids)

    staged_rows: list[tuple[HunterRecoveryOp, HunterCandidate]] = []
    created_count = 0
    updated_count = 0
    for candidate in alpha_candidates:
        cart_id = _candidate_cart_id(candidate)
        guest_name = _candidate_guest_name(candidate)
        cabin_name = _candidate_cabin_name(candidate)
        cart_value = _candidate_cart_value(candidate)
        existing = active_ops.get(cart_id)
        if existing is not None:
            existing.guest_name = guest_name
            existing.cabin_name = cabin_name
            existing.cart_value = cart_value
            updated_count += 1
            staged_rows.append((existing, candidate))
            continue

        row = HunterRecoveryOp(
            cart_id=cart_id,
            guest_name=guest_name,
            cabin_name=cabin_name,
            cart_value=cart_value,
            status=HunterRecoveryOpStatus.QUEUED,
        )
        db.add(row)
        await db.flush()
        active_ops[cart_id] = row
        staged_rows.append((row, candidate))
        created_count += 1

    await db.commit()

    inflight = await _inflight_recovery_job_ids(db, [row.id for row, _ in staged_rows if row.id is not None])
    enqueued_count = 0
    for row, candidate in staged_rows:
        if row.status != HunterRecoveryOpStatus.QUEUED:
            continue
        if str(row.id) in inflight:
            continue
        await enqueue_async_job(
            db,
            worker_name="run_hunter_recovery_draft_job",
            job_name="hunter_recovery_draft",
            payload={
                "recovery_op_id": str(row.id),
                "draft_context": _candidate_draft_context(candidate),
            },
            requested_by=requested_by,
            tenant_id=None,
            request_id=f"hunter-recovery-draft:{str(row.id)[:12]}",
        )
        enqueued_count += 1

    return {
        "created_count": created_count,
        "updated_count": updated_count,
        "enqueued_count": enqueued_count,
    }


async def delete_hunter_candidate(db: AsyncSession, session_fp: str) -> bool:
    entry = await _load_hunter_entry(db, session_fp)
    if entry is None:
        return False
    await db.delete(entry)
    await db.commit()
    return True


def _first_name_from_entry(entry: HunterQueueEntry) -> str:
    display_name = str((entry.payload or {}).get("guest_display_name") or "").strip()
    if display_name:
        return display_name.split()[0]
    email = (entry.guest_email or "").strip()
    if email:
        return email.split("@")[0].split(".")[0] or "there"
    return "there"


def _drop_off_point_from_entry(entry: HunterQueueEntry) -> str:
    payload = entry.payload or {}
    return str(
        payload.get("drop_off_point")
        or payload.get("prey_class")
        or entry.campaign
        or "other"
    ).strip()


def _intent_from_entry(entry: HunterQueueEntry) -> float:
    raw = (entry.payload or {}).get("intent_score_estimate")
    try:
        return float(raw) if raw is not None else float(entry.score) / 10.0
    except (TypeError, ValueError):
        return float(entry.score) / 10.0


def _nemoclaw_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = str(settings.nemoclaw_orchestrator_api_key or "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _nemoclaw_verify_ssl(base_url: str) -> bool:
    override = (os.getenv("NEMOCLAW_ORCHESTRATOR_VERIFY_SSL") or "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False

    host = (urlsplit(base_url).hostname or "").strip().lower()
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback)


def _extract_assigned_worker(action_log: list[str]) -> str | None:
    for entry in action_log:
        if not isinstance(entry, str):
            continue
        if entry.startswith("worker_node_ip="):
            worker_ip = entry.split("=", 1)[1].strip()
            if worker_ip:
                return worker_ip
        if entry.startswith("worker_label="):
            worker_label = entry.split("=", 1)[1].strip()
            if worker_label:
                return worker_label
    return None


async def _dispatch_recovery_draft(
    *,
    recovery_op_id: UUID,
    draft_context: dict[str, Any],
) -> dict[str, Any]:
    base_url = str(settings.nemoclaw_orchestrator_url or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("NemoClaw orchestrator URL is not configured")

    payload = {
        "task_id": f"hunter-recovery-{recovery_op_id}",
        "intent": "draft_recovery_email",
        "context_payload": draft_context,
    }
    timeout = httpx.Timeout(75.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, verify=_nemoclaw_verify_ssl(base_url)) as client:
        response = await client.post(
            f"{base_url}/api/agent/execute",
            json=payload,
            headers=_nemoclaw_headers(),
        )
        response.raise_for_status()
        response_json = response.json() if response.content else {}
    if not isinstance(response_json, dict):
        raise RuntimeError("NemoClaw returned a non-object response")
    return response_json


async def mark_hunter_recovery_op_retry(
    db: AsyncSession,
    *,
    recovery_op_id: UUID,
    request_id: str | None = None,
    error_text: str,
) -> None:
    row = await _load_hunter_recovery_op(db, recovery_op_id)
    if row is None:
        return
    row.status = HunterRecoveryOpStatus.QUEUED
    row.assigned_worker = None
    await db.commit()
    await record_audit_event(
        actor_id="hunter_recovery_worker",
        action="draft_recovery_email_failed",
        resource_type="hunter_recovery_op",
        resource_id=str(recovery_op_id),
        purpose="internal_revenue_recovery",
        tool_name="nemoclaw",
        model_route=settings.orchestrator_source,
        outcome="failure",
        request_id=request_id,
        metadata_json={"error": error_text[:1000]},
        db=db,
    )


async def execute_hunter_recovery_draft(
    db: AsyncSession,
    *,
    recovery_op_id: UUID,
    draft_context: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    row = await _load_hunter_recovery_op(db, recovery_op_id)
    if row is None:
        raise RuntimeError(f"Hunter recovery op {recovery_op_id} not found")
    if row.status == HunterRecoveryOpStatus.DISPATCHED:
        raise RuntimeError(f"Hunter recovery op {recovery_op_id} is already dispatched")

    row.status = HunterRecoveryOpStatus.EXECUTING
    await db.commit()

    latest_meta = await _latest_recovery_meta_by_session(db, row.cart_id)
    merged_context = _candidate_payload(
        {
            **(latest_meta if isinstance(latest_meta, dict) else {}),
            **(draft_context or {}),
            "cart_id": row.cart_id,
            "guest_name": row.guest_name,
            "cabin_name": row.cabin_name,
            "cart_value": str(row.cart_value) if row.cart_value is not None else None,
        }
    )

    response_json = await _dispatch_recovery_draft(
        recovery_op_id=recovery_op_id,
        draft_context=merged_context,
    )
    action_log = response_json.get("action_log") if isinstance(response_json.get("action_log"), list) else []
    result_payload = (
        response_json.get("result_payload")
        if isinstance(response_json.get("result_payload"), dict)
        else {}
    )
    draft_body = str(result_payload.get("draft_body") or "").strip()
    if not draft_body:
        raise RuntimeError("NemoClaw draft response did not include draft_body")

    row.ai_draft_body = draft_body
    row.status = HunterRecoveryOpStatus.DRAFT_READY
    row.assigned_worker = _extract_assigned_worker([str(item) for item in action_log])
    await db.commit()
    await record_audit_event(
        actor_id="hunter_recovery_worker",
        action="draft_recovery_email_ready",
        resource_type="hunter_recovery_op",
        resource_id=str(recovery_op_id),
        purpose="internal_revenue_recovery",
        tool_name="nemoclaw",
        model_route=settings.orchestrator_source,
        outcome="success",
        request_id=request_id,
        metadata_json={
            "assigned_worker": row.assigned_worker,
            "cart_id": row.cart_id,
            "action_log": [str(item)[:200] for item in action_log[:8]],
        },
        db=db,
    )
    return {
        "recovery_op_id": str(row.id),
        "status": "draft_ready",
        "queue_status": row.status.value,
        "assigned_worker": row.assigned_worker,
    }


async def mark_hunter_candidate_failed(
    db: AsyncSession,
    *,
    session_fp: str,
    error_text: str,
) -> None:
    entry = await _load_hunter_entry(db, session_fp)
    if entry is None:
        return
    entry.status = "failed"
    entry.last_error = error_text[:1000]
    await db.commit()


async def execute_hunter_candidate(
    db: AsyncSession,
    *,
    session_fp: str,
    async_job_run_id: UUID | None = None,
) -> dict[str, Any]:
    entry = await _load_hunter_entry(db, session_fp)
    if entry is None:
        raise RuntimeError(f"Hunter candidate {session_fp} not found")

    payload = entry.payload or {}
    drop_off_point = _drop_off_point_from_entry(entry)
    property_slug = str(payload.get("property_slug") or "").strip().lower() or None
    guest_raw = payload.get("linked_guest_id")
    try:
        guest_id = UUID(str(guest_raw)) if guest_raw else None
    except (TypeError, ValueError):
        guest_id = None

    intent = _intent_from_entry(entry)
    first_name = _first_name_from_entry(entry)
    friction = str(payload.get("friction_label") or "").strip()
    book_url = get_concierge_book_url()

    templates = list(
        (
            await db.execute(
                select(RueBaRueLegacyRecoveryTemplate).where(
                    RueBaRueLegacyRecoveryTemplate.is_active.is_(True),
                    RueBaRueLegacyRecoveryTemplate.channel == "sms",
                )
            )
        ).scalars().all()
    )
    template = _pick_legacy_template(templates, drop_off_point=drop_off_point)
    if template is None:
        raise RuntimeError(f"No active recovery template for drop-off point {drop_off_point}")

    ctx = _SafeFormatDict(
        {
            "first_name": first_name,
            "book_url": book_url,
            "property_slug": property_slug or "your cabin",
            "friction_label": friction,
        }
    )
    legacy_body = _render_legacy_body(template, ctx=ctx)
    sovereign_body = _render_sovereign_recovery_body(
        first_name=first_name,
        property_slug=property_slug,
        book_url=book_url,
        friction_label=friction,
    )
    dedupe_hash = compute_recovery_dedupe_hash(
        session_fp=session_fp,
        drop_off_point=drop_off_point,
        property_slug=property_slug,
        guest_id=guest_id,
        intent_score_estimate=intent,
    )

    existing = (
        await db.execute(
            select(RecoveryParityComparison).where(
                RecoveryParityComparison.dedupe_hash == dedupe_hash
            )
        )
    ).scalar_one_or_none()

    created = False
    comparison = existing
    if comparison is None:
        comparison = RecoveryParityComparison(
            dedupe_hash=dedupe_hash,
            session_fp=session_fp,
            guest_id=guest_id,
            property_slug=property_slug,
            drop_off_point=drop_off_point,
            intent_score_estimate=intent,
            legacy_template_key=template.template_key,
            legacy_body=legacy_body,
            sovereign_body=sovereign_body,
            parity_summary={
                "legacy_char_count": len(legacy_body),
                "sovereign_char_count": len(sovereign_body),
                "delta_chars": len(sovereign_body) - len(legacy_body),
                "trigger": "hunter_execute",
            },
            candidate_snapshot=_candidate_payload(
                {
                    "session_fp_suffix": payload.get("session_fp_suffix"),
                    "last_seen_at": payload.get("last_seen_at"),
                    "friction_label": payload.get("friction_label"),
                    "drop_off_point_label": payload.get("drop_off_point_label"),
                    "guest_display_name": payload.get("guest_display_name"),
                    "prey_class": payload.get("prey_class"),
                }
            ),
            async_job_run_id=async_job_run_id,
        )
        db.add(comparison)
        created = True

    entry.status = "sent"
    entry.last_error = None
    payload["last_triggered_at"] = datetime.utcnow().isoformat()
    payload["last_triggered_job_id"] = str(async_job_run_id) if async_job_run_id else None
    payload["draft_ready"] = True
    payload["recovery_parity_comparison_id"] = str(comparison.id) if comparison and comparison.id else None
    entry.payload = payload
    await db.flush()
    if comparison is not None and payload.get("recovery_parity_comparison_id") in {None, ""}:
        entry.payload["recovery_parity_comparison_id"] = str(comparison.id)
    await db.commit()

    return {
        "session_fp": session_fp,
        "status": "draft_generated",
        "created": created,
        "recovery_parity_comparison_id": str(comparison.id) if comparison is not None else None,
        "queue_status": entry.status,
    }


async def sweep_hunter_queue(
    db: AsyncSession,
    *,
    candidate_limit: int | None = None,
    trigger: str = "scheduled",
) -> dict[str, Any]:
    limit = max(1, min(int(candidate_limit or settings.hunter_queue_candidate_limit), 200))
    started_at = datetime.utcnow()
    run = HunterRun(trigger=trigger, campaign="reactivation", stats={})
    db.add(run)
    await db.flush()

    target_alpha = await _collect_target_alpha_candidates(db, limit=limit)
    target_bravo = await _collect_target_bravo_candidates(db, limit=limit)
    merged = _merge_candidates([*target_alpha, *target_bravo])
    inserted_count, updated_count = await _upsert_candidates(db, merged)
    recovery_ops = await _stage_recovery_ops(
        db,
        candidates=target_alpha,
        requested_by="system_hunter_queue_sweep",
    )

    completed_at = datetime.utcnow()
    summary = {
        "trigger": trigger,
        "candidate_limit": limit,
        "target_alpha_count": len(target_alpha),
        "target_bravo_count": len(target_bravo),
        "queued_candidates": len(merged),
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "recovery_ops_created_count": recovery_ops["created_count"],
        "recovery_ops_updated_count": recovery_ops["updated_count"],
        "recovery_ops_enqueued_count": recovery_ops["enqueued_count"],
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    run.stats = summary
    run.completed_at = completed_at
    await db.commit()
    return summary
