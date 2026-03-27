#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="${SCRIPT_DIR}/systemd"

if systemctl list-unit-files | grep -q '^fgp-backend\.service'; then
  sudo systemctl disable --now fgp-backend.service || true
fi
if systemctl list-unit-files | grep -q '^fgp-frontend\.service'; then
  sudo systemctl disable --now fgp-frontend.service || true
fi

sudo ln -sf "${UNIT_DIR}/fortress-backend.service" /etc/systemd/system/fortress-backend.service
sudo ln -sf "${UNIT_DIR}/fortress-frontend.service" /etc/systemd/system/fortress-frontend.service
sudo ln -sf "${UNIT_DIR}/fortress-arq-worker.service" /etc/systemd/system/fortress-arq-worker.service
sudo ln -sf "${UNIT_DIR}/fortress-vllm-bridge.service" /etc/systemd/system/fortress-vllm-bridge.service

sudo systemctl daemon-reload
sudo systemctl enable fortress-backend.service fortress-frontend.service fortress-arq-worker.service fortress-vllm-bridge.service
sudo systemctl restart fortress-backend.service fortress-frontend.service fortress-arq-worker.service fortress-vllm-bridge.service
