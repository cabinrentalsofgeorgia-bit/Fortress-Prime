"""
build_holdout.py — sample eval holdout rows from llm_training_captures.

Pulls last 7 days of captures, samples up to HOLDOUT_SIZE_PER_DOMAIN rows per
domain, marks them eval_holdout=True so the exporter skips them, and writes a
manifest JSON to HOLDOUT_DIR for run_eval.py to consume.

Domain detection via source_module prefix patterns:
  legal    → source_module starts with 'legal_'
  vrs      → source_module contains 'vrs' or 'concierge' or 'reservation'
  pricing  → source_module in (quote_engine, pricing_engine, rate_*)
  macro    → source_module in (macro_treasury, ota_vision_recon, market_*)

Usage:
  python build_holdout.py [--dry-run] [--date YYYY-MM-DD]

  --dry-run : validate config and query counts without marking rows or writing files
  --date    : override today's date (for testing)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"build_holdout"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("build_holdout")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_URI              = os.getenv("POSTGRES_ADMIN_URI",
                        "postgresql://fortress_admin:fortress@127.0.0.1:5432/fortress_shadow"
                      ).replace("+asyncpg", "")
HOLDOUT_DIR         = Path(os.getenv("HOLDOUT_DIR",
                        "/mnt/fortress_nas/finetune-artifacts/holdouts"))
HOLDOUT_DAYS        = int(os.getenv("EVAL_HOLDOUT_DAYS",   "7"))
HOLDOUT_PER_DOMAIN  = int(os.getenv("EVAL_HOLDOUT_SIZE",   "50"))

DOMAIN_PATTERNS: dict[str, list[str]] = {
    "legal":   ["legal_"],
    "vrs":     ["vrs_", "concierge", "reservation"],
    "pricing": ["quote_engine", "pricing_engine", "rate_"],
    "macro":   ["macro_treasury", "ota_vision_recon", "market_"],
}


def detect_domain(source_module: str) -> str:
    sm = source_module.lower()
    for domain, patterns in DOMAIN_PATTERNS.items():
        if any(p in sm for p in patterns):
            return domain
    return "other"


def build_holdout(today: date, dry_run: bool) -> dict:
    cutoff = today - timedelta(days=HOLDOUT_DAYS)
    log.info("Sampling holdout from last %d days (since %s)", HOLDOUT_DAYS, cutoff.isoformat())

    conn = psycopg2.connect(DB_URI)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT id, source_module, model_used, user_prompt, assistant_resp, created_at
            FROM llm_training_captures
            WHERE created_at >= %s
              AND (eval_holdout IS NULL OR eval_holdout = FALSE)
              -- MVP v1: include pending rows so first eval cycle runs same-night as
              -- first training. Tighten to exported-only in Phase 4c when volume is sufficient.
              AND status IN ('pending', 'exported')
        """, (cutoff,))
        rows = cur.fetchall()
        log.info("Found %d eligible rows in window", len(rows))

        # Group by domain
        by_domain: dict[str, list] = {d: [] for d in DOMAIN_PATTERNS}
        by_domain["other"] = []
        for row in rows:
            d = detect_domain(row["source_module"])
            by_domain[d].append(row)

        # Sample per domain
        holdout_ids: list[str] = []
        holdout_records: list[dict] = []
        domain_counts: dict[str, int] = {}

        for domain, domain_rows in by_domain.items():
            if not domain_rows:
                log.info("Domain %s: 0 eligible rows — skipping", domain)
                domain_counts[domain] = 0
                continue
            sample_size = min(len(domain_rows), HOLDOUT_PER_DOMAIN)
            sampled = random.sample(domain_rows, sample_size)
            domain_counts[domain] = sample_size
            log.info("Domain %s: %d/%d sampled", domain, sample_size, len(domain_rows))
            for row in sampled:
                holdout_ids.append(str(row["id"]))
                holdout_records.append({
                    "id": str(row["id"]),
                    "domain": domain,
                    "source_module": row["source_module"],
                    "model_used": row["model_used"],
                    "user_prompt": row["user_prompt"],
                    "teacher_response": row["assistant_resp"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                })

        manifest = {
            "holdout_date": today.isoformat(),
            "built_at": datetime.now(tz=timezone.utc).isoformat(),
            "holdout_days": HOLDOUT_DAYS,
            "holdout_per_domain": HOLDOUT_PER_DOMAIN,
            "total_holdout": len(holdout_records),
            "domain_counts": domain_counts,
            "records": holdout_records,
        }

        if dry_run:
            log.info("[DRY RUN] Would mark %d rows as eval_holdout=True", len(holdout_ids))
            log.info("[DRY RUN] Would write manifest to %s", HOLDOUT_DIR / f"holdout-{today.isoformat()}.json")
            log.info("[DRY RUN] domain_counts=%s", domain_counts)
            conn.rollback()
            return manifest

        if holdout_ids:
            cur.execute(
                "UPDATE llm_training_captures SET eval_holdout = TRUE WHERE id::text = ANY(%s)",
                (holdout_ids,)
            )
            log.info("Marked %d rows eval_holdout=True", cur.rowcount)

        HOLDOUT_DIR.mkdir(parents=True, exist_ok=True)
        manifest_path = HOLDOUT_DIR / f"holdout-{today.isoformat()}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        log.info("Manifest written to %s (%d records)", manifest_path, len(holdout_records))

        conn.commit()
        return manifest

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build eval holdout set")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count and plan without marking rows or writing files")
    parser.add_argument("--date", default=None,
                        help="Override today's date (YYYY-MM-DD)")
    args = parser.parse_args()

    today = date.fromisoformat(args.date) if args.date else date.today()
    log.info("build_holdout starting date=%s dry_run=%s", today, args.dry_run)

    manifest = build_holdout(today, args.dry_run)
    log.info("Complete. total_holdout=%d domain_counts=%s",
             manifest["total_holdout"], manifest["domain_counts"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
