#!/bin/bash

# --- CONFIGURATION ---
REMOTE_IP="192.168.0.104"
NAS_CACHE="/mnt/fortress_nas/nim_cache"
PROJECT_DIR="$HOME/Fortress-Prime"

# Get Key
KEY=$(grep "NGC_API_KEY=" "$PROJECT_DIR/.env" | cut -d '=' -f2 | tr -d '"')

echo "👁️ DEPLOYING: Llama 3.2 90B Vision (The Forensic Auditor)"
echo "   [+] Mission: Scan NAS, ID files, 'See' receipts/contracts"

# Launch Remote Container on Spark 1 (--gpus all only, no --runtime=nvidia)
ssh admin@$REMOTE_IP "
    export NGC_API_KEY='$KEY'

    # Stop the old worker (if running)
    docker stop fortress-worker 2>/dev/null || true
    docker rm fortress-worker 2>/dev/null || true

    # Prune space
    docker system prune -f > /dev/null 2>&1

    # Launch the Vision Brain
    docker run -d --name fortress-worker \
      --gpus all \
      --restart always \
      -v $NAS_CACHE:/opt/nim/.cache \
      -e NGC_API_KEY=\$NGC_API_KEY \
      -e NIM_MAX_INPUT_TOKEN=32000 \
      -e NIM_MAX_OUTPUT_TOKEN=4096 \
      -p 8000:8000 \
      nvcr.io/nim/meta/llama-3.2-90b-vision-instruct:latest
"

echo "✅ VISION UPGRADE STARTED."
echo "   Monitor: ssh admin@$REMOTE_IP 'docker logs -f fortress-worker'"
