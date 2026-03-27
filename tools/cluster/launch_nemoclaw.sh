#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_ROOT="${ROOT_DIR}/fortress-guest-platform"
RAY_DASHBOARD_ADDRESS="${RAY_DASHBOARD_ADDRESS:-http://192.168.0.100:8265}"
SERVE_APP_NAME="${SERVE_APP_NAME:-nemoclaw-alpha}"
DEPLOY_SCRIPT="${DEPLOY_SCRIPT:-backend/orchestration/deploy_nemoclaw_serve.py}"
RAY_RUNTIME_ENV_JSON="${RAY_RUNTIME_ENV_JSON:-{\"excludes\":[\"backend/scripts/drupal_granular_blueprint.json\",\"apps\",\"backend/.pytest_cache\",\"backend/.ruff_cache\",\".pytest_cache\",\".uv-venv\",\"node_modules\"]}}"

echo "[FORTRESS PRIME] Initiating NemoClaw Ray Serve deployment..."

if ! "${ROOT_DIR}/tools/cluster/check_ray_cluster_health.sh" >/dev/null; then
  echo "CRITICAL: Ray matrix is not healthy. Run tools/cluster/check_ray_cluster_health.sh first." >&2
  exit 1
fi

cd "${APP_ROOT}"
export PYTHONPATH="${APP_ROOT}:${PYTHONPATH:-}"

ray job submit \
  --no-wait \
  --address "${RAY_DASHBOARD_ADDRESS}" \
  --runtime-env-json "${RAY_RUNTIME_ENV_JSON}" \
  --working-dir "${APP_ROOT}" \
  -- python3 "${DEPLOY_SCRIPT}"

echo "[FORTRESS PRIME] NemoClaw Orchestrator deployed."
echo "Ingress available at: http://192.168.0.100:8000/api/agent/execute"
echo
sleep 8
serve status --address "${RAY_DASHBOARD_ADDRESS}"
