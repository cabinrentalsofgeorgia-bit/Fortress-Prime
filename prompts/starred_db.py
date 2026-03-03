"""
Fortress Prime — Starred Responses Database
=============================================
SQLite-backed store for human-approved "golden" AI responses.
These starred responses power the Dynamic Few-Shot Prompting system.

Learning Loop:
    1. AI generates a response -> logged via log_prompt_execution()
    2. Human reviews via: python -m prompts.review --template guest_email_reply -v
    3. Human stars the good ones: python -m prompts.review --star <run_id> --tag pets
    4. Next time a guest asks about pets, the starred examples are injected
       into the prompt automatically.

Database: prompts/starred_responses.db (SQLite)

Usage:
    from prompts.starred_db import star_response, get_examples_for_topic, format_examples

    # Star a response from the logs
    star_response(run_id="abc123", topic_tag="ev_charging",
                  guest_input="Can I charge my Tesla?",
                  ai_output="Yes! We have a Level 2 charger...")

    # Retrieve and format for injection
    examples = get_examples_for_topic("ev_charging", limit=3)
    formatted = format_examples(examples)
    # -> "User: Can I charge my Tesla?\\nAI: Yes! We have a Level 2 charger..."
"""

import os
import sys
import sqlite3
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# Centralized path resolution (NAS-first, local fallback)
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.fortress_paths import STARRED_DB_PATH

# Database location — resolved by fortress_paths:
#   NAS:   /mnt/fortress_nas/fortress_data/ai_brain/starred_responses.db
#   Local: ./data/starred_responses.db
DB_PATH = STARRED_DB_PATH


# =============================================================================
# SCHEMA
# =============================================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS starred_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE,                  -- Links back to the prompt execution log
    topic_tag TEXT NOT NULL,             -- e.g., "ev_charging", "pets", "hot_tub"
    guest_input TEXT NOT NULL,           -- The original guest email/question
    ai_output TEXT NOT NULL,             -- The AI response that was approved
    cabin_name TEXT,                     -- Which cabin this was for (optional)
    tone TEXT,                           -- What tone was used (optional)
    quality_score INTEGER DEFAULT 5,     -- 1-5 quality rating (default: 5 = starred)
    starred_by TEXT DEFAULT 'operator',  -- Who starred it
    notes TEXT,                          -- Optional notes about why it was starred
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active INTEGER DEFAULT 1            -- Soft delete: 0 = inactive, 1 = active
);

CREATE INDEX IF NOT EXISTS idx_sr_topic ON starred_responses(topic_tag);
CREATE INDEX IF NOT EXISTS idx_sr_active ON starred_responses(active);
CREATE INDEX IF NOT EXISTS idx_sr_run_id ON starred_responses(run_id);
CREATE INDEX IF NOT EXISTS idx_sr_quality ON starred_responses(quality_score);

