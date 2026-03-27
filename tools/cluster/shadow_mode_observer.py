#!/usr/bin/env python3
"""
CLI wrapper for the backend shadow-mode observer.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "fortress-guest-platform"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from backend.services.shadow_mode_observer import DEFAULT_AUDIT_PATH, run_shadow_audit


def load_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.payload_file:
        return json.loads(Path(args.payload_file).read_text())
    if args.stdin:
        raw = sys.stdin.read().strip()
        if not raw:
            raise ValueError("stdin was empty")
        return json.loads(raw)
    if args.payload_json:
        return json.loads(args.payload_json)
    raise ValueError("Provide one of --payload-file, --payload-json, or --stdin")


async def main_async(args: argparse.Namespace) -> int:
    payload = load_payload(args)
    result = await run_shadow_audit(
        payload=payload,
        metadata={"orchestrator": "spark-node-2-leader", "source": "cli"},
        audit_path=args.audit_path,
        remote_closer_url=args.remote_closer_url or None,
        timeout_seconds=args.timeout_seconds,
        tolerance=args.tolerance,
    )
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay a quote request in shadow mode and append a comparison report.")
    parser.add_argument("--payload-file", help="Path to a JSON payload matching POST /api/quotes/generate.")
    parser.add_argument("--payload-json", help="Inline JSON payload.")
    parser.add_argument("--stdin", action="store_true", help="Read the JSON payload from stdin.")
    parser.add_argument("--audit-path", default=str(DEFAULT_AUDIT_PATH), help="Markdown file to append the comparison report to.")
    parser.add_argument("--remote-closer-url", default="", help="Optional remote Node 2 closer endpoint. Falls back to local contract on failure.")
    parser.add_argument("--timeout-seconds", type=float, default=20.0, help="Timeout for remote closer requests.")
    parser.add_argument("--tolerance", default="0.01", help="Allowed monetary drift before the report is flagged.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
