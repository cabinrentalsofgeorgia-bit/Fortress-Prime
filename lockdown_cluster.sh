#!/bin/bash

# --- CONFIGURATION ---
# We save backups to the NAS so they survive a node crash
BACKUP_ROOT="/mnt/fortress_nas/backups"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M")
BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"
PROJECT_DIR="$HOME/Fortress-Prime"
DB_NAME="fortress_db"
DB_USER="miner_bot"

# --- 1. PREPARE NAS ---
mkdir -p "$BACKUP_DIR"
echo "🔒 STARTING SYSTEM LOCKDOWN: $TIMESTAMP"
echo "   Target: $BACKUP_DIR"

# --- 2. BACKUP DATABASE (The Memories) ---
echo "   [+] Dumping Database ($DB_NAME)..."
# We use pg_dump to create a restore-ready file
# PGPASSWORD is set inline to avoid interactive prompt
export PGPASSWORD="mining_secret_123"
if pg_dump -h localhost -U $DB_USER $DB_NAME > "$BACKUP_DIR/fortress_db.sql"; then
    echo "       ✅ Database Secured (SQL Dump created)."
else
    echo "       ❌ DATABASE BACKUP FAILED!"
fi

# --- 3. BACKUP CODE & CONFIG (The Logic) ---
echo "   [+] Zipping Code and Configuration..."
# We exclude 'venv' and '__pycache__' because they are huge and can be reinstalled
tar --exclude='venv' --exclude='__pycache__' --exclude='.git' \
    -czf "$BACKUP_DIR/source_code.tar.gz" \
    -C "$HOME" Fortress-Prime

if [ -f "$BACKUP_DIR/source_code.tar.gz" ]; then
    echo "       ✅ Codebase Secured."
else
    echo "       ❌ CODE BACKUP FAILED!"
fi

# --- 4. VERIFY NVIDIA ASSETS (The Heavy Weights) ---
echo "   [+] Verifying NVIDIA Model Cache on NAS..."
if [ -d "/mnt/fortress_nas/nim_cache" ]; then
    SIZE=$(du -sh /mnt/fortress_nas/nim_cache | awk '{print $1}')
    echo "       ✅ NVIDIA Models found on NAS ($SIZE). Safe from node crash."
else
    echo "       ⚠️  WARNING: NIM Cache not found on NAS! Models might be local only."
fi

# --- 5. CLEANUP (Rotation) ---
# Keep only the last 7 backups to save space
echo "   [+] Rotating old backups (Keeping last 7)..."
ls -dt $BACKUP_ROOT/* 2>/dev/null | tail -n +8 | xargs -r rm -rf

echo "------------------------------------------------"
echo "✅ LOCKDOWN COMPLETE. CLUSTER IS SAFE."
echo "------------------------------------------------"
