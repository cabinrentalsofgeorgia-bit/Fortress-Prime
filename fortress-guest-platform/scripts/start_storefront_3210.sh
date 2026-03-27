#!/usr/bin/env bash
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/seo_runtime_common.sh"

cd "${FRONTEND_ROOT}"
python3 - <<'PY'
import os
from pathlib import Path
from dotenv import load_dotenv

base = Path(os.environ['FRONTEND_ROOT'])
load_dotenv(base / '.env.local')
load_dotenv(base.parents[1] / '.env.security', override=True)
os.environ['FGP_BACKEND_URL'] = 'http://127.0.0.1:8118'
os.execvpe(
    'npm',
    ['npm', 'run', 'start', '--', '--hostname', '127.0.0.1', '--port', '3210'],
    os.environ,
)
PY
