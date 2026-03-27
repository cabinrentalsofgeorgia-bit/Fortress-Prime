from __future__ import annotations

import os
import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

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

from backend.api import hunter as hunter_api
from backend.api.hunter import router as hunter_router
from backend.core.database import get_db
from backend.core.queue import get_arq_pool
from backend.core.security import get_current_user
from backend.models.hunter_recovery_op import HunterRecoveryOpStatus
from backend.models.staff import StaffRole


def build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(hunter_router, prefix="/api")
    return app


class DummyScalarResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalars(self) -> "DummyScalarResult":
        return self

    def all(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


@pytest.mark.asyncio
async def test_hunter_queue_supports_pending_review_alias() -> None:
    app = build_test_app()
    now = datetime(2026, 3, 26, 7, 25, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(
            id=uuid4(),
            session_fp="session-fp-queued",
            property_id=uuid4(),
            reservation_id=uuid4(),
            guest_phone="+17065551212",
            guest_email="queued@example.com",
            campaign="reactivation",
            payload={"source": "streamline"},
            score=87,
            status="queued",
            last_error=None,
            created_at=now,
            updated_at=now,
        ),
        SimpleNamespace(
            id=uuid4(),
            session_fp="session-fp-processing",
            property_id=None,
            reservation_id=None,
            guest_phone=None,
            guest_email="processing@example.com",
            campaign="reactivation",
            payload={"source": "shadow"},
            score=73,
            status="processing",
            last_error=None,
            created_at=now,
            updated_at=now,
        ),
    ]

    class DummySession:
        async def execute(self, _query):
            return DummyScalarResult(rows)

    async def override_get_db():
        yield DummySession()

    async def override_get_current_user():
        return SimpleNamespace(
            id=uuid4(),
            email="reviewer@example.com",
            role=StaffRole.REVIEWER,
            is_active=True,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/hunter/queue?status_filter=pending_review&limit=50")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert [row["status"] for row in payload] == ["queued", "processing"]
    assert payload[0]["guest_email"] == "queued@example.com"
    assert payload[1]["payload"] == {"source": "shadow"}
    assert payload[0]["session_fp"] == "session-fp-queued"


@pytest.mark.asyncio
async def test_hunter_execute_enqueues_job_and_marks_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_test_app()
    entry = SimpleNamespace(
        id=uuid4(),
        session_fp="abc123sessionfp00",
        status="queued",
        last_error=None,
    )
    events: list[str] = []

    class DummySession:
        async def execute(self, _query):
            return DummyScalarResult(entry)

        async def commit(self):
            events.append("commit")

    async def override_get_db():
        yield DummySession()

    async def override_get_current_user():
        return SimpleNamespace(
            id=uuid4(),
            email="reviewer@example.com",
            role=StaffRole.REVIEWER,
            is_active=True,
        )

    async def override_get_arq_pool():
        return object()

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
        events.append(f"enqueue:{worker_name}:{job_name}:{payload['session_fp']}:{requested_by}")
        return SimpleNamespace(id="job-hunter-execute-123")

    monkeypatch.setattr(hunter_api, "enqueue_async_job", fake_enqueue_async_job)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_arq_pool] = override_get_arq_pool

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/hunter/execute",
            json={"session_fp": "abc123sessionfp00"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 202
    assert events == [
        "enqueue:run_hunter_execute_job:hunter_execute:abc123sessionfp00:reviewer@example.com",
        "commit",
    ]
    assert entry.status == "processing"
    assert response.json()["job_id"] == "job-hunter-execute-123"


@pytest.mark.asyncio
async def test_hunter_dismiss_deletes_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_test_app()
    events: list[str] = []

    async def override_get_db():
        yield object()

    async def override_get_current_user():
        return SimpleNamespace(
            id=uuid4(),
            email="reviewer@example.com",
            role=StaffRole.REVIEWER,
            is_active=True,
        )

    async def fake_delete_hunter_candidate(_db, session_fp: str) -> bool:
        events.append(session_fp)
        return True

    monkeypatch.setattr(hunter_api, "delete_hunter_candidate", fake_delete_hunter_candidate)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete("/api/hunter/queue/abc123sessionfp")

    app.dependency_overrides.clear()

    assert response.status_code == 204
    assert events == ["abc123sessionfp"]


@pytest.mark.asyncio
async def test_hunter_operations_lists_recovery_ops() -> None:
    app = build_test_app()
    now = datetime(2026, 3, 26, 19, 0, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(
            id=uuid4(),
            cart_id="session-fp-1",
            guest_name="Ada Guest",
            cabin_name="Ridge Line Lodge",
            cart_value=321.45,
            status=HunterRecoveryOpStatus.DRAFT_READY,
            ai_draft_body="Draft body",
            assigned_worker="192.168.0.104",
            created_at=now,
        )
    ]

    class DummySession:
        async def execute(self, _query):
            return DummyScalarResult(rows)

    async def override_get_db():
        yield DummySession()

    async def override_get_current_user():
        return SimpleNamespace(
            id=uuid4(),
            email="reviewer@example.com",
            role=StaffRole.REVIEWER,
            is_active=True,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/hunter/operations")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["cart_id"] == "session-fp-1"
    assert payload[0]["status"] == "DRAFT_READY"
    assert payload[0]["assigned_worker"] == "192.168.0.104"


@pytest.mark.asyncio
async def test_hunter_approve_dispatches_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_test_app()
    op_id = uuid4()
    op = SimpleNamespace(
        id=op_id,
        cart_id="abc123sessionfp00",
        guest_name="Ada Guest",
        cabin_name="Ridge Line Lodge",
        cart_value=None,
        status=HunterRecoveryOpStatus.DRAFT_READY,
        ai_draft_body="Return for your stay.",
        assigned_worker="192.168.0.104",
        created_at=datetime(2026, 3, 26, 19, 5, tzinfo=timezone.utc),
    )
    guest = SimpleNamespace(email="ada@example.com", phone=None)
    events: list[str] = []

    class DummySession:
        async def get(self, model, lookup_id):
            assert lookup_id == op_id
            return op

        async def commit(self):
            events.append("commit")

    async def override_get_db():
        yield DummySession()

    async def override_get_current_user():
        return SimpleNamespace(
            id=uuid4(),
            email="manager@example.com",
            role=StaffRole.MANAGER,
            is_active=True,
        )

    async def fake_resolve_recovery_guest_contact(db, *, cart_id: str):
        events.append(f"resolve:{cart_id}")
        return guest

    async def fake_dispatch_recovery_contact(*, guest, op):
        events.append(f"dispatch:{guest.email}:{op.cart_id}")
        return "email"

    async def fake_record_audit_event(**kwargs):
        events.append(f"audit:{kwargs['tool_name']}:{kwargs['resource_id']}")
        return None

    monkeypatch.setattr(hunter_api, "_resolve_recovery_guest_contact", fake_resolve_recovery_guest_contact)
    monkeypatch.setattr(hunter_api, "_dispatch_recovery_contact", fake_dispatch_recovery_contact)
    monkeypatch.setattr(hunter_api, "record_audit_event", fake_record_audit_event)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/hunter/approve/{op_id}")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert op.status == HunterRecoveryOpStatus.DISPATCHED
    assert events == [
        "resolve:abc123sessionfp00",
        "dispatch:ada@example.com:abc123sessionfp00",
        "commit",
        f"audit:email:{op_id}",
    ]
    assert response.json()["channel"] == "email"
