#!/usr/bin/env python3
"""
Division 2: Sovereign Pricing Executor Daemon

Listens to market.thesis.approved events from the Quant Swarm.  For each
approved thesis it:
  1. Extracts a deterministic pricing delta via SWARM (Qwen 2.5)
  2. Clamps the delta to absolute safety guardrails (+/- 5%)
  3. Stages the recommendation on pricing.adjustment.staged (Redpanda)

The staged recommendation awaits human approval on the Command Center glass
before any live rate change is executed (per Rule 002 and Rule 012 — Copilot
Principle).  When Streamline grants write-API access, the execution step
plugs in at _execute_approved_adjustment().

Value chain:
    market_sentinel -> quant_swarm -> risk_manager -> thesis.approved
    -> THIS DAEMON -> pricing.adjustment.staged -> Human approves on glass
    -> (future) Streamline rate push

Usage:
    python -m src.pricing_executor_daemon

Deployment:
    nohup python -m src.pricing_executor_daemon >> /tmp/pricing_executor.log 2>&1 &
"""

import os
import re
import json
import asyncio
import logging
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer
from config import get_inference_client

from src.event_publisher import EventPublisher, close_event_publisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("pricing_executor")

REDPANDA_BROKER = os.getenv("KAFKA_BROKER_URL", "192.168.0.100:19092")
CONSUMER_GROUP = "pricing_execution_v1"

# Absolute daily pricing guardrails — breaching these requires Human override
MAX_UPWARD_ADJUSTMENT = 0.05    # +5%
MAX_DOWNWARD_ADJUSTMENT = -0.05  # -5%


# ---------------------------------------------------------------------------
# Step 1: Delta Extraction (SWARM — fast, deterministic)
# ---------------------------------------------------------------------------

async def extract_pricing_delta(thesis: str) -> float:
    """Use SWARM to parse the thesis into a single float pricing delta."""
    client, model = get_inference_client("SWARM")

    prompt = (
        "You are a strictly deterministic JSON parser. "
        "Read the following macroeconomic pricing thesis and extract the "
        "recommended global pricing adjustment for the cabin portfolio. "
        "If the thesis recommends a rate increase of 2%, output 0.02. "
        "If a decrease of 3%, output -0.03. "
        "If no clear adjustment is recommended, output 0.00.\n\n"
        f"THESIS:\n{thesis}\n\n"
        'Respond ONLY with valid JSON: {"adjustment_delta": 0.00}'
    )

    def _call():
        return client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=64,
        )

    try:
        resp = await asyncio.to_thread(_call)
        raw = resp.choices[0].message.content.strip()

        # Primary: parse as JSON
        try:
            parsed = json.loads(raw)
            return float(parsed.get("adjustment_delta", 0.0))
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: extract first float from the response
        match = re.search(r"-?\d+\.?\d*", raw)
        if match:
            value = float(match.group())
            if abs(value) > 1:
                value = value / 100.0
            return value

        log.warning("Could not parse delta from SWARM response: %s", raw[:100])
        return 0.0

    except Exception as e:
        log.error("Delta extraction failed: %s. Defaulting to 0.0.", e)
        return 0.0


# ---------------------------------------------------------------------------
# Step 2: Safety Guardrails
# ---------------------------------------------------------------------------

def apply_guardrails(raw_delta: float) -> float:
    """Clamp the delta to the absolute daily adjustment bounds."""
    return max(min(raw_delta, MAX_UPWARD_ADJUSTMENT), MAX_DOWNWARD_ADJUSTMENT)


# ---------------------------------------------------------------------------
# Step 3: Stage the Recommendation (Copilot Principle — human approves)
# ---------------------------------------------------------------------------

async def stage_pricing_recommendation(
    raw_delta: float,
    safe_delta: float,
    thesis: str,
    source_ticks: dict,
):
    """Publish the constrained recommendation for human review."""
    recommendation = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_delta_pct": round(raw_delta * 100, 2),
        "constrained_delta_pct": round(safe_delta * 100, 2),
        "multiplier": round(1.0 + safe_delta, 4),
        "guardrail_hit": abs(raw_delta) > abs(safe_delta),
        "source_ticks": source_ticks,
        "thesis_excerpt": thesis[:500],
        "status": "staged",
        "requires_human_approval": True,
    }

    await EventPublisher.publish(
        topic="pricing.adjustment.staged",
        payload=recommendation,
        key="portfolio_daily",
    )

    log.info(
        "STAGED: %+.2f%% adjustment (raw %+.2f%%, guardrail %s). "
        "Awaiting human approval on glass.",
        safe_delta * 100,
        raw_delta * 100,
        "HIT" if recommendation["guardrail_hit"] else "clear",
    )
    return recommendation


# ---------------------------------------------------------------------------
# Step 4: Future Streamline Execution (placeholder)
# ---------------------------------------------------------------------------

async def _execute_approved_adjustment(multiplier: float):
    """
    Placeholder for live Streamline rate push.

    Streamline VRS currently exposes read-only methods (GetPropertyRates,
    GetReservationPrice).  When write access is granted:
      1. Fetch current base rates via GetPropertyRates
      2. Apply multiplier to each property's nightly rate
      3. Push via the new SetPropertyRates / UpdateRates method
      4. Log the change to analytics_events with event_type='rate_adjustment'

    This function will NOT execute until:
      - Streamline grants write API access
      - Human approves the staged recommendation on the glass
      - The adjustment is registered in the audit trail
    """
    log.info(
        "EXECUTION PENDING: multiplier=%.4f — Streamline write API not yet available. "
        "Staged for human review.",
        multiplier,
    )


# ---------------------------------------------------------------------------
# Event Processing
# ---------------------------------------------------------------------------

async def process_approved_thesis(payload: dict):
    """Full pipeline: extract delta -> guardrails -> stage recommendation."""
    thesis = payload.get("thesis", "")
    source_ticks = payload.get("source_ticks", {})

    if not thesis:
        log.warning("Empty thesis received. Skipping.")
        return

    log.info("Approved thesis received. Extracting pricing delta...")

    raw_delta = await extract_pricing_delta(thesis)
    safe_delta = apply_guardrails(raw_delta)

    if safe_delta == 0.0:
        log.info("Delta is 0.0. No pricing action required.")
        return

    recommendation = await stage_pricing_recommendation(
        raw_delta=raw_delta,
        safe_delta=safe_delta,
        thesis=thesis,
        source_ticks=source_ticks,
    )

    await _execute_approved_adjustment(recommendation["multiplier"])


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------

async def consume_events():
    """Listen to market.thesis.approved and process each approved thesis."""
    consumer = AIOKafkaConsumer(
        "market.thesis.approved",
        bootstrap_servers=REDPANDA_BROKER,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="earliest",
    )

    await consumer.start()
    log.info("Pricing Executor online — listening on %s", REDPANDA_BROKER)

    try:
        async for msg in consumer:
            try:
                await process_approved_thesis(msg.value)
            except Exception as e:
                log.error("Failed to process thesis: %s", e)
    except asyncio.CancelledError:
        log.info("Shutdown initiated.")
    finally:
        await consumer.stop()
        await close_event_publisher()
        log.info("Pricing Executor shut down cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(consume_events())
    except KeyboardInterrupt:
        log.info("Manual shutdown of Pricing Executor.")
