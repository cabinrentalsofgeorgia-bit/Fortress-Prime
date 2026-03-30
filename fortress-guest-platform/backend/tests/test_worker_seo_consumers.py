from __future__ import annotations

import asyncio
import os
import sys
import types
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

fake_arq = types.ModuleType("arq")
fake_arq.create_pool = lambda *args, **kwargs: None
fake_arq_connections = types.ModuleType("arq.connections")
fake_arq_connections.ArqRedis = type("ArqRedis", (), {})


class _FakeRedisSettings:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


fake_arq_connections.RedisSettings = _FakeRedisSettings
sys.modules.setdefault("arq", fake_arq)
sys.modules.setdefault("arq.connections", fake_arq_connections)

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
    monkeypatch.setattr(worker.settings, "hunter_queue_sweep_enabled", False)
    monkeypatch.setattr(worker.settings, "async_job_watchdog_enabled", False)
    
    async def fake_enforce_sovereign_boundary() -> None:
        return None

    redis_requested = False

    async def fake_create_seo_event_redis():
        nonlocal redis_requested
        redis_requested = True
        raise AssertionError("startup should not request redis when all SEO consumers are disabled")

    monkeypatch.setattr(worker, "create_seo_event_redis", fake_create_seo_event_redis)
    monkeypatch.setattr(worker, "enforce_sovereign_boundary", fake_enforce_sovereign_boundary)

    ctx: dict[str, object] = {}
    asyncio.run(worker.startup(ctx))

    assert redis_requested is False
    assert "seo_redis" not in ctx


def test_startup_still_arms_semrush_observer_when_seo_consumers_disabled(monkeypatch) -> None:
    monkeypatch.setenv("SEO_GRADING_CONSUMER_ENABLED", "0")
    monkeypatch.setenv("SEO_REWRITE_CONSUMER_ENABLED", "0")
    monkeypatch.setenv("SEO_DEPLOY_CONSUMER_ENABLED", "0")
    monkeypatch.setattr(worker.settings, "semrush_shadow_observer_enabled", True)
    monkeypatch.setattr(worker.settings, "hunter_queue_sweep_enabled", False)
    monkeypatch.setattr(worker.settings, "async_job_watchdog_enabled", False)

    async def fake_enforce_sovereign_boundary() -> None:
        return None

    async def fake_observer_loop() -> None:
        raise asyncio.CancelledError

    original_create_task = asyncio.create_task

    def tracking_create_task(coro, *, name=None):
        return original_create_task(coro, name=name)

    monkeypatch.setattr(worker, "_semrush_shadow_observer_loop", fake_observer_loop)
    monkeypatch.setattr(worker, "enforce_sovereign_boundary", fake_enforce_sovereign_boundary)
    monkeypatch.setattr(asyncio, "create_task", tracking_create_task)

    ctx: dict[str, object] = {}
    asyncio.run(worker.startup(ctx))

    assert "semrush_shadow_observer_task" in ctx


def test_enqueue_semrush_shadow_observation_skips_when_agentic_system_inactive(monkeypatch) -> None:
    class DummySession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_count_jobs_by_status(db, *, status: str, job_name: str) -> int:
        raise AssertionError("job counts should not be queried when agentic system is inactive")

    monkeypatch.setattr(worker.settings, "agentic_system_active", False)
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(worker, "count_jobs_by_status", fake_count_jobs_by_status)

    asyncio.run(worker._enqueue_semrush_shadow_observation_if_idle())


def test_enqueue_semrush_shadow_observation_enqueues_when_idle(monkeypatch) -> None:
    events: list[str] = []

    class DummySession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_count_jobs_by_status(db, *, status: str, job_name: str) -> int:
        events.append(f"count:{status}:{job_name}")
        return 0

    async def fake_enqueue_async_job(
        db,
        *,
        worker_name: str,
        job_name: str,
        payload: dict,
        requested_by: str | None = None,
        tenant_id: str | None = None,
        request_id: str | None = None,
        redis=None,
    ):
        events.append(f"enqueue:{worker_name}:{job_name}:{requested_by}:{request_id}")
        return SimpleNamespace(id="job-123")

    monkeypatch.setattr(worker.settings, "agentic_system_active", True)
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(worker, "count_jobs_by_status", fake_count_jobs_by_status)
    monkeypatch.setattr(worker, "enqueue_async_job", fake_enqueue_async_job)

    asyncio.run(worker._enqueue_semrush_shadow_observation_if_idle())

    assert events == [
        "count:queued:seo_parity_observation",
        "count:running:seo_parity_observation",
        "enqueue:run_seo_parity_observation_job:seo_parity_observation:system_shadow_parallel:semrush-shadow-observer",
    ]


