#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/admin/Fortress-Prime"
APP_DIR="${ROOT_DIR}/fortress-guest-platform/apps/storefront"
NODE_BIN="/home/admin/.nvm/versions/node/v20.20.0/bin/node"
NEXT_BIN="${ROOT_DIR}/fortress-guest-platform/node_modules/next/dist/bin/next"

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

load_env_file "${ROOT_DIR}/fortress-guest-platform/.env"
load_env_file "${ROOT_DIR}/fortress-guest-platform/.env.dgx"
load_env_file "${ROOT_DIR}/.env.security"

export FGP_BACKEND_URL="${FGP_BACKEND_URL:-http://127.0.0.1:8100}"
export NEXT_PUBLIC_APP_URL="${STOREFRONT_BASE_URL:-https://cabin-rentals-of-georgia.com}"

cd "${APP_DIR}"
exec "${NODE_BIN}" "${NEXT_BIN}" start --hostname 0.0.0.0 --port 3001
