#!/usr/bin/env python3
"""
Sovereign Escalation Processor
=================================
The missing link between OODA REFLECT and the Prompt Governor.

When Division agents escalate events (escalated=true in the reflection log),
this processor:
    1. Reads unprocessed escalations from NAS
    2. Feeds them to the Sovereign (r1:70b) for analysis
    3. If the Sovereign recommends optimization → invokes prompt_governor
    4. Logs the Sovereign's decision to the optimizations log

This can run as:
    - A standalone script:  python3 -m sovereign.process_escalations
    - A cron job (every 15 min)
    - Called by the webhook server after each OODA cycle

Architecture:
    OODA REFLECT → reflection_log (NAS) → THIS PROCESSOR → prompt_governor → new prompt
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

from config import captain_think

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("sovereign.escalations")

# Marker file: tracks which reflections have been processed
PROCESSED_MARKER = "_sovereign_processed.json"


# =============================================================================
# ESCALATION READER
# =============================================================================

def _get_log_dir() -> Path:
    """Get the reflection log directory."""
    try:
        from src.fortress_paths import paths
        return paths.logs_dir / "recursive_core"
    except ImportError:
        return Path("data/logs/recursive_core")


def get_unprocessed_escalations() -> List[Dict[str, Any]]:
    """
    Read all escalated reflections that the Sovereign hasn't processed yet.
    """
    log_dir = _get_log_dir()
    marker_path = log_dir / PROCESSED_MARKER

    # Load previously processed event IDs
    processed_ids = set()
    if marker_path.exists():
        try:
            processed_ids = set(json.loads(marker_path.read_text()))
        except Exception:
            pass

    # Scan all reflection log files
    escalations = []
    for log_file in sorted(log_dir.glob("reflections_*.jsonl")):
        for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                if entry.get("escalated") and entry.get("event_id") not in processed_ids:
                    escalations.append(entry)
            except json.JSONDecodeError:
                continue

    logger.info(f"Found {len(escalations)} unprocessed escalations")
    return escalations


def mark_processed(event_ids: List[str]) -> None:
    """Mark event IDs as processed by the Sovereign."""
    log_dir = _get_log_dir()
    marker_path = log_dir / PROCESSED_MARKER

    existing = set()
    if marker_path.exists():
        try:
            existing = set(json.loads(marker_path.read_text()))
        except Exception:
            pass

    existing.update(event_ids)
    marker_path.write_text(json.dumps(sorted(existing), indent=2))


# =============================================================================
# SOVEREIGN ANALYSIS
# =============================================================================

def analyze_escalation(escalation: Dict[str, Any]) -> Dict[str, Any]:
    """
    The Sovereign (r1) analyzes a single escalation and decides what to do.

    Returns:
        {
            "event_id": str,
            "analysis": str (r1's reasoning),
            "action": "optimize_prompt" | "adjust_threshold" | "acknowledge" | "ignore",
            "recommendation": str,
            "new_rules": [...] (any specific rules to add)
        }
    """
    event_id = escalation.get("event_id", "unknown")
    division = escalation.get("division", "unknown")
    reflection = escalation.get("reflection", {})
    variance = escalation.get("variance_pct", 0)

    prompt = (
        f"You are the Tier 1 Sovereign of the Fortress financial system.\n"
        f"A Division agent has escalated an event that requires your analysis.\n\n"
        f"ESCALATION DETAILS:\n"
        f"  Event ID:    {event_id}\n"
        f"  Division:    {division}\n"
        f"  Variance:    {variance:.2f}%\n"
        f"  Reason:      {reflection.get('reason', 'N/A')}\n"
        f"  Action failed: {reflection.get('action_failed', False)}\n"
        f"  High variance: {reflection.get('high_variance', False)}\n"
        f"  Threshold:   {reflection.get('threshold', 5.0)}%\n\n"
        f"CONTEXT:\n"
        f"  - Division B (Property Management) processes trust accounting\n"
        f"  - Guest deposits are held in escrow until checkout + 7 days\n"
        f"  - Trust ledger must always balance to zero (deposits = payouts)\n"
        f"  - A non-zero trust delta is a compliance violation\n\n"
        f"ANALYZE this escalation and respond with JSON:\n"
        f'{{\n'
        f'  "analysis": "Your detailed analysis of why this happened",\n'
        f'  "action": "optimize_prompt | adjust_threshold | acknowledge",\n'
        f'  "recommendation": "Specific recommendation for the Division agent",\n'
        f'  "severity": "critical | high | medium | low",\n'
        f'  "new_rules": ["any new rules to add to the agent prompt"]\n'
        f'}}'
    )

    system_role = (
        "You are the Meta-Cognition engine of the Fortress AI financial system. "
        "You analyze escalated events from subordinate Division agents and determine "
        "whether their prompts need rewriting, their thresholds need adjusting, or "
        "the event simply needs acknowledgment. Be precise and analytical. "
        "Respond ONLY with valid JSON."
    )

    logger.info(f"Sovereign analyzing escalation: {event_id} ({division})...")
    response = captain_think(prompt, system_role=system_role, temperature=0.3)

    # Strip <think> tags
    clean = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
    json_match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
    json_str = json_match.group(0) if json_match else clean

    result = {
        "event_id": event_id,
        "division": division,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        parsed = json.loads(json_str)
        result.update(parsed)
    except json.JSONDecodeError:
        logger.warning(f"Sovereign response not valid JSON: {clean[:300]}")
        result["analysis"] = clean[:500]
        result["action"] = "acknowledge"
        result["recommendation"] = "Manual review needed — r1 response was not parseable."
        result["severity"] = "high"
        result["new_rules"] = []

    return result


def execute_sovereign_decision(decision: Dict[str, Any]) -> None:
    """
    Execute the Sovereign's decision on an escalation.
    """
    action = decision.get("action", "acknowledge")
    event_id = decision.get("event_id", "unknown")
    division = decision.get("division", "unknown")

    logger.info(
        f"Sovereign decision for {event_id}: {action} "
        f"(severity={decision.get('severity', 'N/A')})"
    )

    if action == "optimize_prompt":
        # Invoke the Prompt Governor
        logger.info(f"  Triggering Prompt Governor for {division}...")
        try:
            from sovereign.prompt_governor import optimize_prompt, commit_prompt

            agent_id = f"{division}.agent"
            result = optimize_prompt(
                agent_id=agent_id,
                failure_log=[decision],
            )

            if "new_prompt" in result:
                commit_prompt(
                    agent_id=agent_id,
                    new_prompt=result["new_prompt"],
                    reasoning=decision.get("recommendation", "Sovereign-directed optimization"),
                )
                logger.info(f"  Prompt rewritten for {agent_id}")
            else:
                logger.info(f"  Prompt Governor did not produce a new prompt")

        except Exception as e:
            logger.error(f"  Prompt optimization failed: {e}")

    elif action == "adjust_threshold":
        logger.info(f"  Recommendation: {decision.get('recommendation', 'N/A')}")
        # In production, this would update the threshold config

    elif action == "acknowledge":
        logger.info(f"  Acknowledged. No prompt change needed.")
        logger.info(f"  Recommendation: {decision.get('recommendation', 'N/A')}")

    # Always log the decision
    from recursive_core.reflection_log import log_optimization
    log_optimization(
        agent_id=f"{division}.agent",
        action=f"sovereign_{action}",
        old_value=f"escalation:{event_id}",
        new_value=decision.get("recommendation", "")[:200],
        reasoning=decision.get("analysis", "")[:200],
    )


# =============================================================================
# MAIN
# =============================================================================

def process_all() -> List[Dict[str, Any]]:
    """
    Process all unprocessed escalations.
    Returns the list of Sovereign decisions.
    """
    escalations = get_unprocessed_escalations()

    if not escalations:
        logger.info("No unprocessed escalations. Sovereign is at rest.")
        return []

    decisions = []
    for esc in escalations:
        decision = analyze_escalation(esc)
        execute_sovereign_decision(decision)
        decisions.append(decision)

    # Mark as processed
    processed_ids = [e.get("event_id") for e in escalations if e.get("event_id")]
    mark_processed(processed_ids)

    logger.info(f"Sovereign processed {len(decisions)} escalation(s)")
    return decisions


if __name__ == "__main__":
    print()
    print("=" * 64)
    print("  SOVEREIGN — ESCALATION PROCESSOR")
    print("  DeepSeek R1:70b Meta-Cognition Analysis")
    print("=" * 64)
    print()

    decisions = process_all()

    if not decisions:
        print("  No escalations to process.")
    else:
        for d in decisions:
            print(f"  Event:          {d.get('event_id')}")
            print(f"  Division:       {d.get('division')}")
            print(f"  Severity:       {d.get('severity', 'N/A')}")
            print(f"  Action:         {d.get('action')}")
            print(f"  Analysis:       {d.get('analysis', 'N/A')[:200]}")
            print(f"  Recommendation: {d.get('recommendation', 'N/A')[:200]}")
            if d.get("new_rules"):
                print(f"  New Rules:")
                for rule in d["new_rules"]:
                    print(f"    - {rule}")
            print()

    print("=" * 64)