def test_startup_arms_research_scout_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("SEO_GRADING_CONSUMER_ENABLED", "0")
    monkeypatch.setenv("SEO_REWRITE_CONSUMER_ENABLED", "0")
    monkeypatch.setenv("SEO_DEPLOY_CONSUMER_ENABLED", "0")
    monkeypatch.setattr(worker.settings, "semrush_shadow_observer_enabled", False)
    monkeypatch.setattr(worker.settings, "research_scout_enabled", True)
    monkeypatch.setattr(worker.settings, "hunter_queue_sweep_enabled", False)
    monkeypatch.setattr(worker.settings, "async_job_watchdog_enabled", False)

    async def fake_enforce_sovereign_boundary() -> None:
        return None

    async def fake_scout_loop() -> None:
        raise asyncio.CancelledError

    original_create_task = asyncio.create_task

    def tracking_create_task(coro, *, name=None):
        return original_create_task(coro, name=name)

    monkeypatch.setattr(worker, "_research_scout_loop", fake_scout_loop)
    monkeypatch.setattr(worker, "enforce_sovereign_boundary", fake_enforce_sovereign_boundary)
    monkeypatch.setattr(asyncio, "create_task", tracking_create_task)

    ctx: dict[str, object] = {}
    asyncio.run(worker.startup(ctx))

    assert "research_scout_task" in ctx


def test_enqueue_research_scout_enqueues_when_idle(monkeypatch) -> None:
    events: list[str] = []

    class DummySession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_count_jobs_by_status(db, *, status: str, job_name: str) -> int:
        events.append(f"count:{status}:{job_name}")
        return 0

    async def fake_enqueue_async_job(
        db,
        *,
        worker_name: str,
        job_name: str,
        payload: dict,
        requested_by: str | None = None,
        tenant_id: str | None = None,
        request_id: str | None = None,
        redis=None,
    ):
        events.append(
            f"enqueue:{worker_name}:{job_name}:{requested_by}:{request_id}:{payload.get('market')}"
        )
        return SimpleNamespace(id="job-scout-123")

    monkeypatch.setattr(worker.settings, "agentic_system_active", True)
    monkeypatch.setattr(worker.settings, "research_scout_market", "Blue Ridge, Georgia")
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(worker, "count_jobs_by_status", fake_count_jobs_by_status)
    monkeypatch.setattr(worker, "enqueue_async_job", fake_enqueue_async_job)

    asyncio.run(worker._enqueue_research_scout_if_idle())

    assert events == [
        "count:queued:research_scout_cycle",
        "count:running:research_scout_cycle",
        "enqueue:run_research_scout_job:research_scout_cycle:system_research_scout:research-scout-observer:Blue Ridge, Georgia",
    ]


