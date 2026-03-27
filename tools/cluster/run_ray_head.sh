#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/ray_runtime_common.sh"

RAY_BIN="$(resolve_ray_bin)"
RAY_NODE_IP="${RAY_NODE_IP:-192.168.0.100}"
RAY_PORT="${RAY_PORT:-6390}"
RAY_DASHBOARD_HOST="${RAY_DASHBOARD_HOST:-0.0.0.0}"
RAY_DASHBOARD_PORT="${RAY_DASHBOARD_PORT:-8265}"
RAY_TEMP_DIR="${RAY_TEMP_DIR:-/tmp/ray}"

exec "${RAY_BIN}" start \
  --head \
  --node-ip-address="${RAY_NODE_IP}" \
  --port="${RAY_PORT}" \
  --dashboard-host="${RAY_DASHBOARD_HOST}" \
  --dashboard-port="${RAY_DASHBOARD_PORT}" \
  --temp-dir="${RAY_TEMP_DIR}" \
  --disable-usage-stats \
  --block
