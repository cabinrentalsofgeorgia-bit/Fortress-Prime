#!/usr/bin/env bash
set -euo pipefail

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="${OUT_DIR:-/home/admin/Fortress-Prime/docs/ops-evidence}"
OUT_FILE="${OUT_DIR}/health-snapshot-${STAMP}.log"

mkdir -p "${OUT_DIR}"

{
  echo "=== Fortress Ops Health Snapshot (${STAMP}) ==="
  echo
  echo "[local] docker service status"
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' || true
  echo
  echo "[local] gateway health"
  curl -sS -m 3 http://127.0.0.1:8000/health || echo "gateway unreachable"
  echo
  echo "[compute] preflight summary"
  if [ -x "/home/admin/Fortress-Prime/deploy/compute/nuc_preflight.sh" ]; then
    bash /home/admin/Fortress-Prime/deploy/compute/nuc_preflight.sh || true
  else
    echo "preflight script unavailable"
  fi
  echo
  echo "[governance] gate status"
  bash /home/admin/Fortress-Prime/bin/governance_gate.sh || true
} | tee "${OUT_FILE}"

echo "[ops] Snapshot written to ${OUT_FILE}"
