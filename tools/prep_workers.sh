#!/bin/bash
# tools/prep_workers.sh
# Run this from the CAPTAIN (192.168.0.100)
# Prepares workers for Wolfpack deployment: creates dirs, fixes Docker permissions.

WORKERS=("192.168.0.105" "192.168.0.106")  # Spark-03 (Ocular), Spark-04 (Sovereign)
REMOTE_USER="admin"

echo "🔧 COMMENCING WORKER PREP..."
echo ""

for IP in "${WORKERS[@]}"; do
  echo "------------------------------------------------"
  echo "Targeting: $IP"

  # 1. Connectivity Check
  if ping -c 1 -W 1 "$IP" &>/dev/null; then
    echo "✅ Network: ONLINE"
  else
    echo "❌ Network: UNREACHABLE. Check power/cables."
    continue
  fi

  # 2. Remote Setup
  echo "🛠️  Configuring Node..."
  ssh -t "$REMOTE_USER@$IP" bash -s << EOF
    set -e
    # A. Create Project Directory
    mkdir -p ~/Fortress-Prime
    echo "   -> Directory Created."

    # B. Fix Docker Permissions
    if ! groups | grep -q docker; then
      echo "   -> Adding user to 'docker' group..."
      sudo usermod -aG docker \$USER
      echo "   -> User added. PERMISSION FIX REQUIRES LOGOUT/LOGIN (or run: newgrp docker)"
    else
      echo "   -> Docker permissions already OK."
    fi
EOF
  echo ""
done

echo "------------------------------------------------"
echo "🔧 PREP COMPLETE. If permissions were changed, log out/in on workers or run: newgrp docker"
echo "   Then re-run: ./deploy_wolfpack.sh"
echo "------------------------------------------------"
