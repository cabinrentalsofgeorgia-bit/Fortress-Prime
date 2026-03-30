"""
ARQ Redis connection helpers shared by the API and worker.
"""
from __future__ import annotations

from typing import cast
from urllib.parse import urlparse

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import Request

from backend.core.config import settings


def _redis_settings_from_url(url: str) -> RedisSettings:
    parsed = urlparse(url)
    database = parsed.path.lstrip("/")
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        username=parsed.username,
        password=parsed.password,
        database=int(database or 0),
        ssl=parsed.scheme == "rediss",
    )


def get_arq_redis_settings() -> RedisSettings:
    return _redis_settings_from_url(settings.arq_redis_url)


async def create_arq_pool() -> ArqRedis:
    return await create_pool(get_arq_redis_settings())


def get_arq_pool(request: Request) -> ArqRedis:
    pool = getattr(request.app.state, "arq_pool", None)
    if pool is None:
        raise RuntimeError("ARQ pool is not initialized")
    return cast(ArqRedis, pool)
