#!/usr/bin/env python3
"""
check_schema_staleness.py — CI gate: verify schema.meta.json matches live migration state.

Exits 0 if the snapshot is current; exits 1 with a GitHub Actions error annotation
if any migration files have changed since the dump was generated.

Usage:
  python3 fortress-guest-platform/ci/check_schema_staleness.py

Detection mechanism: compares the git tree hash of
  fortress-guest-platform/backend/alembic/versions/
stored in schema.meta.json against the current HEAD tree hash.
If they differ, a migration was added/modified since the last dump.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_META = Path(__file__).parent / "schema.meta.json"
_VERSIONS_PATH = "fortress-guest-platform/backend/alembic/versions"


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), *args],
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def main() -> int:
    if not _META.exists():
        print("::error::ci/schema.meta.json not found — run 'make ci-schema-dump' first.")
        return 1

    meta = json.loads(_META.read_text())
    stored_tree = meta.get("alembic_versions_tree", "")
    if not stored_tree:
        print("::error::schema.meta.json is missing alembic_versions_tree — regenerate with 'make ci-schema-dump'.")
        return 1

    current_tree = _git("rev-parse", f"HEAD:{_VERSIONS_PATH}")
    if not current_tree:
        # Fallback: can't determine tree (e.g. shallow clone) — allow through with warning
        print("::warning::Could not determine alembic versions tree hash — skipping staleness check.")
        return 0

    if stored_tree == current_tree:
        print(f"Schema snapshot is current (tree={stored_tree[:12]}).")
        return 0

    print("::error::Schema snapshot is stale.")
    print(f"  Stored tree:  {stored_tree[:12]}")
    print(f"  Current tree: {current_tree[:12]}")
    print("  Migration files have changed since the last 'make ci-schema-dump'.")
    print("  Fix: run 'make ci-schema-dump' and commit fortress-guest-platform/ci/")
    return 1


if __name__ == "__main__":
    sys.exit(main())
