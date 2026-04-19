#!/usr/bin/env python3
"""
backfill_label_historical.py — One-off Godhead labeling for historical exported captures.

Labels only dedup winners (capture_metadata->>'dedup_winner' = 'true') from
llm_training_captures WHERE status='exported' that have no label yet.

Bypasses the nightly 1-day window. Respects the daily budget cap. Safe to
re-run: the write_label_sync UPSERT uses ON CONFLICT DO NOTHING.

Usage:
  python3 src/backfill_label_historical.py [--dry-run]

  --dry-run : query and estimate cost without calling Godhead or writing labels
"""
from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load env files before backend imports — DB_URI is resolved at labeling_pipeline import time.
# override=False so an explicitly set process env always wins.
_repo_root = Path(__file__).resolve().parent.parent
for _env_file in [".env", ".env.dgx", ".env.security"]:
    _env_path = _repo_root / "fortress-guest-platform" / _env_file
    if _env_path.exists():
        load_dotenv(_env_path, override=False)

# Import shared labeling primitives
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fortress-guest-platform"))
from backend.services.labeling_pipeline import (
    DB_URI,
    _estimate_call_cost,
    _GODHEAD_TEACHERS,
    _DEFAULT_TEACHER,
    call_godhead_sync,
    check_budget_remaining,
    write_label_sync,
)

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"backfill_label"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("backfill_label")

_CAPTURE_TABLE = "llm_training_captures"


def _fetch_unlabeled_winners(conn: psycopg2.extensions.connection) -> list[Any]:
    """
    Return dedup-winner exported captures that have no label yet.

    Winner criteria: capture_metadata->>'dedup_winner' = 'true'.
    Singletons (capture_metadata IS NULL) are excluded — this script only runs
    after the dedup tagging step has been applied via dedup_historical_captures().
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT tc.id::text, tc.task_type, tc.user_prompt, tc.assistant_resp
        FROM llm_training_captures tc
        LEFT JOIN capture_labels cl
          ON cl.capture_id = tc.id
         AND cl.capture_table = %s
        WHERE tc.status = 'exported'
          AND (tc.capture_metadata->>'dedup_winner') = 'true'
          AND tc.task_type IS NOT NULL
          AND cl.id IS NULL
        ORDER BY tc.created_at ASC
    """, (_CAPTURE_TABLE,))
    return cur.fetchall()


def run(dry_run: bool) -> dict:
    """Label all unlabeled dedup winners. Returns stats dict."""
    log.info("backfill_label_start dry_run=%s", dry_run)

    remaining = check_budget_remaining()
    log.info("budget_remaining=$%.4f", remaining)

    conn = psycopg2.connect(DB_URI)
    rows = _fetch_unlabeled_winners(conn)
    conn.close()

    log.info("unlabeled_winners=%d", len(rows))

    n_processed = 0
    n_labeled   = 0
    n_skipped   = 0
    n_errors    = 0
    spent       = Decimal("0")

    if not rows:
        log.info("Nothing to label — all dedup winners already have labels.")
    else:
        for row in rows:
            task_type = row["task_type"] or "unknown"
            n_processed += 1

            est = _estimate_call_cost(
                _GODHEAD_TEACHERS.get(task_type, _DEFAULT_TEACHER)[0]
            )
            if spent + est > remaining:
                log.warning(
                    "budget_exhausted spent=$%.4f remaining=$%.4f — stopping.",
                    spent, remaining,
                )
                n_skipped += len(rows) - n_processed + 1
                break

            if dry_run:
                log.info(
                    "[DRY RUN] would label capture_id=%s task=%s est_cost=$%.4f",
                    row["id"][:8], task_type, est,
                )
                spent += est
                n_labeled += 1
                continue

            try:
                model, decision, reasoning, cost = call_godhead_sync(
                    task_type,
                    row["user_prompt"] or "",
                    row["assistant_resp"] or "",
                )
                write_label_sync(
                    row["id"], _CAPTURE_TABLE, task_type,
                    model, decision, reasoning, cost,
                )
                spent += cost
                n_labeled += 1
                log.info(
                    "labeled capture_id=%s task=%s decision=%s cost=$%.4f",
                    row["id"][:8], task_type, decision, cost,
                )
            except Exception as exc:
                n_errors += 1
                log.error("label_error capture_id=%s error=%s", row["id"][:8], str(exc)[:200])

    stats = {
        "processed": n_processed,
        "labeled": n_labeled,
        "skipped_budget": n_skipped,
        "errors": n_errors,
        "total_cost_usd": float(spent),
    }
    log.info("backfill_label_complete stats=%s", stats)
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill Godhead labels for historical captures")
    parser.add_argument("--dry-run", action="store_true",
                        help="Estimate cost without calling Godhead or writing labels")
    args = parser.parse_args()
    result = run(args.dry_run)
    import json
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result["errors"] == 0 else 1)
