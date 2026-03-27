#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE_PATH="${ROOT_DIR}/deploy/compute/openshell/worker-sidecar-template.yaml"
GATEWAY_NAME="${OPEN_SHELL_GATEWAY:-nemoclaw}"
LITELLM_GATEWAY_IP="${LITELLM_GATEWAY_IP:-192.168.0.100}"
OPENSHELL_INFERENCE_PROVIDER_NAME="${OPENSHELL_INFERENCE_PROVIDER_NAME:-fortress-relay-svc}"
OPENSHELL_INFERENCE_BASE_URL="${OPENSHELL_INFERENCE_BASE_URL:-http://litellm-relay.openshell.svc.cluster.local:4010/v1}"
OPENSHELL_INFERENCE_MODEL="${OPENSHELL_INFERENCE_MODEL:-nemotron-3-super-120b}"
SSH_USER="${SSH_USER:-admin}"
SSH_OPTS=(
  -o BatchMode=yes
  -o ConnectTimeout=8
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

usage() {
  cat <<'EOF'
Usage:
  ./tools/cluster/provision_worker.sh <target-ip>

Example:
  ./tools/cluster/provision_worker.sh 192.168.0.105

What it does:
  1. Verifies node-local OpenShell PKI exists on the target.
  2. Creates/updates the required Kubernetes TLS secrets from that PKI.
  3. Creates/updates the OpenShell LiteLLM auth secret from the exported operator environment.
  4. Materializes deploy/compute/openshell/worker-sidecar-template.yaml with the target octet.
  5. Applies the rendered manifest over SSH directly into the target cluster.

Required env:
  OPENSHELL_LITELLM_API_KEY or LITELLM_API_KEY or LITELLM_MASTER_KEY

Secrets are not read from Git and are not copied from another worker.
EOF
}

fail() {
  echo "[FATAL] $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

normalize_ip() {
  local input="$1"
  if [[ "$input" =~ ^192\.168\.0\.([0-9]{1,3})$ ]]; then
    echo "$input"
    return 0
  fi
  if [[ "$input" =~ ^([0-9]{1,3})$ ]]; then
    echo "192.168.0.${BASH_REMATCH[1]}"
    return 0
  fi
  return 1
}

materialize_manifest() {
  local octet="$1"
  local handshake_secret="$2"
  sed \
    -e "s/{{NODE_OCTET}}/${octet}/g" \
    -e "s/{{SSH_HANDSHAKE_SECRET}}/${handshake_secret}/g" \
    -e "s/{{LITELLM_GATEWAY_IP}}/${LITELLM_GATEWAY_IP}/g" \
    "${TEMPLATE_PATH}"
}

resolve_litellm_api_key() {
  if [[ -n "${OPENSHELL_LITELLM_API_KEY:-}" ]]; then
    printf '%s' "${OPENSHELL_LITELLM_API_KEY}"
    return 0
  fi
  if [[ -n "${LITELLM_API_KEY:-}" ]]; then
    printf '%s' "${LITELLM_API_KEY}"
    return 0
  fi
  if [[ -n "${LITELLM_MASTER_KEY:-}" ]]; then
    printf '%s' "${LITELLM_MASTER_KEY}"
    return 0
  fi

  return 1
}

require_cmd sed
require_cmd ssh
require_cmd openssl
require_cmd base64

[[ -f "${TEMPLATE_PATH}" ]] || fail "Template not found: ${TEMPLATE_PATH}"
[[ $# -eq 1 ]] || { usage; exit 1; }

TARGET_IP="$(normalize_ip "$1")" || fail "Expected target IP like 192.168.0.105 or octet like 105"
OCTET="${TARGET_IP##*.}"
CONTAINER_NAME="${OPENSHELL_K3S_CONTAINER:-openshell-cluster-nemoclaw-${OCTET}}"

echo "[FORTRESS PRIME] Provisioning OpenShell worker ${TARGET_IP}"
echo "[i] Template: ${TEMPLATE_PATH}"
echo "[i] Target container fallback: ${CONTAINER_NAME}"
echo "[i] LiteLLM gateway target: ${LITELLM_GATEWAY_IP}:4000"

LITELLM_API_KEY_VALUE="$(resolve_litellm_api_key)" || fail \
  "Unable to resolve LiteLLM API key. Export OPENSHELL_LITELLM_API_KEY, LITELLM_API_KEY, or LITELLM_MASTER_KEY."
[[ -n "${LITELLM_API_KEY_VALUE}" ]] || fail \
  "Resolved LiteLLM API key is empty. Refusing to provision litellm-auth secret."

CURRENT_SECRET="$(
  ssh "${SSH_OPTS[@]}" "${SSH_USER}@${TARGET_IP}" \
    "set -euo pipefail
     if docker container inspect '${CONTAINER_NAME}' >/dev/null 2>&1; then
       docker exec '${CONTAINER_NAME}' kubectl -n openshell get statefulset openshell -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name==\"OPENSHELL_SSH_HANDSHAKE_SECRET\")].value}' 2>/dev/null || true
     elif command -v k3s >/dev/null 2>&1; then
       sudo k3s kubectl -n openshell get statefulset openshell -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name==\"OPENSHELL_SSH_HANDSHAKE_SECRET\")].value}' 2>/dev/null || true
     fi"
)"

HANDSHAKE_SECRET="${CURRENT_SECRET:-$(openssl rand -hex 32)}"

echo "[i] Using per-node handshake secret: ${HANDSHAKE_SECRET:0:8}... (preserved or generated)"
echo "[i] Creating/updating node-local PKI secrets and applying manifest..."

MANIFEST_B64="$(materialize_manifest "${OCTET}" "${HANDSHAKE_SECRET}" | base64 -w0)"
LITELLM_API_KEY_B64="$(printf '%s' "${LITELLM_API_KEY_VALUE}" | base64 -w0)"

ssh "${SSH_OPTS[@]}" "${SSH_USER}@${TARGET_IP}" \
  "TARGET_IP='${TARGET_IP}' TARGET_OCTET='${OCTET}' CONTAINER_NAME='${CONTAINER_NAME}' GATEWAY_NAME='${GATEWAY_NAME}' HANDSHAKE_SECRET='${HANDSHAKE_SECRET}' MANIFEST_B64='${MANIFEST_B64}' LITELLM_API_KEY_B64='${LITELLM_API_KEY_B64}' bash -s" <<'REMOTE'
set -euo pipefail

MANIFEST="$(printf '%s' "${MANIFEST_B64}" | base64 -d)"
HOME_DIR="${HOME:-/home/admin}"
PROFILE_DIR="${HOME_DIR}/.config/openshell/gateways/${GATEWAY_NAME}"
MTLS_DIR="${PROFILE_DIR}/mtls"
PKI_DIR="${PROFILE_DIR}/pki"

required_local_files=(
  "${MTLS_DIR}/ca.crt"
  "${MTLS_DIR}/tls.crt"
  "${MTLS_DIR}/tls.key"
  "${PKI_DIR}/ca.crt"
  "${PKI_DIR}/server.crt"
  "${PKI_DIR}/server.key"
)

for path in "${required_local_files[@]}"; do
  [[ -f "${path}" ]] || {
    echo "[FATAL] Missing node-local PKI file: ${path}" >&2
    echo "        Generate node-local OpenShell PKI before running provision_worker.sh." >&2
    exit 1
  }
done

mkdir -p "${PROFILE_DIR}"
cat > "${PROFILE_DIR}/metadata.json" <<EOF
{
  "name": "${GATEWAY_NAME}",
  "gateway_endpoint": "https://127.0.0.1:8080",
  "is_remote": false,
  "gateway_port": 8080
}
EOF
chmod 700 "${PROFILE_DIR}" "${MTLS_DIR}" "${PKI_DIR}" 2>/dev/null || true
chmod 600 "${MTLS_DIR}/tls.key" "${PKI_DIR}/server.key" 2>/dev/null || true

if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  KUBECTL_APPLY=(docker exec -i "${CONTAINER_NAME}" kubectl apply -f -)
  KUBECTL_RAW=(docker exec -i "${CONTAINER_NAME}" kubectl)
elif command -v k3s >/dev/null 2>&1; then
  KUBECTL_APPLY=(sudo k3s kubectl apply -f -)
  KUBECTL_RAW=(sudo k3s kubectl)
else
  echo "[FATAL] No reachable Kubernetes control plane found on ${TARGET_IP}." >&2
  echo "        Expected Docker container ${CONTAINER_NAME} or host k3s." >&2
  exit 1
fi

echo "[+] Ensuring openshell namespace exists..."
printf '%s\n' 'apiVersion: v1' 'kind: Namespace' 'metadata:' '  name: openshell' | "${KUBECTL_APPLY[@]}"

echo "[+] Syncing TLS secrets from node-local PKI..."
encode_b64() {
  base64 -w0 "$1"
}

apply_secret_yaml() {
  printf '%s' "$1" | "${KUBECTL_APPLY[@]}"
}

SERVER_CA_B64="$(encode_b64 "${PKI_DIR}/ca.crt")"
SERVER_TLS_CRT_B64="$(encode_b64 "${PKI_DIR}/server.crt")"
SERVER_TLS_KEY_B64="$(encode_b64 "${PKI_DIR}/server.key")"
CLIENT_CA_B64="$(encode_b64 "${MTLS_DIR}/ca.crt")"
CLIENT_TLS_CRT_B64="$(encode_b64 "${MTLS_DIR}/tls.crt")"
CLIENT_TLS_KEY_B64="$(encode_b64 "${MTLS_DIR}/tls.key")"

apply_secret_yaml "$(cat <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: openshell-server-client-ca
  namespace: openshell
type: Opaque
data:
  ca.crt: ${SERVER_CA_B64}
EOF
)"

apply_secret_yaml "$(cat <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: openshell-server-tls
  namespace: openshell
type: kubernetes.io/tls
data:
  tls.crt: ${SERVER_TLS_CRT_B64}
  tls.key: ${SERVER_TLS_KEY_B64}
EOF
)"

apply_secret_yaml "$(cat <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: litellm-auth
  namespace: openshell
type: Opaque
data:
  LITELLM_API_KEY: ${LITELLM_API_KEY_B64}
EOF
)"

