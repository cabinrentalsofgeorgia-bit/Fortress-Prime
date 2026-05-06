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


@pytest.mark.asyncio
async def test_counsel_validation_endpoint_returns_manifest(monkeypatch):
    monkeypatch.setattr(
        legal_workbench_api,
        "load_latest_validation",
        lambda slug: {
            "case_slug": slug,
            "execution_id": "fortress-validation-test",
            "status": "DRAFT / COUNSEL REVIEW REQUIRED",
            "records": [
                {
                    "item_id": "issue-01",
                    "item_title": "Issue",
                    "validation_status": "needs_counsel_review",
                    "source_refs": [{"document_id": "d1"}],
                    "locked_restricted_related": False,
                }
            ],
            "queues": [],
            "summary": {"total_workbench_items": 1},
        },
    )

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/fortress-legal-production-review/counsel-validation")

    assert response.status_code == 200
    body = response.json()
    assert body["execution_id"] == "fortress-validation-test"
    assert body["records"][0]["validation_status"] == "needs_counsel_review"


@pytest.mark.asyncio
async def test_counsel_validation_action_never_uses_final_legal_conclusion(monkeypatch):
    def fake_apply_validation_action(slug, **kwargs):
        assert slug == "fortress-legal-production-review"
        assert kwargs["validation_status"] != "final_legal_conclusion"
        return {
            "case_slug": slug,
            "updated_record": {
                "item_id": kwargs["item_id"],
                "validation_status": "accepted_for_review_use",
            },
        }

    monkeypatch.setattr(legal_workbench_api, "apply_validation_action", fake_apply_validation_action)

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/internal/legal/cases/fortress-legal-production-review/counsel-validation/actions",
            json={"item_id": "issue-01", "action": "accept"},
        )

    assert response.status_code == 200
    assert response.json()["updated_record"]["validation_status"] == "accepted_for_review_use"
