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


@pytest.mark.asyncio
async def test_counsel_signoff_packet_endpoint_returns_manifest(monkeypatch):
    monkeypatch.setattr(
        legal_workbench_api,
        "load_latest_signoff_packet",
        lambda slug: {
            "case_slug": slug,
            "execution_id": "fortress-signoff-packet-test",
            "signoff_status": "COUNSEL_SIGNOFF_PENDING",
            "packet_checksum": "abc123",
            "sections": [],
        },
    )

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/fortress-legal-production-review/counsel-signoff-packet")

    assert response.status_code == 200
    assert response.json()["signoff_status"] == "COUNSEL_SIGNOFF_PENDING"


@pytest.mark.asyncio
async def test_source_integrity_endpoint_returns_manifest_without_body_text(monkeypatch):
    monkeypatch.setattr(
        legal_workbench_api,
        "load_latest_source_integrity",
        lambda slug: {
            "case_slug": slug,
            "execution_id": "fortress-source-integrity-test",
            "status": "SOURCE_INTEGRITY_VALIDATION_COMPLETE_WITH_UNRESOLVED_ITEMS",
            "source_integrity_summary": {
                "total_material_items": 297,
                "checked": 297,
                "source_verified_for_review_use": 0,
                "source_missing": 230,
                "needs_page_or_chunk_review": 67,
                "signoff_blockers": 297,
                "counsel_signoff_pending": True,
            },
            "records": [
                {
                    "item_id": "issue-01",
                    "source_support_status": "source_missing",
                    "source_refs_claimed": [{"document_id": "d1", "file_name": "safe-metadata.pdf"}],
                    "source_notes": "No safe source reference is attached.",
                }
            ],
        },
    )

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/fortress-legal-production-review/source-integrity")

    assert response.status_code == 200
    body = response.json()
    assert body["execution_id"] == "fortress-source-integrity-test"
    assert body["source_integrity_summary"]["counsel_signoff_pending"] is True
    assert "document_body" not in response.text
    assert "final_legal_conclusion" not in response.text


@pytest.mark.asyncio
async def test_source_integrity_endpoint_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(legal_workbench_api, "load_latest_source_integrity", lambda slug: None)

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/missing/source-integrity")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_source_remediation_endpoint_returns_manifest_without_body_text(monkeypatch):
    monkeypatch.setattr(
        legal_workbench_api,
        "load_latest_source_remediation",
        lambda slug: {
            "case_slug": slug,
            "execution_id": "fortress-source-remediation-test",
            "status": "SOURCE_REMEDIATION_COMPLETE_NO_SIGNOFF_SUBSET_READY",
            "remediation_summary": {
                "total_blockers_processed": 297,
                "remaining_blockers": 297,
                "verified_subset_count": 0,
                "counsel_signoff_pending": True,
            },
            "verified_subset": {"item_count": 0, "items": []},
            "refined_blocker_register": [
                {
                    "item_id": "issue-01",
                    "remediation_outcome": "unresolved_unsupported",
                    "source_notes_safe": "No claimed source reference is available.",
                }
            ],
        },
    )

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/fortress-legal-production-review/source-remediation")

    assert response.status_code == 200
    body = response.json()
    assert body["execution_id"] == "fortress-source-remediation-test"
    assert body["remediation_summary"]["counsel_signoff_pending"] is True
    assert "document_body" not in response.text
    assert "final_legal_conclusion" not in response.text


@pytest.mark.asyncio
async def test_source_remediation_endpoint_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(legal_workbench_api, "load_latest_source_remediation", lambda slug: None)

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/missing/source-remediation")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_source_link_repair_endpoint_returns_manifest_without_body_text(monkeypatch):
    monkeypatch.setattr(
        legal_workbench_api,
        "load_latest_source_link_repair",
        lambda slug: {
            "case_slug": slug,
            "execution_id": "fortress-source-link-repair-test",
            "status": "SOURCE_LINK_REPAIR_COMPLETE_VERIFIED_SUBSET_READY",
            "repair_summary": {
                "total_blockers_processed": 297,
                "verified_subset_count": 65,
                "remaining_unresolved": 232,
                "counsel_signoff_pending": True,
            },
            "verified_subset": {"item_count": 65, "items": []},
            "refined_unresolved_register": [],
        },
    )

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/fortress-legal-production-review/source-link-repair")

    assert response.status_code == 200
    body = response.json()
    assert body["execution_id"] == "fortress-source-link-repair-test"
    assert body["repair_summary"]["counsel_signoff_pending"] is True
    assert "document_body" not in response.text
    assert "final_legal_conclusion" not in response.text


