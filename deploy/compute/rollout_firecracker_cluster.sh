#!/usr/bin/env bash
# =============================================================================
# rollout_firecracker_cluster.sh
# Promote Firecracker sandbox settings across all DGX nodes in nodes.env.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
NODES_ENV="${REPO_DIR}/deploy/compute/nodes.env"
CANARY_ENV="${REPO_DIR}/deploy/compute/sandbox_canary.env"

usage() {
  cat <<'EOF'
Usage:
  deploy/compute/rollout_firecracker_cluster.sh apply
  deploy/compute/rollout_firecracker_cluster.sh status
  deploy/compute/rollout_firecracker_cluster.sh rollback

Notes:
  - Uses deploy/compute/nodes.env for DGX_NODES.
  - Uses deploy/compute/sandbox_canary.env as runtime template.
EOF
}

ACTION="${1:-}"
if [[ -z "${ACTION}" ]]; then
  usage
  exit 1
fi
if [[ "${ACTION}" != "apply" && "${ACTION}" != "status" && "${ACTION}" != "rollback" ]]; then
  usage
  exit 1
fi

if [[ ! -f "${NODES_ENV}" ]]; then
  echo "ERROR: missing ${NODES_ENV}" >&2
  exit 1
fi
if [[ ! -f "${CANARY_ENV}" ]]; then
  echo "ERROR: missing ${CANARY_ENV}" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${NODES_ENV}"
# shellcheck disable=SC1090
source "${CANARY_ENV}"

