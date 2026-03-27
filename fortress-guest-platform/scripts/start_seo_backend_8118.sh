#!/usr/bin/env bash
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/seo_runtime_common.sh"

cd "${APP_ROOT}"
"${APP_ROOT}/.uv-venv/bin/python" - <<'PY'
import os
from dotenv import load_dotenv

load_dotenv('.env')
load_dotenv('../.env.security', override=True)
os.execvpe(
    './.uv-venv/bin/uvicorn',
    ['./.uv-venv/bin/uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8118'],
    os.environ,
)
PY
