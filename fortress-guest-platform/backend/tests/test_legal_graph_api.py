"""Focused tests for the legal graph API."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import run  # noqa: F401
import backend.api.legal_graph as legal_graph_api
from backend.core.security import get_current_user


def _user(role: str = "manager") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        email=f"{role}@fortress.local",
        role=role,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_graph_snapshot_auto_builds_when_initial_snapshot_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()

    @asynccontextmanager
    async def override_session_local():
        yield session

    get_snapshot = AsyncMock(
        side_effect=[
            {"case_slug": "demo-case", "nodes": [], "edges": []},
            {
                "case_slug": "demo-case",
                "nodes": [
                    {
                        "id": "node-1",
                        "case_slug": "demo-case",
                        "entity_type": "case",
                        "entity_reference_id": None,
                        "label": "Demo Case",
                        "properties_json": {"summary": "Fallback graph"},
                    }
                ],
                "edges": [],
            },
        ]
    )
    build_graph = AsyncMock(return_value={"status": "graph_built", "case_slug": "demo-case", "nodes": 1, "edges": 0})

    monkeypatch.setattr(legal_graph_api, "AsyncSessionLocal", override_session_local)
    monkeypatch.setattr(legal_graph_api.LegalCaseGraphBuilder, "get_graph_snapshot", get_snapshot)
    monkeypatch.setattr(legal_graph_api.LegalCaseGraphBuilder, "build_baseline_graph", build_graph)

    app = FastAPI()
    app.include_router(legal_graph_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return _user("manager")

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/demo-case/graph/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert len(body["nodes"]) == 1
    assert body["nodes"][0]["label"] == "Demo Case"
    build_graph.assert_awaited_once_with(case_slug="demo-case", db=session)
    assert get_snapshot.await_count == 2
