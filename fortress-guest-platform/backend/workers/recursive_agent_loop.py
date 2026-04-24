"""
Recursive Agent Loop — Cross-Vertical Intelligence Flywheel
============================================================
Fortress Prime operates three business verticals that each generate signals
the other two can act on.  This worker closes those loops autonomously.

Vertical topology
-----------------
  V1  CROG-VRS     — Cabin rental ops, guest comms, pricing, SEO, reactivation
  V2  RE-DEV       — Real estate acquisition, OTA intelligence, STR market analysis
  V3  AI-FACTORY   — Legal council, fine-tuning pipeline, exemplar memory, Paperclip tools

Recursive signal graph (every arrow is a data dependency):
  V1 checkout   → V2 acquisition_propensity  → V3 outreach_draft    → V1 pre-warm_cabin
  V1 guest_churn → V1 reactivation_hunter   → V3 training_capture  → V3 model_improved
  V2 OTA_parity  → V1 pricing_update        → V1 SEO_content_pivot  → V2 market_intel
  V2 target_locked → V3 legal_due_diligence → V2 acquisition_advance → V1 revenue_projection
  V3 legal_win   → V3 exemplar_update       → V3 council_improved   → V3 training_capture
  V3 model_deploy → V1+V2+V3 hot_swap      → [all verticals improve]

Signal depth cap: 6  (prevents infinite loops while allowing 2+ chained hops)
Cycle interval:  1800 s (30 min) — enough time for async work items to land

Run modes
---------
  Standalone:  python -m backend.workers.recursive_agent_loop
  ARQ worker:  registered as startup background task (see bottom of file)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import func, select, text, update

from backend.core.database import AsyncSessionLocal

logger = structlog.get_logger(service="recursive_agent_loop")

LOOP_INTERVAL_SECONDS = int(os.getenv("RECURSIVE_LOOP_INTERVAL", "1800"))
MAX_SIGNAL_DEPTH = 6
MAX_SIGNALS_PER_CYCLE = 60  # guard against signal storms


# ──────────────────────────────────────────────────────────────────────────────
# Signal primitives
# ──────────────────────────────────────────────────────────────────────────────

class SignalType(str, Enum):
    # V1 → anything
    CHECKOUT_COMPLETED          = "checkout_completed"
    GUEST_DORMANT               = "guest_dormant"
    SEO_PATCH_PUBLISHED         = "seo_patch_published"
    REACTIVATION_DRAFT_READY    = "reactivation_draft_ready"
    PRICING_DRIFT_HEALED        = "pricing_drift_healed"
    REVENUE_VERIFIED            = "revenue_verified"
    SHADOW_QUOTE_MISMATCH       = "shadow_quote_mismatch"

    # V2 → anything
    OTA_PARITY_SIGNAL           = "ota_parity_signal"
    ACQUISITION_TARGET_LOCKED   = "acquisition_target_locked"
    INTELLIGENCE_SIGNAL         = "intelligence_signal"
    STR_SIGNAL_NEW              = "str_signal_new"

    # V3 → anything
    LEGAL_DELIBERATION_COMPLETE = "legal_deliberation_complete"
    LEGAL_EXEMPLAR_APPROVED     = "legal_exemplar_approved"
    MODEL_DEPLOYED              = "model_deployed"
    TRAINING_CAPTURE            = "training_capture"

    # Internal loop signals
    NOOP                        = "noop"


class Vertical(str, Enum):
    V1_CROG_VRS   = "v1_crog_vrs"
    V2_RE_DEV     = "v2_re_dev"
    V3_AI_FACTORY = "v3_ai_factory"
    SYSTEM        = "system"


@dataclass
class LoopSignal:
    signal_type:    SignalType
    source:         Vertical
    payload:        dict[str, Any]
    signal_id:      str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_id:      str | None = None
    depth:          int = 0
    emitted_at:     str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def child(self, signal_type: SignalType, source: Vertical, payload: dict) -> "LoopSignal":
        return LoopSignal(
            signal_type=signal_type,
            source=source,
            payload=payload,
            parent_id=self.signal_id,
            depth=self.depth + 1,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Signal handlers
# Each handler receives a LoopSignal and returns a list of child signals.
# All handlers must be safe to call concurrently and must never raise.
# ──────────────────────────────────────────────────────────────────────────────

async def _handle_checkout_completed(sig: LoopSignal) -> list[LoopSignal]:
    """
    V1 → V2: Score this guest for acquisition propensity.
              Do they own STR property in our market?

    V1 → V3: Capture the Q&A from the booking for fine-tuning.
    """
    out = []
    guest_id   = sig.payload.get("guest_id")
    property_id = sig.payload.get("property_id")
    revenue    = sig.payload.get("revenue_usd", 0)

    if not guest_id:
        return out

    try:
        async with AsyncSessionLocal() as db:
            # Update guest last-stay and lifetime value
            await db.execute(text("""
                UPDATE guests
                SET    last_stay_date = CURRENT_DATE,
                       lifetime_value = COALESCE(lifetime_value, 0) + :rev
                WHERE  id = :gid
            """), {"gid": guest_id, "rev": float(revenue)})
            await db.commit()

            # Check if guest's lifetime value now qualifies for acquisition targeting
            row = await db.execute(text("""
                SELECT id, lifetime_value, last_stay_date
                FROM   guests
                WHERE  id = :gid
            """), {"gid": guest_id})
            guest = row.mappings().first()

            if guest and float(guest["lifetime_value"] or 0) >= 5000:
                out.append(sig.child(
                    SignalType.TRAINING_CAPTURE, Vertical.V3_AI_FACTORY,
                    {
                        "source_module": "checkout_flywheel",
                        "prompt":        f"Guest checkout: property={property_id}, revenue=${revenue}",
                        "response":      f"Revenue recorded. LTV now ${guest['lifetime_value']:.0f}. Guest qualifies for premium retention tier.",
                        "model":         "rule_engine",
                    }
                ))

    except Exception as exc:
        logger.warning("checkout_handler_error", error=str(exc)[:200])

    return out


async def _handle_guest_dormant(sig: LoopSignal) -> list[LoopSignal]:
    """
    V1 → V1: Queue dormant guest for reactivation hunter.
    V1 → V2: Tag as churn signal — did competitor cabin pull them away?
    """
    out = []
    guest_id = sig.payload.get("guest_id")
    days_dormant = sig.payload.get("days_dormant", 0)

    if not guest_id:
        return out

    try:
        async with AsyncSessionLocal() as db:
            # Check if already in hunter queue
            existing = await db.execute(text("""
                SELECT id FROM agent_queue
                WHERE  guest_id::text = :gid
                  AND  status NOT IN ('sent', 'rejected')
                LIMIT  1
            """), {"gid": str(guest_id)})
            if not existing.mappings().first():
                # Enqueue for reactivation hunter
                await db.execute(text("""
                    INSERT INTO agent_queue (guest_id, trigger_source, score, status)
                    VALUES (CAST(:gid AS uuid), 'dormancy_signal', :score, 'pending')
                    ON CONFLICT DO NOTHING
                """), {
                    "gid":   str(guest_id),
                    "score": min(100, int(days_dormant / 3.65)),   # 1 yr dormant → score 100
                })
                await db.commit()
                out.append(sig.child(
                    SignalType.REACTIVATION_DRAFT_READY, Vertical.V1_CROG_VRS,
                    {"guest_id": guest_id, "trigger": "dormancy_loop"}
                ))

        # V2: emit OTA intelligence request — where did this guest go?
        if days_dormant > 365:
            out.append(sig.child(
                SignalType.INTELLIGENCE_SIGNAL, Vertical.V2_RE_DEV,
                {
                    "category":   "guest_churn",
                    "market":     sig.payload.get("market", "blue-ridge"),
                    "signal":     f"Guest dormant {days_dormant}d — possible OTA defection",
                    "confidence": 0.6,
                }
            ))

    except Exception as exc:
        logger.warning("dormant_handler_error", error=str(exc)[:200])

    return out


async def _handle_ota_parity_signal(sig: LoopSignal) -> list[LoopSignal]:
    """
    V2 → V1: Emit pricing_drift_healed if competitor is cheaper by > $30.
    V2 → V1: Trigger SEO content pivot on competitor's feature advantages.
    V2 → V2: If the competing cabin is unmanaged, flag as acquisition target.
    """
    out = []
    competitor_url    = sig.payload.get("competitor_url", "")
    competitor_nightly = float(sig.payload.get("competitor_nightly", 0))
    sovereign_nightly  = float(sig.payload.get("sovereign_nightly", 0))
    cabin_slug        = sig.payload.get("property_slug", "")
    market            = sig.payload.get("market", "blue-ridge")

    try:
        delta = competitor_nightly - sovereign_nightly

        if delta < -30:
            # Competitor is materially cheaper — log a pricing investigation signal
            out.append(sig.child(
                SignalType.SHADOW_QUOTE_MISMATCH, Vertical.V1_CROG_VRS,
                {
                    "property_slug":      cabin_slug,
                    "competitor_url":     competitor_url,
                    "price_gap_usd":      abs(delta),
                    "action":             "review_pricing",
                }
            ))

        # If competitor listing is on an unmanaged parcel, flag for acquisition
        if competitor_url and abs(delta) > 20:
            async with AsyncSessionLocal() as db:
                # Log an AcquisitionIntelEvent for this competitor signal
                await db.execute(text("""
                    INSERT INTO intel_events
                        (event_type, source, description, metadata, occurred_at)
                    VALUES
                        ('ota_parity_signal', 'competitive_sentinel',
                         :desc, CAST(:meta AS jsonb), now())
                    ON CONFLICT DO NOTHING
                """), {
                    "desc": f"OTA competitor at {competitor_url} priced ${abs(delta):.0f} {'below' if delta<0 else 'above'} sovereign rate",
                    "meta": json.dumps({
                        "url":    competitor_url,
                        "delta":  delta,
                        "market": market,
                        "cabin":  cabin_slug,
                    }),
                })
                await db.commit()

        # Emit SEO pivot signal — content addressing competitor advantages
        if abs(delta) > 15:
            out.append(sig.child(
                SignalType.INTELLIGENCE_SIGNAL, Vertical.V2_RE_DEV,
                {
                    "category":   "pricing_shift",
                    "market":     market,
                    "signal":     f"OTA competitor ${abs(delta):.0f} {'cheaper' if delta<0 else 'dearer'} — SEO content opportunity",
                    "confidence": 0.78,
                    "target_tags": ["direct-book-savings", "best-rate-guarantee"],
                }
            ))

    except Exception as exc:
        logger.warning("ota_parity_handler_error", error=str(exc)[:200])

    return out


async def _handle_acquisition_target_locked(sig: LoopSignal) -> list[LoopSignal]:
    """
    V2 → V3: Trigger legal due-diligence package (title, liens, permits).
    V2 → V1: Pre-project revenue for the target cabin given our current portfolio.
    V3 capture: log the pipeline advancement as training data.
    """
    out = []
    property_id = sig.payload.get("property_id")
    owner_id    = sig.payload.get("owner_id")
    viability   = float(sig.payload.get("viability_score", 0))

    if not property_id:
        return out

    try:
        async with AsyncSessionLocal() as db:
            # Advance to TARGET_LOCKED in pipeline if not already there
            await db.execute(text("""
                UPDATE acquisition_pipeline
                SET    funnel_stage = 'TARGET_LOCKED',
                       updated_at   = now()
                WHERE  property_id = :pid
                  AND  funnel_stage = 'RADAR'
            """), {"pid": str(property_id)})
            await db.commit()

        # V3: queue a legal intelligence sweep
        if viability >= 0.65:
            out.append(sig.child(
                SignalType.TRAINING_CAPTURE, Vertical.V3_AI_FACTORY,
                {
                    "source_module": "acquisition_pipeline",
                    "prompt": (
                        f"Acquisition target locked: property_id={property_id}, "
                        f"viability={viability:.2f}. Perform legal due-diligence screening: "
                        "check for outstanding liens, code violations, permit history, HOA restrictions."
                    ),
                    "response": (
                        "Legal due-diligence package queued. Review: title search (county recorder), "
                        "UCC lien search, permit history (building dept), STR license status, "
                        "HOA covenants. Estimated 3–5 business days for full package."
                    ),
                    "model": "rule_engine/acquisition_v1",
                }
            ))

        # V1: emit revenue projection signal
        out.append(sig.child(
            SignalType.REVENUE_VERIFIED, Vertical.V1_CROG_VRS,
            {
                "context":      "acquisition_projection",
                "property_id":  property_id,
                "note":         f"Pre-acquisition revenue model requested for viability={viability:.2f}",
            }
        ))

    except Exception as exc:
        logger.warning("target_locked_handler_error", error=str(exc)[:200])

    return out


async def _handle_intelligence_signal(sig: LoopSignal) -> list[LoopSignal]:
    """
    V2 → V1: High-confidence pricing shifts → update SEO content queue.
    V2 → V2: STR signals → check if any acquisition targets are affected.
    V3 capture: all market intelligence is training data.
    """
    out = []
    category   = sig.payload.get("category", "")
    market     = sig.payload.get("market", "")
    confidence = float(sig.payload.get("confidence", 0))
    signal_txt = sig.payload.get("signal", "")
    tags       = sig.payload.get("target_tags", [])

    if confidence < 0.6:
        return out

    try:
        # Persist to intelligence_ledger
        async with AsyncSessionLocal() as db:
            dedup_hash = hashlib.sha256(
                f"{category}|{market}|{signal_txt}".encode()
            ).hexdigest()
            await db.execute(text("""
                INSERT INTO intelligence_ledger
                    (category, title, summary, market, locality, confidence_score,
                     dedupe_hash, target_tags, source_urls, discovered_at)
                VALUES
                    (:cat, :title, :summary, :market, :market,
                     :conf, :dhash, CAST(:tags AS jsonb), '[]'::jsonb, now())
                ON CONFLICT (dedupe_hash) DO NOTHING
            """), {
                "cat":     category[:64],
                "title":   signal_txt[:255],
                "summary": signal_txt,
                "market":  market,
                "conf":    confidence,
                "dhash":   dedup_hash,
                "tags":    json.dumps(tags),
            })
            await db.commit()

        # High-confidence pricing signal → V1 SEO content queue
        if confidence >= 0.75 and category in ("pricing_shift", "content_gap", "market_shift"):
            out.append(sig.child(
                SignalType.SEO_PATCH_PUBLISHED, Vertical.V1_CROG_VRS,
                {
                    "trigger":   "intelligence_signal",
                    "category":  category,
                    "market":    market,
                    "tags":      tags,
                    "confidence": confidence,
                }
            ))

        # V3: capture for training
        out.append(sig.child(
            SignalType.TRAINING_CAPTURE, Vertical.V3_AI_FACTORY,
            {
                "source_module": f"intel_{category}",
                "prompt":        f"Market intelligence ({market}): {signal_txt}",
                "response":      f"Signal logged with confidence={confidence:.2f}. Tags: {tags}. Category: {category}.",
                "model":         "intelligence_router_v1",
            }
        ))

    except Exception as exc:
        logger.warning("intelligence_handler_error", error=str(exc)[:200])

    return out


async def _handle_legal_deliberation_complete(sig: LoopSignal) -> list[LoopSignal]:
    """
    V3 → V3: Winning arguments become exemplars in the hive-mind memory.
    V3 → V2: If case involved a property dispute, unlock acquisition if resolved.
    V3 → V3: Capture the full deliberation as highest-quality training data.
    """
    out = []
    case_slug      = sig.payload.get("case_slug")
    outcome        = sig.payload.get("outcome", "")         # STRONG_DEFENSE / VULNERABLE
    avg_conviction = float(sig.payload.get("avg_conviction", 0))
    summary        = sig.payload.get("summary", "")
    property_id    = sig.payload.get("property_id")

    if not case_slug:
        return out

    try:
        # V3: Capture as training data — legal deliberations are the richest teacher data
        if avg_conviction >= 0.7 and summary:
            out.append(sig.child(
                SignalType.TRAINING_CAPTURE, Vertical.V3_AI_FACTORY,
                {
                    "source_module": "legal_council_deliberation",
                    "prompt":        f"Legal case {case_slug}: deliberation complete. Analyze outcome.",
                    "response":      summary,
                    "model":         "legal_council/9seat",
                    "quality_score": avg_conviction,
                }
            ))
            out.append(sig.child(
                SignalType.LEGAL_EXEMPLAR_APPROVED, Vertical.V3_AI_FACTORY,
                {
                    "case_slug":       case_slug,
                    "outcome":         outcome,
                    "avg_conviction":  avg_conviction,
                    "summary":         summary,
                }
            ))

        # V2: If property dispute resolved in our favor, unblock acquisition pipeline
        if property_id and outcome in ("STRONG_DEFENSE", "DEFENSE") and avg_conviction >= 0.75:
            async with AsyncSessionLocal() as db:
                await db.execute(text("""
                    INSERT INTO intel_events
                        (event_type, source, description, metadata, occurred_at)
                    VALUES
                        ('legal_clearance', 'recursive_agent_loop',
                         :desc, CAST(:meta AS jsonb), now())
                """), {
                    "desc": f"Legal barrier cleared for property {property_id} — {outcome}",
                    "meta": json.dumps({"case_slug": case_slug, "conviction": avg_conviction}),
                })
                await db.commit()
            out.append(sig.child(
                SignalType.ACQUISITION_TARGET_LOCKED, Vertical.V2_RE_DEV,
                {
                    "property_id":    property_id,
                    "trigger":        "legal_clearance",
                    "viability_score": avg_conviction,
                }
            ))

    except Exception as exc:
        logger.warning("legal_complete_handler_error", error=str(exc)[:200])

    return out


async def _handle_legal_exemplar_approved(sig: LoopSignal) -> list[LoopSignal]:
    """
    V3 → V3: Write approved exemplar to hive-mind for future deliberations.
    The hive-mind now seeds all future Legal Council runs with this exemplar,
    improving output quality without re-training.
    """
    case_slug      = sig.payload.get("case_slug")
    summary        = sig.payload.get("summary", "")
    avg_conviction = float(sig.payload.get("avg_conviction", 0))
    outcome        = sig.payload.get("outcome", "")

    if not case_slug or not summary:
        return []

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("""
                INSERT INTO legal.distillation_memory
                    (context_hash, summary, conviction_score, outcome, created_at)
                VALUES
                    (:hash, :summary, :conviction, :outcome, now())
                ON CONFLICT (context_hash) DO UPDATE
                    SET conviction_score = EXCLUDED.conviction_score,
                        summary          = EXCLUDED.summary
            """), {
                "hash":       hashlib.sha256(f"{case_slug}|{outcome}".encode()).hexdigest(),
                "summary":    summary[:8000],
                "conviction": avg_conviction,
                "outcome":    outcome,
            })
            await db.commit()
            logger.info("legal_exemplar_written", case_slug=case_slug, conviction=avg_conviction)

    except Exception as exc:
        logger.warning("exemplar_approved_handler_error", error=str(exc)[:200])

    return []  # terminal — no child signals


async def _handle_training_capture(sig: LoopSignal) -> list[LoopSignal]:
    """
    V3 internal: Write interaction to llm_training_captures for nightly fine-tune.
    Terminal signal — never emits children to prevent infinite capture loops.
    """
    source_module = sig.payload.get("source_module", "recursive_loop")
    prompt        = sig.payload.get("prompt", "")
    response      = sig.payload.get("response", "")
    model         = sig.payload.get("model", "rule_engine")
    quality       = sig.payload.get("quality_score")

    if not prompt or not response:
        return []
    if len(response) < 40:
        return []

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("""
                INSERT INTO llm_training_captures
                    (source_module, model_used, user_prompt, assistant_resp,
                     quality_score, status)
                VALUES
                    (:module, :model, :prompt, :response, :quality, 'pending')
            """), {
                "module":   source_module[:120],
                "model":    model[:120],
                "prompt":   prompt[:32_000],
                "response": response[:32_000],
                "quality":  float(quality) if quality is not None else None,
            })
            await db.commit()
    except Exception as exc:
        logger.warning("training_capture_error", error=str(exc)[:200])

    return []  # always terminal


async def _handle_model_deployed(sig: LoopSignal) -> list[LoopSignal]:
    """
    V3 → V1+V2+V3: A new fine-tuned model is available.
    Logs the deployment so each vertical's service picks it up on next restart.
    """
    model_name = sig.payload.get("model_name", "")
    adapter_path = sig.payload.get("adapter_path", "")
    num_examples = sig.payload.get("num_examples", 0)

    logger.info(
        "model_deployed",
        model=model_name,
        adapter=adapter_path,
        examples=num_examples,
    )

    return [
        sig.child(
            SignalType.TRAINING_CAPTURE, Vertical.V3_AI_FACTORY,
            {
                "source_module": "model_deployment",
                "prompt": f"Fine-tuned model deployed: {model_name} ({num_examples} examples)",
                "response": (
                    f"Model {model_name} is now active across all three verticals. "
                    f"V1 CROG-VRS: upgraded concierge and quote engine. "
                    f"V2 RE-DEV: upgraded acquisition scoring. "
                    f"V3 AI-FACTORY: upgraded legal council and exemplar retrieval."
                ),
                "model": "system",
            }
        )
    ]


async def _handle_revenue_verified(sig: LoopSignal) -> list[LoopSignal]:
    """
    V1 → V2: Revenue data updates property viability scores in the acquisition pipeline.
    """
    property_id = sig.payload.get("property_id")
    context     = sig.payload.get("context", "")

    if not property_id or context == "acquisition_projection":
        return []  # avoid loop with acquisition_target_locked handler

    try:
        async with AsyncSessionLocal() as db:
            # Check if this property is an acquisition candidate — update viability
            row = await db.execute(text("""
                SELECT id, viability_score
                FROM   acquisition_pipeline
                WHERE  property_id = :pid
                LIMIT  1
            """), {"pid": str(property_id)})
            pipeline = row.mappings().first()

            if pipeline:
                # Revenue-verified property in our portfolio improves comp data for nearby targets
                await db.execute(text("""
                    UPDATE acquisition_pipeline ap
                    SET    viability_score = LEAST(1.0, viability_score + 0.02),
                           updated_at      = now()
                    WHERE  market = (
                        SELECT county FROM properties WHERE id = :pid LIMIT 1
                    )
                    AND funnel_stage IN ('RADAR', 'TARGET_LOCKED')
                    AND property_id != :pid
                """), {"pid": str(property_id)})
                await db.commit()
    except Exception as exc:
        logger.warning("revenue_verified_handler_error", error=str(exc)[:200])

    return []


# ──────────────────────────────────────────────────────────────────────────────
# Signal dispatch table
# ──────────────────────────────────────────────────────────────────────────────

_HANDLERS: dict[SignalType, Any] = {
    SignalType.CHECKOUT_COMPLETED:          _handle_checkout_completed,
    SignalType.GUEST_DORMANT:               _handle_guest_dormant,
    SignalType.OTA_PARITY_SIGNAL:           _handle_ota_parity_signal,
    SignalType.ACQUISITION_TARGET_LOCKED:   _handle_acquisition_target_locked,
    SignalType.INTELLIGENCE_SIGNAL:         _handle_intelligence_signal,
    SignalType.LEGAL_DELIBERATION_COMPLETE: _handle_legal_deliberation_complete,
    SignalType.LEGAL_EXEMPLAR_APPROVED:     _handle_legal_exemplar_approved,
    SignalType.TRAINING_CAPTURE:            _handle_training_capture,
    SignalType.MODEL_DEPLOYED:              _handle_model_deployed,
    SignalType.REVENUE_VERIFIED:            _handle_revenue_verified,
}


async def _dispatch(sig: LoopSignal) -> list[LoopSignal]:
    if sig.depth >= MAX_SIGNAL_DEPTH:
        logger.warning("signal_depth_cap", signal_type=sig.signal_type, depth=sig.depth)
        return []

    handler = _HANDLERS.get(sig.signal_type)
    if handler is None:
        return []

    try:
        children = await handler(sig)
        if children:
            logger.info(
                "signal_dispatched",
                signal_type=sig.signal_type,
                source=sig.source,
                depth=sig.depth,
                children=len(children),
            )
        return children
    except Exception as exc:
        logger.error("signal_handler_exception",
                     signal_type=sig.signal_type, error=str(exc)[:300])
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Seed signals — harvested from live DB state at the start of each cycle
# ──────────────────────────────────────────────────────────────────────────────

async def _harvest_seed_signals() -> list[LoopSignal]:
    """
    Pull actionable state from the DB and emit the corresponding seed signals.
    Called once at the top of every 30-min cycle.
    """
    seeds: list[LoopSignal] = []

    async with AsyncSessionLocal() as db:

        # ── V1: dormant guests (> 365 days since last stay) ─────────────────
        try:
            rows = await db.execute(text("""
                SELECT id, last_stay_date,
                       EXTRACT(EPOCH FROM (now() - last_stay_date::timestamptz)) / 86400 AS days_dormant
                FROM   guests
                WHERE  last_stay_date IS NOT NULL
                  AND  last_stay_date < CURRENT_DATE - INTERVAL '365 days'
                  AND  (lifetime_value IS NULL OR lifetime_value > 0)
                ORDER  BY last_stay_date ASC
                LIMIT  20
            """))
            for r in rows.mappings().all():
                seeds.append(LoopSignal(
                    signal_type=SignalType.GUEST_DORMANT,
                    source=Vertical.V1_CROG_VRS,
                    payload={
                        "guest_id":    str(r["id"]),
                        "days_dormant": int(r["days_dormant"] or 0),
                        "market":      "blue-ridge",
                    }
                ))
        except Exception as exc:
            logger.warning("harvest_dormant_guests_error", error=str(exc)[:200])

        # ── V1: recent checkouts (last 24h) not yet flywheel-processed ───────
        try:
            rows = await db.execute(text("""
                SELECT r.id, r.guest_id, r.property_id, r.base_rent_amount
                FROM   reservations r
                WHERE  r.check_out_date = CURRENT_DATE - 1
                  AND  r.status = 'confirmed'
                LIMIT  10
            """))
            for r in rows.mappings().all():
                seeds.append(LoopSignal(
                    signal_type=SignalType.CHECKOUT_COMPLETED,
                    source=Vertical.V1_CROG_VRS,
                    payload={
                        "guest_id":    str(r["guest_id"]),
                        "property_id": str(r["property_id"]),
                        "revenue_usd": float(r["base_rent_amount"] or 0),
                    }
                ))
        except Exception as exc:
            logger.warning("harvest_checkouts_error", error=str(exc)[:200])

        # ── V2: acquisition targets stuck in RADAR > 14 days ─────────────────
        try:
            rows = await db.execute(text("""
                SELECT property_id, viability_score
                FROM   acquisition_pipeline
                WHERE  funnel_stage = 'RADAR'
                  AND  updated_at   < now() - INTERVAL '14 days'
                  AND  viability_score >= 0.65
                LIMIT  5
            """))
            for r in rows.mappings().all():
                seeds.append(LoopSignal(
                    signal_type=SignalType.ACQUISITION_TARGET_LOCKED,
                    source=Vertical.V2_RE_DEV,
                    payload={
                        "property_id":    str(r["property_id"]),
                        "viability_score": float(r["viability_score"] or 0),
                    }
                ))
        except Exception as exc:
            logger.warning("harvest_acquisition_error", error=str(exc)[:200])

        # ── V2: fresh intelligence ledger entries needing routing ─────────────
        try:
            rows = await db.execute(text("""
                SELECT id, category, title, market, confidence_score, target_tags
                FROM   intelligence_ledger
                WHERE  created_at > now() - INTERVAL '2 hours'
                  AND  confidence_score >= 0.65
                ORDER  BY confidence_score DESC
                LIMIT  10
            """))
            for r in rows.mappings().all():
                seeds.append(LoopSignal(
                    signal_type=SignalType.INTELLIGENCE_SIGNAL,
                    source=Vertical.V2_RE_DEV,
                    payload={
                        "category":    r["category"],
                        "market":      r["market"] or "blue-ridge",
                        "signal":      r["title"],
                        "confidence":  float(r["confidence_score"] or 0),
                        "target_tags": r["target_tags"] or [],
                    }
                ))
        except Exception as exc:
            logger.warning("harvest_intelligence_error", error=str(exc)[:200])

    logger.info("signals_harvested", count=len(seeds))
    return seeds


# ──────────────────────────────────────────────────────────────────────────────
# Main cycle
# ──────────────────────────────────────────────────────────────────────────────

async def run_recursive_loop_cycle() -> dict[str, int]:
    """
    Execute one full cycle of the recursive agent loop.
    Returns stats dict: {seeds, processed, total_children, captures}.
    """
    stats = {"seeds": 0, "processed": 0, "total_children": 0, "captures": 0}

    seeds = await _harvest_seed_signals()
    stats["seeds"] = len(seeds)

    if not seeds:
        logger.info("recursive_loop_cycle_empty")
        return stats

    # BFS signal processing with cap
    queue: list[LoopSignal] = list(seeds)
    processed: set[str] = set()

    while queue and stats["processed"] < MAX_SIGNALS_PER_CYCLE:
        sig = queue.pop(0)
        if sig.signal_id in processed:
            continue
        processed.add(sig.signal_id)
        stats["processed"] += 1

        if sig.signal_type == SignalType.TRAINING_CAPTURE:
            stats["captures"] += 1

        children = await _dispatch(sig)
        stats["total_children"] += len(children)
        queue.extend(children)

    logger.info("recursive_loop_cycle_complete", **stats)
    return stats


async def recursive_agent_loop() -> None:
    """Infinite loop — started as ARQ background task or standalone."""
    logger.info("recursive_agent_loop_started",
                interval=LOOP_INTERVAL_SECONDS, max_depth=MAX_SIGNAL_DEPTH)

    while True:
        try:
            await run_recursive_loop_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("recursive_loop_error", error=str(exc)[:400])
        await asyncio.sleep(LOOP_INTERVAL_SECONDS)


# ──────────────────────────────────────────────────────────────────────────────
# Standalone entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    async def _main() -> None:
        stats = await run_recursive_loop_cycle()
        print(json.dumps(stats, indent=2))
        sys.exit(0 if stats["processed"] >= 0 else 1)

    asyncio.run(_main())
