#!/bin/bash
# Wrapper for launchd: sources .env (JWT_SECRET, DB, etc.) then runs master_console.py.
# Used by com.crog.master_console.plist so secrets stay out of the plist.
# REPO is derived from script location so it works for any install path.
set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
[[ -f "${REPO}/.env" ]] && set -a && source "${REPO}/.env" && set +a
exec "${REPO}/venv/bin/python" "${REPO}/tools/master_console.py" "$@"
