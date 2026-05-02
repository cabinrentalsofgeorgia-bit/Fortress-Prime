#!/usr/bin/env bash
# run-fortress-nightly-finetune.sh
# Wrapper for the nightly fine-tune job — mirrors the pattern used by
# run-fortress-backend.sh so env files are loaded identically.
set -euo pipefail

ROOT_DIR="/home/admin/Fortress-Prime"
APP_DIR="${ROOT_DIR}/fortress-guest-platform"

# Use the dedicated CUDA-capable training env when present. The app envs are
# intentionally CPU-only on DGX Spark, which is fine for web/backend work but
# cannot run the nightly LoRA trainer.
if [[ -x "${ROOT_DIR}/venv_finetune/bin/python" ]]; then
  PYTHON="${ROOT_DIR}/venv_finetune/bin/python"
elif [[ -x "${APP_DIR}/.uv-venv/bin/python" ]]; then
  PYTHON="${APP_DIR}/.uv-venv/bin/python"
else
  PYTHON="${APP_DIR}/venv/bin/python"
fi

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

export PYTHONUNBUFFERED=1
export PYTHONPATH="${APP_DIR}:${ROOT_DIR}/src:${PYTHONPATH:-}"

# HuggingFace cache on NAS so we never re-download
export HF_HOME="${HF_HOME:-/mnt/ai_bulk/huggingface_cache}"
export TRANSFORMERS_CACHE="${HF_HOME}/hub"

exec "${PYTHON}" "${ROOT_DIR}/src/nightly_finetune.py" "$@"
