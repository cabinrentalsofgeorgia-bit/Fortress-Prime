# SEO Operator Runtime Runbook

This runbook captures the verified local runtime needed to operate the SEO approval and deploy loop from the internal dashboard.

## Launcher Scripts

These wrappers mirror the verified commands and live in `fortress-guest-platform/scripts/`.

- `start_seo_backend_8118.sh`
- `start_storefront_3210.sh`
- `start_primary_arq_worker.sh`
- `start_seo_deploy_consumer.sh`
- `start_seo_smoke_backend_8124.sh`
- `start_seo_operator_stack.sh`
- `stop_seo_operator_stack.sh`
- `run_seo_smoke_8124.sh`

### One-command stack bring-up

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
./scripts/start_seo_operator_stack.sh
```

The stack launcher is idempotent. It checks `8118`, `3210`, `8124`, the primary ARQ worker, and the deploy consumer before starting anything, and writes logs plus stack-owned service PID files to `fortress-guest-platform/runtime-logs/seo-operator/`.

When the stack launcher starts the primary ARQ worker through `start_primary_arq_worker.sh`, it disables the in-process deploy consumer inside `backend.core.worker.WorkerSettings`. That leaves deploy-event ownership with the dedicated standalone `start_seo_deploy_consumer.sh` process and avoids two deploy listeners competing for `fortress:seo:deploy_events`.

### One-command stack teardown

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
./scripts/stop_seo_operator_stack.sh
```

The stop launcher sends termination signals to the fixed listeners on `8118`, `3210`, and `8124`, plus the exact stack-owned ARQ worker and deploy-consumer PIDs recorded under `fortress-guest-platform/runtime-logs/seo-operator/*.pid`. It then waits for those listeners and process IDs to exit and warns if anything still lingers after `SIGTERM`.

## Stable Runtime

### Backend on `8118`

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
./.uv-venv/bin/python - <<'PY'
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
```

### Storefront on `3210`

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform/frontend-next
python3 - <<'PY'
import os
from pathlib import Path
from dotenv import load_dotenv

base = Path('/home/admin/Fortress-Prime/fortress-guest-platform/frontend-next')
load_dotenv(base / '.env.local')
load_dotenv(base.parents[1] / '.env.security', override=True)
os.environ['FGP_BACKEND_URL'] = 'http://127.0.0.1:8118'
os.execvpe(
    'npm',
    ['npm', 'run', 'start', '--', '--hostname', '127.0.0.1', '--port', '3210'],
    os.environ,
)
PY
```

### Primary ARQ worker

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
SEO_DEPLOY_CONSUMER_ENABLED=0 ./.uv-venv/bin/arq backend.core.worker.WorkerSettings
```

Use `SEO_DEPLOY_CONSUMER_ENABLED=0` whenever the standalone deploy consumer below is running. If you intentionally want ARQ to own deploy events instead, do not launch `start_seo_deploy_consumer.sh`.

### SEO deploy consumer

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
./.uv-venv/bin/python - <<'PY'
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
```

### Isolated smoke backend on `8124`

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
./.uv-venv/bin/python - <<'PY'
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
```

## Verified Smoke Command

This command was used successfully after the queue-shape fix in `backend/scripts/smoke_test_seo.py`.

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
python3 - <<'PY'
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
```

## Verification Notes

- `http://127.0.0.1:3210/api/revalidate-seo` returned `200` with the active edge secret.
- The final smoke passed `ingest -> queue -> approve -> edge live -> cleanup`.

## Known Gotchas

- The storefront on `3210` must load `../../.env.security`, not `../.env.security`.
- The smoke path may require a plain `postgresql://` URI for `asyncpg`, even when app runtime settings prefer `postgresql+asyncpg://`.
- `stop_seo_operator_stack.sh` only manages the stack-owned listeners and worker processes. It does not stop Redis or PostgreSQL.
- If `stop_seo_operator_stack.sh` warns that a listener or worker still lingers after `SIGTERM`, inspect for orphaned `uvicorn`, `node`, or `arq` processes before assuming the operator loop itself is broken.
