#!/bin/bash
# DeepSeek R1 Distill 70B — Sovereign Brain (NVIDIA NIM)
# Run on Captain (Spark-02) by default, or on Spark-04 if you have a dedicated node.
# On Spark-04: run this script there, then set BRAIN_NIM_URL=http://<spark04_ip>:8000 on Captain.

# --- CONFIGURATION ---
NAS_CACHE="/mnt/fortress_nas/nim_cache"
PROJECT_DIR="$HOME/Fortress-Prime"

# Load API Key from .env
if [ -z "$NGC_API_KEY" ]; then
    if grep -q "NGC_API_KEY=" "$PROJECT_DIR/.env"; then
        export NGC_API_KEY=$(grep "NGC_API_KEY=" "$PROJECT_DIR/.env" | cut -d '=' -f2 | tr -d '"')
    else
        echo "❌ NGC_API_KEY missing. Please export it or add to .env"
        exit 1
    fi
fi

echo "🧠 MAXING OUT SPARK 2: DeepSeek R1 Distill (70B)..."
echo "   [+] Target: NVIDIA GB10 (Blackwell Class)"
echo "   [+] Precision: Optimized (FP8/FP4)"

# --- STOP OLD BRAIN ---
docker stop fortress-nim 2>/dev/null || true
docker rm fortress-nim 2>/dev/null || true

# --- LAUNCH DEEPSEEK R1 (70B) ---
# We use --gpus all (no --runtime=nvidia for compatibility with Docker default config)
# MAX_INPUT_TOKEN=64000 uses your high RAM for reading massive docs
docker run -d --name fortress-nim \
  --gpus all \
  --restart always \
  -v "$NAS_CACHE:/opt/nim/.cache" \
  -e NGC_API_KEY="$NGC_API_KEY" \
  -e NIM_MAX_INPUT_TOKEN=64000 \
  -e NIM_MAX_OUTPUT_TOKEN=8192 \
  -p 8000:8000 \
  nvcr.io/nim/deepseek-ai/deepseek-r1-distill-llama-70b:latest

echo "✅ DEEPSEEK 70B DEPLOYED."
echo "   Monitor Download: docker logs -f fortress-nim"
