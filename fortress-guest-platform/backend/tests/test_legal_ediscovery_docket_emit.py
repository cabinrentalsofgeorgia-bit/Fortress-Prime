"""Legal e-discovery upload should emit docket_updated for new PDF filings."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import run  # noqa: F401
import backend.services.legal_ediscovery as legal_ediscovery


@pytest.mark.asyncio
async def test_emit_docket_updated_event_for_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Result:
        def mappings(self):
            return self

        def first(self):
            return {"case_number": "SUV2026000013", "status": "OPEN"}

    db = AsyncMock()
    db.execute.return_value = _Result()
    publish_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(legal_ediscovery, "publish_vrs_event", publish_mock)

    emitted = await legal_ediscovery._emit_docket_updated_event(
        db=db,
        case_slug="fish-trap-suv2026000013",
        document_id="doc-1",
        file_name="hostile_filing.pdf",
        mime_type="application/pdf",
        nfs_path="/mnt/fortress_nas/legal_vault/fish-trap-suv2026000013/doc-1_hostile_filing.pdf",
    )

    assert emitted is True
    assert publish_mock.await_count == 1
    event = publish_mock.await_args.args[0]
    assert event.event_type == "docket_updated"
    assert event.current_state["document_path"].endswith(".pdf")


@pytest.mark.asyncio
async def test_emit_docket_updated_skips_non_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    publish_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(legal_ediscovery, "publish_vrs_event", publish_mock)

    emitted = await legal_ediscovery._emit_docket_updated_event(
        db=AsyncMock(),
        case_slug="fish-trap-suv2026000013",
        document_id="doc-2",
        file_name="notes.txt",
        mime_type="text/plain",
        nfs_path="/tmp/notes.txt",
    )

    assert emitted is False
    assert publish_mock.await_count == 0
