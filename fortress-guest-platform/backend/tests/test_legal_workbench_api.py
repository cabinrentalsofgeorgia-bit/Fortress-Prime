from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

import run  # noqa: F401
import backend.api.legal_workbench as legal_workbench_api
from backend.core.security import get_current_user


@pytest.mark.asyncio
async def test_counsel_workbench_endpoint_requires_auth_dependency(monkeypatch):
    monkeypatch.setattr(
        legal_workbench_api,
        "load_latest_workbench",
        lambda slug: {
            "case_slug": slug,
            "execution_id": "fortress-counsel-review-test",
            "status": "DRAFT / COUNSEL REVIEW REQUIRED",
            "issue_matrix": [],
            "evidence_binders": [],
            "contradiction_triage": [],
            "consolidated_review_queue": [],
        },
    )

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/fortress-legal-production-review/counsel-workbench")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DRAFT / COUNSEL REVIEW REQUIRED"
    assert body["case_slug"] == "fortress-legal-production-review"


@pytest.mark.asyncio
async def test_counsel_workbench_endpoint_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(legal_workbench_api, "load_latest_workbench", lambda slug: None)

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/missing/counsel-workbench")

    assert response.status_code == 404
