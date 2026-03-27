#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../infra/mikrotik/split_horizon.rsc"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "RouterOS config not found: ${CONFIG_FILE}" >&2
  exit 1
fi

read -r -p "MikroTik IP address: " MIKROTIK_IP
read -r -p "MikroTik admin username: " MIKROTIK_USER

if [[ -z "${MIKROTIK_IP}" || -z "${MIKROTIK_USER}" ]]; then
  echo "Both MikroTik IP and username are required." >&2
  exit 1
fi

echo "Applying split-horizon DNS config to ${MIKROTIK_USER}@${MIKROTIK_IP}..."
ssh "${MIKROTIK_USER}@${MIKROTIK_IP}" < "${CONFIG_FILE}"
echo "RouterOS split-horizon DNS applied."
