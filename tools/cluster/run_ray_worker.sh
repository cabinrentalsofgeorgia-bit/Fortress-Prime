#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/ray_runtime_common.sh"

RAY_BIN="$(resolve_ray_bin)"
RAY_NODE_IP="${RAY_NODE_IP:?RAY_NODE_IP must be set}"
RAY_HEAD_ADDRESS="${RAY_HEAD_ADDRESS:?RAY_HEAD_ADDRESS must be set}"

exec "${RAY_BIN}" start \
  --address="${RAY_HEAD_ADDRESS}" \
  --node-ip-address="${RAY_NODE_IP}" \
  --disable-usage-stats \
  --block
