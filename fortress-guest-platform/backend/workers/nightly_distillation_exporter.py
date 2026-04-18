"""
Nightly Distillation Exporter
==============================
Runs once per night (02:00 via systemd timer).

Reads pending rows from `llm_training_captures` in fortress_shadow, normalises
them into instruction-tuning ChatML JSONL, and appends to the NAS training log
at /mnt/ai_bulk/training_logs/YYYY-MM-DD.jsonl.

Table bootstrap
---------------
The `llm_training_captures` table is created on first run (IF NOT EXISTS)
so there is no separate migration step.

Row lifecycle: pending → exported (never deleted so the NAS JSONL can be
re-generated without data loss).
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import AsyncSessionLocal

logger = structlog.get_logger(service="distillation_exporter")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TRAINING_LOG_DIR = Path(
    os.getenv("INTERACTION_LOG_DIR", "/mnt/ai_bulk/training_logs")
)
MIN_RESPONSE_CHARS = 80
MAX_RESPONSE_CHARS = 16_000

# ---------------------------------------------------------------------------
# Table DDL — created on first exporter run (one statement per execute call
# because asyncpg rejects multi-statement prepared queries)
# ---------------------------------------------------------------------------
_BOOTSTRAP_DDLS = [
    """
    CREATE TABLE IF NOT EXISTS llm_training_captures (
        id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        source_module  VARCHAR(120) NOT NULL,
        model_used     VARCHAR(120) NOT NULL,
        user_prompt    TEXT         NOT NULL,
        assistant_resp TEXT         NOT NULL,
        quality_score  FLOAT,
        status         VARCHAR(20)  NOT NULL DEFAULT 'pending',
        created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_llm_training_captures_status
        ON llm_training_captures (status)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_llm_training_captures_module
        ON llm_training_captures (source_module)
    """,
]

# ---------------------------------------------------------------------------
# Module → system prompt mapping
# ---------------------------------------------------------------------------
_SYSTEM_PROMPTS: dict[str, str] = {
    "vrs_agent_dispatcher": (
        "You are a senior VRS (vacation rental software) operations agent for "
        "Cabin Rentals of Georgia. You handle reservation management, guest "
        "communications, and operational workflows with precision and warmth."
    ),
    "vrs_reactivation_hunter": (
        "You are a guest re-engagement specialist at Cabin Rentals of Georgia. "
        "Your role is to craft personalised, persuasive outreach that reactivates "
        "lapsed guests and converts cart-abandoned bookings."
    ),
    "quote_engine": (
        "You are a hospitality pricing expert. Given property details, dates, and "
        "amenity information, produce clear, accurate guest-facing pricing summaries."
    ),
    "quote_engine_verification": (
        "You are a pricing verification specialist. Validate that pricing summaries "
        "are accurate, complete, and aligned with the property's amenities and policies."
    ),
    "legal_agent_orchestrator": (
        "You are a sophisticated legal AI assistant specialising in property law, "
        "contract disputes, and civil litigation strategy. Reason carefully and "
        "cite applicable statutes or case precedents when relevant."
    ),
    "legal_case_graph": (
        "You are a legal knowledge-graph analyst. Extract structured relationships "
        "from case facts and produce precise entity–relationship analysis."
    ),
    "legal_case_graph_focused": (
        "You are a legal knowledge-graph analyst specialising in targeted document "
        "examination. Identify the most legally significant claims and relationships."
    ),
    "legal_chronology": (
        "You are a legal chronology specialist. Reconstruct and analyse timelines "
        "of events from legal documents and correspondence."
    ),
    "legal_discovery_engine": (
        "You are an expert in civil discovery practice. Generate targeted, "
        "exhaustive discovery requests that expose key facts in litigation."
    ),
    "legal_deposition_prep": (
        "You are a deposition preparation specialist. Develop incisive question "
        "sequences that establish facts, test credibility, and lock in testimony."
    ),
    "macro_treasury": (
        "You are a macro-economic and real estate market intelligence analyst. "
        "Synthesise economic signals, market trends, and competitive data into "
        "strategic property acquisition insights."
    ),
    "ota_vision_recon": (
        "You are an OTA (Online Travel Agency) competitive intelligence analyst. "
        "Evaluate market positioning, pricing dynamics, and listing performance "
        "across Airbnb, VRBO, and direct-booking channels."
    ),
    "research_scout": (
        "You are a real estate research scout. Evaluate market intelligence entries "
        "for relevance, accuracy, and actionable signal strength."
    ),
    "resilient_inference": (
        "You are a sovereign AI assistant operating within Fortress Prime, an "
        "on-premises AI platform for luxury cabin rentals and real estate. "
        "Respond with precision, depth, and domain expertise."
    ),
}

_DEFAULT_SYSTEM_PROMPT = (
    "You are a sovereign AI assistant operating within Fortress Prime, an "
    "on-premises AI platform for luxury cabin rentals and real estate. "
    "Respond with precision, depth, and domain expertise."
)


def _get_system_prompt(source_module: str) -> str:
    return _SYSTEM_PROMPTS.get(source_module, _DEFAULT_SYSTEM_PROMPT)


def _to_chatml(row: dict[str, Any]) -> dict[str, Any] | None:
    prompt   = (row.get("user_prompt")    or "").strip()
    response = (row.get("assistant_resp") or "").strip()
    if (
        not prompt
        or not response
        or len(response) < MIN_RESPONSE_CHARS
        or len(response) > MAX_RESPONSE_CHARS
    ):
        return None

    return {
        "messages": [
            {"role": "system",    "content": _get_system_prompt(row["source_module"])},
            {"role": "user",      "content": prompt},
            {"role": "assistant", "content": response},
        ],
        "_meta": {
            "id":            str(row["id"]),
            "source_module": row["source_module"],
            "teacher_model": row["model_used"],
            "captured_at":   row["created_at"].isoformat() if row.get("created_at") else None,
        },
    }


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------
async def run_distillation_export(
    *,
    batch_size: int = 500,
    dry_run: bool = False,
) -> dict[str, int]:
    today = date.today().isoformat()
    out_path = TRAINING_LOG_DIR / f"{today}.jsonl"
    TRAINING_LOG_DIR.mkdir(parents=True, exist_ok=True)

    stats = {"fetched": 0, "exported": 0, "skipped": 0, "errors": 0}
    logger.info("distillation_export_start", output_path=str(out_path), dry_run=dry_run)

    async with AsyncSessionLocal() as db:
        # Bootstrap table on first run (one statement per execute — asyncpg limitation)
        for ddl in _BOOTSTRAP_DDLS:
            await db.execute(text(ddl))
        await db.commit()

        result = await db.execute(text("""
            SELECT id, source_module, model_used,
                   user_prompt, assistant_resp, created_at
            FROM   llm_training_captures
            WHERE  status = 'pending'
              AND  (eval_holdout IS NULL OR eval_holdout = FALSE)
            ORDER  BY created_at ASC
            LIMIT  :lim
        """), {"lim": batch_size})

        rows = result.mappings().all()
        stats["fetched"] = len(rows)

        if not rows:
            logger.info("distillation_export_no_rows")
            return stats

        exported_ids: list[str] = []

        with open(out_path, "a", encoding="utf-8") as fh:
            for row in rows:
                try:
                    record = _to_chatml(dict(row))
                    if record is None:
                        stats["skipped"] += 1
                        continue
                    if not dry_run:
                        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    exported_ids.append(str(row["id"]))
                    stats["exported"] += 1
                except Exception as exc:
                    stats["errors"] += 1
                    logger.error(
                        "distillation_export_row_error",
                        row_id=str(row["id"]),
                        error=str(exc)[:200],
                    )

        if exported_ids and not dry_run:
            # asyncpg requires explicit array binding — use unnest() workaround
            placeholders = ", ".join(f"'{eid}'" for eid in exported_ids)
            await db.execute(text(f"""
                UPDATE llm_training_captures
                SET    status = 'exported'
                WHERE  id IN ({placeholders})
            """))
            await db.commit()

    logger.info("distillation_export_complete", **stats, output_path=str(out_path))
    return stats


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio
    import sys

    async def _main() -> None:
        stats = await run_distillation_export()
        if stats["errors"] > 0:
            sys.exit(1)

    asyncio.run(_main())
