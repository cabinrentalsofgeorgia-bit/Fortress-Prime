#!/usr/bin/env python3
"""
Compatibility wrapper for the systemd worker entrypoint.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parent
APP_ROOT = REPO_ROOT / "fortress-guest-platform"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

for env_file in (
    REPO_ROOT / ".env",
    APP_ROOT / ".env",
    REPO_ROOT / ".env.security",
):
    if env_file.exists():
        load_dotenv(env_file, override=True)

from arq import check_health, run_worker

from backend.core.worker import WorkerSettings

DEPRECATION_MESSAGE = (
    "nas_worker.py is a deprecated duplicate ARQ entrypoint. "
    "Use fortress-arq-worker.service as the sole async worker for backend.core.worker.WorkerSettings."
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the Fortress ARQ worker using the current WorkerSettings.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Override ARQ max_jobs for this process.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run an ARQ health check and exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if os.getenv("FORTRESS_ALLOW_LEGACY_NAS_WORKER", "").strip().lower() not in {"1", "true", "yes"}:
        print(DEPRECATION_MESSAGE, file=sys.stderr)
        return 2
    if args.check:
        return check_health(WorkerSettings)

    kwargs: dict[str, int] = {}
    if args.workers is not None:
        kwargs["max_jobs"] = int(args.workers)
    run_worker(WorkerSettings, **kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
