#!/bin/bash
# ==============================================================================
# FORTRESS PRIME — NIGHT SHIFT PROTOCOL
# ==============================================================================
# Schedule: 01:00 AM nightly (via cron)
# Purpose:  Chip away at the image backlog while the operator sleeps.
# Safety:   Hard-killed at 4 hours (14400s) to free Spark 1 GPU by 05:00.
#
# The Vision Indexer uses Spark 1's llama3.2-vision:90b (90B parameters)
# to generate forensic-quality descriptions of every image on the NAS.
# After indexing, images become searchable by text content.
#
# Deduplication is built-in: previously indexed files (by SHA-256) are
# skipped automatically, so this is safe to run every night.
# ==============================================================================

set -euo pipefail

FORTRESS_HOME="/home/admin/Fortress-Prime"
LOG_DIR="/mnt/fortress_nas/fortress_data/ai_brain/logs/vision_indexer"
SYSTEM_LOG="/mnt/fortress_nas/fortress_data/ai_brain/logs/vision_indexer/night_shift_system.log"
RUN_LOG="${LOG_DIR}/night_shift_$(date +%Y%m%d).log"

# Directories to index (in priority order — highest value first)
# The indexer skips already-processed files, so repeating dirs is safe.
TARGETS=(
    "/mnt/fortress_nas/Real_Estate_Assets/Properties"
    "/mnt/fortress_nas/raw_images"
    "/mnt/fortress_nas/Real_Estate_Assets/Personal_Documents"
)

# Time budget per target (seconds). Total must stay under 14400 (4 hours).
TIME_PER_TARGET=4500  # 75 minutes each, ~3.75 hours total with overhead

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$SYSTEM_LOG"
}

# ==============================================================================
# PRE-FLIGHT CHECKS
# ==============================================================================

# 1. NAS must be mounted
if [ ! -d "/mnt/fortress_nas/fortress_data/ai_brain" ]; then
    log "[ABORT] NAS not mounted. Night Shift cancelled."
    exit 1
fi

# 2. Ensure log directory exists
mkdir -p "$LOG_DIR"

# 3. Check that Spark 1 (Muscle node) is reachable
if ! curl -s --connect-timeout 5 http://192.168.0.104:11434/api/tags > /dev/null 2>&1; then
    log "[ABORT] Spark 1 (Muscle Node) unreachable. Vision model offline."
    exit 1
fi

# ==============================================================================
# EXECUTION
# ==============================================================================

log "[START] Night Shift beginning. Targets: ${#TARGETS[@]} directories."

cd "$FORTRESS_HOME"

TOTAL_PROCESSED=0

for target in "${TARGETS[@]}"; do
    if [ ! -d "$target" ]; then
        log "[SKIP] Directory not found: $target"
        continue
    fi

    log "[INDEX] Starting: $target (budget: ${TIME_PER_TARGET}s)"

    timeout "$TIME_PER_TARGET" /usr/bin/python3 -m src.vision_indexer \
        --scan-dir "$target" \
        --sidecar \
        --image-only \
        >> "$RUN_LOG" 2>&1 || true
    # 'timeout' returns 124 on time-limit; '|| true' prevents set -e from killing us

    log "[DONE] Finished: $target"
done

log "[END] Night Shift complete. See details: $RUN_LOG"
