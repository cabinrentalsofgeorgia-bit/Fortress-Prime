#!/bin/bash
# =============================================================================
# FORTRESS PRIME - GPU Unlock Script for DGX Spark (GB10)
# =============================================================================
#
# PROBLEM: Ollama reports "0 B VRAM" on DGX Spark because cudaMemGetInfo
#          doesn't account for reclaimable memory in the unified memory
#          architecture (UMA). Ollama falls back to pure CPU mode.
#
# FIX:    1. Flush page caches so memory reports more accurately
#         2. Add OLLAMA_NUM_GPU=999 to force GPU layer offloading
#         3. Increase context window from 4096 to 32768
#         4. Restart Ollama service
#
# USAGE:  sudo bash fix_gpu_ollama.sh
# =============================================================================

set -e

echo "============================================================"
echo "  FORTRESS PRIME - GPU Unlock for DGX Spark"
echo "============================================================"
echo

# --- Step 1: Flush page caches ---
echo "[1/5] Flushing page caches for accurate memory reporting..."
sync
echo 3 > /proc/sys/vm/drop_caches
echo "  Done. Freed reclaimable memory."
echo

# --- Step 2: Create systemd override ---
echo "[2/5] Creating Ollama service override..."
mkdir -p /etc/systemd/system/ollama.service.d

cat > /etc/systemd/system/ollama.service.d/gpu-override.conf << 'OVERRIDE'
[Service]
# Force GPU offloading on DGX Spark (GB10 unified memory)
# OLLAMA_NUM_GPU=999 tells Ollama to offload ALL layers to GPU
# regardless of what cudaMemGetInfo reports
Environment="OLLAMA_NUM_GPU=999"

# Increase context window (default 4096 is too small for large prompts)
Environment="OLLAMA_CONTEXT_LENGTH=32768"

# Enable flash attention for efficiency
Environment="OLLAMA_FLASH_ATTENTION=true"

# Keep host binding
Environment="OLLAMA_HOST=0.0.0.0"

# Enable debug logging to verify GPU detection
Environment="OLLAMA_DEBUG=INFO"
OVERRIDE

echo "  Created /etc/systemd/system/ollama.service.d/gpu-override.conf"
echo

# --- Step 3: Reload systemd ---
echo "[3/5] Reloading systemd daemon..."
systemctl daemon-reload
echo "  Done."
echo

# --- Step 4: Restart Ollama ---
echo "[4/5] Restarting Ollama service..."
systemctl restart ollama
sleep 3
echo "  Done. Waiting for GPU detection..."
echo

# --- Step 5: Verify ---
echo "[5/5] Checking GPU status..."
sleep 5

echo
echo "  --- nvidia-smi ---"
nvidia-smi
echo
echo "  --- Ollama startup logs ---"
journalctl -u ollama --no-pager -n 30
echo
echo "  --- Ollama service status ---"
systemctl status ollama --no-pager | head -15
echo

echo "============================================================"
echo "  GPU Unlock complete."
echo "  Check above for 'offloading N layers to gpu'"
echo "  If you see 'CPU' only, the GB10 may need a newer Ollama."
echo "============================================================"
