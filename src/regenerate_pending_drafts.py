#!/usr/bin/env python3
"""
regenerate_pending_drafts.py — Re-run concierge triage on stale pending drafts.

Identifies email_messages rows where approval_status='pending_approval' but
ai_meta.composition_mode is missing or not a post-PR-113 value.  Those rows
were generated before the exemplar-aware composer landed and have generic
fallback text.  This script re-runs the full pipeline (council + retriever +
composer) and updates ai_draft / ai_meta / ai_confidence in place, preserving
row ID, inquirer linkage, IMAP UID, and original inquiry text.

Usage:
  python3 -m src.regenerate_pending_drafts --dry-run
  python3 -m src.regenerate_pending_drafts --limit 5
  python3 -m src.regenerate_pending_drafts              # all stale rows
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional
from uuid import UUID

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "fortress-guest-platform" / ".env", override=False)
load_dotenv(Path(__file__).parent.parent / ".env", override=False)

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"regen_drafts"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("regen_drafts")

# Valid composition_mode values introduced by PR #113
_VALID_MODES = frozenset({
    "council_plus_1_exemplars",
    "council_plus_2_exemplars",
    "council_plus_3_exemplars",
    "council_only",
})

_QUERY_STALE = """
    SELECT id, email_from, subject,
           ai_meta->>'composition_mode' AS comp_mode,
           length(COALESCE(ai_draft, '')) AS draft_len
    FROM email_messages
    WHERE approval_status = 'pending_approval'
      AND direction = 'inbound'
      AND (
          ai_meta IS NULL
          OR ai_meta->>'composition_mode' IS NULL
          OR ai_meta->>'composition_mode' NOT IN (
              'council_plus_1_exemplars',
              'council_plus_2_exemplars',
              'council_plus_3_exemplars',
              'council_only'
          )
      )
    ORDER BY created_at ASC
"""


async def _run(dry_run: bool, limit: Optional[int]) -> None:
    import psycopg2

    from backend.core.database import async_session_factory
    from backend.services.email_message_service import EmailMessageService

    # Collect stale row IDs via psycopg2 (simple sync read, no ORM needed)
    api_uri = os.getenv("POSTGRES_API_URI", "").replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(api_uri)
    with conn.cursor() as cur:
        cur.execute(_QUERY_STALE)
        rows = cur.fetchall()
    conn.close()

    if limit is not None:
        rows = rows[:limit]

    total = len(rows)
    log.info("stale_rows_found count=%d dry_run=%s limit=%s", total, dry_run, limit)

    if total == 0:
        log.info("nothing_to_do")
        return

    if dry_run:
        log.info("DRY RUN — rows that would be regenerated:")
        for r in rows:
            row_id, email_from, subject, comp_mode, draft_len = r
            log.info(
                "  would_regen id=%s from=%s subject=%s current_mode=%s draft_len=%d",
                str(row_id)[:8], email_from, subject[:50], comp_mode, draft_len,
            )
        return

    regenerated = 0
    failed = 0

    for r in rows:
        row_id, email_from, subject, old_mode, old_draft_len = r
        log.info(
            "regenerating id=%s old_mode=%s old_draft_len=%d",
            str(row_id)[:8], old_mode, old_draft_len,
        )
        try:
            async with async_session_factory() as db:
                svc = EmailMessageService(db)
                msg = await svc.generate_draft_for_inbound(UUID(str(row_id)))

            new_mode = (msg.ai_meta or {}).get("composition_mode", "unknown")
            new_draft_len = len(msg.ai_draft or "")
            new_scores = (msg.ai_meta or {}).get("exemplar_scores", [])
            log.info(
                "regenerated id=%s new_mode=%s new_draft_len=%d exemplar_scores=%s",
                str(row_id)[:8], new_mode, new_draft_len, new_scores,
            )
            regenerated += 1
        except Exception as exc:  # noqa: BLE001
            log.error("regen_failed id=%s err=%s", str(row_id)[:8], str(exc)[:200])
            failed += 1

    log.info(
        "complete total=%d regenerated=%d failed=%d",
        total, regenerated, failed,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Regenerate stale pending email drafts")
    ap.add_argument("--dry-run", action="store_true", help="Report only, no writes")
    ap.add_argument("--limit", type=int, default=None, help="Max rows to process")
    args = ap.parse_args()
    try:
        asyncio.run(_run(dry_run=args.dry_run, limit=args.limit))
    except Exception as exc:
        log.error("fatal error=%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
