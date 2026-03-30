"""
Roll up StorefrontIntentEvent rows into funnel edges + recovery candidates (Strike 10).

Staff-only consumers should call :func:`build_funnel_hq_payload` with a DB session.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.storefront_intent import EVENT_WEIGHTS
from backend.models.guest import Guest
from backend.models.storefront_intent import StorefrontIntentEvent
from backend.models.storefront_session_guest_link import StorefrontSessionGuestLink

# Ordered journey for leakage math (coarse; see sovereign-intent boundaries).
FUNNEL_PAIRS: list[tuple[str, str, str, str]] = [
    ("page_view", "property_view", "Browse", "Property view"),
    ("property_view", "quote_open", "Property view", "Quote opened"),
    ("quote_open", "checkout_step", "Quote opened", "Checkout step"),
    ("checkout_step", "funnel_hold_started", "Checkout step", "Hold started"),
]

_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Furthest stage reached in-window (friction identification for Recovery HQ).
DROP_OFF_POINT_LABELS: dict[str, str] = {
    "funnel_hold_started": "Hold started (rare in recovery queue)",
    "checkout_step": "Checkout step",
    "quote_open": "Quote opened",
    "property_view": "Property view",
    "page_view": "Browse",
    "other": "Early / unknown",
}


@dataclass(frozen=True)
class FunnelEdgeStat:
    from_stage: str
    to_stage: str
    from_label: str
    to_label: str
    from_count: int
    to_count: int
    retention_pct: float | None
    leakage_pct: float | None


@dataclass(frozen=True)
class RecoveryCandidate:
    session_fp_suffix: str
    session_fp: str
    last_event_type: str
    last_seen_at: datetime
    intent_score_estimate: float
    deepest_funnel_stage: str
    friction_label: str
    linked_guest_id: UUID | None
    property_slug: str | None
    meta: dict[str, Any]


def _session_types_from_rows(rows: list[tuple[str, str]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for fp, et in rows:
        out.setdefault(fp, set()).add(et)
    return out


def compute_funnel_edges(session_types: dict[str, set[str]]) -> list[FunnelEdgeStat]:
    """Pure funnel math for tests and :func:`build_funnel_hq_payload`."""
    stats: list[FunnelEdgeStat] = []
    for from_ev, to_ev, from_lbl, to_lbl in FUNNEL_PAIRS:
        from_count = sum(1 for types in session_types.values() if from_ev in types)
        to_count = sum(
            1 for types in session_types.values() if from_ev in types and to_ev in types
        )
        retention = (to_count / from_count) * 100.0 if from_count else None
        leakage = (100.0 - retention) if retention is not None else None
        stats.append(
            FunnelEdgeStat(
                from_stage=from_ev,
                to_stage=to_ev,
                from_label=from_lbl,
                to_label=to_lbl,
                from_count=from_count,
                to_count=to_count,
                retention_pct=round(retention, 2) if retention is not None else None,
                leakage_pct=round(leakage, 2) if leakage is not None else None,
            )
        )
    return stats


def _deepest_stage(types: set[str]) -> str:
    order = ["funnel_hold_started", "checkout_step", "quote_open", "property_view", "page_view"]
    for s in order:
        if s in types:
            return s
    return "other"


def _friction_label(deepest: str) -> str:
    return {
        "page_view": "Dropped after browse",
        "property_view": "Dropped after property view",
        "quote_open": "Dropped after quote",
        "checkout_step": "Dropped after checkout step",
        "funnel_hold_started": "Reached hold",
        "other": "Early / unknown",
    }.get(deepest, "Early / unknown")


def _intent_score(types: set[str]) -> float:
    return sum(EVENT_WEIGHTS.get(t, 0.0) for t in types)


def _norm_slug(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower()
    if not s or len(s) > 255:
        return None
    return s if _SLUG_OK.match(s) else None


async def build_funnel_hq_payload(
    db: AsyncSession,
    *,
    window_hours: int = 168,
    recovery_limit: int = 50,
    stale_after_hours: int = 2,
    min_stale_minutes: int | None = None,
) -> dict[str, Any]:
    window_hours = max(1, min(window_hours, 24 * 90))
    recovery_limit = max(1, min(recovery_limit, 200))
    stale_after_hours = max(1, min(stale_after_hours, 168))
    if min_stale_minutes is None:
        min_stale_minutes = stale_after_hours * 60
    min_stale_minutes = max(0, min(min_stale_minutes, 168 * 60))

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=window_hours)
    stale_before = now - timedelta(minutes=min_stale_minutes)

    detail_stmt = select(
        StorefrontIntentEvent.session_fp,
        StorefrontIntentEvent.event_type,
        StorefrontIntentEvent.created_at,
        StorefrontIntentEvent.property_slug,
        StorefrontIntentEvent.meta,
    ).where(StorefrontIntentEvent.created_at >= since)
    ev_rows = (await db.execute(detail_stmt)).all()

    session_types: dict[str, set[str]] = {}
    last_by_fp: dict[str, tuple[datetime, str, str | None, dict[str, Any]]] = {}
    for fp, et, created_at, pslug, meta in ev_rows:
        fp_s = str(fp)
        session_types.setdefault(fp_s, set()).add(str(et))
        prev = last_by_fp.get(fp_s)
        if prev is None or created_at > prev[0]:
            last_by_fp[fp_s] = (
                created_at,
                str(et),
                str(pslug) if pslug else None,
                meta if isinstance(meta, dict) else {},
            )

    edges = compute_funnel_edges(session_types)

    hold_fps: set[str] = set()
    if session_types:
        hold_stmt = select(StorefrontIntentEvent.session_fp).where(
            StorefrontIntentEvent.event_type == "funnel_hold_started",
            StorefrontIntentEvent.session_fp.in_(session_types.keys()),
        )
        hold_fps = {str(x) for x in (await db.execute(hold_stmt)).scalars().all()}

    recovery: list[RecoveryCandidate] = []
    for fp, types in session_types.items():
        if "quote_open" not in types and "checkout_step" not in types:
            continue
        if fp in hold_fps:
            continue
        last_row = last_by_fp.get(fp)
        if not last_row:
            continue
        last_at, last_type, last_slug, last_meta = last_row
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        if last_at > stale_before:
            continue
        deepest = _deepest_stage(types)
        recovery.append(
            RecoveryCandidate(
                session_fp_suffix=fp[-8:] if len(fp) >= 8 else fp,
                session_fp=fp,
                last_event_type=last_type,
                last_seen_at=last_at,
                intent_score_estimate=round(_intent_score(types), 2),
                deepest_funnel_stage=deepest,
                friction_label=_friction_label(deepest),
                linked_guest_id=None,
                property_slug=_norm_slug(last_slug),
                meta=last_meta,
            )
        )

    recovery.sort(
        key=lambda r: (r.intent_score_estimate, r.last_seen_at.timestamp()),
        reverse=True,
    )
    recovery = recovery[:recovery_limit]

    cand_fps = [r.session_fp for r in recovery]
    guest_by_fp: dict[str, UUID] = {}
    if cand_fps:
        try:
            link_stmt = (
                select(StorefrontSessionGuestLink)
                .where(StorefrontSessionGuestLink.session_fp.in_(cand_fps))
                .order_by(desc(StorefrontSessionGuestLink.created_at))
            )
            for link in (await db.execute(link_stmt)).scalars().all():
                fp = str(link.session_fp)
                if fp not in guest_by_fp:
                    guest_by_fp[fp] = link.guest_id
        except Exception:
            await db.rollback()

    guest_ids = list({gid for gid in guest_by_fp.values()})
    guest_rows: dict[UUID, Guest] = {}
    if guest_ids:
        try:
            gr = await db.execute(select(Guest).where(Guest.id.in_(guest_ids)))
            for g in gr.scalars().all():
                guest_rows[g.id] = g
        except Exception:
            await db.rollback()

    recovery_out: list[dict[str, Any]] = []
    for r in recovery:
        d = r.__dict__.copy()
        gid = guest_by_fp.get(r.session_fp)
        d["linked_guest_id"] = gid
        d["drop_off_point"] = r.deepest_funnel_stage
        d["drop_off_point_label"] = DROP_OFF_POINT_LABELS.get(
            r.deepest_funnel_stage, r.deepest_funnel_stage
        )
        if gid is not None and gid in guest_rows:
            g = guest_rows[gid]
            d["guest_email"] = g.email
            d["guest_phone"] = g.phone
            d["guest_display_name"] = f"{g.first_name} {g.last_name}".strip() or None
        else:
            d["guest_email"] = None
            d["guest_phone"] = None
            d["guest_display_name"] = None
        meta = r.meta if isinstance(r.meta, dict) else {}
        d["quote_id"] = str(meta.get("quote_id") or meta.get("guest_quote_id") or "").strip() or None
        d["cart_id"] = str(meta.get("cart_id") or d["quote_id"] or "").strip() or None
        d["check_in"] = str(meta.get("check_in") or "").strip() or None
        d["check_out"] = str(meta.get("check_out") or "").strip() or None
        d["adults"] = meta.get("adults")
        d["children"] = meta.get("children")
        d["pets"] = meta.get("pets")
        d["cart_value"] = (
            meta.get("cart_value")
            or meta.get("quote_total")
            or meta.get("total_amount")
            or meta.get("total")
        )
        recovery_out.append(d)

    return {
        "window_hours": window_hours,
        "distinct_sessions_in_window": len(session_types),
        "generated_at": now,
        "min_stale_minutes": min_stale_minutes,
        "edges": [e.__dict__ for e in edges],
        "recovery": recovery_out,
    }
