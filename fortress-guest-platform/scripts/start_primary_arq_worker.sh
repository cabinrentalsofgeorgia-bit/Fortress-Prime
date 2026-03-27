#!/usr/bin/env bash
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/seo_runtime_common.sh"

cd "${APP_ROOT}"
export SEO_DEPLOY_CONSUMER_ENABLED=0
exec -a "fortress-seo-primary-arq-worker" "${APP_ROOT}/.uv-venv/bin/arq" backend.core.worker.WorkerSettings
