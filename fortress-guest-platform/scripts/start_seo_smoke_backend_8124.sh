#!/usr/bin/env bash
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/seo_runtime_common.sh"

cd "${APP_ROOT}"
exec "${APP_ROOT}/.uv-venv/bin/python" - <<'PY'
import os
from dotenv import load_dotenv

load_dotenv('.env')
load_dotenv('../.env.security', override=True)
os.environ['ARQ_REDIS_URL'] = 'redis://127.0.0.1:6379/4'
os.environ['STOREFRONT_BASE_URL'] = 'http://127.0.0.1:3210'
os.environ['SEO_SWARM_API_KEY'] = 'cursor-smoke-seo-key'
os.execvpe(
    './.uv-venv/bin/uvicorn',
    ['./.uv-venv/bin/uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8124'],
    os.environ,
)
PY
