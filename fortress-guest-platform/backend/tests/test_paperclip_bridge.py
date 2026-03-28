from __future__ import annotations

import asyncio
import os
import sys
import types

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

from backend.api.paperclip_bridge import router as paperclip_bridge_router
from backend.api import paperclip_bridge as paperclip_bridge_api


def build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(paperclip_bridge_router, prefix="/api/paperclip")
    return app


@pytest.mark.asyncio
async def test_paperclip_execute_accepts_and_callbacks_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = build_test_app()
    tasks: list[asyncio.Task[None]] = []
    captured_posts: list[tuple[str, dict[str, object], dict[str, str]]] = []
    real_create_task = asyncio.create_task

    class FakeResponse:
        def __init__(
            self,
            *,
            status_code: int,
            json_payload: dict[str, object] | None = None,
        ) -> None:
            self.status_code = status_code
            self._json_payload = json_payload or {}
            self.content = b"{}"
            self.request = httpx.Request("POST", "http://test")

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("boom", request=self.request, response=self)

        def json(self) -> dict[str, object]:
            return self._json_payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, *, json: dict[str, object], headers: dict[str, str]):
            captured_posts.append((url, json, headers))
            if url.endswith("/api/agent/execute"):
                return FakeResponse(
                    status_code=200,
                    json_payload={
                        "task_id": "paperclip-run-run_123",
                        "status": "success",
                        "action_log": ["execution_path=openshell_cli"],
                        "result_payload": {"draft_body": "bridge complete"},
                    },
                )
            if url.endswith("/api/heartbeat-runs/run_123/callback"):
                return FakeResponse(status_code=200)
            raise AssertionError(f"Unexpected URL: {url}")

    def capture_task(coro):
        task = real_create_task(coro)
        tasks.append(task)
        return task

    monkeypatch.setattr(paperclip_bridge_api.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(paperclip_bridge_api.asyncio, "create_task", capture_task)
    monkeypatch.setattr(paperclip_bridge_api.settings, "swarm_api_key", "paperclip-bridge-token", raising=False)
    monkeypatch.setattr(paperclip_bridge_api.settings, "nemoclaw_orchestrator_url", "http://127.0.0.1:8000", raising=False)
    monkeypatch.setattr(paperclip_bridge_api.settings, "nemoclaw_orchestrator_api_key", "nemoclaw-key", raising=False)
    monkeypatch.setattr(
        paperclip_bridge_api.settings,
        "paperclip_control_plane_url",
        "http://paperclip.paperclip.svc.cluster.local:3100",
        raising=False,
    )
    monkeypatch.setattr(
        paperclip_bridge_api.settings,
        "paperclip_control_plane_api_key",
        "paperclip-callback-key",
        raising=False,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/paperclip/execute",
            headers={"X-Swarm-Token": "paperclip-bridge-token"},
            json={
                "runId": "run_123",
                "agentId": "agent_456",
                "companyId": "company_789",
                "taskId": None,
                "issueId": "issue_111",
                "wakeReason": "task_assigned",
                "wakeCommentId": None,
                "approvalId": None,
                "approvalStatus": None,
                "issueIds": ["issue_111"],
                "context": {
                    "taskId": "issue_111",
                    "wakeReason": "task_assigned",
                    "paperclipWorkspace": {"cwd": "/workspace", "source": "manual"},
                },
            },
        )

    await asyncio.gather(*tasks)

    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "executionId": "run_123"}
    assert captured_posts[0][0] == "http://127.0.0.1:8000/api/agent/execute"
    assert captured_posts[0][1]["task_id"] == "issue_111"
    assert captured_posts[0][1]["context_payload"]["paperclip_run_id"] == "run_123"
    assert captured_posts[0][2]["x-api-key"] == "nemoclaw-key"
    assert captured_posts[1][0] == "http://paperclip.paperclip.svc.cluster.local:3100/api/heartbeat-runs/run_123/callback"
    assert captured_posts[1][1]["status"] == "succeeded"
    assert captured_posts[1][2]["Authorization"] == "Bearer paperclip-callback-key"


@pytest.mark.asyncio
async def test_paperclip_execute_requires_callback_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = build_test_app()

    monkeypatch.setattr(paperclip_bridge_api.settings, "swarm_api_key", "paperclip-bridge-token", raising=False)
    monkeypatch.setattr(paperclip_bridge_api.settings, "paperclip_control_plane_url", "", raising=False)
    monkeypatch.setattr(paperclip_bridge_api.settings, "paperclip_control_plane_api_key", "", raising=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/paperclip/execute",
            headers={"X-Swarm-Token": "paperclip-bridge-token"},
            json={
                "runId": "run_123",
                "agentId": "agent_456",
                "companyId": "company_789",
                "taskId": "task_1",
                "issueId": "task_1",
                "wakeReason": "manual",
                "wakeCommentId": None,
                "approvalId": None,
                "approvalStatus": None,
                "issueIds": ["task_1"],
                "context": {"taskId": "task_1", "wakeReason": "manual"},
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Paperclip control-plane URL is not configured."
