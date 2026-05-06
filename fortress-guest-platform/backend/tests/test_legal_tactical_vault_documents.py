from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import backend.api.legal_tactical as tactical
from backend.api.legal_tactical import list_vault_documents


class _Row:
    def __init__(self, **values):
        self._mapping = values


def _patch_legacy_session(monkeypatch: pytest.MonkeyPatch, rows: list[_Row]) -> AsyncMock:
    session = AsyncMock()
    result = SimpleNamespace(fetchall=lambda: rows)
    session.execute = AsyncMock(return_value=result)

    @asynccontextmanager
    async def fake_session():
        yield session

    monkeypatch.setattr(tactical, "LegacySession", fake_session)
    return session


@pytest.mark.asyncio
async def test_list_vault_documents_reads_legacy_metadata_only(monkeypatch: pytest.MonkeyPatch):
    session = _patch_legacy_session(
        monkeypatch,
        [
            _Row(
                id="doc-1",
                file_name="completed.pdf",
                mime_type="application/pdf",
                file_size_bytes=2048,
                chunk_count=12,
                processing_status="completed",
                error_detail=None,
                created_at=datetime(2026, 5, 6, 1, 54, tzinfo=timezone.utc),
            ),
            _Row(
                id="doc-2",
                file_name="privileged.pdf",
                mime_type="application/pdf",
                file_size_bytes=1024,
                chunk_count=0,
                processing_status="locked_privileged",
                error_detail=None,
                created_at=datetime(2026, 5, 6, 1, 55, tzinfo=timezone.utc),
            ),
        ],
    )

    payload = await list_vault_documents("fortress-legal-production-review")

    assert payload["case_slug"] == "fortress-legal-production-review"
    assert payload["total"] == 2
    assert {doc["processing_status"] for doc in payload["documents"]} == {
        "completed",
        "locked_privileged",
    }
    assert all("nfs_path" not in doc for doc in payload["documents"])
    assert all("file_hash" not in doc for doc in payload["documents"])
    assert all("vector_ids" not in doc for doc in payload["documents"])
    assert all("content" not in doc for doc in payload["documents"])

    sql = str(session.execute.await_args.args[0])
    assert "FROM legal.vault_documents" in sql
    assert "nfs_path" not in sql
    assert "file_hash" not in sql
    assert "vector_ids" not in sql
    assert session.execute.await_args.args[1] == {"slug": "fortress-legal-production-review"}
