from __future__ import annotations

import asyncio
import os
import pickle
import sys
import types
from types import SimpleNamespace
from uuid import uuid4

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
from backend.services import hunter_service


def test_normalize_session_fp_is_deterministic(monkeypatch) -> None:
    monkeypatch.setattr(hunter_service.settings, "audit_log_signing_key", "test-pepper", raising=False)
    session_id = str(uuid4())

    first = hunter_service._normalize_session_fp(session_id)
    second = hunter_service._normalize_session_fp(session_id)

    assert first == second
    assert len(first) == 64
    assert hunter_service._normalize_session_fp(first) == first


def test_hunter_candidate_filters_skip_synthetic_and_contactless() -> None:
    assert hunter_service._is_synthetic_identity(
        guest_email="shadow.lead+smoke@example.com",
        guest_display_name="Shadow Smoke",
    )
    assert hunter_service._is_synthetic_identity(
        guest_email="ops@crog-ai.com",
        guest_display_name="Real Operator",
    )
    assert not hunter_service._is_synthetic_identity(
        guest_email="guest@protonmail.com",
        guest_display_name="Ada Lovelace",
    )
    assert not hunter_service._has_recovery_contact_channel(guest_email=None, guest_phone=None)
    assert hunter_service._has_recovery_contact_channel(
        guest_email="guest@protonmail.com",
        guest_phone=None,
    )


def test_nemoclaw_verify_ssl_disables_for_private_hosts(monkeypatch) -> None:
    monkeypatch.delenv("NEMOCLAW_ORCHESTRATOR_VERIFY_SSL", raising=False)

    assert not hunter_service._nemoclaw_verify_ssl("https://192.168.0.104:8080")
    assert not hunter_service._nemoclaw_verify_ssl("https://127.0.0.1:8000")
    assert hunter_service._nemoclaw_verify_ssl("https://api.example.com")


def test_collect_target_alpha_candidates_filters_synthetic_and_contactless(monkeypatch) -> None:
    async def fake_build_funnel_hq_payload(db, *, recovery_limit: int, stale_after_hours: int, min_stale_minutes: int):
        return {
            "recovery": [
                {
                    "session_fp": "real-session",
                    "property_slug": "real-cabin",
                    "guest_email": "guest@protonmail.com",
                    "guest_phone": None,
                    "guest_display_name": "Ada Guest",
                    "intent_score_estimate": 4.5,
                    "drop_off_point": "checkout_step",
                },
                {
                    "session_fp": "synthetic-session",
                    "property_slug": "real-cabin",
                    "guest_email": "shadow.lead+smoke@example.com",
                    "guest_phone": "4045551414",
                    "guest_display_name": "Shadow Smoke",
                    "intent_score_estimate": 8.5,
                    "drop_off_point": "checkout_step",
                },
                {
                    "session_fp": "contactless-session",
                    "property_slug": "real-cabin",
                    "guest_email": None,
                    "guest_phone": None,
                    "guest_display_name": None,
                    "intent_score_estimate": 2.0,
                    "drop_off_point": "quote_open",
                },
            ]
        }

    async def fake_property_ids_by_slug(db, slugs: set[str]):
        return {"real-cabin": "property-id-1"}

    monkeypatch.setattr(hunter_service, "build_funnel_hq_payload", fake_build_funnel_hq_payload)
    monkeypatch.setattr(hunter_service, "_property_ids_by_slug", fake_property_ids_by_slug)

    candidates = asyncio.run(hunter_service._collect_target_alpha_candidates(object(), limit=10))

    assert len(candidates) == 1
    assert candidates[0].guest_email == "guest@protonmail.com"
    assert candidates[0].campaign == "abandoned_quote"


