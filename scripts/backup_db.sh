#!/usr/bin/env bash
# CROG-VRS Automated Database Backup — Fortress Prime
# Dumps fortress_db and fortress_guest nightly, compresses, copies to Synology NAS.
# Designed for host-native PostgreSQL 16 on DGX Spark-1 (Captain).
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (override via environment if needed)
# ---------------------------------------------------------------------------
LOCAL_BACKUP_DIR="${BACKUP_LOCAL_DIR:-/home/admin/Fortress-Prime/backups}"
NAS_BACKUP_DIR="${BACKUP_NAS_DIR:-/mnt/fortress_nas/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
DATABASES="${BACKUP_DATABASES:-fortress_db fortress_guest}"
PG_DUMP="/usr/bin/pg_dump"
TIMESTAMP="$(date +%Y-%m-%d_%H-%M)"
LOG_TAG="[fortress-backup ${TIMESTAMP}]"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "${LOG_TAG} $*"; }
die()  { echo "${LOG_TAG} FATAL: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
command -v gzip  >/dev/null 2>&1 || die "gzip not found"
[[ -x "${PG_DUMP}" ]]            || die "pg_dump not found at ${PG_DUMP}"
systemctl is-active --quiet postgresql || die "postgresql service is not running"
mountpoint -q "${NAS_BACKUP_DIR%/*}"   || die "NAS is not mounted at ${NAS_BACKUP_DIR%/*}"

mkdir -p "${LOCAL_BACKUP_DIR}"
mkdir -p "${NAS_BACKUP_DIR}"

# ---------------------------------------------------------------------------
# Dump each database
# ---------------------------------------------------------------------------
FAIL=0
for DB in ${DATABASES}; do
    LOCAL_FILE="${LOCAL_BACKUP_DIR}/${DB}_${TIMESTAMP}.sql.gz"
    log "Dumping ${DB} ..."

    if sudo -u postgres "${PG_DUMP}" --verbose --format=plain "${DB}" 2>/dev/null \
        | gzip -9 > "${LOCAL_FILE}"; then

        SIZE=$(stat --printf='%s' "${LOCAL_FILE}" 2>/dev/null || echo 0)
        if [[ "${SIZE}" -lt 1024 ]]; then
            log "WARNING: ${DB} dump is suspiciously small (${SIZE} bytes)"
            FAIL=1
            continue
        fi

        if ! gzip -t "${LOCAL_FILE}" 2>/dev/null; then
            log "ERROR: ${DB} gzip integrity check failed"
            FAIL=1
            continue
        fi

        log "${DB} dump OK — $(numfmt --to=iec "${SIZE}")"

        # Copy to NAS
        if cp "${LOCAL_FILE}" "${NAS_BACKUP_DIR}/${DB}_${TIMESTAMP}.sql.gz"; then
            log "${DB} copied to NAS"
        else
            log "ERROR: failed to copy ${DB} to NAS"
            FAIL=1
        fi
    else
        log "ERROR: pg_dump failed for ${DB}"
        FAIL=1
    fi
done

# ---------------------------------------------------------------------------
# Prune local backups older than RETENTION_DAYS
# ---------------------------------------------------------------------------
log "Pruning local backups older than ${RETENTION_DAYS} days ..."
find "${LOCAL_BACKUP_DIR}" -type f -name "*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete 2>/dev/null || true

log "Pruning NAS backups older than ${RETENTION_DAYS} days ..."
find "${NAS_BACKUP_DIR}" -maxdepth 1 -type f -name "*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete 2>/dev/null || true

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
if [[ "${FAIL}" -eq 0 ]]; then
    log "All backups completed successfully."
else
    log "One or more backups FAILED — review output above."
    exit 1
fi
