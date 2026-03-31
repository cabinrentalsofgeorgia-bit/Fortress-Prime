#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
APP_DIR="${ROOT_DIR}/fortress-guest-platform"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"

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

export HERMES_UID="${HERMES_UID:-$(id -u)}"
export HERMES_GID="${HERMES_GID:-$(id -g)}"
export HERMES_MEMORY_HOST_PATH="${HERMES_MEMORY_HOST_PATH:-/opt/crog/hermes_memory}"
export HERMES_CUDA_IMAGE="${HERMES_CUDA_IMAGE:-nvidia/cuda:13.0.0-runtime-ubuntu22.04}"
export HERMES_HOST_PORT="${HERMES_HOST_PORT:-8310}"
export HERMES_SYSTEM_PROMPT_PATH="${HERMES_SYSTEM_PROMPT_PATH:-/app/docs/paperclip/AGENTS.md}"

mkdir -p "${HERMES_MEMORY_HOST_PATH}"

if [[ ! -w "${HERMES_MEMORY_HOST_PATH}" ]]; then
  echo "Hermes memory path is not writable: ${HERMES_MEMORY_HOST_PATH}" >&2
  exit 1
fi

exec docker compose -f "${COMPOSE_FILE}" up --build "$@"
