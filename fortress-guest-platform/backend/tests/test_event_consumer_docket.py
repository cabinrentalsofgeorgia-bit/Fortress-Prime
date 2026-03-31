"""VRS event consumer hostile-filing flow tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import run  # noqa: F401
import backend.vrs.application.event_consumer as event_consumer
from backend.vrs.domain.automations import StreamlineEventPayload


@pytest.mark.asyncio
async def test_handle_docket_updated_event_calls_fireclaw_then_threat_assessor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "motion.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    fireclaw_mock = AsyncMock(
        return_value={
            "guest": {
                "status": "success",
                "metadata": {
                    "sha256_hash": "abc123",
                    "pages": 3,
                    "file_size_bytes": 1234,
                },
                "sanitized_content": "SAFE TEXT",
            },
            "stderr": "",
        }
    )
    threat_mock = AsyncMock(
        return_value={
            "status": "success",
            "data": {
                "artifact_filename": "Legal_Threat_Assessment_SUV2026000013.json",
                "vault_path": "/mnt/fortress_nas/sectors/legal/fish-trap-suv2026000013/filings/outgoing/x.json",
            },
        }
    )
    monkeypatch.setattr(event_consumer, "_post_fireclaw_interrogate", fireclaw_mock)
    monkeypatch.setattr(event_consumer, "_post_legal_threat_assessor", threat_mock)

    event = StreamlineEventPayload(
        entity_type="legal_document",
        entity_id="motion.pdf",
        event_type="docket_updated",
        previous_state={},
        current_state={
            "case_slug": "fish-trap-suv2026000013",
            "case_number": "SUV2026000013",
            "document_path": str(pdf_path),
            "filing_name": "motion.pdf",
            "target_vault_path": "/mnt/fortress_nas/sectors/legal/fish-trap-suv2026000013/filings/outgoing",
            "persist_to_vault": True,
        },
    )

    result = await event_consumer.handle_docket_updated_event(event)

    assert fireclaw_mock.await_count == 1
    assert threat_mock.await_count == 1
    threat_payload = threat_mock.await_args.args[0]
    assert threat_payload["case_number"] == "SUV2026000013"
    assert threat_payload["document_text"] == "SAFE TEXT"
    assert threat_payload["metadata"]["sha256_hash"] == "abc123"
    assert result["paperclip"]["data"]["artifact_filename"].endswith(".json")


@pytest.mark.asyncio
async def test_process_automation_queue_shortcuts_docket_updated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = StreamlineEventPayload(
        entity_type="legal_document",
        entity_id="motion.pdf",
        event_type="docket_updated",
        previous_state={},
        current_state={
            "case_slug": "fish-trap-suv2026000013",
            "case_number": "SUV2026000013",
            "document_path": "/tmp/motion.pdf",
        },
    )

    calls = {"count": 0}

    async def fake_brpop(_key: str, timeout: int = 5):
        if calls["count"] == 0:
            calls["count"] += 1
            return ("fortress:events:streamline", event.model_dump_json())
        raise asyncio.CancelledError()

    handle_mock = AsyncMock(return_value={"status": "ok"})
    close_mock = AsyncMock(return_value=None)
    sleep_mock = AsyncMock(return_value=None)
    commit_mock = AsyncMock(return_value=None)
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    execute_mock = AsyncMock(return_value=result)
    session = AsyncMock()
    session.execute = execute_mock
    session.commit = commit_mock

    class _FakeSessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(event_consumer.redis_client, "brpop", fake_brpop)
    monkeypatch.setattr(event_consumer, "handle_docket_updated_event", handle_mock)
    monkeypatch.setattr(event_consumer, "close_bus", close_mock)
    monkeypatch.setattr(event_consumer.asyncio, "sleep", sleep_mock)
    monkeypatch.setattr(event_consumer, "AsyncSessionLocal", lambda: _FakeSessionContext())

    await event_consumer.process_automation_queue()

    assert handle_mock.await_count == 1
    assert commit_mock.await_count == 1
    assert close_mock.await_count == 1


@pytest.mark.asyncio
async def test_process_automation_queue_shortcuts_reactivation_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = StreamlineEventPayload(
        entity_type="guest",
        entity_id="11111111-1111-1111-1111-111111111111",
        event_type="reactivation_dispatched",
        previous_state={},
        current_state={
            "guest_id": "11111111-1111-1111-1111-111111111111",
            "target_score": 92,
        },
    )

    calls = {"count": 0}

    async def fake_brpop(_key: str, timeout: int = 5):
        if calls["count"] == 0:
            calls["count"] += 1
            return ("fortress:events:streamline", event.model_dump_json())
        raise asyncio.CancelledError()

    handler_mock = AsyncMock(
        return_value={"queue_entry": {"id": "queue-123"}, "workflow": "draft_reactivation_sequence"}
    )
    close_mock = AsyncMock(return_value=None)
    sleep_mock = AsyncMock(return_value=None)
    commit_mock = AsyncMock(return_value=None)
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    execute_mock = AsyncMock(return_value=result)
    session = AsyncMock()
    session.execute = execute_mock
    session.commit = commit_mock

    class _FakeSessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(event_consumer.redis_client, "brpop", fake_brpop)
    monkeypatch.setattr(event_consumer, "handle_reactivation_dispatched_event", handler_mock)
    monkeypatch.setattr(event_consumer, "close_bus", close_mock)
    monkeypatch.setattr(event_consumer.asyncio, "sleep", sleep_mock)
    monkeypatch.setattr(event_consumer, "AsyncSessionLocal", lambda: _FakeSessionContext())

    await event_consumer.process_automation_queue()

    assert handler_mock.await_count == 1
    assert commit_mock.await_count == 2
    assert close_mock.await_count == 1
