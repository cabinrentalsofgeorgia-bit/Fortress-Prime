#!/bin/bash
# tools/ngc_login_workers.sh
# Run from CAPTAIN (192.168.0.100)
# Logs both Wolfpack workers into NVIDIA NGC so they can pull NIM images.
#
# Usage:
#   ./tools/ngc_login_workers.sh
#
# IMPORTANT: Run from a real interactive terminal (not via automation).
# Docker login requires TTY; auth_remote.sh has the same requirement.
# Reads NGC_API_KEY from .env (same as auth_remote.sh) or NGC_KEY env var.

WORKERS=("192.168.0.105" "192.168.0.106")
REMOTE_USER="admin"
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

# Resolve key: NGC_KEY env, then NGC_API_KEY from .env (matches auth_remote.sh)
if [ -n "$NGC_KEY" ]; then
  KEY="$NGC_KEY"
elif [ -f "$PROJECT_DIR/.env" ] && grep -q "NGC_API_KEY=" "$PROJECT_DIR/.env"; then
  KEY=$(grep "NGC_API_KEY=" "$PROJECT_DIR/.env" | cut -d '=' -f2 | tr -d '"')
fi

if [ -z "$KEY" ]; then
  echo "❌ NGC key not found. Set NGC_KEY or add NGC_API_KEY=... to .env"
  echo "   Get your key: https://ngc.nvidia.com/setup/api-key"
  exit 1
fi

echo "🔐 NGC Handshake — Authenticating Wolfpack workers..."
echo ""

for IP in "${WORKERS[@]}"; do
  echo "   -> $IP..."
  # Same pattern as auth_remote.sh — run from a real terminal for best results
  if echo "$KEY" | ssh "$REMOTE_USER@$IP" "docker login nvcr.io -u \$oauthtoken --password-stdin" 2>/dev/null; then
    echo "      ✅ $IP authenticated"
  else
    echo "      ❌ $IP failed (run from interactive terminal if automated)"
  fi
  echo ""
done

echo "------------------------------------------------"
echo "🔐 NGC Handshake complete. Run: ./deploy_wolfpack.sh"
echo "------------------------------------------------"