required_vars=(
  DGX_NODES
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
    echo "ERROR: ${v} is required" >&2
    exit 1
  fi
done

SSH_OPTS=(-p "${DGX_SSH_PORT}" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8)
SCP_OPTS=(-P "${DGX_SSH_PORT}" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8)

ARTIFACT_DIR="/tmp/fc-artifacts"
FIRECRACKER_LOCAL="${ARTIFACT_DIR}/firecracker"
JAILER_LOCAL="${ARTIFACT_DIR}/jailer"
KERNEL_LOCAL="${ARTIFACT_DIR}/kernel.bin"
ROOTFS_LOCAL="${ARTIFACT_DIR}/rootfs.ext4"
RUNNER_LOCAL="${REPO_DIR}/deploy/compute/fortress-firecracker-runner"
GUEST_AGENT_BIN_LOCAL="${REPO_DIR}/deploy/compute/firecracker_guest_agent"
GUEST_AGENT_SERVICE_LOCAL="${REPO_DIR}/deploy/compute/firecracker_guest_agent.service"
INJECT_SCRIPT_LOCAL="${REPO_DIR}/deploy/compute/inject_guest_agent_rootfs.sh"

build_env_file() {
  local out="$1"
  cat >"${out}" <<EOF
SANDBOX_RUNTIME="${SANDBOX_RUNTIME}"
SANDBOX_MEMORY_MB="${SANDBOX_MEMORY_MB:-512}"
SANDBOX_VCPU_COUNT="${SANDBOX_VCPU_COUNT:-1}"
SANDBOX_FIRECRACKER_HELPER="${SANDBOX_FIRECRACKER_HELPER}"
SANDBOX_FIRECRACKER_BIN="${SANDBOX_FIRECRACKER_BIN}"
SANDBOX_JAILER_BIN="${SANDBOX_JAILER_BIN}"
SANDBOX_KERNEL_IMAGE="${SANDBOX_KERNEL_IMAGE}"
SANDBOX_ROOTFS_IMAGE="${SANDBOX_ROOTFS_IMAGE}"
FORTRESS_FIRECRACKER_RUNNER_MODE="${FORTRESS_FIRECRACKER_RUNNER_MODE:-firecracker_microvm_scaffold}"
FORTRESS_FIRECRACKER_FALLBACK_TO_HOST_ON_BOOT_FAIL="${FORTRESS_FIRECRACKER_FALLBACK_TO_HOST_ON_BOOT_FAIL:-true}"
FORTRESS_FIRECRACKER_EXECUTION_MODE="${FORTRESS_FIRECRACKER_EXECUTION_MODE:-guest_exec}"
FORTRESS_FIRECRACKER_GUEST_CID="${FORTRESS_FIRECRACKER_GUEST_CID:-3}"
FORTRESS_GUEST_AGENT_PORT="${FORTRESS_GUEST_AGENT_PORT:-5000}"
FORTRESS_FIRECRACKER_GUEST_BOOT_WAIT_MS="${FORTRESS_FIRECRACKER_GUEST_BOOT_WAIT_MS:-900}"
FORTRESS_FIRECRACKER_GUEST_INIT_DIRECT="${FORTRESS_FIRECRACKER_GUEST_INIT_DIRECT:-true}"
EOF
}

restart_backend() {
  local remote="$1"
  ssh "${SSH_OPTS[@]}" "${remote}" "bash -lc 'fuser -k -9 8100/tcp >/dev/null 2>&1 || true; sleep 2; cd \"${REMOTE_APP_DIR}\"; [ -f \"${REMOTE_SANDBOX_ENV}\" ] && set -a && . \"${REMOTE_SANDBOX_ENV}\" && set +a || true; [ -f \".env.security\" ] && set -a && . \".env.security\" && set +a || true; nohup python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8100 --log-level info >/tmp/fgp_restart.log 2>&1 < /dev/null & echo restarted'"
}

check_health() {
  local remote="$1"
  ssh "${SSH_OPTS[@]}" "${remote}" "curl -sf '${HEALTHCHECK_URL}' >/dev/null && echo health:ok"
}

IFS=',' read -r -a DGX_NODE_LIST <<< "${DGX_NODES}"
if [[ ${#DGX_NODE_LIST[@]} -eq 0 ]]; then
  echo "ERROR: DGX_NODES resolved to empty list" >&2
  exit 1
fi

if [[ "${ACTION}" == "apply" ]]; then
  for f in "${FIRECRACKER_LOCAL}" "${JAILER_LOCAL}" "${KERNEL_LOCAL}" "${ROOTFS_LOCAL}" "${RUNNER_LOCAL}" "${GUEST_AGENT_BIN_LOCAL}" "${GUEST_AGENT_SERVICE_LOCAL}" "${INJECT_SCRIPT_LOCAL}"; do
    if [[ ! -f "${f}" ]]; then
      echo "ERROR: required local artifact missing: ${f}" >&2
      exit 1
    fi
  done
fi

for node in "${DGX_NODE_LIST[@]}"; do
  node="$(echo "${node}" | xargs)"
  [[ -z "${node}" ]] && continue
  remote="${DGX_SSH_USER}@${node}"
  echo "==== ${ACTION} ${node} ===="

  if [[ "${ACTION}" == "status" ]]; then
    ssh "${SSH_OPTS[@]}" "${remote}" "if [ -f '${REMOTE_SANDBOX_ENV}' ]; then echo 'override:present'; else echo 'override:absent'; fi"
    check_health "${remote}"
    continue
  fi

  if [[ "${ACTION}" == "rollback" ]]; then
    ssh "${SSH_OPTS[@]}" "${remote}" "rm -f '${REMOTE_SANDBOX_ENV}'"
    restart_backend "${remote}"
    sleep 3
    check_health "${remote}"
    continue
  fi

  # ACTION=apply
  ssh "${SSH_OPTS[@]}" "${remote}" "sudo mkdir -p /opt/firecracker/bin /opt/firecracker/images && sudo chown -R ${DGX_SSH_USER}:${DGX_SSH_USER} /opt/firecracker"
  ssh "${SSH_OPTS[@]}" "${remote}" "mkdir -p '${REPO_DIR}/deploy/compute'"
  scp "${SCP_OPTS[@]}" "${FIRECRACKER_LOCAL}" "${JAILER_LOCAL}" "${remote}:/opt/firecracker/bin/"
  scp "${SCP_OPTS[@]}" "${KERNEL_LOCAL}" "${ROOTFS_LOCAL}" "${remote}:/opt/firecracker/images/"
  scp "${SCP_OPTS[@]}" "${RUNNER_LOCAL}" "${remote}:/opt/firecracker/bin/"
  scp "${SCP_OPTS[@]}" "${GUEST_AGENT_BIN_LOCAL}" "${GUEST_AGENT_SERVICE_LOCAL}" "${INJECT_SCRIPT_LOCAL}" "${remote}:${REPO_DIR}/deploy/compute/"
  ssh "${SSH_OPTS[@]}" "${remote}" "chmod +x /opt/firecracker/bin/firecracker /opt/firecracker/bin/jailer /opt/firecracker/bin/fortress-firecracker-runner ${REPO_DIR}/deploy/compute/inject_guest_agent_rootfs.sh && ${REPO_DIR}/deploy/compute/inject_guest_agent_rootfs.sh /opt/firecracker/images/rootfs.ext4"
  ssh "${SSH_OPTS[@]}" "${remote}" "sudo setfacl -m u:${DGX_SSH_USER}:rw /dev/kvm || true"

  tmp_env="$(mktemp)"
  build_env_file "${tmp_env}"
  ssh "${SSH_OPTS[@]}" "${remote}" "mkdir -p '$(dirname "${REMOTE_SANDBOX_ENV}")'"
  scp "${SCP_OPTS[@]}" "${tmp_env}" "${remote}:${REMOTE_SANDBOX_ENV}"
  rm -f "${tmp_env}"

  if ssh "${SSH_OPTS[@]}" "${remote}" "python3 -m uvicorn --help >/dev/null 2>&1"; then
    restart_backend "${remote}"
    sleep 3
    check_health "${remote}"
  else
    echo "backend_restart:skipped (uvicorn missing on ${node})"
  fi
done

echo "Cluster ${ACTION} complete."
