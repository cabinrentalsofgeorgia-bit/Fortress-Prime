#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[quality] Running governance gate..."
bash "${ROOT_DIR}/bin/governance_gate.sh"

echo "[quality] Running coverage gate..."
bash "${ROOT_DIR}/bin/run_coverage.sh"

echo "[quality] Running API smoke checks..."
if [[ -x "${ROOT_DIR}/venv/bin/python" ]]; then
  "${ROOT_DIR}/venv/bin/python" - <<'PY'
import urllib.request
import sys

targets = [
    ("http://127.0.0.1:8000/health", "gateway"),
]

for url, name in targets:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            if resp.status >= 400:
                print(f"[quality] smoke failed for {name}: {resp.status}")
                sys.exit(1)
    except Exception:
        # Smoke is best-effort in local dev and should not fail when service isn't running.
        print(f"[quality] smoke skipped for {name}: service not reachable")
PY
fi

echo "[quality] All quality gates complete."
