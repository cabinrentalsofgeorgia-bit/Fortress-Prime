#!/bin/bash
# One-time setup for Tier 1 SOTA on Mac Mini.
# Creates log dir, installs launchd plists, loads services.
# Run from repo root or deploy/mac/; requires sudo for system daemons.
#
# master_console runs via deploy/mac/run_master_console.sh, which sources .env (JWT_SECRET, etc.).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
MAC_DIR="${REPO}/deploy/mac"
LOG_DIR="/var/log/crog"
LAUNCHD_DIR="/Library/LaunchDaemons"
SOTA_USER="$(whoami)"

echo "CROG Tier 1 SOTA — Mac Mini setup"
echo "  REPO: ${REPO}"
echo "  LOG_DIR: ${LOG_DIR}"
echo "  LAUNCHD_DIR: ${LAUNCHD_DIR}"
echo ""

# 1. Create log directory (sudo)
if [[ ! -d "${LOG_DIR}" ]]; then
  echo "Creating ${LOG_DIR}"
  sudo mkdir -p "${LOG_DIR}"
  sudo chown "${SOTA_USER}:staff" "${LOG_DIR}"
  sudo chmod 755 "${LOG_DIR}"
else
  echo "Log dir exists: ${LOG_DIR}"
fi

# 2. Detect nginx binary for ai_gateway (Apple Silicon: /opt/homebrew/bin/nginx, Intel: /usr/local/bin/nginx)
NGINX_BIN="/usr/local/bin/nginx"
if [[ -x /opt/homebrew/bin/nginx ]]; then
  NGINX_BIN="/opt/homebrew/bin/nginx"
fi
if [[ ! -x "${NGINX_BIN}" ]]; then
  echo "WARNING: nginx not found at ${NGINX_BIN}; ai_gateway may fail to start."
fi

# 3. Ensure wrapper is executable (sources .env for JWT_SECRET)
chmod +x "${MAC_DIR}/run_master_console.sh" 2>/dev/null || true

# 4. Substitute __SOTA_REPO__ and __SOTA_USER__ in plist templates and install to LaunchDaemons
echo "Installing plists into ${LAUNCHD_DIR}"
sed "s|__SOTA_REPO__|${REPO}|g; s|__SOTA_USER__|${SOTA_USER}|g" "${MAC_DIR}/com.crog.master_console.plist" | sudo tee "${LAUNCHD_DIR}/com.crog.master_console.plist" >/dev/null
sed "s|__SOTA_REPO__|${REPO}|g; s|__SOTA_USER__|${SOTA_USER}|g; s|__NGINX_BIN__|${NGINX_BIN}|g" "${MAC_DIR}/com.crog.ai_gateway.plist" | sudo tee "${LAUNCHD_DIR}/com.crog.ai_gateway.plist" >/dev/null
sudo chown root:wheel "${LAUNCHD_DIR}/com.crog.master_console.plist" "${LAUNCHD_DIR}/com.crog.ai_gateway.plist"
sudo chmod 644 "${LAUNCHD_DIR}/com.crog.master_console.plist" "${LAUNCHD_DIR}/com.crog.ai_gateway.plist"

# 5. Load services (unload first if already loaded to pick up changes)
for label in com.crog.master_console com.crog.ai_gateway; do
  sudo launchctl list "${label}" &>/dev/null && sudo launchctl unload "${LAUNCHD_DIR}/${label}.plist" || true
  sudo launchctl load "${LAUNCHD_DIR}/${label}.plist"
  echo "  Loaded: ${label}"
done

echo ""
echo "Validate:"
echo "  launchctl list | grep com.crog"
echo "  curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9800/  # master_console"
echo "  curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/  # ai_gateway"
echo ""
echo "Logs: ${LOG_DIR}/"
