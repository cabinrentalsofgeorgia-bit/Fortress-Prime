#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONSTRAINTS_FILE="${ROOT_DIR}/constraints.txt"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! -f "${CONSTRAINTS_FILE}" ]]; then
  echo "ERROR: constraints file not found at ${CONSTRAINTS_FILE}" >&2
  exit 1
fi

echo "[deps] Installing root requirements with shared constraints..."
"${PYTHON_BIN}" -m pip install -r "${ROOT_DIR}/requirements.txt" -c "${CONSTRAINTS_FILE}"

echo "[deps] Installing fortress-guest-platform requirements with shared constraints..."
"${PYTHON_BIN}" -m pip install -r "${ROOT_DIR}/fortress-guest-platform/requirements.txt" -c "${CONSTRAINTS_FILE}"

echo "[deps] Installing crog-gateway requirements with shared constraints..."
"${PYTHON_BIN}" -m pip install -r "${ROOT_DIR}/crog-gateway/requirements.txt" -c "${CONSTRAINTS_FILE}"

echo "[deps] Dependency installation complete."
