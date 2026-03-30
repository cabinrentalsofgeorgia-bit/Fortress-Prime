"""
Concierge Alpha shadow lane: legacy Rue Ba Rue template vs sovereign recovery drafts (Strike 16.4).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.recovery_parity_comparison import RecoveryParityComparison
from backend.models.rue_bar_rue_legacy_recovery_template import RueBaRueLegacyRecoveryTemplate
from backend.services.enticer_swarm_service import get_concierge_book_url
from backend.services.funnel_analytics_service import build_funnel_hq_payload

logger = logging.getLogger(__name__)


class _SafeFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:  # noqa: ARG002
        return ""


def compute_recovery_dedupe_hash(
    *,
    session_fp: str,
    drop_off_point: str,
    property_slug: str | None,
    guest_id: UUID | None,
    intent_score_estimate: float,
) -> str:
    """
    Stable identity for a recovery candidate + intent snapshot.

    Intent is included so materially stronger funnel signals create a fresh comparison row
    without spamming identical drafts every scheduler tick.
    """
    gid = str(guest_id) if guest_id is not None else ""
    slug = (property_slug or "").strip().lower()
    raw = f"{session_fp}|{drop_off_point}|{slug}|{gid}|{intent_score_estimate:.4f}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _first_name_from_candidate(cand: dict[str, Any]) -> str:
    name = (cand.get("guest_display_name") or "").strip()
    if name:
        return name.split()[0]
    return "there"


def _property_label(slug: str | None) -> str:
    if not slug:
        return "your cabin"
    return slug.replace("-", " ").title()


def _pick_legacy_template(
    rows: list[RueBaRueLegacyRecoveryTemplate],
    *,
    drop_off_point: str,
) -> RueBaRueLegacyRecoveryTemplate | None:
    exact = [r for r in rows if r.audience_rule == drop_off_point]
    if exact:
        return exact[0]
    wild = [r for r in rows if r.audience_rule == "*"]
    return wild[0] if wild else None


def _render_legacy_body(template: RueBaRueLegacyRecoveryTemplate, *, ctx: dict[str, str]) -> str:
    return template.body_template.format_map(_SafeFormatDict(ctx))


def _render_sovereign_recovery_body(
    *,
    first_name: str,
    property_slug: str | None,
    book_url: str,
    friction_label: str,
) -> str:
    cabin = _property_label(property_slug)
    friction = (friction_label or "the booking flow").strip().lower()
    return (
        f"Cabin Rentals of Georgia — Hi {first_name}, you left {cabin} in the funnel "
        f"({friction}). Your direct booking link is ready: {book_url}. Reply STOP to opt out."
    )


def _snapshot_last_seen(raw: dict[str, Any]) -> str | None:
    ls = raw.get("last_seen_at")
    if isinstance(ls, datetime):
        return ls.isoformat()
    if ls is None:
        return None
    return str(ls)


async def run_concierge_shadow_draft_cycle(
    db: AsyncSession,
    *,
    async_job_run_id: UUID | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """
    Pull high-intent recovery candidates, render legacy + sovereign SMS bodies, persist fresh rows.
    """
    if not settings.concierge_shadow_draft_enabled:
        return {
            "disabled": True,
            "candidates_considered": 0,
            "inserted_count": 0,
            "skipped_duplicate_count": 0,
            "skipped_no_template": 0,
        }

    limit = max(1, min(int(settings.concierge_recovery_parity_candidate_limit), 200))
    funnel = await build_funnel_hq_payload(db, recovery_limit=limit)
    recovery = funnel.get("recovery") if isinstance(funnel.get("recovery"), list) else []

    tpl_rows = list(
        (
            await db.execute(
                select(RueBaRueLegacyRecoveryTemplate).where(
                    RueBaRueLegacyRecoveryTemplate.is_active.is_(True),
                    RueBaRueLegacyRecoveryTemplate.channel == "sms",
                )
            )
        ).scalars().all()
    )

    book_url = get_concierge_book_url()
    inserted = 0
    skipped_dup = 0
    skipped_tpl = 0

    hashes: list[str] = []
    planned: list[tuple[str, dict[str, Any], RueBaRueLegacyRecoveryTemplate, str, str, str]] = []

    for raw in recovery:
        if not isinstance(raw, dict):
            continue
        session_fp = str(raw.get("session_fp") or "").strip()
        if not session_fp:
            continue
        drop_off = str(raw.get("drop_off_point") or raw.get("deepest_funnel_stage") or "other")
        pslug = raw.get("property_slug")
        property_slug = str(pslug).strip().lower() if pslug else None
        guest_raw = raw.get("linked_guest_id")
        try:
            guest_id = UUID(str(guest_raw)) if guest_raw else None
        except (ValueError, TypeError):
            guest_id = None
        try:
            intent = float(raw.get("intent_score_estimate") or 0.0)
        except (TypeError, ValueError):
            intent = 0.0

        template = _pick_legacy_template(tpl_rows, drop_off_point=drop_off)
        if template is None:
            skipped_tpl += 1
            continue

        first_name = _first_name_from_candidate(raw)
        friction = str(raw.get("friction_label") or "")
        ctx = {
            "first_name": first_name,
            "book_url": book_url,
            "property_slug": property_slug or "your cabin",
            "friction_label": friction,
        }
        legacy_body = _render_legacy_body(template, ctx=ctx)
        sovereign_body = _render_sovereign_recovery_body(
            first_name=first_name,
            property_slug=property_slug,
            book_url=book_url,
            friction_label=friction,
        )
        h = compute_recovery_dedupe_hash(
            session_fp=session_fp,
            drop_off_point=drop_off,
            property_slug=property_slug,
            guest_id=guest_id,
            intent_score_estimate=intent,
        )
        hashes.append(h)
        planned.append((h, raw, template, legacy_body, sovereign_body, drop_off))

    if not planned:
        return {
            "disabled": False,
            "candidates_considered": len(recovery),
            "inserted_count": 0,
            "skipped_duplicate_count": 0,
            "skipped_no_template": skipped_tpl,
            "request_id": request_id,
        }

    existing: set[str] = set()
    ex_stmt = select(RecoveryParityComparison.dedupe_hash).where(RecoveryParityComparison.dedupe_hash.in_(hashes))
    existing = {str(x) for x in (await db.execute(ex_stmt)).scalars().all()}

    for h, raw, template, legacy_body, sovereign_body, drop_off in planned:
        if h in existing:
            skipped_dup += 1
            continue
        session_fp = str(raw.get("session_fp") or "")
        guest_raw = raw.get("linked_guest_id")
        try:
            guest_id = UUID(str(guest_raw)) if guest_raw else None
        except (ValueError, TypeError):
            guest_id = None
        pslug = raw.get("property_slug")
        property_slug = str(pslug).strip().lower() if pslug else None
        try:
            intent = float(raw.get("intent_score_estimate") or 0.0)
        except (TypeError, ValueError):
            intent = 0.0

        parity_summary: dict[str, Any] = {
            "legacy_char_count": len(legacy_body),
            "sovereign_char_count": len(sovereign_body),
            "delta_chars": len(sovereign_body) - len(legacy_body),
        }
        candidate_snapshot: dict[str, Any] = {
            "session_fp_suffix": raw.get("session_fp_suffix"),
            "last_seen_at": _snapshot_last_seen(raw),
            "friction_label": raw.get("friction_label"),
            "drop_off_point_label": raw.get("drop_off_point_label"),
            "guest_display_name": raw.get("guest_display_name"),
        }
        row = RecoveryParityComparison(
            dedupe_hash=h,
            session_fp=session_fp,
            guest_id=guest_id,
            property_slug=property_slug,
            drop_off_point=drop_off,
            intent_score_estimate=intent,
            legacy_template_key=template.template_key,
            legacy_body=legacy_body,
            sovereign_body=sovereign_body,
            parity_summary=parity_summary,
            candidate_snapshot=candidate_snapshot,
            async_job_run_id=async_job_run_id,
        )
        db.add(row)
        inserted += 1
        existing.add(h)

    await db.commit()
    logger.info(
        "concierge_shadow_draft_cycle_complete",
        extra={
            "inserted": inserted,
            "skipped_duplicate": skipped_dup,
            "skipped_no_template": skipped_tpl,
            "candidates": len(recovery),
        },
    )
    return {
        "disabled": False,
        "candidates_considered": len(recovery),
        "inserted_count": inserted,
        "skipped_duplicate_count": skipped_dup,
        "skipped_no_template": skipped_tpl,
        "request_id": request_id,
    }
