"""
Godhead Swarm — Multi-agent forensics engine for Legacy-vs-DGX parity auditing.

Phase 3: Recursive Learning & Self-Healing.

Pipeline: Paper Clip → Claw → Hermes (LLM) → Nemo (Recursive Write)
"""

from __future__ import annotations

import json
import structlog
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.blocked_day import BlockedDay
from backend.models.learned_rule import LearnedRule
from backend.models.property import Property
from backend.models.shadow_discrepancy import ShadowDiscrepancy
from backend.models.pricing import QuoteRequest
from backend.services.pricing_service import calculate_fast_quote, PricingError
from backend.services.swarm_service import submit_chat_completion

logger = structlog.get_logger("godhead_swarm")

TWO_PLACES = Decimal("0.01")

HERMES_SYSTEM_PROMPT = """\
You are Hermes, a forensic pricing analyst for a vacation rental platform.
You receive an Evidence Packet describing a pricing discrepancy between a
Legacy booking system and the sovereign DGX Quote Engine.

Your job:
1. Diagnose WHY the two totals differ.
2. Identify the missing mathematical operator (fee, discount, tax, rate issue).
3. If you can infer a corrective rule, provide it.

You MUST respond with ONLY a valid JSON object — no markdown, no explanation
outside the JSON. Use this exact schema:

{
  "diagnosis": "<concise human-readable explanation>",
  "confidence": <float 0.0-1.0>,
  "inferred_rule": {
    "rule_name": "<short snake_case name>",
    "adjustment_type": "flat_fee" | "percentage",
    "adjustment_value": <number — negative for discounts, positive for surcharges>,
    "trigger_condition": { <key-value pairs describing when this rule fires> }
  } | null
}

Set "inferred_rule" to null if you cannot confidently infer a corrective rule.
Set "confidence" to reflect how certain you are (>0.75 = high confidence).

Common patterns to look for:
- Cleaning fee mismatch (~$150 flat)
- Pet fee mismatch (~$200 flat)
- Tax calculation divergence (12% of subtotal)
- Early-bird / last-minute discount (percentage of rent)
- Minimum-night surcharge
- Extra-guest fee (per guest above base occupancy)
"""

HERMES_FALLBACK_MODEL = "qwen2.5:7b"


def _build_hermes_prompt(evidence: dict[str, Any]) -> str:
    safe_evidence = {}
    for k, v in evidence.items():
        if isinstance(v, (date, datetime)):
            safe_evidence[k] = v.isoformat()
        elif isinstance(v, UUID):
            safe_evidence[k] = str(v)
        elif isinstance(v, Decimal):
            safe_evidence[k] = float(v)
        else:
            safe_evidence[k] = v

    return (
        "Analyze this Evidence Packet and return your JSON diagnosis:\n\n"
        f"```json\n{json.dumps(safe_evidence, indent=2, default=str)}\n```"
    )


