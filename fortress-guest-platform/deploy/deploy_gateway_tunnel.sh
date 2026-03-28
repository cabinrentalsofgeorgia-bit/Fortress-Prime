#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../infra/gateway/config.yml"
TARGET_MODE="${TARGET_MODE:-local}"
GATEWAY_HOST="${GATEWAY_HOST:-admin@192.168.0.114}"
SSH_KEY="/home/admin/.ssh/id_ed25519_fortress"
SSH_OPTS=(-o IdentitiesOnly=yes -i "${SSH_KEY}")
CLOUDFLARE_TUNNEL_ID="${CLOUDFLARE_TUNNEL_ID:-aa7222a3-c1c9-4ee3-97c8-fb46b41a654e}"
RENDERED_CONFIG="$(mktemp)"
trap 'rm -f "${RENDERED_CONFIG}"' EXIT

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Gateway config not found: ${CONFIG_FILE}" >&2
  exit 1
fi

python3 - "${CONFIG_FILE}" "${RENDERED_CONFIG}" "${CLOUDFLARE_TUNNEL_ID}" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text()
target = Path(sys.argv[2])
tunnel_id = sys.argv[3]
target.write_text(source.replace("${CLOUDFLARE_TUNNEL_ID}", tunnel_id))
PY

if [[ "${TARGET_MODE}" == "local" ]]; then
  echo "Installing Cloudflare Tunnel config locally on this host..."
  sudo mkdir -p /etc/cloudflared
  sudo cp "${RENDERED_CONFIG}" /etc/cloudflared/config.yml
  sudo cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
  sudo systemctl restart cloudflared
  echo "Cloudflare Tunnel config deployed locally."
  exit 0
fi

echo "Creating Cloudflared config directory on ${GATEWAY_HOST}..."
ssh "${SSH_OPTS[@]}" "${GATEWAY_HOST}" "sudo mkdir -p /etc/cloudflared"

echo "Copying tunnel config to ${GATEWAY_HOST}..."
scp "${SSH_OPTS[@]}" "${RENDERED_CONFIG}" "${GATEWAY_HOST}:/tmp/crog-ai-cloudflared-config.yml"

echo "Installing tunnel config and restarting cloudflared..."
ssh "${SSH_OPTS[@]}" "${GATEWAY_HOST}" "sudo mv /tmp/crog-ai-cloudflared-config.yml /etc/cloudflared/config.yml && sudo cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate && sudo systemctl restart cloudflared"

echo "Cloudflare Tunnel config deployed to ${GATEWAY_HOST}."
