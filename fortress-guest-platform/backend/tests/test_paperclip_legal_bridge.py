"""Paperclip legal bridge contract tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import run  # noqa: F401  # Installs the runtime .pyc fallback finder used by production launch.
import backend.api.paperclip_bridge as paperclip_bridge
from backend.core.database import get_db


def build_paperclip_bridge_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(paperclip_bridge.router, prefix="/api/agent")
    return app


@pytest.fixture
def app() -> FastAPI:
    app = build_paperclip_bridge_test_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.fixture(autouse=True)
def configure_swarm_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paperclip_bridge.settings, "swarm_api_key", "test-swarm-token")
    paperclip_bridge._load_hermes_system_prompt.cache_clear()


def test_directive_payload_includes_hermes_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    contract_path = tmp_path / "AGENTS.md"
    contract_path.write_text("You are Hermes, Lead Underwriter.", encoding="utf-8")
    monkeypatch.setattr(paperclip_bridge.settings, "hermes_system_prompt_path", str(contract_path))

    payload = paperclip_bridge.PaperclipExecuteRequest.model_validate(
        {
            "runId": "run-123",
            "agentId": "agent-123",
            "companyId": "company-123",
            "wakeReason": "heartbeat",
            "context": {},
        }
    )

    directive = paperclip_bridge._directive_payload(payload)

    assert directive["context_payload"]["hermes_contract"] == {
        "source_path": str(contract_path),
        "system_prompt": "You are Hermes, Lead Underwriter.",
    }


@pytest.mark.asyncio
async def test_legal_search_bridge_returns_success_payload(app: FastAPI) -> None:
    with patch(
        "backend.api.paperclip_bridge.synthesize_historic_search",
        new=AsyncMock(
            return_value={
                "answer": "Chronology reconstructed.",
                "records_searched": 13,
                "latency_ms": 51234,
            }
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/legal-search",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "query": "Reconstruct the chronology.",
                    "case_slug": "fish-trap-suv2026000013",
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["records_searched"] == 13
    assert body["data"]["latency_ms"] == 51234


@pytest.mark.asyncio
async def test_legal_docgen_bridge_persists_case_artifact(
    app: FastAPI,
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paperclip_bridge.settings, "LEGAL_VAULT_ROOT", str(tmp_path))

    with (
        patch(
            "backend.api.paperclip_bridge._case_slug_exists",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.api.paperclip_bridge.generate_answer_and_defenses",
            return_value=b"docx-bytes",
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/legal-docgen",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "case_slug": "fish-trap-suv2026000013",
                    "case_brief": "\n".join(
                        [
                            "CASE NUMBER: SUV2026000013",
                            "PLAINTIFF: GENERALI GLOBAL ASSISTANCE, INC.",
                            "DEFENDANT: CABIN RENTALS OF GEORGIA, LLC",
                            "JUDGE: Honorable J. David Stuart",
                        ]
                    ),
                    "consensus": {
                        "consensus_signal": "DEFENSE",
                        "top_defense_arguments": ["Failure to state a claim"],
                        "top_risk_factors": [],
                    },
                    "persist_to_vault": True,
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["filename"] == "Answer_and_Defenses_SUV2026000013.docx"
    assert body["data"]["download_url"].endswith(body["data"]["stored_filename"])
    assert body["data"]["vault_path"].endswith(body["data"]["stored_filename"])
    assert body["data"]["size_bytes"] == len(b"docx-bytes")
    assert (tmp_path / "fish-trap-suv2026000013" / "filings" / "outgoing" / body["data"]["stored_filename"]).read_bytes() == b"docx-bytes"


@pytest.mark.asyncio
async def test_legal_docgen_bridge_returns_structured_error(app: FastAPI) -> None:
    with patch(
        "backend.api.paperclip_bridge.generate_answer_and_defenses",
        side_effect=RuntimeError("template exploded"),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/legal-docgen",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "case_brief": "CASE NUMBER: SUV2026000013\nPLAINTIFF: GENERALI GLOBAL ASSISTANCE, INC.",
                    "consensus": {"consensus_signal": "DEFENSE"},
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "error"
    assert "DocGen failure" in body["error_message"]


@pytest.mark.asyncio
async def test_legal_draft_answer_workflow_returns_search_consensus_and_artifact(
    app: FastAPI,
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paperclip_bridge.settings, "LEGAL_VAULT_ROOT", str(tmp_path))

    with (
        patch(
            "backend.api.paperclip_bridge._case_slug_exists",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.api.paperclip_bridge.synthesize_historic_search",
            new=AsyncMock(
                return_value={
                    "answer": "Chronology and contradictions summary.",
                    "records_searched": 13,
                    "latency_ms": 50123,
                }
            ),
        ),
        patch(
            "backend.api.paperclip_bridge.run_council_deliberation",
            new=AsyncMock(
                return_value={
                    "session_id": "session-123",
                    "consensus_signal": "DEFENSE",
                    "consensus_conviction": 0.88,
                    "top_defense_arguments": ["Privity missing"],
                    "top_risk_factors": ["Signatory unclear"],
                    "event_id": "event-123",
                    "sha256_signature": "abc123",
                }
            ),
        ),
        patch(
            "backend.api.paperclip_bridge.generate_answer_and_defenses",
            return_value=b"workflow-docx",
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/legal-draft-answer",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "case_slug": "fish-trap-suv2026000013",
                    "query": "Draft a pleading-ready answer.",
                    "case_number": "SUV2026000013",
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["workflow"] == "draft_answer_from_case_slug"
    assert body["data"]["search"]["records_searched"] == 13
    assert body["data"]["council"]["consensus_signal"] == "DEFENSE"
    assert body["data"]["artifact"]["filename"] == "Answer_and_Defenses_SUV2026000013.docx"
    assert body["data"]["artifact"]["download_url"].endswith(body["data"]["artifact"]["stored_filename"])
    assert (tmp_path / "fish-trap-suv2026000013" / "filings" / "outgoing" / body["data"]["artifact"]["stored_filename"]).read_bytes() == b"workflow-docx"


@pytest.mark.asyncio
async def test_legal_raw_evidence_ingest_bridge_returns_success_payload(app: FastAPI) -> None:
    fake_pack = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    with patch(
        "backend.api.paperclip_bridge.LegalDiscoveryEngine.ingest_raw_evidence",
        new=AsyncMock(
            return_value={
                "case_slug": "fish-trap-suv2026000013",
                "legacy_pack_id": fake_pack,
                "v2_pack_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "nodes_persisted": 2,
                "edges_persisted": 1,
                "claims_persisted": 1,
                "node_labels": ["A", "B"],
                "claims": [{"item_number": 1, "sequence_number": 1, "category": "INTERROGATORY", "preview": "x"}],
            }
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/legal-raw-evidence-ingest",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "case_slug": "fish-trap-suv2026000013",
                    "pack_id": fake_pack,
                    "payload_text": "The affiant stated the schedule was accurate.",
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["nodes_persisted"] == 2
    assert body["data"]["claims_persisted"] == 1


@pytest.mark.asyncio
async def test_legal_threat_assessor_bridge_persists_case_artifact(
    app: FastAPI,
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paperclip_bridge.settings, "LEGAL_VAULT_ROOT", str(tmp_path))

    with (
        patch(
            "backend.api.paperclip_bridge._resolve_case_slug_and_meta",
            new=AsyncMock(
                return_value={
                    "case_slug": "fish-trap-suv2026000013",
                    "case_number": "SUV2026000013",
                }
            ),
        ),
        patch(
            "backend.api.paperclip_bridge._case_slug_exists",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.api.paperclip_bridge.synthesize_historic_search",
            new=AsyncMock(
                return_value={
                    "answer": "Strategic exposure is moderate; attack standing and damages.",
                    "records_searched": 11,
                    "inference_source": "historic_search",
                    "latency_ms": 1234,
                }
            ),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/legal-threat-assessor",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "case_number": "SUV2026000013",
                    "case_slug": "fish-trap-suv2026000013",
                    "filing_name": "Opposition_Brief.pdf",
                    "document_text": "Sanitized hostile filing text.",
                    "metadata": {
                        "sha256_hash": "abc123",
                        "pages": 4,
                        "file_size_bytes": 2048,
                    },
                    "persist_to_vault": True,
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["artifact"]["metadata"]["sha256_hash"] == "abc123"
    assert body["data"]["artifact"]["threat_assessment"].startswith("Strategic exposure")
    assert body["data"]["artifact_filename"] == "Legal_Threat_Assessment_SUV2026000013.json"
    stored = tmp_path / "fish-trap-suv2026000013" / "filings" / "outgoing" / body["data"]["stored_filename"]
    assert stored.exists()


@pytest.mark.asyncio
async def test_legal_raw_evidence_ingest_bridge_rejects_bad_pack_uuid(app: FastAPI) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/agent/tools/legal-raw-evidence-ingest",
            headers={"Authorization": "Bearer test-swarm-token"},
            json={
                "case_slug": "fish-trap-suv2026000013",
                # Valid length for the field; invalid UUID characters → handler error body.
                "pack_id": "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
                "payload_text": "Some evidence text.",
            },
        )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "error"
    assert "UUID" in body["error_message"]


@pytest.mark.asyncio
async def test_legal_raw_evidence_ingest_bridge_maps_http_exception(app: FastAPI) -> None:
    from fastapi import HTTPException

    with patch(
        "backend.api.paperclip_bridge.LegalDiscoveryEngine.ingest_raw_evidence",
        new=AsyncMock(side_effect=HTTPException(status_code=422, detail="legacy_pack_id does not belong")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/legal-raw-evidence-ingest",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "case_slug": "fish-trap-suv2026000013",
                    "pack_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "payload_text": "Evidence.",
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "error"
    assert "legacy_pack_id" in body["error_message"]


@pytest.mark.asyncio
async def test_legal_deposition_outline_bridge_success_and_persists_json(
    app: FastAPI,
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paperclip_bridge.settings, "LEGAL_VAULT_ROOT", str(tmp_path))

    fake_outline = {
        "case_slug": "fish-trap-suv2026000013",
        "deponent_entity": "Jane Doe",
        "generated_at": "2026-03-29T12:00:00+00:00",
        "summary": "Test outline",
        "pressure_points": [],
        "questioning_outline": [],
        "exhibit_sequence": [],
        "council_risk_factors": [],
        "source_alert_summaries": [],
        "council_provenance": {"event_id": None, "timestamp": None, "consensus_signal": None},
        "inference_source": "mock",
        "graph_context": {
            "full_graph_node_count": 0,
            "full_graph_edge_count": 0,
            "subgraph_node_count": 0,
            "subgraph_edge_count": 0,
        },
        "metadata": {
            "ingestion_latency_ms": {},
            "ingestion_row_counts": {"deliberation_ledger_seat_opinions": None},
            "inference_latency_ms": {},
            "mode": "llm",
            "inference_source": "mock",
        },
    }

    with (
        patch(
            "backend.api.paperclip_bridge._case_slug_exists",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.api.paperclip_bridge.generate_deposition_outline",
            new=AsyncMock(return_value=fake_outline),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/legal-deposition-outline",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "case_slug": "fish-trap-suv2026000013",
                    "deponent_entity": "Jane Doe",
                    "case_number": "SUV2026000013",
                    "persist_to_vault": True,
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["artifact_filename"] == "Deposition_Outline_Jane_Doe_SUV2026000013.json"
    assert body["data"]["outline"]["summary"] == "Test outline"
    assert body["data"]["download_url"].endswith(body["data"]["stored_filename"])
    stored = tmp_path / "fish-trap-suv2026000013" / "filings" / "outgoing" / body["data"]["stored_filename"]
    assert stored.exists()
    assert b'"summary": "Test outline"' in stored.read_bytes()


@pytest.mark.asyncio
async def test_legal_deposition_outline_bridge_validation_error(app: FastAPI) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/agent/tools/legal-deposition-outline",
            headers={"Authorization": "Bearer test-swarm-token"},
            json={
                "case_slug": "fish-trap-suv2026000013",
                "deponent_entity": "",
            },
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_legal_deposition_outline_bridge_structured_error(app: FastAPI) -> None:
    with patch(
        "backend.api.paperclip_bridge.generate_deposition_outline",
        new=AsyncMock(side_effect=RuntimeError("graph exploded")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/legal-deposition-outline",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "case_slug": "fish-trap-suv2026000013",
                    "deponent_entity": "Jane Doe",
                    "persist_to_vault": False,
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "error"
    assert "Deposition outline failure" in body["error_message"]
    assert "graph exploded" in body["error_message"]


@pytest.mark.asyncio
async def test_guest_triage_bridge_returns_success_payload(app: FastAPI) -> None:
    fake_triage = {
        "workflow": "guest_comm_triage",
        "session_id": "paperclip-concierge-test",
        "guest": {"id": "g1", "full_name": "Test Guest"},
        "triage": {"consensus_signal": "RESOLVE", "escalation_level": "standard"},
        "draft_reply": {"text": "Thanks — we're on it.", "is_draft": True, "channel": "sms"},
    }
    with patch(
        "backend.api.paperclip_bridge.run_guest_triage",
        new=AsyncMock(return_value=fake_triage),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/guest-triage",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "guest_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "inbound_message": "The hot tub is not heating.",
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["session_id"] == "paperclip-concierge-test"
    assert body["data"]["draft_reply"]["is_draft"] is True


@pytest.mark.asyncio
async def test_guest_triage_bridge_maps_value_error(app: FastAPI) -> None:
    with patch(
        "backend.api.paperclip_bridge.run_guest_triage",
        new=AsyncMock(side_effect=ValueError("guest_id not found: x")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/guest-triage",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "guest_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "inbound_message": "Hello",
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "error"
    assert "guest_id not found" in body["error_message"]


@pytest.mark.asyncio
async def test_guest_triage_bridge_structured_error_on_engine_failure(app: FastAPI) -> None:
    with patch(
        "backend.api.paperclip_bridge.run_guest_triage",
        new=AsyncMock(side_effect=RuntimeError("LLM plane down")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/guest-triage",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "guest_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "inbound_message": "Hello",
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "error"
    assert "Guest triage failure" in body["error_message"]
    assert "LLM plane down" in body["error_message"]


@pytest.mark.asyncio
async def test_guest_triage_bridge_validation_requires_inbound_without_message_id(app: FastAPI) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/agent/tools/guest-triage",
            headers={"Authorization": "Bearer test-swarm-token"},
            json={
                "guest_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            },
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_guest_resolve_conflict_bridge_returns_success_payload(app: FastAPI) -> None:
    fake_resolution = {
        "workflow": "guest_conflict_resolution",
        "session_id": "paperclip-conflict-test",
        "guest": {"id": "g1", "full_name": "Test Guest"},
        "conflict_resolution": {
            "complaint_legitimacy": "likely_legitimate_failure",
            "corrective_scheduling": "schedule_or_confirm_corrective_visit",
            "consensus_signal": "CAUTION",
        },
        "audit_log": {"status": "persisted", "table": "core.deliberation_logs"},
    }
    with patch(
        "backend.api.paperclip_bridge.run_guest_resolve_conflict",
        new=AsyncMock(return_value=fake_resolution),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/guest-resolve-conflict",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "guest_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "inbound_message": "The Wi-Fi still isn't working and I want a refund.",
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["workflow"] == "guest_conflict_resolution"
    assert body["data"]["audit_log"]["status"] == "persisted"


@pytest.mark.asyncio
async def test_guest_resolve_conflict_bridge_maps_value_error(app: FastAPI) -> None:
    with patch(
        "backend.api.paperclip_bridge.run_guest_resolve_conflict",
        new=AsyncMock(side_effect=ValueError("message_id not found: x")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/guest-resolve-conflict",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "guest_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "inbound_message": "Refund me.",
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "error"
    assert "message_id not found" in body["error_message"]


@pytest.mark.asyncio
async def test_guest_resolve_conflict_bridge_structured_error_on_engine_failure(app: FastAPI) -> None:
    with patch(
        "backend.api.paperclip_bridge.run_guest_resolve_conflict",
        new=AsyncMock(side_effect=RuntimeError("field reality fetch failed")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/guest-resolve-conflict",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "guest_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "inbound_message": "Dirty cabin, refund now.",
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "error"
    assert "Guest conflict resolution failure" in body["error_message"]
    assert "field reality fetch failed" in body["error_message"]


@pytest.mark.asyncio
async def test_guest_resolve_conflict_bridge_validation_requires_anchor(app: FastAPI) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/agent/tools/guest-resolve-conflict",
            headers={"Authorization": "Bearer test-swarm-token"},
            json={"inbound_message": "Broken hot tub."},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_guest_send_sms_bridge_returns_success_payload(app: FastAPI) -> None:
    fake_send = {
        "workflow": "guest_send_sms",
        "dispatched": True,
        "delivery": {
            "message_id": "m1",
            "external_id": "SM123",
            "status": "sent",
            "phone_to": "+17065551212",
        },
        "audit_log": {"status": "persisted", "table": "core.deliberation_logs", "id": "log1"},
    }
    with patch(
        "backend.api.paperclip_bridge.run_guest_send_sms",
        new=AsyncMock(return_value=fake_send),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/guest-send-sms",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "guest_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "body": "We verified the issue and are following up now.",
                    "consensus_conviction": 0.91,
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["workflow"] == "guest_send_sms"
    assert body["data"]["delivery"]["status"] == "sent"


@pytest.mark.asyncio
async def test_guest_send_sms_bridge_maps_threshold_rejection(app: FastAPI) -> None:
    with patch(
        "backend.api.paperclip_bridge.run_guest_send_sms",
        new=AsyncMock(side_effect=ValueError("Consensus conviction 0.6200 is below send threshold 0.8000.")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/guest-send-sms",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "guest_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "body": "Draft reply.",
                    "consensus_conviction": 0.62,
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "error"
    assert "below send threshold" in body["error_message"]


@pytest.mark.asyncio
async def test_guest_send_sms_bridge_validation_requires_anchor(app: FastAPI) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/agent/tools/guest-send-sms",
            headers={"Authorization": "Bearer test-swarm-token"},
            json={
                "body": "Draft reply.",
                "consensus_conviction": 0.91,
            },
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_draft_reactivation_sequence_bridge_returns_success_payload(app: FastAPI) -> None:
    with patch(
        "backend.api.paperclip_bridge.draft_reactivation_sequence",
        new=AsyncMock(
            return_value={
                "workflow": "draft_reactivation_sequence",
                "queue_entry": {"id": "queue-123", "status": "pending_review"},
                "draft_reply": {"text": "We would love to welcome you back.", "is_draft": True},
            }
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/draft-reactivation-sequence",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "guest_id": "11111111-1111-1111-1111-111111111111",
                    "target_score": 93,
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["workflow"] == "draft_reactivation_sequence"
    assert body["data"]["queue_entry"]["id"] == "queue-123"


@pytest.mark.asyncio
async def test_acquisition_score_viability_bridge_returns_success_payload(app: FastAPI) -> None:
    with patch(
        "backend.api.paperclip_bridge.score_acquisition_property",
        new=AsyncMock(
            return_value={
                "property": {"property_id": "11111111-1111-1111-1111-111111111111"},
                "viability_score": 0.82,
                "score_components": {"market_control": 0.22},
                "recommended_action": "advance_to_target_locked",
            }
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/acquisition-score-viability",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={"property_id": "11111111-1111-1111-1111-111111111111"},
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["viability_score"] == 0.82
    assert body["data"]["recommended_action"] == "advance_to_target_locked"


@pytest.mark.asyncio
async def test_acquisition_read_candidates_bridge_returns_typed_payload(app: FastAPI) -> None:
    with patch(
        "backend.api.paperclip_bridge.list_acquisition_candidates",
        new=AsyncMock(
            return_value=[
                paperclip_bridge.AcquisitionCandidateSchema.model_validate(
                    {
                        "property_id": "11111111-1111-1111-1111-111111111111",
                        "status": "UNMANAGED",
                        "management_company": None,
                        "bedrooms": 4,
                        "bathrooms": 3.5,
                        "projected_adr": 425.0,
                        "projected_annual_revenue": 155000.0,
                        "parcel": {
                            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                            "parcel_id": "FANNIN-001",
                            "county_name": "Fannin",
                            "assessed_value": 640000.0,
                            "zoning_code": "R-1",
                            "is_waterfront": False,
                            "is_ridgeline": True,
                        },
                        "owner": {
                            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                            "legal_name": "Jane Owner",
                            "tax_mailing_address": "123 Ridge Line Rd",
                            "primary_residence_state": "GA",
                            "psychological_profile": {"angle": "asset stewardship"},
                            "contacts": [
                                {
                                    "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                                    "contact_type": "EMAIL",
                                    "contact_value": "jane@example.com",
                                    "source": "skiptrace",
                                    "confidence_score": 0.91,
                                    "is_dnc": False,
                                }
                            ],
                        },
                        "pipeline": {
                            "id": None,
                            "stage": None,
                            "llm_viability_score": None,
                            "next_action_date": None,
                            "rejection_reason": None,
                        },
                        "recent_intel_events": [
                            {
                                "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                                "event_type": "STR_REGISTRY_SYNC",
                                "event_description": "Fresh STR registry observation.",
                                "raw_source_data": {"source": "firecrawl"},
                                "detected_at": "2026-03-30T17:00:00Z",
                            }
                        ],
                        "recent_str_signals": [],
                        "score_viability_input": {
                            "property_id": "11111111-1111-1111-1111-111111111111",
                        },
                    }
                )
            ]
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/acquisition-read-candidates",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={"limit": 5},
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"][0]["property_id"] == "11111111-1111-1111-1111-111111111111"
    assert body["data"][0]["score_viability_input"]["property_id"] == "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_hermes_underwriter_heartbeat_processes_candidates() -> None:
    db = AsyncMock()
    candidate = paperclip_bridge.AcquisitionCandidateSchema.model_validate(
        {
            "property_id": "11111111-1111-1111-1111-111111111111",
            "status": "UNMANAGED",
            "management_company": None,
            "bedrooms": None,
            "bathrooms": None,
            "projected_adr": None,
            "projected_annual_revenue": None,
            "parcel": {
                "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "parcel_id": "FANNIN-001",
                "county_name": "Fannin",
                "assessed_value": 371460.0,
                "zoning_code": "R4",
                "is_waterfront": False,
                "is_ridgeline": False,
            },
            "owner": {
                "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "legal_name": "Jane Owner",
                "tax_mailing_address": "123 Main St",
                "primary_residence_state": "GA",
                "psychological_profile": {"angle": "Property Pride"},
                "contacts": [],
            },
            "pipeline": {
                "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "stage": "RADAR",
                "llm_viability_score": None,
                "next_action_date": None,
                "rejection_reason": None,
            },
            "recent_intel_events": [],
                "recent_str_signals": [],
            "score_viability_input": {
                "property_id": "11111111-1111-1111-1111-111111111111",
            },
        }
    )
    payload = paperclip_bridge.PaperclipExecuteRequest.model_validate(
        {
            "runId": "run-123",
            "agentId": "agent-123",
            "companyId": "company-123",
            "wakeReason": "paperclip_heartbeat",
            "context": {},
        }
    )

    with (
        patch(
            "backend.api.paperclip_bridge.list_acquisition_candidates",
            new=AsyncMock(return_value=[candidate]),
        ),
        patch(
            "backend.api.paperclip_bridge.enrich_owner_contacts_from_internal_registry",
            new=AsyncMock(
                return_value={
                    "owner_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "legal_name": "Jane Owner",
                    "matched_registry_rows": 0,
                    "apollo_match_count": 0,
                    "b2c_provider_name": "strict_mock_b2c_provider",
                    "b2c_provider_match_count": 2,
                    "b2c_provider_error": None,
                    "external_results_considered": 0,
                    "external_lookup_error": None,
                    "added_contacts": [
                        {
                            "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                            "contact_type": "CELL",
                            "contact_value": "+15550109999",
                            "source": "strict_mock_b2c_provider",
                            "confidence_score": 0.99,
                            "is_dnc": False,
                        }
                    ],
                    "linked_property_id": "11111111-1111-1111-1111-111111111111",
                }
            ),
        ) as contact_enrichment,
        patch(
            "backend.api.paperclip_bridge.score_acquisition_property",
            new=AsyncMock(
                return_value={
                    "viability_score": 0.70,
                    "score_components": {"market_control": 0.22},
                    "recommended_action": "advance_to_target_locked",
                }
            ),
        ),
        patch(
            "backend.api.paperclip_bridge.append_acquisition_intel_event",
            new=AsyncMock(return_value={"id": "event-123"}),
        ),
        patch(
            "backend.api.paperclip_bridge.advance_acquisition_pipeline",
            new=AsyncMock(
                return_value={
                    "stage": "TARGET_LOCKED",
                    "llm_viability_score": 0.70,
                    "next_action_date": "2026-04-02",
                }
            ),
        ),
    ):
        result = await paperclip_bridge._run_hermes_underwriter_heartbeat(db, payload)

    assert result.status == "succeeded"
    assert result.result_payload["workflow"] == "hermes_underwriter_heartbeat"
    assert result.result_payload["processed_count"] == 1
    assert result.result_payload["processed"][0]["event_id"] == "event-123"
    assert result.result_payload["processed"][0]["contact_enrichment"]["b2c_provider_name"] == "strict_mock_b2c_provider"
    assert result.result_payload["processed"][0]["stage"] == "TARGET_LOCKED"
    contact_enrichment.assert_awaited_once()
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_acquisition_enrich_owner_psychology_bridge_returns_success_payload(app: FastAPI) -> None:
    with patch(
        "backend.api.paperclip_bridge.enrich_owner_psychology",
        new=AsyncMock(
            return_value={
                "owner_id": "22222222-2222-2222-2222-222222222222",
                "legal_name": "Jane Owner",
                "psychological_profile": {"angle": "Property Pride"},
                "linked_property_id": "11111111-1111-1111-1111-111111111111",
            }
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/acquisition-enrich-owner-psychology",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "owner_id": "22222222-2222-2222-2222-222222222222",
                    "property_id": "11111111-1111-1111-1111-111111111111",
                    "profile_patch": {"angle": "Property Pride"},
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["psychological_profile"]["angle"] == "Property Pride"


@pytest.mark.asyncio
async def test_acquisition_enrich_owner_contacts_bridge_returns_success_payload(app: FastAPI) -> None:
    with patch(
        "backend.api.paperclip_bridge.enrich_owner_contacts_from_internal_registry",
        new=AsyncMock(
            return_value={
                "owner_id": "22222222-2222-2222-2222-222222222222",
                "legal_name": "Jane Owner",
                "matched_registry_rows": 1,
                "apollo_match_count": 0,
                "b2c_provider_name": "strict_mock_b2c_provider",
                "b2c_provider_match_count": 0,
                "b2c_provider_error": None,
                "external_results_considered": 0,
                "external_lookup_error": None,
                "added_contacts": [
                    {
                        "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                        "contact_type": "EMAIL",
                        "contact_value": "owner@example.com",
                        "source": "owner_property_map",
                        "confidence_score": 0.95,
                        "is_dnc": False,
                    }
                ],
                "linked_property_id": "11111111-1111-1111-1111-111111111111",
            }
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/acquisition-enrich-owner-contacts",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "owner_id": "22222222-2222-2222-2222-222222222222",
                    "property_id": "11111111-1111-1111-1111-111111111111",
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["matched_registry_rows"] == 1
    assert body["data"]["added_contacts"][0]["contact_value"] == "owner@example.com"


@pytest.mark.asyncio
async def test_acquisition_draft_outreach_sequence_bridge_returns_success_payload(app: FastAPI) -> None:
    with patch(
        "backend.api.paperclip_bridge.draft_acquisition_outreach_sequence",
        new=AsyncMock(
            return_value={
                "recommended_channel": "EMAIL",
                "angle": "owner legacy",
                "candidate_contacts": [{"contact_type": "EMAIL", "contact_value": "owner@example.com"}],
                "drafts": {"email_subject": "Idea for parcel", "sms_body": "Quick summary available."},
            }
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/acquisition-draft-outreach-sequence",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={"property_id": "11111111-1111-1111-1111-111111111111"},
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["recommended_channel"] == "EMAIL"
    assert body["data"]["drafts"]["email_subject"] == "Idea for parcel"


@pytest.mark.asyncio
async def test_acquisition_run_ingestion_bridge_returns_queued_job(app: FastAPI) -> None:
    fake_redis = SimpleNamespace(aclose=AsyncMock())
    fake_job = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333",
        job_name="acquisition_ingestion_cycle",
        queue_name="fortress:arq",
        status="queued",
        requested_by="paperclip_bridge",
        tenant_id=None,
        request_id="paperclip-acquisition-test",
        arq_job_id="33333333-3333-3333-3333-333333333333",
        attempts=0,
        payload_json={"county_name": "Fannin"},
        result_json={},
        error_text=None,
        created_at=None,
        started_at=None,
        finished_at=None,
        updated_at=None,
    )
    with (
        patch(
            "backend.api.paperclip_bridge._create_arq_pool",
            new=AsyncMock(return_value=fake_redis),
        ),
        patch(
            "backend.api.paperclip_bridge._enqueue_async_job",
            new=AsyncMock(return_value=fake_job),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/tools/acquisition-run-ingestion",
                headers={"Authorization": "Bearer test-swarm-token"},
                json={
                    "county_name": "Fannin",
                    "qpublic_url": "https://example.com/qpublic",
                    "dry_run": True,
                },
            )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["data"]["queued"] is True
    assert body["data"]["job"]["job_name"] == "acquisition_ingestion_cycle"