@pytest.mark.asyncio
async def test_source_link_repair_endpoint_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(legal_workbench_api, "load_latest_source_link_repair", lambda slug: None)

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/missing/source-link-repair")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_targeted_source_completion_endpoint_returns_manifest_without_body_text(monkeypatch):
    monkeypatch.setattr(
        legal_workbench_api,
        "load_latest_targeted_source_completion",
        lambda slug: {
            "case_slug": slug,
            "execution_id": "fortress-targeted-source-completion-test",
            "status": "TARGETED_SOURCE_COMPLETION_VERIFIED_SUBSET_EXPANDED",
            "completion_summary": {
                "items_processed": 282,
                "prior_verified_subset_count": 15,
                "new_verified_subset_count": 65,
                "verified_subset_delta": 50,
                "remaining_unresolved": 232,
                "counsel_signoff_pending": True,
            },
            "expanded_verified_subset": {"new_item_count": 65, "new_items": []},
            "refined_unresolved_register": [],
        },
    )

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/fortress-legal-production-review/targeted-source-completion")

    assert response.status_code == 200
    body = response.json()
    assert body["execution_id"] == "fortress-targeted-source-completion-test"
    assert body["completion_summary"]["counsel_signoff_pending"] is True
    assert body["completion_summary"]["verified_subset_delta"] == 50
    assert "document_body" not in response.text
    assert "final_legal_conclusion" not in response.text


@pytest.mark.asyncio
async def test_targeted_source_completion_endpoint_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(legal_workbench_api, "load_latest_targeted_source_completion", lambda slug: None)

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/missing/targeted-source-completion")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_limited_signoff_candidate_endpoint_returns_manifest_without_body_text(monkeypatch):
    monkeypatch.setattr(
        legal_workbench_api,
        "load_latest_limited_signoff_candidate",
        lambda slug: {
            "case_slug": slug,
            "execution_id": "fortress-limited-signoff-candidate-test",
            "status": "LIMITED_SIGNOFF_CANDIDATE_PACKET_READY",
            "verified_subset_used": {"item_count": 65},
            "tier_summary": {
                "tier_1_count": 21,
                "tier_2_count": 81,
                "tier_3_count": 130,
            },
            "limited_signoff_candidate_packet": {
                "included_item_count": 65,
                "excluded_item_count": 232,
                "counsel_signoff_pending": True,
                "explicit_signoff_recorded": False,
            },
        },
    )

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/fortress-legal-production-review/limited-signoff-candidate")

    assert response.status_code == 200
    body = response.json()
    assert body["execution_id"] == "fortress-limited-signoff-candidate-test"
    assert body["limited_signoff_candidate_packet"]["explicit_signoff_recorded"] is False
    assert "document_body" not in response.text
    assert "final_legal_conclusion" not in response.text


@pytest.mark.asyncio
async def test_limited_signoff_candidate_endpoint_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(legal_workbench_api, "load_latest_limited_signoff_candidate", lambda slug: None)

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/missing/limited-signoff-candidate")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_counsel_signoff_decision_endpoint_returns_manifest_without_body_text(monkeypatch):
    monkeypatch.setattr(
        legal_workbench_api,
        "load_latest_decision_workflow",
        lambda slug: {
            "case_slug": slug,
            "execution_id": "fortress-signoff-decision-test",
            "status": "COUNSEL_SIGNOFF_DECISION_WORKFLOW_READY",
            "counsel_status": "COUNSEL_SIGNOFF_PENDING",
            "packet": {
                "packet_execution_id": "fortress-limited-signoff-candidate-test",
                "packet_version": 1,
                "packet_hash": "abc123",
                "included_verified_subset": 65,
                "excluded_unresolved_items": 232,
            },
            "decision_readiness": {
                "auto_signoff_prevented": True,
                "external_submission_authority_available": False,
                "final_legal_conclusion_available": False,
            },
            "decision_paths": [],
            "decision_records": [],
        },
    )

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/internal/legal/cases/fortress-legal-production-review/counsel-signoff-decision")

    assert response.status_code == 200
    body = response.json()
    assert body["execution_id"] == "fortress-signoff-decision-test"
    assert body["counsel_status"] == "COUNSEL_SIGNOFF_PENDING"
    assert body["decision_readiness"]["auto_signoff_prevented"] is True
    assert "document_body" not in response.text
    assert "authorized_for_external_submission" not in response.text
    assert "final_legal_conclusion" not in response.text


