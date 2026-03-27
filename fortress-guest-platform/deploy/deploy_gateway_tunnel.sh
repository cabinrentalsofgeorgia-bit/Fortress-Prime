#!/usr/bin/env bash
set -euo pipefail

GATEWAY_HOST="admin@192.168.0.114"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../infra/gateway/config.yml"
SSH_KEY="/home/admin/.ssh/id_ed25519_fortress"
SSH_OPTS=(-o IdentitiesOnly=yes -i "${SSH_KEY}")

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Gateway config not found: ${CONFIG_FILE}" >&2
  exit 1
fi

echo "Creating Cloudflared config directory on ${GATEWAY_HOST}..."
ssh "${SSH_OPTS[@]}" "${GATEWAY_HOST}" "sudo mkdir -p /etc/cloudflared"

echo "Copying tunnel config to ${GATEWAY_HOST}..."
scp "${SSH_OPTS[@]}" "${CONFIG_FILE}" "${GATEWAY_HOST}:/tmp/crog-ai-cloudflared-config.yml"

echo "Installing tunnel config and restarting cloudflared..."
ssh "${SSH_OPTS[@]}" "${GATEWAY_HOST}" "sudo mv /tmp/crog-ai-cloudflared-config.yml /etc/cloudflared/config.yml && sudo systemctl restart cloudflared"

echo "Cloudflare Tunnel config deployed to ${GATEWAY_HOST}."
