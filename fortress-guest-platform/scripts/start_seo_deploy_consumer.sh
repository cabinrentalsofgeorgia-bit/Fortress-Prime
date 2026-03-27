#!/usr/bin/env bash
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/seo_runtime_common.sh"

cd "${APP_ROOT}"
exec -a "fortress-seo-deploy-consumer" "${APP_ROOT}/.uv-venv/bin/python" - <<'PY'
import asyncio
import os
from dotenv import load_dotenv

load_dotenv('.env')
load_dotenv('../.env.security', override=True)
os.environ['ARQ_REDIS_URL'] = 'redis://127.0.0.1:6379/4'
os.environ['STOREFRONT_BASE_URL'] = 'http://127.0.0.1:3210'
os.environ['SEO_SWARM_API_KEY'] = 'cursor-smoke-seo-key'

from backend.services.seo_deploy_consumer import SEODeployWorker
from backend.vrs.infrastructure.seo_event_bus import create_seo_event_redis

async def main():
    redis = await create_seo_event_redis()
    worker = SEODeployWorker(redis)
    try:
        await worker.start()
    finally:
        await redis.aclose()

asyncio.run(main())
PY
