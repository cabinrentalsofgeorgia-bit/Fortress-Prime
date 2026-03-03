#!/usr/bin/env python3
"""
Download all MailPlus (info@cabin-rentals-of-georgia.com) emails and use them
as intelligence for CROG VRS.

1. Runs the Email Bridge in MailPlus-only mode with a long backfill and no
   fetch limit, so every email in the mailbox is ingested into email_archive.
2. Optionally exports those emails to a JSON file for VRS/knowledge use.

Usage:
    # Download all MailPlus emails into email_archive (last 10 years, no limit)
    python3 tools/download_mailplus_for_vrs.py

    # Custom backfill window (days) and output path
    python3 tools/download_mailplus_for_vrs.py --backfill-days 365 --export data/vrs_intelligence/mailplus_archive.json

    # Only export already-ingested MailPlus emails (no IMAP fetch)
    python3 tools/download_mailplus_for_vrs.py --export-only --export data/vrs_intelligence/mailplus_archive.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


def run_mailplus_backfill(backfill_days: int = 3650, dry_run: bool = False) -> int:
    """Run email_bridge with --mailplus-only, --backfill N, --max-fetch 0. Returns exit code."""
    cmd = [
        sys.executable, "-m", "src.email_bridge",
        "--mailplus-only",
        "--backfill", str(backfill_days),
        "--max-fetch", "0",
    ]
    if dry_run:
        cmd.append("--dry-run")
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return result.returncode


def export_mailplus_from_archive(export_path: Path) -> int:
    """Export all email_archive rows with category imap_nas_mailplus to JSON. Returns count."""
    import psycopg2
    import psycopg2.extras

    dbname = os.getenv("DB_NAME", "fortress_db")
    user = os.getenv("DB_USER", "miner_bot")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    password = os.getenv("DB_PASS", "") or os.getenv("DB_PASSWORD", "")

    conn = psycopg2.connect(
        dbname=dbname, user=user, host=host, port=port, password=password
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id, category, sender, subject, content, sent_at,
               division, division_confidence, division_summary
        FROM email_archive
        WHERE category LIKE 'imap_nas_mailplus%'
        ORDER BY sent_at ASC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    # Serialize for JSON (datetime -> iso string)
    out = []
    for r in rows:
        d = dict(r)
        if d.get("sent_at"):
            d["sent_at"] = d["sent_at"].isoformat() if hasattr(d["sent_at"], "isoformat") else str(d["sent_at"])
        out.append(d)

    export_path.parent.mkdir(parents=True, exist_ok=True)
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    return len(out)


def main():
    parser = argparse.ArgumentParser(
        description="Download MailPlus (info@) emails for CROG VRS intelligence"
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=3650,
        help="Backfill window in days (default 3650 ≈ 10 years)",
    )
    parser.add_argument(
        "--export",
        type=Path,
        default=None,
        help="Export path for JSON (e.g. data/vrs_intelligence/mailplus_archive.json)",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Skip IMAP fetch; only export already-ingested MailPlus emails to JSON",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run bridge in dry-run (no DB writes)",
    )
    args = parser.parse_args()

    if not args.export_only:
        code = run_mailplus_backfill(
            backfill_days=args.backfill_days,
            dry_run=args.dry_run,
        )
        if code != 0:
            print("Email bridge exited with code", code)
            sys.exit(code)

    if args.export:
        export_path = args.export if args.export.is_absolute() else PROJECT_ROOT / args.export
        n = export_mailplus_from_archive(export_path)
        print(f"Exported {n} MailPlus emails to {export_path}")
    else:
        print("Done. MailPlus emails are in email_archive (category=imap_nas_mailplus).")
        print("Use --export path/to/file.json to write a JSON copy for VRS intelligence.")


if __name__ == "__main__":
    main()