def test_startup_arms_hunter_queue_sweep_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("SEO_GRADING_CONSUMER_ENABLED", "0")
    monkeypatch.setenv("SEO_REWRITE_CONSUMER_ENABLED", "0")
    monkeypatch.setenv("SEO_DEPLOY_CONSUMER_ENABLED", "0")
    monkeypatch.setattr(worker.settings, "semrush_shadow_observer_enabled", False)
    monkeypatch.setattr(worker.settings, "research_scout_enabled", False)
    monkeypatch.setattr(worker.settings, "concierge_shadow_draft_enabled", False)
    monkeypatch.setattr(worker.settings, "hunter_queue_sweep_enabled", True)
    monkeypatch.setattr(worker.settings, "async_job_watchdog_enabled", False)

    async def fake_enforce_sovereign_boundary() -> None:
        return None

    async def fake_hunter_loop() -> None:
        raise asyncio.CancelledError

    class FakeStreamlineVRS:
        def __init__(self) -> None:
            self.is_configured = False

    original_create_task = asyncio.create_task

    def tracking_create_task(coro, *, name=None):
        return original_create_task(coro, name=name)

    monkeypatch.setattr(worker, "_hunter_queue_sweep_loop", fake_hunter_loop)
    monkeypatch.setattr(worker, "StreamlineVRS", FakeStreamlineVRS)
    monkeypatch.setattr(worker, "enforce_sovereign_boundary", fake_enforce_sovereign_boundary)
    monkeypatch.setattr(asyncio, "create_task", tracking_create_task)

    ctx: dict[str, object] = {}
    asyncio.run(worker.startup(ctx))

    assert "hunter_queue_sweep_task" in ctx


def test_validate_worker_registry_raises_when_required_function_missing(monkeypatch) -> None:
    monkeypatch.setattr(worker.WorkerSettings, "functions", [worker.process_streamline_event_job])

    try:
        worker._validate_worker_registry()
    except RuntimeError as exc:
        assert "run_hunter_execute_job" in str(exc)
    else:
        raise AssertionError("expected worker registry validation to fail")


def test_enqueue_hunter_queue_sweep_enqueues_when_idle(monkeypatch) -> None:
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
        return SimpleNamespace(id="job-hunter-123")

    monkeypatch.setattr(worker.settings, "agentic_system_active", True)
    monkeypatch.setattr(worker.settings, "hunter_queue_sweep_enabled", True)
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(worker, "count_jobs_by_status", fake_count_jobs_by_status)
    monkeypatch.setattr(worker, "enqueue_async_job", fake_enqueue_async_job)

    asyncio.run(worker._enqueue_hunter_queue_sweep_if_idle())

    assert events == [
        "count:queued:hunter_queue_sweep",
        "count:running:hunter_queue_sweep",
        "enqueue:run_hunter_queue_sweep_job:hunter_queue_sweep:system_hunter_queue_sweep:hunter-queue-sweep-observer",
    ]


def test_run_hunter_queue_sweep_job_delegates_to_service(monkeypatch) -> None:
    events: list[str] = []

    async def fake_sweep_hunter_queue(db, *, candidate_limit: int | None = None, trigger: str = "scheduled"):
        events.append(f"sweep:{candidate_limit}:{trigger}")
        return {"queued_candidates": 3}

    async def fake_with_job(job_id, job_try, runner):
        result = await runner(object(), SimpleNamespace(job_name="hunter_queue_sweep"))
        events.append(f"with-job:{job_id}:{job_try}")
        return result

    monkeypatch.setattr(worker.settings, "hunter_queue_candidate_limit", 50)
    monkeypatch.setattr(hunter_service, "sweep_hunter_queue", fake_sweep_hunter_queue)
    monkeypatch.setattr(worker, "_with_job", fake_with_job)

    result = asyncio.run(worker.run_hunter_queue_sweep_job({"job_try": 1}, "job-hunter-1"))

    assert events == [
        "sweep:50:hunter_queue_sweep",
        "with-job:job-hunter-1:1",
    ]
    assert result["hunter_queue_sweep"]["queued_candidates"] == 3


