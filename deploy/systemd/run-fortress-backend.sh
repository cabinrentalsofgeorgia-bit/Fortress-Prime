#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/admin/Fortress-Prime"
APP_DIR="${ROOT_DIR}/fortress-guest-platform"
VENV_DIR="${APP_DIR}/.uv-venv"

load_env_file() {
  local env_file="$1"
  if [[ -f "${env_file}" ]]; then
    while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
      local line="${raw_line#"${raw_line%%[![:space:]]*}"}"
      line="${line%"${line##*[![:space:]]}"}"
      [[ -z "${line}" || "${line}" == \#* || "${line}" != *=* ]] && continue
      local key="${line%%=*}"
      local value="${line#*=}"
      key="${key%"${key##*[![:space:]]}"}"
      value="${value#"${value%%[![:space:]]*}"}"
      value="${value%"${value##*[![:space:]]}"}"
      value="${value%\"}"
      value="${value#\"}"
      value="${value%\'}"
      value="${value#\'}"
      export "${key}=${value}"
    done < "${env_file}"
  fi
}

load_env_file "${APP_DIR}/.env"
load_env_file "${APP_DIR}/.env.dgx"
load_env_file "${ROOT_DIR}/.env.security"

export DB_AUTO_CREATE_TABLES="${DB_AUTO_CREATE_TABLES:-false}"
export PYTHONUNBUFFERED=1

cd "${APP_DIR}"
exec "${VENV_DIR}/bin/python" run.py
