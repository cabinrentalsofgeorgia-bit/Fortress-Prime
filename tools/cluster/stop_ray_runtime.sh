#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/ray_runtime_common.sh"

RAY_BIN="$(resolve_ray_bin)"

if "${RAY_BIN}" stop; then
  exit 0
fi

exec "${RAY_BIN}" stop --force
