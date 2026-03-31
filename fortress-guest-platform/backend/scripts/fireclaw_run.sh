#!/usr/bin/env bash
# Thin wrapper: delegates to fireclaw_run.py (requires root for loop mount).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/fireclaw_run.py" "$@"
