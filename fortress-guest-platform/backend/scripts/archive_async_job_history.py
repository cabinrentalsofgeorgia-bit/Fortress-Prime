#!/usr/bin/env python3
"""
Archive historical async job ledger rows to JSONL before pruning them.

Default behavior is dry-run. Pass --apply to write the archive file and delete
the matching rows from async_job_runs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[3]

for candidate in (PROJECT_ROOT, REPO_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

for env_file in (REPO_ROOT / ".env", PROJECT_ROOT / ".env", REPO_ROOT / ".env.security"):
    if env_file.exists():
        load_dotenv(env_file, override=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archive historical failed/cancelled async_job_runs rows to JSONL before pruning.",
    )
    parser.add_argument(
        "--older-than-minutes",
        type=int,
        default=60,
        help="Archive rows finished at least this many minutes ago (default: 60).",
    )
    parser.add_argument(
        "--status",
        action="append",
        default=None,
        help="Ledger status to archive. Repeatable. Defaults to failed and cancelled.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum rows to archive in one run (default: 500).",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional archive JSONL path. Defaults under backend/artifacts/async-job-archives/.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the archive file and delete the matching rows.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    from backend.core.database import close_db, get_session_factory
    from backend.services.async_job_archive import archive_async_job_history

    output_path = Path(args.output).expanduser() if args.output else None
    statuses = list(dict.fromkeys(args.status or ["failed", "cancelled"]))

    try:
        factory = get_session_factory()
        async with factory() as db:
            result = await archive_async_job_history(
                db,
                older_than_minutes=int(args.older_than_minutes),
                statuses=statuses,
                limit=int(args.limit),
                apply=bool(args.apply),
                output_path=output_path,
                app_root=PROJECT_ROOT,
            )

        print(
            json.dumps(
                {
                    "matched_rows": result.matched_rows,
                    "statuses": list(result.statuses),
                    "older_than_minutes": result.older_than_minutes,
                    "cutoff_utc": result.cutoff_utc,
                    "apply": result.apply,
                }
            )
        )
        if result.matched_rows == 0:
            return 0

        if not result.apply:
            for item in result.preview:
                print(
                    json.dumps(
                        {
                            "id": item.id,
                            "job_name": item.job_name,
                            "status": item.status,
                            "finished_at": item.finished_at,
                            "error_text": item.error_text,
                        }
                    )
                )
            if result.preview_truncated > 0:
                print(json.dumps({"preview_truncated": result.preview_truncated}))
            return 0

        print(
            json.dumps(
                {
                    "archived_rows": result.archived_rows,
                    "archive_path": result.archive_path,
                }
            )
        )
        return 0
    finally:
        await close_db()


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
