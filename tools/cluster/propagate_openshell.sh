#!/usr/bin/env bash
# Re-extract OpenShell client TLS from each worker's local k3s secret, refresh mtls
# material under ~/.config/openshell/gateways/nemoclaw, verify gateway connectivity,
# and warm the my-assistant sandbox.
#
# Run from the head or any operator host with SSH access to the Ray workers.
# Preflight: tools/cluster/check_ray_cluster_health.sh
#
# Prerequisites on EACH worker (.104, .105, .106):
#   - openshell CLI: in PATH or at ${HOME}/.local/bin/openshell (install before this script)
#   - Docker sidecar: default name openshell-cluster-nemoclaw-<LAN-last-octet>
#   - kubectl inside that container can read secret openshell-client-tls in namespace openshell
#
# If a worker fails with "openshell not found", install the CLI on that host to match .104,
# then re-run this script.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKER_NODES=(
  "192.168.0.104"
  "192.168.0.105"
  "192.168.0.106"
)
OPEN_SHELL_GATEWAY="${OPEN_SHELL_GATEWAY:-nemoclaw}"
SANDBOX_NAME="${NEMOCLAW_OPENSHELL_SANDBOX:-my-assistant}"
# Override if your Docker container name does not follow openshell-cluster-nemoclaw-<last-octet>
# OPENSHELL_K3S_CONTAINER=my-custom-name ./tools/cluster/propagate_openshell.sh

SSH_OPTS=(
  -o BatchMode=yes
  -o ConnectTimeout=6
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

echo "[FORTRESS PRIME] Initiating OpenShell worker propagation..."

if [[ "${SKIP_RAY_CHECK:-0}" != "1" ]]; then
  if ! "${ROOT_DIR}/tools/cluster/check_ray_cluster_health.sh" >/dev/null 2>&1; then
    echo "CRITICAL: Ray matrix is not healthy. Run tools/cluster/check_ray_cluster_health.sh first." >&2
    echo "           Or set SKIP_RAY_CHECK=1 to bypass (not recommended)." >&2
    exit 1
  fi
  echo "[+] Ray cluster health gate passed."
fi

for NODE in "${WORKER_NODES[@]}"; do
  OCTET="${NODE##*.}"
  CONTAINER="${OPENSHELL_K3S_CONTAINER:-openshell-cluster-nemoclaw-${OCTET}}"
  echo "----------------------------------------"
  echo "Target: ${NODE} (k3s container: ${CONTAINER})"

  ssh "${SSH_OPTS[@]}" "${NODE}" bash -s -- "${CONTAINER}" "${OPEN_SHELL_GATEWAY}" "${SANDBOX_NAME}" <<'REMOTE'
set -euo pipefail
CONTAINER="$1"
OPEN_SHELL_GATEWAY="$2"
SANDBOX_NAME="$3"

export HOME="${HOME:-/home/admin}"
export PATH="${HOME}/.local/bin:/usr/local/bin:/usr/bin:${PATH:-}"
export OPENSHELL_GATEWAY="${OPEN_SHELL_GATEWAY}"

MTLS_DIR="${HOME}/.config/openshell/gateways/${OPEN_SHELL_GATEWAY}/mtls"
PROFILE_DIR="${HOME}/.config/openshell/gateways/${OPEN_SHELL_GATEWAY}"

echo "  [+] Verifying openshell binary..."
OPENSHELL_BIN=""
if command -v openshell >/dev/null 2>&1; then
  OPENSHELL_BIN="$(command -v openshell)"
elif [[ -x "${HOME}/.local/bin/openshell" ]]; then
  OPENSHELL_BIN="${HOME}/.local/bin/openshell"
else
  echo "  [FATAL] openshell not found in PATH or ${HOME}/.local/bin/openshell on $(hostname)" >&2
  echo "  [i] Install the OpenShell CLI on this worker (same layout as 192.168.0.104), then re-run propagate_openshell.sh." >&2
  exit 1
fi
echo "  [i] Using openshell: ${OPENSHELL_BIN}"

echo "  [+] Verifying k3s sidecar container..."
if ! docker inspect "${CONTAINER}" >/dev/null 2>&1; then
  echo "  [FATAL] Docker container not found: ${CONTAINER}" >&2
  echo "  [i] Set OPENSHELL_K3S_CONTAINER to the correct name on this host." >&2
  exit 1
fi

echo "  [+] Re-extracting authoritative TLS material from k3s secret openshell-client-tls..."
mkdir -p "${PROFILE_DIR}" "${MTLS_DIR}"
chmod 700 "${PROFILE_DIR}" "${MTLS_DIR}" 2>/dev/null || chmod 700 "${MTLS_DIR}"

cat > "${PROFILE_DIR}/metadata.json" <<EOF
{
  "name": "${OPEN_SHELL_GATEWAY}",
  "gateway_endpoint": "https://127.0.0.1:8080",
  "is_remote": false,
  "gateway_port": 8080
}
EOF

extract_b64_field() {
  local key="$1"
  local out="$2"
  docker exec "${CONTAINER}" sh -lc "kubectl -n openshell get secret openshell-client-tls -o go-template='{{index .data \"${key}\"}}' | base64 -d" >"${out}"
}

extract_b64_field "tls.crt" "${MTLS_DIR}/tls.crt"
extract_b64_field "tls.key" "${MTLS_DIR}/tls.key"
extract_b64_field "ca.crt" "${MTLS_DIR}/ca.crt"
chmod 600 "${MTLS_DIR}/tls.key" 2>/dev/null || true
chmod 644 "${MTLS_DIR}/tls.crt" "${MTLS_DIR}/ca.crt" 2>/dev/null || true

echo "  [+] Verifying gateway connection..."
if ! "${OPENSHELL_BIN}" status -g "${OPEN_SHELL_GATEWAY}" 2>/dev/null | grep -q "Connected"; then
  echo "  [FATAL] OpenShell gateway handshake failed on $(hostname). Check mtls and gateway." >&2
  exit 1
fi

echo "  [+] Warming sandbox: ${SANDBOX_NAME}..."
if "${OPENSHELL_BIN}" sandbox init -g "${OPEN_SHELL_GATEWAY}" "${SANDBOX_NAME}" 2>/dev/null; then
  echo "  [i] sandbox init ok"
else
  echo "  [i] sandbox init not available or no-op; continuing"
fi

echo "  [SUCCESS] $(hostname) OpenShell ready for gateway=${OPEN_SHELL_GATEWAY} sandbox=${SANDBOX_NAME}"
REMOTE

done

echo "----------------------------------------"
echo "[FORTRESS PRIME] Propagation complete. All workers armed."
echo "Next: ./tools/cluster/launch_nemoclaw.sh"
echo "Then: curl -s http://192.168.0.100:8000/health"
