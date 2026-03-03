#!/bin/bash

# --- CONFIGURATION ---
REMOTE_IP="192.168.0.104"
REMOTE_USER="admin"
NAS_CACHE="/mnt/fortress_nas/nim_cache"
PROJECT_DIR="$HOME/Fortress-Prime"

# Load Key
if [ -z "$NGC_API_KEY" ]; then
    export NGC_API_KEY=$(grep "NGC_API_KEY=" "$PROJECT_DIR/.env" | cut -d '=' -f2 | tr -d '"')
fi

echo "🚀 IGNITING ENGINE 2 (Spark 1: The Worker)..."
echo "   [+] Model: Meta Llama 3.3 70B (The best Tool-User)"
echo "   [+] Target: $REMOTE_IP"

# Send the launch command to Spark 1
# On Spark 1, ensure admin can run docker: sudo usermod -aG docker admin; then log out/in
ssh $REMOTE_USER@$REMOTE_IP "
    export NGC_API_KEY='$NGC_API_KEY'

    # Stop old containers
    docker stop fortress-worker 2>/dev/null || true
    docker rm fortress-worker 2>/dev/null || true

    # Launch Llama 3.3 70B (--gpus all for Docker compatibility)
    # We map the SAME NAS cache so they share storage!
    docker run -d --name fortress-worker \\
      --gpus all \\
      --restart always \\
      -v $NAS_CACHE:/opt/nim/.cache \\
      -e NGC_API_KEY=\$NGC_API_KEY \\
      -e NIM_MAX_INPUT_TOKEN=32000 \\
      -e NIM_MAX_OUTPUT_TOKEN=4096 \\
      -p 8000:8000 \\
      nvcr.io/nim/meta/llama-3.3-70b-instruct:latest
"

echo "✅ SIGNAL SENT."
echo "   Spark 1 is now downloading Llama 3.3 70B (~40GB)."
echo "   To monitor it, run: ssh $REMOTE_USER@$REMOTE_IP 'docker logs -f fortress-worker'"