-- Topic aliases: maps variant names to canonical topics
-- e.g., "tesla" -> "ev_charging", "wifi" -> "internet"
CREATE TABLE IF NOT EXISTS topic_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias TEXT UNIQUE NOT NULL,
    canonical_topic TEXT NOT NULL
);
"""

# Pre-built topic aliases
DEFAULT_ALIASES = [
    # EV / Charging
    ("tesla", "ev_charging"), ("ev", "ev_charging"), ("charger", "ev_charging"),
    ("electric vehicle", "ev_charging"), ("charging station", "ev_charging"),
    ("level 2", "ev_charging"), ("nema 14-50", "ev_charging"),
    # Internet / WiFi
    ("wifi", "internet"), ("wi-fi", "internet"), ("internet speed", "internet"),
    ("streaming", "internet"), ("starlink", "internet"), ("router", "internet"),
    # Hot Tub
    ("hot tub", "hot_tub"), ("jacuzzi", "hot_tub"), ("spa", "hot_tub"),
    # Pets
    ("dog", "pets"), ("cat", "pets"), ("pet fee", "pets"),
    ("pet friendly", "pets"), ("animal", "pets"), ("service dog", "pets"),
    # Check-in / Check-out
    ("check in", "checkin"), ("check-in", "checkin"), ("checkout", "checkout"),
    ("check out", "checkout"), ("check-out", "checkout"),
    ("early checkin", "checkin"), ("late checkout", "checkout"),
    ("key", "checkin"), ("lockbox", "checkin"), ("door code", "checkin"),
    # Kitchen
    ("kitchen", "kitchen"), ("cook", "kitchen"), ("grill", "kitchen"),
    ("bbq", "kitchen"), ("oven", "kitchen"), ("dishwasher", "kitchen"),
    ("coffee", "kitchen"), ("keurig", "kitchen"),
    # Heating / HVAC
    ("heat", "hvac"), ("heater", "hvac"), ("furnace", "hvac"),
    ("ac", "hvac"), ("air conditioning", "hvac"), ("thermostat", "hvac"),
    ("fireplace", "hvac"),
    # Parking
    ("parking", "parking"), ("driveway", "parking"), ("garage", "parking"),
    ("4wd", "parking"), ("four wheel drive", "parking"), ("steep", "parking"),
    # Activities
    ("hiking", "activities"), ("fishing", "activities"), ("tubing", "activities"),
    ("kayak", "activities"), ("rafting", "activities"), ("horseback", "activities"),
    ("zipline", "activities"), ("vineyard", "activities"), ("winery", "activities"),
    # Accessibility
    ("wheelchair", "accessibility"), ("accessible", "accessibility"),
    ("ada", "accessibility"), ("stairs", "accessibility"), ("ramp", "accessibility"),
]


@dataclass
class StarredResponse:
    """A single human-approved golden response."""
    id: int
    run_id: str
    topic_tag: str
    guest_input: str
    ai_output: str
    cabin_name: Optional[str]
    tone: Optional[str]
    quality_score: int
    starred_by: str
    notes: Optional[str]
    created_at: str
    active: bool


# =============================================================================
# DATABASE CONNECTION
# =============================================================================

def _get_conn() -> sqlite3.Connection:
    """Get a connection to the starred responses database."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database schema and seed topic aliases."""
    conn = _get_conn()
    conn.executescript(SCHEMA)

    # Seed default aliases (skip if already exist)
    for alias, canonical in DEFAULT_ALIASES:
        conn.execute(
            "INSERT OR IGNORE INTO topic_aliases (alias, canonical_topic) VALUES (?, ?)",
            (alias, canonical)
        )

    conn.commit()
    conn.close()


# Auto-initialize on import
init_db()


# =============================================================================
# STAR / UNSTAR OPERATIONS
# =============================================================================

def star_response(
    run_id: str,
    topic_tag: str,
    guest_input: str,
    ai_output: str,
    cabin_name: Optional[str] = None,
    tone: Optional[str] = None,
    quality_score: int = 5,
    starred_by: str = "operator",
    notes: Optional[str] = None,
) -> int:
    """
    Star a response as a "golden example" for dynamic few-shot injection.

    Args:
        run_id:        The execution log run_id to link back to.
        topic_tag:     Topic category (e.g., "ev_charging", "pets", "hot_tub").
        guest_input:   The original guest question/email.
        ai_output:     The AI response that was approved.
        cabin_name:    Which cabin this was for (optional, for context).
        tone:          What tone modifier was used (optional).
        quality_score: Rating 1-5 (5 = excellent, default).
        starred_by:    Who starred it (default: "operator").
        notes:         Optional notes about why this response is good.

    Returns:
        The database ID of the starred entry.

    Example:
        star_response(
            run_id="abc123",
            topic_tag="ev_charging",
            guest_input="Can I charge my Tesla at the cabin?",
            ai_output="Yes! We have a Level 2 EV charger (NEMA 14-50 outlet) in the carport...",
            cabin_name="Rolling River",
            quality_score=5,
            notes="Great response — specific, accurate, mentions the outlet type."
        )
    """
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO starred_responses
        (run_id, topic_tag, guest_input, ai_output, cabin_name, tone,
         quality_score, starred_by, notes, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (run_id, topic_tag.lower(), guest_input, ai_output,
          cabin_name, tone, quality_score, starred_by, notes))
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def unstar_response(run_id: str) -> bool:
    """Soft-delete a starred response (sets active=0)."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE starred_responses SET active = 0 WHERE run_id = ?", (run_id,))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return affected > 0


def update_quality(run_id: str, quality_score: int) -> bool:
    """Update the quality score of a starred response."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE starred_responses SET quality_score = ? WHERE run_id = ?",
        (quality_score, run_id)
    )
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return affected > 0


