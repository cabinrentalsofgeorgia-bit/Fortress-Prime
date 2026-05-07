"""Counsel review workbench artifact loader.

The workbench is intentionally artifact-backed so this product layer can be
versioned without schema changes or additional document/vector writes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

AUDIT_DIR = Path("/mnt/fortress_nas/audits")
WORKBENCH_PREFIX = "fortress-counsel-review-"


def _candidate_manifests(case_slug: str) -> list[Path]:
    if not AUDIT_DIR.exists():
        return []
    candidates: list[Path] = []
    for path in AUDIT_DIR.glob(f"{WORKBENCH_PREFIX}*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("case_slug") == case_slug:
            candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def load_latest_workbench(case_slug: str) -> dict[str, Any] | None:
    """Return the latest case-scoped workbench manifest, if one exists."""
    for path in _candidate_manifests(case_slug):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["manifest_path"] = str(path)
        return payload
    return None

