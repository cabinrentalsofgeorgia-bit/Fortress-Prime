#!/usr/bin/env bash
# NOPASSWD sudo wrapper for Fortress backend user → root fireclaw_run.py
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec sudo -n "$HERE/fireclaw_run.py" "$@"