# =============================================================================
# RETRIEVAL
# =============================================================================

def get_examples_for_topic(
    topic_tag: str,
    limit: int = 3,
    min_quality: int = 4,
) -> List[StarredResponse]:
    """
    Retrieve the best starred responses for a given topic.

    Sorted by quality_score DESC, then newest first.
    Only returns active entries with quality >= min_quality.

    Args:
        topic_tag:   The topic to fetch examples for (e.g., "ev_charging").
        limit:       Max examples to return (default: 3).
        min_quality: Minimum quality score to include (default: 4).

    Returns:
        List of StarredResponse objects, best quality first.
    """
    # Resolve alias to canonical topic
    canonical = resolve_topic_alias(topic_tag)

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, run_id, topic_tag, guest_input, ai_output, cabin_name,
               tone, quality_score, starred_by, notes, created_at, active
        FROM starred_responses
        WHERE topic_tag = ? AND active = 1 AND quality_score >= ?
        ORDER BY quality_score DESC, created_at DESC
        LIMIT ?
    """, (canonical, min_quality, limit))

    results = []
    for row in cur.fetchall():
        results.append(StarredResponse(
            id=row["id"],
            run_id=row["run_id"],
            topic_tag=row["topic_tag"],
            guest_input=row["guest_input"],
            ai_output=row["ai_output"],
            cabin_name=row["cabin_name"],
            tone=row["tone"],
            quality_score=row["quality_score"],
            starred_by=row["starred_by"],
            notes=row["notes"],
            created_at=row["created_at"],
            active=bool(row["active"]),
        ))

    conn.close()
    return results


def get_all_starred(
    topic_filter: Optional[str] = None,
    limit: int = 50,
) -> List[StarredResponse]:
    """Retrieve all starred responses, optionally filtered by topic."""
    conn = _get_conn()
    cur = conn.cursor()

    if topic_filter:
        canonical = resolve_topic_alias(topic_filter)
        cur.execute("""
            SELECT id, run_id, topic_tag, guest_input, ai_output, cabin_name,
                   tone, quality_score, starred_by, notes, created_at, active
            FROM starred_responses
            WHERE topic_tag = ? AND active = 1
            ORDER BY quality_score DESC, created_at DESC
            LIMIT ?
        """, (canonical, limit))
    else:
        cur.execute("""
            SELECT id, run_id, topic_tag, guest_input, ai_output, cabin_name,
                   tone, quality_score, starred_by, notes, created_at, active
            FROM starred_responses
            WHERE active = 1
            ORDER BY topic_tag, quality_score DESC
            LIMIT ?
        """, (limit,))

    results = []
    for row in cur.fetchall():
        results.append(StarredResponse(
            id=row["id"],
            run_id=row["run_id"],
            topic_tag=row["topic_tag"],
            guest_input=row["guest_input"],
            ai_output=row["ai_output"],
            cabin_name=row["cabin_name"],
            tone=row["tone"],
            quality_score=row["quality_score"],
            starred_by=row["starred_by"],
            notes=row["notes"],
            created_at=row["created_at"],
            active=bool(row["active"]),
        ))

    conn.close()
    return results


def get_topic_stats() -> Dict[str, int]:
    """Return count of starred responses per topic."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT topic_tag, COUNT(*) as cnt
        FROM starred_responses WHERE active = 1
        GROUP BY topic_tag ORDER BY cnt DESC
    """)
    stats = {row["topic_tag"]: row["cnt"] for row in cur.fetchall()}
    conn.close()
    return stats


# =============================================================================
# TOPIC ALIAS RESOLUTION
# =============================================================================

def resolve_topic_alias(topic: str) -> str:
    """Resolve a topic alias to its canonical form."""
    topic_lower = topic.lower().strip()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT canonical_topic FROM topic_aliases WHERE alias = ?",
        (topic_lower,)
    )
    row = cur.fetchone()
    conn.close()
    return row["canonical_topic"] if row else topic_lower


def add_topic_alias(alias: str, canonical_topic: str):
    """Add a new topic alias mapping."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO topic_aliases (alias, canonical_topic) VALUES (?, ?)",
        (alias.lower(), canonical_topic.lower())
    )
    conn.commit()
    conn.close()


