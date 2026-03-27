#!/usr/bin/env bash
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/seo_runtime_common.sh"

cd "${APP_ROOT}"
exec python3 - <<'PY'
import os
from dotenv import load_dotenv

load_dotenv('.env')
load_dotenv('../.env.security', override=True)
uri = os.getenv('POSTGRES_API_URI', '').strip()
if uri.startswith('postgresql+asyncpg://'):
    os.environ['POSTGRES_API_URI'] = 'postgresql://' + uri[len('postgresql+asyncpg://'):]
elif uri.startswith('postgres+asyncpg://'):
    os.environ['POSTGRES_API_URI'] = 'postgresql://' + uri[len('postgres+asyncpg://'):]

os.environ['SEO_SMOKE_API_BASE'] = 'http://127.0.0.1:8124'
os.environ['SEO_SWARM_API_KEY'] = 'cursor-smoke-seo-key'
os.environ['SWARM_SEO_API_KEY'] = 'cursor-smoke-seo-key'
os.environ['SWARM_API_KEY'] = 'cursor-smoke-seo-key'
os.execvpe('python3', ['python3', 'backend/scripts/smoke_test_seo.py'], os.environ)
PY
