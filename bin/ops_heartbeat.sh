#!/bin/bash
# =============================================================================
# DIVISION 3: OPERATIONS HEARTBEAT
# =============================================================================
# Runs daily at 06:00 via cron. Performs:
#   1. Ingest any new CSV files in the Streamline_Exports landing zone
#   2. Generate tasks from pending turnovers
#   3. Print status report to log
# =============================================================================

set -e

FORTRESS_DIR="/home/admin/Fortress-Prime"
CSV_DIR="/mnt/fortress_nas/Financial_Ledger/Streamline_Exports"
PROCESSED_DIR="${CSV_DIR}/.processed"
LOG_DIR="${FORTRESS_DIR}/logs"
GROUNDSKEEPER="${FORTRESS_DIR}/src/groundskeeper.py"

mkdir -p "${PROCESSED_DIR}" "${LOG_DIR}"

echo "========================================"
echo "  DIVISION 3 HEARTBEAT — $(date)"
echo "========================================"

cd "${FORTRESS_DIR}"

# Step 1: Ingest any new CSVs in the landing zone
NEW_FILES=0
if [ -d "${CSV_DIR}" ]; then
    for csv_file in "${CSV_DIR}"/*.csv; do
        [ -f "${csv_file}" ] || continue

        basename=$(basename "${csv_file}")

        # Skip already-processed files
        if [ -f "${PROCESSED_DIR}/${basename}.done" ]; then
            continue
        fi

        echo "  [INGEST] New CSV found: ${basename}"

        # Ingest properties first, then reservations
        /usr/bin/python3 "${GROUNDSKEEPER}" --ingest-props "${csv_file}" 2>&1
        /usr/bin/python3 "${GROUNDSKEEPER}" --ingest-res "${csv_file}" 2>&1

        # Mark as processed
        touch "${PROCESSED_DIR}/${basename}.done"
        NEW_FILES=$((NEW_FILES + 1))
    done
fi

if [ "${NEW_FILES}" -eq 0 ]; then
    echo "  [INGEST] No new CSV files."
fi

# Step 2: Generate tasks from any pending turnovers
echo "  [GENERATE] Running task generator..."
/usr/bin/python3 "${GROUNDSKEEPER}" --run 2>&1

# Step 3: Status report
echo ""
/usr/bin/python3 "${GROUNDSKEEPER}" --report 2>&1

echo ""
echo "  Heartbeat complete — $(date)"
echo "========================================"