apply_secret_yaml "$(cat <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: openshell-client-tls
  namespace: openshell
type: Opaque
data:
  ca.crt: ${CLIENT_CA_B64}
  tls.crt: ${CLIENT_TLS_CRT_B64}
  tls.key: ${CLIENT_TLS_KEY_B64}
EOF
)"

echo "[+] Applying rendered OpenShell worker manifest..."
printf '%s' "${MANIFEST}" | "${KUBECTL_APPLY[@]}"

echo "[+] Waiting for statefulset rollout..."
"${KUBECTL_RAW[@]}" -n openshell rollout status statefulset/openshell --timeout=120s

resolve_openshell_bin() {
  if command -v openshell >/dev/null 2>&1; then
    command -v openshell
    return 0
  fi
  for candidate in /home/admin/.local/bin/openshell /usr/local/bin/openshell; do
    [[ -x "${candidate}" ]] && {
      printf '%s\n' "${candidate}"
      return 0
    }
  done
  return 1
}

OPENSHELL_BIN="$(resolve_openshell_bin)" || {
  echo "[FATAL] openshell CLI not found on ${TARGET_IP}." >&2
  exit 1
}

echo "[+] Wiring gateway-managed inference.local route..."
"${OPENSHELL_BIN}" provider delete "${OPENSHELL_INFERENCE_PROVIDER_NAME}" -g "${GATEWAY_NAME}" >/dev/null 2>&1 || true
"${OPENSHELL_BIN}" provider create \
  -g "${GATEWAY_NAME}" \
  --name "${OPENSHELL_INFERENCE_PROVIDER_NAME}" \
  --type openai \
  --credential OPENAI_API_KEY=dummy \
  --config OPENAI_BASE_URL="${OPENSHELL_INFERENCE_BASE_URL}" >/dev/null
"${OPENSHELL_BIN}" inference set \
  -g "${GATEWAY_NAME}" \
  --provider "${OPENSHELL_INFERENCE_PROVIDER_NAME}" \
  --model "${OPENSHELL_INFERENCE_MODEL}" \
  --no-verify >/dev/null
sleep 7
"${OPENSHELL_BIN}" inference get -g "${GATEWAY_NAME}"

echo "[SUCCESS] ${TARGET_IP} provisioned with OpenShell sidecar IaC."
REMOTE

echo "[FORTRESS PRIME] Worker ${TARGET_IP} provisioned."
echo "[i] Next: ./tools/cluster/propagate_openshell.sh"