@pytest.mark.asyncio
async def test_counsel_signoff_decision_rejects_unconfirmed_signoff(monkeypatch):
    def fake_record_decision(slug, **kwargs):
        assert slug == "fortress-legal-production-review"
        assert kwargs["decision_type"] != "final_legal_conclusion"
        if kwargs["decision_type"] == "counsel_approved_for_internal_review_use":
            if not kwargs["explicit_scope_confirmed"]:
                raise ValueError("explicit_scope_confirmation_required")
        return {
            "case_slug": slug,
            "status": "COUNSEL_SIGNOFF_DECISION_WORKFLOW_READY",
            "counsel_status": "COUNSEL_SIGNOFF_PENDING",
            "decision_records": [],
        }

    monkeypatch.setattr(legal_workbench_api, "record_decision", fake_record_decision)

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        blocked = await client.post(
            "/api/internal/legal/cases/fortress-legal-production-review/counsel-signoff-decision/decisions",
            json={
                "decision_type": "counsel_approved_for_internal_review_use",
                "decision_scope": "limited_packet",
                "explicit_scope_confirmed": False,
                "unresolved_exclusions_acknowledged": True,
                "privilege_handling_acknowledged": True,
                "no_external_submission_authority_acknowledged": True,
            },
        )
        deferred = await client.post(
            "/api/internal/legal/cases/fortress-legal-production-review/counsel-signoff-decision/decisions",
            json={
                "decision_type": "signoff_deferred",
                "decision_scope": "limited_packet",
                "explicit_scope_confirmed": False,
                "unresolved_exclusions_acknowledged": False,
                "privilege_handling_acknowledged": False,
                "no_external_submission_authority_acknowledged": False,
            },
        )

    assert blocked.status_code == 400
    assert deferred.status_code == 200
    assert deferred.json()["counsel_status"] == "COUNSEL_SIGNOFF_PENDING"


@pytest.mark.asyncio
async def test_counsel_signoff_capture_requires_explicit_scope(monkeypatch):
    def fake_capture_signoff_action(slug, **kwargs):
        assert slug == "fortress-legal-production-review"
        assert kwargs["signoff_type"] != "final_legal_conclusion"
        if not kwargs["scope_confirmed"]:
            raise ValueError("scope_confirmation_required")
        return {"case_slug": slug, "signoff_status": "OPERATOR_REVIEW_ACKNOWLEDGMENT"}

    monkeypatch.setattr(legal_workbench_api, "capture_signoff_action", fake_capture_signoff_action)

    app = FastAPI()
    app.include_router(legal_workbench_api.router, prefix="/api/internal/legal")

    async def override_current_user():
        return SimpleNamespace(id="u1", email="manager@example.test", role="manager", is_active=True)

    app.dependency_overrides[get_current_user] = override_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        blocked = await client.post(
            "/api/internal/legal/cases/fortress-legal-production-review/counsel-signoff-packet/signoff",
            json={"signoff_type": "operator_review_acknowledgment", "scope_confirmed": False},
        )
        allowed = await client.post(
            "/api/internal/legal/cases/fortress-legal-production-review/counsel-signoff-packet/signoff",
            json={"signoff_type": "operator_review_acknowledgment", "scope_confirmed": True},
        )

    assert blocked.status_code == 400
    assert allowed.status_code == 200
    assert allowed.json()["signoff_status"] == "OPERATOR_REVIEW_ACKNOWLEDGMENT"
