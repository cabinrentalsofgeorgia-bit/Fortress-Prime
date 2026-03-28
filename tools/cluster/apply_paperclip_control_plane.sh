#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MANIFEST_DIR="${REPO_ROOT}/deploy/compute/paperclip"

usage() {
  cat <<'EOF'
Usage:
  tools/cluster/apply_paperclip_control_plane.sh --secret-file /absolute/path/paperclip-runtime.yaml

Applies the sovereign Paperclip control-plane manifests to the reachable k3s cluster.

Requirements:
  - A real Secret manifest for `paperclip-runtime` must already exist outside Git.
  - The target host must expose either:
    - host `k3s kubectl`, or
    - Docker container `openshell-cluster-nemoclaw-100` with `kubectl`

The script intentionally refuses to apply `secret.example.yaml`.
EOF
}

SECRET_FILE=""
CONTAINER_NAME="openshell-cluster-nemoclaw-100"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --secret-file)
      SECRET_FILE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[FATAL] Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

[[ -n "${SECRET_FILE}" ]] || {
  echo "[FATAL] --secret-file is required." >&2
  usage >&2
  exit 1
}

[[ -f "${SECRET_FILE}" ]] || {
  echo "[FATAL] Secret manifest not found: ${SECRET_FILE}" >&2
  exit 1
}

if [[ "${SECRET_FILE}" == *"secret.example.yaml" ]]; then
  echo "[FATAL] Refusing to apply placeholder secret.example.yaml." >&2
  exit 1
fi

if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  KUBECTL_APPLY=(docker exec -i "${CONTAINER_NAME}" kubectl apply -f -)
  KUBECTL_RAW=(docker exec -i "${CONTAINER_NAME}" kubectl)
elif command -v k3s >/dev/null 2>&1; then
  KUBECTL_APPLY=(sudo k3s kubectl apply -f -)
  KUBECTL_RAW=(sudo k3s kubectl)
else
  echo "[FATAL] No reachable Kubernetes control plane found." >&2
  echo "        Expected Docker container ${CONTAINER_NAME} or host k3s." >&2
  exit 1
fi

apply_file() {
  local file_path="$1"
  echo "[+] Applying $(basename "${file_path}")"
  "${KUBECTL_APPLY[@]}" < "${file_path}"
}

echo "[+] Applying Paperclip namespace and secret boundary..."
apply_file "${MANIFEST_DIR}/namespace.yaml"
apply_file "${SECRET_FILE}"

echo "[+] Applying Paperclip control-plane manifests..."
apply_file "${MANIFEST_DIR}/configmap.yaml"
apply_file "${MANIFEST_DIR}/pvc.yaml"
apply_file "${MANIFEST_DIR}/service.yaml"
apply_file "${MANIFEST_DIR}/networkpolicy.yaml"
apply_file "${MANIFEST_DIR}/glass-proxy-configmap.yaml"
apply_file "${MANIFEST_DIR}/glass-proxy-deployment.yaml"
apply_file "${MANIFEST_DIR}/glass-proxy-service.yaml"
apply_file "${MANIFEST_DIR}/ingress.yaml"
apply_file "${MANIFEST_DIR}/deployment.yaml"

echo "[+] Current Paperclip objects:"
"${KUBECTL_RAW[@]}" -n paperclip get pods,svc,ingress,pvc

echo "[SUCCESS] Paperclip control-plane manifests applied."
