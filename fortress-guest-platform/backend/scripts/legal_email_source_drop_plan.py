"""Dry-run planner for Fortress Legal email source drops.

This CLI is intentionally manifest-only. It inventories operator-controlled
``.eml`` files and writes chain-of-custody metadata so the operator can review
case/privilege guesses before any DB, Qdrant, NAS vault, or IMAP mutation.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.services.legal.email_intake_foundation import (
    EmailSourceDropSafetyError,
    build_source_drop_plan,
    write_manifest,
)

DEFAULT_AUDIT_DIR = Path("/mnt/fortress_nas/audits")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a manifest-only plan for Fortress Legal .eml source drops",
    )
    parser.add_argument("--source-root", required=True, help="Directory containing .eml files")
    parser.add_argument("--limit", type=int, default=None, help="Optional candidate limit")
    parser.add_argument(
        "--output",
        default=None,
        help="Manifest output path. Defaults to /mnt/fortress_nas/audits/...",
    )
    parser.add_argument(
        "--allow-legacy-mixed-dump",
        action="store_true",
        help="Override the default block on legacy legal_vault/7il-v-knight-ndga source drops",
    )
    parser.add_argument("--json", action="store_true", help="Print full manifest JSON to stdout")
    return parser.parse_args(argv)


def _default_output() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_AUDIT_DIR / f"legal-email-source-drop-plan-{ts}.json"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        plan = build_source_drop_plan(
            Path(args.source_root),
            limit=args.limit,
            allow_legacy_mixed_dump=args.allow_legacy_mixed_dump,
        )
    except (EmailSourceDropSafetyError, FileNotFoundError, NotADirectoryError) as exc:
        print(f"ERROR: {exc}")
        return 2

    output_path = Path(args.output) if args.output else _default_output()
    write_manifest(plan, output_path)

    if args.json:
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    else:
        print(
            "# legal email source-drop plan: "
            f"source_root={plan.source_root} "
            f"candidates={plan.candidate_count} "
            f"attachments={plan.attachment_count} "
            f"skipped={len(plan.skipped)} "
            f"errors={len(plan.errors)} "
            f"manifest={output_path}"
        )
        print("# no IMAP, DB, Qdrant, or NAS vault writes performed")
    return 1 if plan.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
