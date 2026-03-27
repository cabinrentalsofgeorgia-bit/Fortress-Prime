#!/usr/bin/env python3
"""
Inspect Redis and ARQ queue state for the swarm worker.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from redis.asyncio import from_url


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[3]

for candidate in (PROJECT_ROOT, REPO_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)


def load_environment() -> list[Path]:
    loaded_files: list[Path] = []
    env_files = [
        REPO_ROOT / ".env",
        PROJECT_ROOT / ".env",
        REPO_ROOT / ".env.security",
    ]
    for env_file in env_files:
        if env_file.exists():
            load_dotenv(env_file, override=True)
            loaded_files.append(env_file)
    return loaded_files


LOADED_ENV_FILES = load_environment()

from backend.core.config import settings
from backend.vrs.infrastructure.seo_event_bus import (
    SEO_QUEUE_DEPLOY_EVENTS,
    SEO_QUEUE_DLQ,
    SEO_QUEUE_GRADE_REQUESTS,
    SEO_QUEUE_REMAP_GRADE_REQUESTS,
    SEO_QUEUE_REWRITE_REQUESTS,
    SWARM_QUEUE_DLQ,
)


def _format_value(value: str, limit: int = 220) -> str:
    trimmed = value.strip()
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[: limit - 3] + "..."


async def _describe_key(redis, key: str) -> str:
    key_type = await redis.type(key)
    if key_type == "none":
        return f"{key} type=none"
    if key_type == "zset":
        return f"{key} type=zset size={await redis.zcard(key)}"
    if key_type == "list":
        return f"{key} type=list size={await redis.llen(key)}"
    if key_type == "string":
        value = await redis.get(key)
        return f"{key} type=string value={_format_value(str(value or ''))}"
    return f"{key} type={key_type}"


async def _run() -> int:
    heartbeat_key = settings.arq_queue_name + ":health-check"
    keys = [
        settings.arq_queue_name,
        heartbeat_key,
        SEO_QUEUE_GRADE_REQUESTS,
        SEO_QUEUE_REWRITE_REQUESTS,
        SEO_QUEUE_DEPLOY_EVENTS,
        SEO_QUEUE_REMAP_GRADE_REQUESTS,
        SEO_QUEUE_DLQ,
        SWARM_QUEUE_DLQ,
    ]

    redis = from_url(settings.arq_redis_url, decode_responses=True)
    try:
        print("[queue-debug] fortress swarm state")
        print(f"loaded_env_files={len(LOADED_ENV_FILES)}")
        print(f"redis_url={settings.arq_redis_url}")
        print(f"arq_queue_name={settings.arq_queue_name}")
        print(f"health_check_key={heartbeat_key}")

        heartbeat = await redis.get(heartbeat_key)
        print(f"active_worker_heartbeats={1 if heartbeat else 0}")
        if heartbeat:
            print(f"heartbeat_payload={_format_value(heartbeat)}")

        for key in keys:
            print(await _describe_key(redis, key))
        return 0
    finally:
        await redis.aclose()


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
