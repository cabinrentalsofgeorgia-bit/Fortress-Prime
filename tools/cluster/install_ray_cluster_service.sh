#!/usr/bin/env bash
set -euo pipefail

ROLE=""
NODE_IP=""
HEAD_ADDRESS=""
RAY_BIN="${RAY_BIN:-/home/admin/.local/bin/ray}"

usage() {
  cat <<'EOF'
Usage:
  tools/cluster/install_ray_cluster_service.sh --role head --node-ip 192.168.0.100
  tools/cluster/install_ray_cluster_service.sh --role worker --node-ip 192.168.0.105 --head-address 192.168.0.100:6390
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --role)
      ROLE="${2:-}"
      shift 2
      ;;
    --node-ip)
      NODE_IP="${2:-}"
      shift 2
      ;;
    --head-address)
      HEAD_ADDRESS="${2:-}"
      shift 2
      ;;
    --ray-bin)
      RAY_BIN="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${ROLE}" || -z "${NODE_IP}" ]]; then
  usage >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_DIR="${ROOT_DIR}/tools/cluster/systemd"

install_script_file() {
  local source_path="$1"
  local target_path="$2"

  if [[ "${source_path}" != "${target_path}" ]]; then
    sudo install -m 0755 "${source_path}" "${target_path}"
  else
    sudo chmod 0755 "${target_path}"
  fi
}

install_script_file "${ROOT_DIR}/tools/cluster/ray_runtime_common.sh" /home/admin/Fortress-Prime/tools/cluster/ray_runtime_common.sh
install_script_file "${ROOT_DIR}/tools/cluster/run_ray_head.sh" /home/admin/Fortress-Prime/tools/cluster/run_ray_head.sh
install_script_file "${ROOT_DIR}/tools/cluster/run_ray_worker.sh" /home/admin/Fortress-Prime/tools/cluster/run_ray_worker.sh
install_script_file "${ROOT_DIR}/tools/cluster/stop_ray_runtime.sh" /home/admin/Fortress-Prime/tools/cluster/stop_ray_runtime.sh

case "${ROLE}" in
  head)
    sudo tee /etc/default/fortress-ray-head >/dev/null <<EOF
RAY_NODE_IP=${NODE_IP}
RAY_PORT=6390
RAY_DASHBOARD_HOST=0.0.0.0
RAY_DASHBOARD_PORT=8265
RAY_TEMP_DIR=/tmp/ray
RAY_BIN=${RAY_BIN}
EOF
    sudo ln -sf "${UNIT_DIR}/fortress-ray-head.service" /etc/systemd/system/fortress-ray-head.service
    sudo systemctl disable --now fortress-ray-worker.service >/dev/null 2>&1 || true
    sudo -u admin "${RAY_BIN}" stop --force >/dev/null 2>&1 || true
    sudo pkill -f 'ray start --head' >/dev/null 2>&1 || true
    sudo pkill -f 'gcs_server' >/dev/null 2>&1 || true
    sudo systemctl daemon-reload
    sudo systemctl enable --now fortress-ray-head.service
    ;;
  worker)
    if [[ -z "${HEAD_ADDRESS}" ]]; then
      echo "--head-address is required for worker role" >&2
      exit 1
    fi
    sudo tee /etc/default/fortress-ray-worker >/dev/null <<EOF
RAY_NODE_IP=${NODE_IP}
RAY_HEAD_ADDRESS=${HEAD_ADDRESS}
RAY_BIN=${RAY_BIN}
EOF
    sudo ln -sf "${UNIT_DIR}/fortress-ray-worker.service" /etc/systemd/system/fortress-ray-worker.service
    sudo systemctl disable --now fortress-ray-head.service >/dev/null 2>&1 || true
    sudo -u admin "${RAY_BIN}" stop --force >/dev/null 2>&1 || true
    sudo systemctl daemon-reload
    sudo systemctl enable --now fortress-ray-worker.service
    ;;
  *)
    echo "Unsupported role: ${ROLE}" >&2
    exit 1
    ;;
esac
