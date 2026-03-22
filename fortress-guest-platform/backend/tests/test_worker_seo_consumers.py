from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.core import worker


def test_enabled_seo_consumer_specs_respect_flags(monkeypatch) -> None:
    monkeypatch.setenv("SEO_GRADING_CONSUMER_ENABLED", "1")
    monkeypatch.setenv("SEO_REWRITE_CONSUMER_ENABLED", "1")
    monkeypatch.setenv("SEO_DEPLOY_CONSUMER_ENABLED", "0")

    specs = worker._enabled_seo_consumer_specs()
    task_names = [task_name for _worker_key, _task_key, task_name, _worker_cls, _flag_name in specs]

    assert task_names == ["seo_grading_task", "seo_rewrite_task"]


def test_startup_skips_redis_when_all_seo_consumers_disabled(monkeypatch) -> None:
    monkeypatch.setenv("SEO_GRADING_CONSUMER_ENABLED", "0")
    monkeypatch.setenv("SEO_REWRITE_CONSUMER_ENABLED", "0")
    monkeypatch.setenv("SEO_DEPLOY_CONSUMER_ENABLED", "0")

    redis_requested = False

    async def fake_create_seo_event_redis():
        nonlocal redis_requested
        redis_requested = True
        raise AssertionError("startup should not request redis when all SEO consumers are disabled")

    monkeypatch.setattr(worker, "create_seo_event_redis", fake_create_seo_event_redis)

    ctx: dict[str, object] = {}
    asyncio.run(worker.startup(ctx))

    assert redis_requested is False
    assert "seo_redis" not in ctx
