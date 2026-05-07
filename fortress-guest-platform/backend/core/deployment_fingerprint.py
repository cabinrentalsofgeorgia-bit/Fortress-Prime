from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STARTED_AT_UTC = datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git_output(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=_repo_root(),
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def deployment_fingerprint(*, service: str, version: str) -> dict[str, Any]:
    git_sha = _git_output(["rev-parse", "--short=12", "HEAD"])
    dirty_status = _git_output(["status", "--short"])
    return {
        "service": service,
        "version": version,
        "git_sha": git_sha or "unknown",
        "source": "git" if git_sha else "unknown",
        "dirty": bool(dirty_status),
        "started_at_utc": STARTED_AT_UTC,
    }
