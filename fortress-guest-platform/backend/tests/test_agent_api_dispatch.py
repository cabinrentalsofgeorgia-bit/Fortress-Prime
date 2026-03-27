from __future__ import annotations

import json
import os
import sys
import types
from types import SimpleNamespace
from uuid import uuid4

import httpx
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

from backend.api import agent as agent_api
from backend.api.agent import router as agent_router
from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.staff import StaffRole


def build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(agent_router, prefix="/api/agent")
    return app


@pytest.mark.asyncio
async def test_manual_agent_dispatch_forwards_to_nemoclaw(monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_test_app()
    captured: list[tuple[str, dict, dict]] = []
    client_kwargs: list[dict] = []

    async def override_get_db():
        yield object()

    async def override_get_current_user():
        return SimpleNamespace(
            id=uuid4(),
            email="manager@example.com",
            role=StaffRole.MANAGER,
            is_active=True,
        )

    class FakeResponse:
        def __init__(self) -> None:
            self.status_code = 200
            self.content = b'{"status":"success","task_id":"manual-dispatch"}'

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"status": "success", "task_id": "manual-dispatch"}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            client_kwargs.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, *, json: dict, headers: dict[str, str]):
            captured.append((url, json, headers))
            return FakeResponse()

    monkeypatch.setattr(agent_api.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(agent_api.settings, "nemoclaw_orchestrator_url", "http://127.0.0.1:8000", raising=False)
    monkeypatch.setattr(agent_api.settings, "nemoclaw_orchestrator_api_key", "secret-key", raising=False)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/agent/dispatch",
            json={"intent": "run python", "context_payload": {"path": "/tmp/x"}, "target_node": "auto"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured[0][0] == "http://127.0.0.1:8000/api/agent/execute"
    assert captured[0][1]["intent"] == "run python"
    assert captured[0][1]["context_payload"]["requested_by"] == "manager@example.com"
    assert captured[0][2]["x-api-key"] == "secret-key"
    assert client_kwargs[0]["verify"] is False


@pytest.mark.asyncio
async def test_manual_agent_dispatch_disables_tls_verify_for_private_https(monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_test_app()
    client_kwargs: list[dict] = []

    async def override_get_db():
        yield object()

    async def override_get_current_user():
        return SimpleNamespace(
            id=uuid4(),
            email="manager@example.com",
            role=StaffRole.MANAGER,
            is_active=True,
        )

    class FakeResponse:
        def __init__(self) -> None:
            self.status_code = 200
            self.content = b'{"status":"success","task_id":"manual-dispatch"}'

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"status": "success", "task_id": "manual-dispatch"}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            client_kwargs.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, *, json: dict, headers: dict[str, str]):
            return FakeResponse()

    monkeypatch.setattr(agent_api.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(agent_api.settings, "nemoclaw_orchestrator_url", "https://192.168.0.104:8080", raising=False)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/agent/dispatch",
            json={"intent": "run python", "context_payload": {"path": "/tmp/x"}, "target_node": "auto"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert client_kwargs[0]["verify"] is False


@pytest.mark.asyncio
async def test_stream_agent_dispatch_falls_back_to_execute_path(monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_test_app()
    captured_posts: list[tuple[str, dict, dict]] = []

    async def override_get_db():
        yield object()

    async def override_get_current_user():
        return SimpleNamespace(
            id=uuid4(),
            email="manager@example.com",
            role=StaffRole.MANAGER,
            is_active=True,
        )

    class FakeResponse:
        def __init__(
            self,
            *,
            status_code: int,
            headers: dict[str, str] | None = None,
            body: bytes = b"",
            json_payload: dict[str, object] | None = None,
        ) -> None:
            self.status_code = status_code
            self.headers = headers or {}
            self._body = body
            self._json_payload = json_payload or {}
            self.content = body or (json.dumps(self._json_payload).encode("utf-8") if self._json_payload else b"")
            self.text = self.content.decode("utf-8", errors="ignore")
            self.request = httpx.Request("POST", "http://test")

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("boom", request=self.request, response=self)

        def json(self) -> dict[str, object]:
            return self._json_payload

        async def aiter_bytes(self):
            if self._body:
                yield self._body

    class FakeStreamContext:
        def __init__(self, response: FakeResponse) -> None:
            self.response = response

        async def __aenter__(self):
            return self.response

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method: str, url: str, *, json: dict, headers: dict[str, str]):
            assert method == "POST"
            assert url == "http://127.0.0.1:8000/api/agent/execute/stream"
            assert headers["Accept"] == "text/event-stream"
            return FakeStreamContext(FakeResponse(status_code=404))

        async def post(self, url: str, *, json: dict, headers: dict[str, str]):
            captured_posts.append((url, json, headers))
            return FakeResponse(
                status_code=200,
                json_payload={
                    "status": "success",
                    "action_log": ["execution_path=openshell_cli", "sandbox_name=my-assistant"],
                    "result_payload": {"draft_body": "streamed draft"},
                },
            )

    monkeypatch.setattr(agent_api.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(agent_api.settings, "nemoclaw_orchestrator_url", "http://127.0.0.1:8000", raising=False)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/agent/dispatch/stream",
            json={"intent": "run python", "context_payload": {"path": "/tmp/x"}, "target_node": "auto"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert captured_posts[0][0] == "http://127.0.0.1:8000/api/agent/execute"
    assert "data:" in response.text
    assert "streamed draft" in response.text
