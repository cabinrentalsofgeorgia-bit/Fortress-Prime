#!/bin/bash
# Enterprise Audit Protocol — Physical (NAS) vs Digital (DB) vs Wolfpack (logs)
# Run on Captain. Reconciling physical reality with database truth.

set -e
NAS_ROOT="${NAS_ROOT:-/mnt/fortress_nas}"
PROJECT_ROOT="${PROJECT_ROOT:-/home/admin/Fortress-Prime}"
LOG_DIR="${NAS_ROOT}/fortress_data/ai_brain/logs"

echo "=============================================="
echo "  ENTERPRISE AUDIT PROTOCOL"
echo "  Physical vs Digital vs Wolfpack"
echo "=============================================="
echo ""

# --- Step 1: Physical Audit (NAS) ---
echo "--- Step 1: PHYSICAL AUDIT (NAS) ---"
echo "NAS root: $NAS_ROOT"
if [ -d "$NAS_ROOT" ]; then
  echo "Total NAS size (may be slow on large volumes):"
  timeout 60 du -sh "$NAS_ROOT" 2>/dev/null || echo "  (skipped after 60s or unavailable)"
  echo ""
  echo "PST files (top 5 levels):"
  pst_count=$(find "$NAS_ROOT" -maxdepth 5 -name "*.pst" 2>/dev/null | wc -l)
  echo "  *.pst: $pst_count"
  echo "MBOX / maildir:"
  mbox_count=$(find "$NAS_ROOT" -name "*.mbox" -o -name "*.mbx" 2>/dev/null | wc -l)
  echo "  *.mbox/mbx: $mbox_count"
  # Common email-related dirs
  for dir in emails mail Mail archive maildir; do
    if [ -d "$NAS_ROOT/$dir" ]; then
      echo "  $NAS_ROOT/$dir: $(du -sh "$NAS_ROOT/$dir" 2>/dev/null | cut -f1)"
    fi
  done
else
  echo "  NAS root not mounted or missing."
fi
echo ""

# --- Step 2: Digital Audit (Database) ---
echo "--- Step 2: DIGITAL AUDIT (Database) ---"
[ -f "$PROJECT_ROOT/.env" ] && source "$PROJECT_ROOT/.env" 2>/dev/null || true
export PGPASSWORD="${DB_PASSWORD:-$DB_PASS}"
psql -h "${DB_HOST:-localhost}" -U "${DB_USER:-miner_bot}" -d "${DB_NAME:-fortress_db}" -t -A -F'|' -c "
SELECT 
    COUNT(*)::text as total_ingested,
    COUNT(*) FILTER (WHERE is_mined = TRUE)::text as marked_mined,
    COUNT(*) FILTER (WHERE is_mined = FALSE)::text as actual_backlog
FROM email_archive;
" 2>/dev/null | while IFS='|' read -r total mined backlog; do
  echo "  total_ingested:  $total"
  echo "  marked_mined:    $mined"
  echo "  actual_backlog:  $backlog"
  echo ""
  if [ -n "$backlog" ] && [ "$backlog" -gt 0 ]; then
    echo "  -> Backlog is non-zero: $backlog emails not yet mined."
  else
    echo "  -> Backlog is zero: DB thinks mining is complete for current set."
  fi
done

# Signals extracted (hedge_fund)
psql -h "${DB_HOST:-localhost}" -U "${DB_USER:-miner_bot}" -d "${DB_NAME:-fortress_db}" -t -c "SELECT '  Signals extracted: ' || COUNT(*)::text FROM hedge_fund.market_signals;" 2>/dev/null || echo "  Signals: (hedge_fund schema may not exist)"
echo ""

# --- Step 3: Wolfpack / Miner Logs (on workers) ---
echo "--- Step 3: WOLFPACK AUDIT (Spark-03/04 miner.log) ---"
for ip in 192.168.0.105 192.168.0.106; do
  echo "  $ip:"
  ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=no admin@$ip "grep -iE 'Skipping|Error|Extracted|Processed|Batch|Vault|Attacking' ~/Fortress-Prime/miner.log 2>/dev/null | tail -10" 2>/dev/null || echo "    (unreachable)"
done
echo "  Local logs:"
for log in "$LOG_DIR/trader_rig_remine.log" "$LOG_DIR/trader_rig.log" "$PROJECT_ROOT/miner.log" "$LOG_DIR/mining_rig.log"; do
  if [ -f "$log" ]; then
    echo "  File: $log"
    echo "  Recent Skipping / Skip:"
    grep -i 'skip\|skipping' "$log" 2>/dev/null | tail -5 || true
    echo "  Recent Extracted / signal:"
    grep -i 'extracted\|signal(s)' "$log" 2>/dev/null | tail -5 || true
    echo "  Recent Error:"
    grep -i 'error' "$log" 2>/dev/null | tail -3 || true
    echo ""
  fi
done
if [ -d "$LOG_DIR" ]; then
  echo "  Latest log files in $LOG_DIR:"
  ls -la "$LOG_DIR" 2>/dev/null | tail -8
fi
echo ""

echo "=============================================="
echo "  VERDICT"
echo "=============================================="
echo "  If NAS is huge but total_ingested is small -> Ingestion (Feeder) is the bottleneck."
echo "  If actual_backlog ~0 but NAS has more data -> Feed the beast (ingest more)."
echo "  If logs show thousands of Skipping -> Phantom completion (consider reset flags / remine)."
echo "=============================================="
