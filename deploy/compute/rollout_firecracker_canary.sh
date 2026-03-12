#!/usr/bin/env bash
# =============================================================================
# rollout_firecracker_canary.sh
# Reversible Firecracker canary rollout for sandbox runtime on one DGX node.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CANARY_ENV="${REPO_DIR}/deploy/compute/sandbox_canary.env"

usage() {
  cat <<'EOF'
Usage:
  deploy/compute/rollout_firecracker_canary.sh apply
  deploy/compute/rollout_firecracker_canary.sh status
  deploy/compute/rollout_firecracker_canary.sh rollback

Notes:
  - Copy deploy/compute/sandbox_canary.env.example to sandbox_canary.env first.
  - apply writes REMOTE_SANDBOX_ENV and restarts backend.
  - rollback removes REMOTE_SANDBOX_ENV and restarts backend.
EOF
}

if [[ "${1:-}" == "" ]]; then
  usage
  exit 1
fi

ACTION="${1}"
if [[ "${ACTION}" != "apply" && "${ACTION}" != "status" && "${ACTION}" != "rollback" ]]; then
  usage
  exit 1
fi

if [[ ! -f "${CANARY_ENV}" ]]; then
  echo "ERROR: missing ${CANARY_ENV}" >&2
  echo "Copy deploy/compute/sandbox_canary.env.example to sandbox_canary.env and set values." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${CANARY_ENV}"

required_vars=(
  DGX_CANARY_NODE
  DGX_SSH_USER
  DGX_SSH_PORT
  REMOTE_APP_DIR
  REMOTE_SANDBOX_ENV
  SANDBOX_RUNTIME
  SANDBOX_FIRECRACKER_HELPER
  SANDBOX_FIRECRACKER_BIN
  SANDBOX_JAILER_BIN
  SANDBOX_KERNEL_IMAGE
  SANDBOX_ROOTFS_IMAGE
  HEALTHCHECK_URL
)

for v in "${required_vars[@]}"; do
  if [[ -z "${!v:-}" ]]; then
    echo "ERROR: ${v} is required in sandbox_canary.env" >&2
    exit 1
  fi
done

SSH_OPTS=(-p "${DGX_SSH_PORT}" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8)
SCP_OPTS=(-P "${DGX_SSH_PORT}" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8)
REMOTE="${DGX_SSH_USER}@${DGX_CANARY_NODE}"

default_restart_cmd() {
  cat <<EOF
cd "${REMOTE_APP_DIR}" && \
[ -f "${REMOTE_SANDBOX_ENV}" ] && set -a && source "${REMOTE_SANDBOX_ENV}" && set +a || true && \
[ -f ".env.security" ] && set -a && source ".env.security" && set +a || true && \
fuser -k -9 8100/tcp >/dev/null 2>&1 || true && \
sleep 2 && \
nohup python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8100 --log-level info </dev/null > /tmp/fgp_restart.log 2>&1 & disown; exit 0
EOF
}

RESTART_CMD="${BACKEND_RESTART_CMD:-}"
if [[ -z "${RESTART_CMD}" ]]; then
  RESTART_CMD="$(default_restart_cmd)"
fi

run_remote() {
  local cmd="$1"
  ssh "${SSH_OPTS[@]}" "${REMOTE}" "${cmd}"
}

check_health() {
  run_remote "curl -sf '${HEALTHCHECK_URL}' >/dev/null && echo 'health:ok' || (echo 'health:failed' && exit 1)"
}

apply_canary() {
  local tmp_file
  tmp_file="$(mktemp)"
  cat >"${tmp_file}" <<EOF
SANDBOX_RUNTIME="${SANDBOX_RUNTIME}"
SANDBOX_MEMORY_MB="${SANDBOX_MEMORY_MB:-512}"
SANDBOX_VCPU_COUNT="${SANDBOX_VCPU_COUNT:-1}"
SANDBOX_FIRECRACKER_HELPER="${SANDBOX_FIRECRACKER_HELPER}"
SANDBOX_FIRECRACKER_BIN="${SANDBOX_FIRECRACKER_BIN}"
SANDBOX_JAILER_BIN="${SANDBOX_JAILER_BIN}"
SANDBOX_KERNEL_IMAGE="${SANDBOX_KERNEL_IMAGE}"
SANDBOX_ROOTFS_IMAGE="${SANDBOX_ROOTFS_IMAGE}"
FORTRESS_FIRECRACKER_RUNNER_MODE="${FORTRESS_FIRECRACKER_RUNNER_MODE:-bootstrap_host_exec}"
FORTRESS_FIRECRACKER_FALLBACK_TO_HOST_ON_BOOT_FAIL="${FORTRESS_FIRECRACKER_FALLBACK_TO_HOST_ON_BOOT_FAIL:-true}"
FORTRESS_FIRECRACKER_EXECUTION_MODE="${FORTRESS_FIRECRACKER_EXECUTION_MODE:-host_fallback}"
FORTRESS_FIRECRACKER_GUEST_CID="${FORTRESS_FIRECRACKER_GUEST_CID:-3}"
FORTRESS_GUEST_AGENT_PORT="${FORTRESS_GUEST_AGENT_PORT:-5000}"
FORTRESS_FIRECRACKER_GUEST_BOOT_WAIT_MS="${FORTRESS_FIRECRACKER_GUEST_BOOT_WAIT_MS:-900}"
FORTRESS_FIRECRACKER_GUEST_INIT_DIRECT="${FORTRESS_FIRECRACKER_GUEST_INIT_DIRECT:-true}"
EOF

  run_remote "mkdir -p \"$(dirname "${REMOTE_SANDBOX_ENV}")\""
  scp "${SCP_OPTS[@]}" "${tmp_file}" "${REMOTE}:${REMOTE_SANDBOX_ENV}" >/dev/null
  rm -f "${tmp_file}"

  run_remote "test -x '${SANDBOX_FIRECRACKER_HELPER}'"
  run_remote "test -x '${SANDBOX_FIRECRACKER_BIN}'"
  run_remote "test -x '${SANDBOX_JAILER_BIN}'"
  run_remote "test -f '${SANDBOX_KERNEL_IMAGE}'"
  run_remote "test -f '${SANDBOX_ROOTFS_IMAGE}'"

  run_remote "${RESTART_CMD}"
  sleep 4
  check_health
  echo "Canary apply complete on ${DGX_CANARY_NODE}."
}

status_canary() {
  echo "Node: ${DGX_CANARY_NODE}"
  run_remote "if [ -f '${REMOTE_SANDBOX_ENV}' ]; then echo 'override:present'; cat '${REMOTE_SANDBOX_ENV}'; else echo 'override:absent'; fi"
  check_health
}

rollback_canary() {
  run_remote "rm -f '${REMOTE_SANDBOX_ENV}'"
  run_remote "${RESTART_CMD}"
  sleep 4
  check_health
  echo "Canary rollback complete on ${DGX_CANARY_NODE}."
}

case "${ACTION}" in
  apply)
    apply_canary
    ;;
  status)
    status_canary
    ;;
  rollback)
    rollback_canary
    ;;
esac
