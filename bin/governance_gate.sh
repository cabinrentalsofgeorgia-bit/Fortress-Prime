#!/usr/bin/env bash
set -euo pipefail

echo "[governance] Running cursor rule consistency checks..."
python3 "/home/admin/Fortress-Prime/bin/check_cursor_rules.py"
echo "[governance] Running secret hygiene checks..."
python3 "/home/admin/Fortress-Prime/bin/check_secrets_hygiene.py"
echo "[governance] Checks passed."
