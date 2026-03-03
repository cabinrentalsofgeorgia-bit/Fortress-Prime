#!/bin/bash
# =============================================================================
# FORTRESS PRIME - Ollama Upgrade + GPU Unlock for DGX Spark
# =============================================================================
#
# Upgrades Ollama from 0.15.4 to latest (0.15.5+)
# Then restarts with GPU-aware settings for GB10 Blackwell
#
# USAGE: sudo bash upgrade_ollama.sh
# =============================================================================

set -e

echo "============================================================"
echo "  FORTRESS PRIME - Ollama Upgrade + GPU Unlock"
echo "============================================================"
echo

# --- Current version ---
CURRENT=$(ollama --version 2>&1 | grep -oP '[\d.]+' || echo "unknown")
echo "  Current version: $CURRENT"
echo

# --- Step 1: Flush caches ---
echo "[1/6] Flushing page caches for accurate memory reporting..."
sync
echo 3 > /proc/sys/vm/drop_caches
echo "  Done."
echo

# --- Step 2: Stop Ollama ---
echo "[2/6] Stopping Ollama service..."
systemctl stop ollama
sleep 3
echo "  Done."
echo

# --- Step 3: Upgrade Ollama ---
echo "[3/6] Downloading and installing latest Ollama..."
curl -fsSL https://ollama.com/install.sh | sh
echo
NEW=$(ollama --version 2>&1 | grep -oP '[\d.]+' || echo "unknown")
echo "  Upgraded: $CURRENT -> $NEW"
echo

# --- Step 4: Ensure GPU override ---
echo "[4/6] Applying GPU override for DGX Spark..."
mkdir -p /etc/systemd/system/ollama.service.d

cat > /etc/systemd/system/ollama.service.d/gpu-override.conf << 'OVERRIDE'
[Service]
# Force GPU offloading on DGX Spark (GB10 unified memory)
Environment="OLLAMA_NUM_GPU=999"
Environment="OLLAMA_CONTEXT_LENGTH=32768"
Environment="OLLAMA_FLASH_ATTENTION=true"
Environment="OLLAMA_HOST=0.0.0.0"
Environment="OLLAMA_DEBUG=INFO"
OVERRIDE

echo "  Override applied."
echo

# --- Step 5: Reload and restart ---
echo "[5/6] Reloading systemd and starting Ollama..."
systemctl daemon-reload
systemctl start ollama
sleep 5
echo "  Done."
echo

# --- Step 6: Verify ---
echo "[6/6] Verifying GPU detection..."
echo
echo "  --- Ollama Version ---"
ollama --version
echo
echo "  --- nvidia-smi ---"
nvidia-smi
echo
echo "  --- Ollama Startup Logs (GPU detection) ---"
journalctl -u ollama --no-pager -n 30 | grep -i "gpu\|vram\|offload\|layer\|cuda\|inference\|compute\|memory\|device"
echo
echo "  --- Full Recent Logs ---"
journalctl -u ollama --no-pager -n 20
echo

echo "============================================================"
echo "  Upgrade complete. Check logs above for GPU offloading."
echo "  If GPU is active, re-run:"
echo "    python3 nas_migration_agent.py plan"
echo "============================================================"
