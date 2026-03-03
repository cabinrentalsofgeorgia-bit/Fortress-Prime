#!/bin/bash
# ==============================================================================
# FORTRESS PRIME — BLACK BOX CODE BACKUP
# ==============================================================================
# Schedule: 04:00 AM daily (via cron)
# Purpose:  Ensure the Logic (code) is as immortal as the Data (NAS).
#
# If the Spark boot drive dies, the entire Fortress-Prime codebase
# (scripts, configs, prompts, cabin data, credentials structure) can be
# restored from the NAS in minutes.
#
# Retention: 7 daily backups (~7 days of rollback).
# Excludes:  __pycache__, .pyc, venv, node_modules, .git objects (large).
# ==============================================================================

set -euo pipefail

SOURCE_DIR="/home/admin/Fortress-Prime"
BACKUP_DIR="/mnt/fortress_nas/fortress_data/ai_brain/backups/code"
TIMESTAMP=$(date +%Y%m%d_%H%M)
BACKUP_FILE="$BACKUP_DIR/fortress_code_${TIMESTAMP}.tar.gz"
LOG="/mnt/fortress_nas/fortress_data/ai_brain/logs/backup_code.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG"
}

# Pre-flight: NAS must be mounted
if [ ! -d "/mnt/fortress_nas/fortress_data/ai_brain" ]; then
    log "[ABORT] NAS not mounted. Code backup cancelled."
    exit 1
fi

mkdir -p "$BACKUP_DIR"

log "[START] Code backup beginning."

tar -czf "$BACKUP_FILE" \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='venv' \
    --exclude='node_modules' \
    --exclude='.git/objects' \
    -C "$(dirname "$SOURCE_DIR")" \
    "$(basename "$SOURCE_DIR")" \
    2>> "$LOG"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
log "[DONE] Backup complete: $BACKUP_FILE ($SIZE)"

# Retention: keep only the last 7 days
DELETED=$(find "$BACKUP_DIR" -name "fortress_code_*.tar.gz" -mtime +7 -print -delete 2>/dev/null | wc -l)
if [ "$DELETED" -gt 0 ]; then
    log "[CLEANUP] Purged $DELETED old backup(s)."
fi

log "[END] Code backup finished. $SIZE archived, $DELETED old file(s) purged."
