#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd -- "${APP_ROOT}/.." && pwd)"
FRONTEND_ROOT="${APP_ROOT}/apps/storefront"

export SCRIPT_DIR
export APP_ROOT
export REPO_ROOT
export FRONTEND_ROOT