def test_run_hunter_execute_job_delegates_to_service(monkeypatch) -> None:
    events: list[str] = []

    async def fake_execute_hunter_candidate(db, *, session_fp: str, async_job_run_id=None):
        events.append(f"execute:{session_fp}:{bool(async_job_run_id)}")
        return {"status": "draft_generated", "session_fp": session_fp}

    async def fake_mark_hunter_candidate_failed(db, *, session_fp: str, error_text: str):
        events.append(f"failed:{session_fp}:{error_text}")

    async def fake_with_job(job_id, job_try, runner):
        result = await runner(
            object(),
            SimpleNamespace(id=str(uuid4()), job_name="hunter_execute", payload_json={"session_fp": "session-fp-1"}),
        )
        events.append(f"with-job:{job_id}:{job_try}")
        return result

    monkeypatch.setattr(hunter_service, "execute_hunter_candidate", fake_execute_hunter_candidate)
    monkeypatch.setattr(hunter_service, "mark_hunter_candidate_failed", fake_mark_hunter_candidate_failed)
    monkeypatch.setattr(worker, "_with_job", fake_with_job)

    result = asyncio.run(worker.run_hunter_execute_job({"job_try": 1}, "job-hunter-exec-1"))

    assert events == [
        "execute:session-fp-1:True",
        "with-job:job-hunter-exec-1:1",
    ]
    assert result["hunter_execute"]["status"] == "draft_generated"


def test_run_hunter_recovery_draft_job_delegates_to_service(monkeypatch) -> None:
    events: list[str] = []
    recovery_op_id = str(uuid4())

    async def fake_execute_hunter_recovery_draft(
        db,
        *,
        recovery_op_id,
        draft_context=None,
        request_id: str | None = None,
    ):
        events.append(f"recovery:{recovery_op_id}:{bool(draft_context)}:{request_id}")
        return {"status": "draft_ready", "recovery_op_id": str(recovery_op_id)}

    async def fake_mark_hunter_recovery_op_retry(
        db,
        *,
        recovery_op_id,
        request_id: str | None = None,
        error_text: str,
    ):
        events.append(f"retry:{recovery_op_id}:{request_id}:{error_text}")

    async def fake_with_job(job_id, job_try, runner):
        result = await runner(
            object(),
            SimpleNamespace(
                id=str(uuid4()),
                job_name="hunter_recovery_draft",
                payload_json={"recovery_op_id": recovery_op_id, "draft_context": {"guest_name": "Ada"}},
            ),
        )
        events.append(f"with-job:{job_id}:{job_try}")
        return result

    monkeypatch.setattr(hunter_service, "execute_hunter_recovery_draft", fake_execute_hunter_recovery_draft)
    monkeypatch.setattr(hunter_service, "mark_hunter_recovery_op_retry", fake_mark_hunter_recovery_op_retry)
    monkeypatch.setattr(worker, "_with_job", fake_with_job)

    result = asyncio.run(worker.run_hunter_recovery_draft_job({"job_try": 1}, "job-hunter-recovery-1"))

    assert events[0].startswith(f"recovery:{recovery_op_id}:True:")
    assert events[1] == "with-job:job-hunter-recovery-1:1"
    assert result["hunter_recovery_draft"]["status"] == "draft_ready"


def test_repair_stale_async_jobs_marks_failed_and_repairs_hunter(monkeypatch) -> None:
    events: list[str] = []
    stale_job = SimpleNamespace(
        id=str(uuid4()),
        job_name="hunter_execute",
        status="queued",
        payload_json={"session_fp": "stale-session-fp"},
        attempts=0,
    )

    async def fake_mark_hunter_candidate_failed(db, *, session_fp: str, error_text: str):
        events.append(f"hunter:{session_fp}:{error_text}")

    async def fake_mark_job_failed(db, job, error_text: str, *, attempts: int):
        events.append(f"job:{job.job_name}:{error_text}:{attempts}")
        return job

    monkeypatch.setattr(hunter_service, "mark_hunter_candidate_failed", fake_mark_hunter_candidate_failed)
    monkeypatch.setattr(worker, "mark_job_failed", fake_mark_job_failed)

    repaired = asyncio.run(worker._repair_stale_async_jobs(object(), [stale_job]))

    assert repaired == 1
    assert events == [
        "hunter:stale-session-fp:watchdog_recovered_stale_queued",
        "job:hunter_execute:watchdog_recovered_stale_queued:1",
    ]


