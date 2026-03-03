"""
Reflection Log — Audit Trail for Recursive Self-Improvement
=============================================================
Every time the system grades itself, rewrites a prompt, or detects a
firewall violation, it gets logged here.

Storage:
    Primary:  NAS (data/logs/recursive_core/reflections_YYYY-MM-DD.jsonl)
    Backup:   PostgreSQL (recursive_core.reflection_log table)

This is the system's long-term memory of its own evolution.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("recursive_core.reflection_log")


# =============================================================================
# LOG DIRECTORY
# =============================================================================

def _get_log_dir() -> Path:
    """Get or create the reflection log directory."""
    try:
        from src.fortress_paths import paths
        log_dir = paths.logs_dir / "recursive_core"
    except ImportError:
        log_dir = Path("data/logs/recursive_core")

    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _today_log_path() -> Path:
    """Return the path for today's reflection log file."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _get_log_dir() / f"reflections_{today}.jsonl"


# =============================================================================
# REFLECTION LOGGING (from OODA REFLECT phase)
# =============================================================================

def log_reflection(event) -> None:
    """
    Log an escalated OODA event to the reflection log.

    Called by OODALoop._reflect() when variance exceeds threshold
    or an action fails. This creates the audit trail that the
    Sovereign Escalation Processor reads from.

    Args:
        event: An OODAEvent instance with completed reflection data.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": event.event_id,
        "division": event.division,
        "phase": event.phase.value if hasattr(event.phase, "value") else str(event.phase),
        "variance_pct": event.variance_pct,
        "predicted_value": event.predicted_value,
        "actual_value": event.actual_value,
        "escalated": event.escalated_to_sovereign,
        "reflection": event.reflection,
        "observation": event.observation,
        "decision": event.decision,
    }

    log_path = _today_log_path()
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        logger.info(f"Reflection logged: {event.event_id} → {log_path.name}")
    except Exception as e:
        logger.error(f"Failed to write reflection log: {e}")

    # Backup to PostgreSQL if available
    _backup_to_db(entry)


# =============================================================================
# OPTIMIZATION LOGGING (from Prompt Governor / Sovereign)
# =============================================================================

def log_optimization(
    agent_id: str,
    action: str,
    old_value: str,
    new_value: str,
    reasoning: str = "",
) -> None:
    """
    Log a prompt optimization or Sovereign decision.

    Called by:
        - sovereign/prompt_governor.py when a prompt is rewritten
        - sovereign/orchestrator.py after each cycle
        - sovereign/process_escalations.py after each decision

    Args:
        agent_id:   The agent that was optimized
        action:     What was done (prompt_rewrite, adjust_threshold, etc.)
        old_value:  Previous state
        new_value:  New state
        reasoning:  Why the change was made
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": "optimization",
        "agent_id": agent_id,
        "action": action,
        "old_value": old_value[:500] if old_value else "",
        "new_value": new_value[:500] if new_value else "",
        "reasoning": reasoning[:500] if reasoning else "",
    }

    log_dir = _get_log_dir()
    opt_path = log_dir / "optimizations.jsonl"
    try:
        with open(opt_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        logger.info(f"Optimization logged: {agent_id} / {action}")
    except Exception as e:
        logger.error(f"Failed to write optimization log: {e}")


# =============================================================================
# FIREWALL VIOLATION LOGGING
# =============================================================================

def log_firewall_violation(
    caller_division: str,
    attempted_resource: str,
) -> None:
    """
    Log a firewall violation for Sovereign review.

    Called by recursive_core/firewall.py when a division attempts
    to access data it shouldn't. These are high-priority events.

    Args:
        caller_division:    The division that tried to cross the boundary
        attempted_resource: The resource it tried to access
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": "firewall_violation",
        "caller_division": caller_division,
        "attempted_resource": attempted_resource,
        "severity": "CRITICAL",
    }

    log_dir = _get_log_dir()
    violations_path = log_dir / "firewall_violations.jsonl"
    try:
        with open(violations_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        logger.warning(
            f"Firewall violation logged: {caller_division} → {attempted_resource}"
        )
    except Exception as e:
        logger.error(f"Failed to log firewall violation: {e}")


# =============================================================================
# QUERY HELPERS (for Escalation Processor + Prompt Optimizer)
# =============================================================================

def get_recent_failures(
    agent_id: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Read recent failure/escalation entries from the reflection log.

    Used by the Prompt Optimizer to collect training data for DSPy.

    Args:
        agent_id: Filter by agent/division (optional)
        limit:    Maximum entries to return

    Returns:
        List of failure event dicts, most recent first.
    """
    log_dir = _get_log_dir()
    failures = []

    # Read all reflection log files, newest first
    log_files = sorted(log_dir.glob("reflections_*.jsonl"), reverse=True)

    for log_file in log_files:
        if len(failures) >= limit:
            break
        try:
            for line in reversed(log_file.read_text(encoding="utf-8").strip().split("\n")):
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("escalated"):
                    if agent_id is None or agent_id in entry.get("division", ""):
                        failures.append(entry)
                        if len(failures) >= limit:
                            break
        except Exception:
            continue

    return failures


def get_optimization_history(
    agent_id: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Read the optimization history — a record of every prompt rewrite.

    Args:
        agent_id: Filter by agent (optional)
        limit:    Maximum entries to return

    Returns:
        List of optimization event dicts.
    """
    log_dir = _get_log_dir()
    opt_path = log_dir / "optimizations.jsonl"

    if not opt_path.exists():
        return []

    entries = []
    try:
        for line in reversed(opt_path.read_text(encoding="utf-8").strip().split("\n")):
            if not line.strip():
                continue
            entry = json.loads(line)
            if agent_id is None or entry.get("agent_id") == agent_id:
                entries.append(entry)
                if len(entries) >= limit:
                    break
    except Exception:
        pass

    return entries


# =============================================================================
# DATABASE BACKUP
# =============================================================================

def _backup_to_db(entry: Dict[str, Any]) -> None:
    """Best-effort backup of reflection entries to PostgreSQL."""
    try:
        import psycopg2
        from dotenv import load_dotenv
        import os
        load_dotenv()

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            database=os.getenv("DB_NAME", "fortress_db"),
            user=os.getenv("DB_USER", "miner_bot"),
            password=os.getenv("DB_PASSWORD", os.getenv("DB_PASS", "")),
            connect_timeout=3,
        )
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS reflection_log (
                id          SERIAL PRIMARY KEY,
                timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                event_id    TEXT,
                division    TEXT,
                entry_type  TEXT DEFAULT 'reflection',
                variance_pct REAL,
                escalated   BOOLEAN DEFAULT FALSE,
                data        JSONB,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        cur.execute("""
            INSERT INTO reflection_log (event_id, division, entry_type, variance_pct, escalated, data)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            entry.get("event_id"),
            entry.get("division"),
            entry.get("type", "reflection"),
            entry.get("variance_pct"),
            entry.get("escalated", False),
            json.dumps(entry, default=str),
        ))

        conn.commit()
        conn.close()
    except Exception:
        pass  # Best-effort — NAS is primary
