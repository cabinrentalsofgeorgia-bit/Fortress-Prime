#!/bin/bash
# One-time setup for Tier 1 SOTA on Captain (DGX).
# Installs fortress-inference.service so switch_defcon.sh fortress_legal runs on boot.
# Optional: /home/admin/Fortress-Prime/switch_defcon.sh — if missing, unit is still installed but service will fail at start until added.
# Run: sudo deploy/linux/setup.sh
set -e

# Prefer repo containing this script, else default
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
LINUX_DIR="${REPO}/deploy/linux"
SERVICE_NAME="fortress-inference.service"
SYSTEMD_DIR="/etc/systemd/system"

[[ $(id -u) -eq 0 ]] || { echo "Run with sudo."; exit 1; }

echo "Fortress Tier 1 SOTA — Captain (DGX) setup"
echo "  REPO: ${REPO}"
echo "  Service: ${SERVICE_NAME}"
echo ""

if [[ ! -x "${REPO}/switch_defcon.sh" ]]; then
  echo "WARNING: ${REPO}/switch_defcon.sh not found or not executable."
  echo "Installing unit anyway. Service will fail at start until you add switch_defcon.sh (Constitution Article II requires Human approval to add/modify)."
  echo ""
fi

echo "Installing ${SERVICE_NAME} into ${SYSTEMD_DIR}"
cp "${LINUX_DIR}/fortress-inference.service" "${SYSTEMD_DIR}/"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
echo "  Enabled. Start now with: sudo systemctl start fortress-inference"
echo ""
echo "Validate:"
echo "  systemctl status fortress-inference"
echo "  journalctl -u fortress-inference -f"