def test_run_research_scout_job_routes_inserted_findings(monkeypatch) -> None:
    events: list[str] = []

    async def fake_with_job(job_id: str, job_try: int, runner):
        result = await runner(object(), SimpleNamespace(id=job_id))
        events.append(f"with-job:{job_id}:{job_try}")
        return result

    async def fake_run_cycle(db, *, scout_run_key: str):
        events.append(f"run-cycle:{scout_run_key}")
        return {
            "inserted_count": 1,
            "duplicate_count": 0,
            "inserted_entry_ids": ["entry-1"],
        }

    async def fake_route_inserted_findings(db, *, inserted_entry_ids: list[str] | None):
        events.append(f"route:{','.join(inserted_entry_ids or [])}")
        return {
            "routed_count": 1,
            "seo_draft_count": 2,
            "pricing_signal_count": 1,
            "items": [],
        }

    monkeypatch.setattr(worker, "_with_job", fake_with_job)
    monkeypatch.setattr(worker.research_scout_service, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(
        worker.research_scout_action_router,
        "route_inserted_findings",
        fake_route_inserted_findings,
    )

    result = asyncio.run(worker.run_research_scout_job({"job_try": 1}, "job-scout-1"))

    assert events == [
        "run-cycle:job-scout-1",
        "route:entry-1",
        "with-job:job-scout-1:1",
    ]
    assert result["research_scout"]["actions"]["seo_draft_count"] == 2
    assert result["research_scout"]["actions"]["pricing_signal_count"] == 1


def test_startup_arms_concierge_shadow_draft_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("SEO_GRADING_CONSUMER_ENABLED", "0")
    monkeypatch.setenv("SEO_REWRITE_CONSUMER_ENABLED", "0")
    monkeypatch.setenv("SEO_DEPLOY_CONSUMER_ENABLED", "0")
    monkeypatch.setattr(worker.settings, "semrush_shadow_observer_enabled", False)
    monkeypatch.setattr(worker.settings, "research_scout_enabled", False)
    monkeypatch.setattr(worker.settings, "concierge_shadow_draft_enabled", True)
    monkeypatch.setattr(worker.settings, "hunter_queue_sweep_enabled", False)
    monkeypatch.setattr(worker.settings, "async_job_watchdog_enabled", False)

    async def fake_enforce_sovereign_boundary() -> None:
        return None

    async def fake_concierge_loop() -> None:
        raise asyncio.CancelledError

    original_create_task = asyncio.create_task

    def tracking_create_task(coro, *, name=None):
        return original_create_task(coro, name=name)

    monkeypatch.setattr(worker, "_concierge_shadow_draft_loop", fake_concierge_loop)
    monkeypatch.setattr(worker, "enforce_sovereign_boundary", fake_enforce_sovereign_boundary)
    monkeypatch.setattr(asyncio, "create_task", tracking_create_task)

    ctx: dict[str, object] = {}
    asyncio.run(worker.startup(ctx))

    assert "concierge_shadow_draft_task" in ctx


def test_startup_arms_streamline_availability_sync_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("SEO_GRADING_CONSUMER_ENABLED", "0")
    monkeypatch.setenv("SEO_REWRITE_CONSUMER_ENABLED", "0")
    monkeypatch.setenv("SEO_DEPLOY_CONSUMER_ENABLED", "0")
    monkeypatch.setattr(worker.settings, "semrush_shadow_observer_enabled", False)
    monkeypatch.setattr(worker.settings, "research_scout_enabled", False)
    monkeypatch.setattr(worker.settings, "concierge_shadow_draft_enabled", False)
    monkeypatch.setattr(worker.settings, "hunter_queue_sweep_enabled", False)
    monkeypatch.setattr(worker.settings, "async_job_watchdog_enabled", False)
    monkeypatch.setattr(worker.settings, "streamline_sync_interval", 300)

    class FakeStreamlineVRS:
        def __init__(self) -> None:
            self.is_configured = True

        async def close(self) -> None:
            return None

    async def fake_enforce_sovereign_boundary() -> None:
        return None

    async def fake_streamline_loop(_streamline_vrs) -> None:
        raise asyncio.CancelledError

    original_create_task = asyncio.create_task

    def tracking_create_task(coro, *, name=None):
        return original_create_task(coro, name=name)

    monkeypatch.setattr(worker, "StreamlineVRS", FakeStreamlineVRS)
    monkeypatch.setattr(worker, "_streamline_availability_sync_loop", fake_streamline_loop)
    monkeypatch.setattr(worker, "enforce_sovereign_boundary", fake_enforce_sovereign_boundary)
    monkeypatch.setattr(asyncio, "create_task", tracking_create_task)

    ctx: dict[str, object] = {}
    asyncio.run(worker.startup(ctx))

    assert "streamline_availability_sync_task" in ctx
    assert "streamline_vrs" in ctx


def test_enqueue_concierge_shadow_draft_skips_when_feature_disabled(monkeypatch) -> None:
    class DummySession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_count_jobs_by_status(db, *, status: str, job_name: str) -> int:
        raise AssertionError("job counts should not run when feature is disabled")

    monkeypatch.setattr(worker.settings, "agentic_system_active", True)
    monkeypatch.setattr(worker.settings, "concierge_shadow_draft_enabled", False)
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(worker, "count_jobs_by_status", fake_count_jobs_by_status)

    asyncio.run(worker._enqueue_concierge_shadow_draft_if_idle())


def test_enqueue_concierge_shadow_draft_enqueues_when_idle(monkeypatch) -> None:
    events: list[str] = []

    class DummySession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_count_jobs_by_status(db, *, status: str, job_name: str) -> int:
        events.append(f"count:{status}:{job_name}")
        return 0

    async def fake_enqueue_async_job(
        db,
        *,
        worker_name: str,
        job_name: str,
        payload: dict,
        requested_by: str | None = None,
        tenant_id: str | None = None,
        request_id: str | None = None,
        redis=None,
    ):
        events.append(f"enqueue:{worker_name}:{job_name}:{requested_by}:{request_id}")
        return SimpleNamespace(id="job-concierge-123")

    monkeypatch.setattr(worker.settings, "agentic_system_active", True)
    monkeypatch.setattr(worker.settings, "concierge_shadow_draft_enabled", True)
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(worker, "count_jobs_by_status", fake_count_jobs_by_status)
    monkeypatch.setattr(worker, "enqueue_async_job", fake_enqueue_async_job)

    asyncio.run(worker._enqueue_concierge_shadow_draft_if_idle())

    assert events == [
        "count:queued:concierge_shadow_draft_cycle",
        "count:running:concierge_shadow_draft_cycle",
        "enqueue:run_concierge_shadow_draft_job:concierge_shadow_draft_cycle:system_concierge_shadow_draft:concierge-shadow-draft-observer",
    ]