def test_reconcile_jobs_from_arq_results_marks_success(monkeypatch) -> None:
    events: list[str] = []
    stale_job = SimpleNamespace(
        id=str(uuid4()),
        arq_job_id=None,
        job_name="process_streamline_event",
        status="queued",
        payload_json={},
        attempts=0,
        started_at=None,
        finished_at=None,
        result_json={},
        error_text=None,
    )

    class DummyDb:
        async def commit(self):
            events.append("commit")

    class FakeRedis:
        async def get(self, key: str):
            events.append(f"get:{key}")
            return pickle.dumps(
                {
                    "t": 2,
                    "s": True,
                    "r": {"entity_id": "reservation-1"},
                    "st": 1_774_470_000_000,
                    "ft": 1_774_470_001_000,
                }
            )

    reconciled = asyncio.run(worker._reconcile_jobs_from_arq_results(DummyDb(), [stale_job], FakeRedis()))

    assert reconciled == 1
    assert stale_job.status == "succeeded"
    assert stale_job.result_json == {"entity_id": "reservation-1"}
    assert stale_job.error_text is None
    assert stale_job.attempts == 2
    assert stale_job.started_at is not None
    assert stale_job.finished_at is not None
    assert events == [f"get:arq:result:{stale_job.id}", "commit"]


def test_reconcile_jobs_from_arq_results_marks_hunter_failure(monkeypatch) -> None:
    events: list[str] = []
    stale_job = SimpleNamespace(
        id=str(uuid4()),
        arq_job_id=None,
        job_name="hunter_execute",
        status="queued",
        payload_json={"session_fp": "failed-session-fp"},
        attempts=0,
        started_at=None,
        finished_at=None,
        result_json={},
        error_text=None,
    )

    class DummyDb:
        async def commit(self):
            events.append("commit")

    class FakeRedis:
        async def get(self, key: str):
            events.append(f"get:{key}")
            return pickle.dumps(
                {
                    "t": 1,
                    "s": False,
                    "r": RuntimeError("function 'run_hunter_execute_job' not found"),
                    "st": 1_774_470_000_000,
                    "ft": 1_774_470_001_000,
                }
            )

    async def fake_mark_hunter_candidate_failed(db, *, session_fp: str, error_text: str):
        events.append(f"hunter:{session_fp}:{error_text}")

    monkeypatch.setattr(hunter_service, "mark_hunter_candidate_failed", fake_mark_hunter_candidate_failed)

    reconciled = asyncio.run(worker._reconcile_jobs_from_arq_results(DummyDb(), [stale_job], FakeRedis()))

    assert reconciled == 1
    assert stale_job.status == "failed"
    assert "run_hunter_execute_job" in (stale_job.error_text or "")
    assert stale_job.attempts == 1
    assert events == [
        f"get:arq:result:{stale_job.id}",
        "hunter:failed-session-fp:function 'run_hunter_execute_job' not found",
        "commit",
    ]


def test_run_async_job_watchdog_once_reconciles_before_stale_repair(monkeypatch) -> None:
    events: list[str] = []
    stale_job = SimpleNamespace(
        id=str(uuid4()),
        arq_job_id=None,
        job_name="process_streamline_event",
        status="queued",
        request_id=None,
        payload_json={},
        attempts=0,
        started_at=None,
        finished_at=None,
        result_json={},
        error_text=None,
    )

    class DummyDb:
        async def commit(self):
            events.append("commit")

    class DummySession:
        async def __aenter__(self):
            return DummyDb()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeRedis:
        async def get(self, key: str):
            events.append(f"get:{key}")
            return pickle.dumps({"t": 1, "s": True, "r": {"ok": True}, "ft": 1_774_470_001_000})

        async def aclose(self):
            events.append("close")

    load_results = [[stale_job], []]

    async def fake_load_stale_async_jobs(db):
        events.append("load")
        return load_results.pop(0)

    async def fake_repair_stale_async_jobs(db, jobs):
        raise AssertionError("watchdog should not repair jobs that were reconciled from ARQ results")

    async def fake_create_arq_pool():
        return FakeRedis()

    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(worker, "_load_stale_async_jobs", fake_load_stale_async_jobs)
    monkeypatch.setattr(worker, "_repair_stale_async_jobs", fake_repair_stale_async_jobs)
    monkeypatch.setattr(worker, "create_arq_pool", fake_create_arq_pool)

    asyncio.run(worker._run_async_job_watchdog_once())

    assert stale_job.status == "succeeded"
    assert stale_job.result_json == {"ok": True}
    assert events == ["load", f"get:arq:result:{stale_job.id}", "commit", "load", "close"]
