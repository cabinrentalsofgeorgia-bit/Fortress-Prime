#!/usr/bin/env python3
"""
One-shot Enticer Swarm tick (Strike 11). Schedule via cron or systemd timer on DGX.

Requires: CONCIERGE_RECOVERY_SMS_ENABLED=true, Twilio env, alembic head (dispatches table).

Run from repo app root, e.g.:
  cd fortress-guest-platform && PYTHONPATH=. python backend/scripts/run_enticer_swarm_worker.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.database import get_session_factory
from backend.services.enticer_swarm_service import run_enticer_swarm_tick


async def _main() -> int:
    factory = get_session_factory()
    async with factory() as db:
        result = await run_enticer_swarm_tick(db)
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