def list_topic_aliases() -> Dict[str, str]:
    """Return all topic aliases as {alias: canonical_topic}."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT alias, canonical_topic FROM topic_aliases ORDER BY canonical_topic, alias")
    aliases = {row["alias"]: row["canonical_topic"] for row in cur.fetchall()}
    conn.close()
    return aliases


# =============================================================================
# FORMATTING — Convert starred responses into few-shot prompt text
# =============================================================================

def format_examples(
    examples: List[StarredResponse],
    include_cabin: bool = False,
) -> str:
    """
    Format starred responses into few-shot example text for prompt injection.

    Args:
        examples:      List of StarredResponse objects.
        include_cabin:  Include cabin name in the example header (optional).

    Returns:
        Formatted string ready for injection into the {dynamic_examples} slot.
        Returns empty string if no examples.

    Example output:
        [Verified Response — EV Charging]
        User: Can I charge my Tesla at the cabin?
        AI: Yes! We have a Level 2 EV charger (NEMA 14-50 outlet) in the carport...

        [Verified Response — EV Charging]
        User: What kind of EV charger do you have?
        AI: We have a NEMA 14-50 outlet that supports Level 2 charging...
    """
    if not examples:
        return ""

    parts = []
    for ex in examples:
        header = f"[Verified Response — {ex.topic_tag.replace('_', ' ').title()}"
        if include_cabin and ex.cabin_name:
            header += f" @ {ex.cabin_name}"
        header += "]"

        # Truncate long inputs/outputs for prompt efficiency
        guest_input = ex.guest_input[:300].strip()
        ai_output = ex.ai_output[:500].strip()

        parts.append(f"{header}\nUser: {guest_input}\nAI: {ai_output}")

    return "\n\n".join(parts)


def load_dynamic_examples(topic_tag: str, limit: int = 3) -> str:
    """
    Convenience function: fetch and format starred examples for a topic.
    Returns formatted text ready for prompt injection, or empty string.

    Usage:
        examples_text = load_dynamic_examples("ev_charging")
        prompt = tmpl.render(..., dynamic_examples=examples_text)
    """
    examples = get_examples_for_topic(topic_tag, limit=limit)
    return format_examples(examples)


# =============================================================================
# CLI: python -m prompts.starred_db
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  FORTRESS PRIME — STARRED RESPONSES DATABASE")
    print("=" * 60)

    # Show stats
    stats = get_topic_stats()
    total = sum(stats.values()) if stats else 0

    print(f"\n  Database: {DB_PATH}")
    print(f"  Total Starred: {total}")

    if stats:
        print(f"\n  {'TOPIC':<25} {'COUNT':>8}")
        print(f"  {'-' * 35}")
        for topic, count in stats.items():
            print(f"  {topic:<25} {count:>8}")
    else:
        print("\n  No starred responses yet.")
        print("  Use: python -m prompts.review --star <run_id> --tag <topic>")

    # Show alias count
    aliases = list_topic_aliases()
    print(f"\n  Topic Aliases: {len(aliases)} configured")
    print(f"{'=' * 60}")