def _parse_hermes_response(raw: str) -> dict[str, Any]:
    """Extract JSON from the LLM response, tolerating markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        raise


# ---------------------------------------------------------------------------
# Phase 2 static heuristics — kept as fallback when LLM is unavailable
# ---------------------------------------------------------------------------


def _hermes_static_fallback(evidence: dict[str, Any]) -> dict[str, Any]:
    """Rule-based heuristic diagnosis — fallback when no LLM is reachable."""
    delta = evidence["delta_cents"]
    abs_delta = abs(delta)
    check_in: date = evidence["check_in"]
    check_out: date = evidence["check_out"]
    days_to_arrival = (check_in - date.today()).days

    result: dict[str, Any] = {"diagnosis": "", "confidence": 0.0, "inferred_rule": None}

    if abs_delta == 15000:
        result["diagnosis"] = (
            f"CLEANING_FEE: Delta of ${abs_delta / 100:.2f} matches standard cleaning fee."
        )
        result["confidence"] = 0.85
        result["inferred_rule"] = {
            "rule_name": "missing_cleaning_fee",
            "adjustment_type": "flat_fee",
            "adjustment_value": 150.0 if delta > 0 else -150.0,
            "trigger_condition": {},
        }
    elif abs_delta == 20000:
        result["diagnosis"] = (
            f"PET_FEE: Delta of ${abs_delta / 100:.2f} matches standard pet fee."
        )
        result["confidence"] = 0.85
        result["inferred_rule"] = {
            "rule_name": "missing_pet_fee",
            "adjustment_type": "flat_fee",
            "adjustment_value": 200.0 if delta > 0 else -200.0,
            "trigger_condition": {"pets": ">0"},
        }
    elif abs_delta > 0 and abs_delta % 12 == 0:
        result["diagnosis"] = (
            f"TAX_DISCREPANCY: Delta of ${abs_delta / 100:.2f} is divisible by 12, "
            "suggesting a 12% tax calculation difference."
        )
        result["confidence"] = 0.7
        result["inferred_rule"] = {
            "rule_name": "tax_calculation_correction",
            "adjustment_type": "percentage",
            "adjustment_value": 0.12 if delta > 0 else -0.12,
            "trigger_condition": {},
        }
    else:
        result["diagnosis"] = (
            f"UNKNOWN: Delta of ${abs_delta / 100:.2f} does not match known patterns. "
            "Manual review required."
        )
        result["confidence"] = 0.3

    return result


# ---------------------------------------------------------------------------
# Agent: Paper Clip
# ---------------------------------------------------------------------------


async def agent_paper_clip(payload: dict[str, Any]) -> None:
    """
    Entry agent. Receives a legacy webhook payload, runs our sovereign
    quote pipeline, and compares the result against the legacy total.
    If there's a delta, hands off to Claw.
    """
    property_id = UUID(str(payload["property_id"]))
    check_in = date.fromisoformat(payload["dates"]["check_in"])
    check_out = date.fromisoformat(payload["dates"]["check_out"])
    guests = int(payload.get("guests", 1))
    pets = int(payload.get("pets", 0))
    legacy_total_cents = int(payload["legacy_total_cents"])

    logger.info(
        "paper_clip.start",
        property_id=str(property_id),
        check_in=check_in.isoformat(),
        check_out=check_out.isoformat(),
        legacy_total_cents=legacy_total_cents,
    )

    async with AsyncSessionLocal() as db:
        try:
            quote_request = QuoteRequest(
                property_id=property_id,
                check_in=check_in,
                check_out=check_out,
                adults=max(guests, 1),
                children=0,
                pets=pets,
            )
            dgx_quote = await calculate_fast_quote(quote_request, db)
        except PricingError as exc:
            logger.warning(
                "paper_clip.quote_failed",
                property_id=str(property_id),
                error=str(exc),
            )
            return

    dgx_total_cents = int(
        (dgx_quote.total_amount * Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    delta_cents = legacy_total_cents - dgx_total_cents

    if delta_cents == 0:
        logger.info("paper_clip.match", property_id=str(property_id))
        return

    logger.warning(
        "paper_clip.discrepancy_detected",
        property_id=str(property_id),
        legacy_total_cents=legacy_total_cents,
        dgx_total_cents=dgx_total_cents,
        delta_cents=delta_cents,
    )

    discrepancy_data: dict[str, Any] = {
        "property_id": property_id,
        "check_in": check_in,
        "check_out": check_out,
        "guests": guests,
        "pets": pets,
        "legacy_total_cents": legacy_total_cents,
        "dgx_total_cents": dgx_total_cents,
        "delta_cents": delta_cents,
        "legacy_payload": payload,
        "dgx_payload": dgx_quote.model_dump(mode="json"),
    }
    await agent_claw(discrepancy_data)


# ---------------------------------------------------------------------------
# Agent: Claw
# ---------------------------------------------------------------------------


async def agent_claw(discrepancy_data: dict[str, Any]) -> None:
    """
    Evidence-gathering agent. Fetches rate_card and blocked_days for
    the property and assembles an Evidence Packet for Hermes.
    """
    property_id: UUID = discrepancy_data["property_id"]
    check_in: date = discrepancy_data["check_in"]
    check_out: date = discrepancy_data["check_out"]

    logger.info("claw.gathering_evidence", property_id=str(property_id))

    async with AsyncSessionLocal() as db:
        prop = await db.get(Property, property_id)
        rate_card = prop.rate_card if prop else None

        blocked_stmt = (
            select(BlockedDay)
            .where(BlockedDay.property_id == property_id)
            .where(BlockedDay.start_date < check_out)
            .where(BlockedDay.end_date >= check_in)
        )
        result = await db.execute(blocked_stmt)
        blocked_rows = result.scalars().all()

    blocked_days_list = [
        {
            "start": row.start_date.isoformat(),
            "end": row.end_date.isoformat(),
            "type": row.block_type,
            "source": row.source,
        }
        for row in blocked_rows
    ]

    evidence_packet: dict[str, Any] = {
        **discrepancy_data,
        "rate_card": rate_card,
        "blocked_days": blocked_days_list,
    }

    logger.info(
        "claw.evidence_assembled",
        property_id=str(property_id),
        blocked_day_count=len(blocked_days_list),
    )

    await agent_hermes(evidence_packet)


# ---------------------------------------------------------------------------
# Agent: Hermes  (Phase 3 — LLM-driven with static fallback)
# ---------------------------------------------------------------------------


async def agent_hermes(evidence_packet: dict[str, Any]) -> None:
    """
    Diagnostic agent. Sends the Evidence Packet to the DGX LLM for
    structured JSON analysis. Falls back to static heuristics if the
    LLM is unreachable.
    """
    property_id = evidence_packet["property_id"]

    logger.info(
        "hermes.analyzing",
        property_id=str(property_id),
        delta_cents=evidence_packet["delta_cents"],
    )

    hermes_result: dict[str, Any] | None = None

    model = settings.dgx_inference_model or settings.ollama_fast_model or HERMES_FALLBACK_MODEL
    prompt = _build_hermes_prompt(evidence_packet)

    try:
        llm_response = await submit_chat_completion(
            prompt=prompt,
            model=model,
            system_message=HERMES_SYSTEM_PROMPT,
            timeout_s=30.0,
            extra_payload={"temperature": 0.1, "max_tokens": 1024},
        )
        raw_content = (
            llm_response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        hermes_result = _parse_hermes_response(raw_content)
        logger.info(
            "hermes.llm_diagnosis",
            property_id=str(property_id),
            diagnosis=hermes_result.get("diagnosis"),
            confidence=hermes_result.get("confidence"),
        )
    except Exception as exc:
        logger.warning(
            "hermes.llm_fallback",
            property_id=str(property_id),
            error=str(exc),
        )
        hermes_result = _hermes_static_fallback(evidence_packet)
        logger.info(
            "hermes.static_diagnosis",
            property_id=str(property_id),
            diagnosis=hermes_result.get("diagnosis"),
        )

    diagnosis_data: dict[str, Any] = {
        **evidence_packet,
        "hermes_diagnosis": hermes_result.get("diagnosis", "Analysis failed"),
        "hermes_result": hermes_result,
    }
    await agent_nemo(diagnosis_data)


# ---------------------------------------------------------------------------
# Agent: Nemo  (Phase 3 — Recursive Learning)
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = 0.75


async def agent_nemo(diagnosis_data: dict[str, Any]) -> None:
    """
    Persistence + learning agent.

    1. Writes the forensic record to shadow_discrepancies.
    2. If Hermes provided an inferred_rule with high confidence,
       writes a new LearnedRule row with status='active'.
    3. Updates the shadow_discrepancies row to 'resolved_and_learned'.
    """
    property_id = diagnosis_data["property_id"]
    hermes_result: dict[str, Any] = diagnosis_data.get("hermes_result", {})

    logger.info("nemo.writing_record", property_id=str(property_id))

    record = ShadowDiscrepancy(
        property_id=property_id,
        legacy_total_cents=diagnosis_data["legacy_total_cents"],
        dgx_total_cents=diagnosis_data["dgx_total_cents"],
        delta_cents=diagnosis_data["delta_cents"],
        legacy_payload=diagnosis_data["legacy_payload"],
        dgx_payload=diagnosis_data["dgx_payload"],
        hermes_diagnosis=diagnosis_data["hermes_diagnosis"],
        status="analyzed",
        timestamp=datetime.utcnow(),
    )

    async with AsyncSessionLocal() as db:
        db.add(record)
        await db.flush()
        record_id = record.id

        inferred_rule = hermes_result.get("inferred_rule")
        confidence = float(hermes_result.get("confidence", 0.0))

        if inferred_rule and confidence >= CONFIDENCE_THRESHOLD:
            learned = LearnedRule(
                property_id=property_id,
                rule_name=inferred_rule.get("rule_name", "auto_learned"),
                trigger_condition=inferred_rule.get("trigger_condition", {}),
                adjustment_type=inferred_rule["adjustment_type"],
                adjustment_value=float(inferred_rule["adjustment_value"]),
                confidence_score=confidence,
                status="active",
            )
            db.add(learned)
            await db.flush()

            await db.execute(
                update(ShadowDiscrepancy)
                .where(ShadowDiscrepancy.id == record_id)
                .values(status="resolved_and_learned")
            )

            logger.info(
                "nemo.rule_learned",
                property_id=str(property_id),
                record_id=str(record_id),
                learned_rule_id=str(learned.id),
                rule_name=learned.rule_name,
                confidence=confidence,
            )
        else:
            logger.info(
                "nemo.no_rule_inferred",
                property_id=str(property_id),
                record_id=str(record_id),
                confidence=confidence,
                reason="below threshold" if inferred_rule else "no inferred_rule",
            )

        await db.commit()

    logger.info(
        "nemo.record_persisted",
        property_id=str(property_id),
        record_id=str(record_id),
        final_status="resolved_and_learned" if (inferred_rule and confidence >= CONFIDENCE_THRESHOLD) else "analyzed",
    )
