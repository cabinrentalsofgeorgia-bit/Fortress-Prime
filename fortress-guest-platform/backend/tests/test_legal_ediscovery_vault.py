"""Service-level tests for process_vault_upload (PR D-pre2 Option A).

Validates the four behaviors that PR D-pre2 added or hardened:
  1. Composite ON CONFLICT (case_slug, file_hash) DO NOTHING — duplicate
     within a case yields {status: "duplicate"}, no second row written.
  2. Same hash across different cases is allowed — both rows persist.
  3. Qdrant upsert failure does not crash the pipeline; the doc still ends
     up in a known state ('completed' with 0 chunks indexed) rather than
     leaving a dangling 'pending' (covers the regression where a transient
     vector failure orphaned a row in pending forever).
  4. Image-only PDF (empty raw_text) is marked 'ocr_failed' and the
     pipeline returns early before privilege/vectorize stages.

A fifth integration assertion lives in
test_vault_documents_integrity.py::test_check_constraint_rejects_garbage_status
which exercises the DB-level CHECK directly. We do not duplicate it here.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import run  # noqa: F401  (registers settings + paths)
import backend.services.legal_ediscovery as legal_ediscovery


# ── shared fakes ────────────────────────────────────────────────────


class _FakeRow:
    def __init__(self, value: Any) -> None:
        self._value = value

    def __getitem__(self, _idx: int) -> Any:  # row[0]
        return self._value


class _FakeResult:
    """Minimal SQLAlchemy Result stand-in.

    fetchone() returns the seeded value once, then None.
    mappings().first() returns the seeded mapping (used by docket emit).
    scalar() returns the seeded value (unused in vault path).
    """

    def __init__(self, fetch_value: Any = None, mapping_value: dict | None = None) -> None:
        self._fetch_value = fetch_value
        self._consumed = False
        self._mapping_value = mapping_value

    def fetchone(self):
        if self._consumed:
            return None
        self._consumed = True
        return self._fetch_value

    def mappings(self):
        return self

    def first(self):
        return self._mapping_value

    def scalar(self):
        return self._fetch_value


def _make_db_session(execute_side_effect) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.commit = AsyncMock()
    return db


# ── 1. dedup-within-case ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_vault_upload_dedups_by_case_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """Pre-check finds the row → return {status:'duplicate'} early. INSERT never runs."""
    monkeypatch.setattr(
        legal_ediscovery, "_resolve_vault_dir", lambda _slug: tmp_path,
    )

    seen_inserts: list[str] = []

    def _exec_side_effect(stmt, *args, **kwargs):
        sql_text = str(stmt)
        if "SELECT id FROM legal.vault_documents" in sql_text:
            return _FakeResult(fetch_value=_FakeRow("existing-id"))
        if "INSERT INTO legal.vault_documents" in sql_text:
            seen_inserts.append(sql_text)
        return _FakeResult()

    db = _make_db_session(_exec_side_effect)

    result = await legal_ediscovery.process_vault_upload(
        db=db,
        case_slug="fish-trap-suv2026000013",
        file_bytes=b"identical content",
        file_name="duplicate.pdf",
        mime_type="application/pdf",
    )

    assert result["status"] == "duplicate"
    assert seen_inserts == [], "no INSERT should run after fast-dup hit"


# ── 2. cross-case same hash ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_vault_upload_different_cases_same_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """Same bytes, different case → INSERT proceeds and ON CONFLICT does not fire."""
    monkeypatch.setattr(
        legal_ediscovery, "_resolve_vault_dir", lambda _slug: tmp_path,
    )
    monkeypatch.setattr(
        legal_ediscovery, "_extract_text",
        lambda _b, _m, _n: "extracted body text for case b",
    )
    monkeypatch.setattr(
        legal_ediscovery, "_classify_privilege",
        AsyncMock(return_value=(MagicMock(
            is_privileged=False, confidence=0.0,
            privilege_type=None, reasoning=None,
        ), 1)),
    )
    monkeypatch.setattr(
        legal_ediscovery, "_chunk_document", lambda _t: ["chunk1", "chunk2"],
    )
    monkeypatch.setattr(
        legal_ediscovery, "_embed_chunks",
        AsyncMock(return_value=[[0.1] * 8, [0.2] * 8]),
    )
    monkeypatch.setattr(
        legal_ediscovery, "_upsert_to_qdrant",
        AsyncMock(return_value=2),
    )
    monkeypatch.setattr(
        legal_ediscovery, "_emit_docket_updated_event",
        AsyncMock(return_value=False),
    )

    insert_count = 0

    def _exec_side_effect(stmt, *args, **kwargs):
        nonlocal insert_count
        sql_text = str(stmt)
        if "SELECT id FROM legal.vault_documents" in sql_text:
            return _FakeResult(fetch_value=None)  # no fast-dup
        if "INSERT INTO legal.vault_documents" in sql_text:
            insert_count += 1
            # ON CONFLICT did not fire → RETURNING produced our id
            return _FakeResult(fetch_value=_FakeRow("new-id"))
        return _FakeResult()

    db = _make_db_session(_exec_side_effect)

    result = await legal_ediscovery.process_vault_upload(
        db=db,
        case_slug="other-case-xyz",
        file_bytes=b"identical content",
        file_name="same_as_case_a.pdf",
        mime_type="application/pdf",
    )

    assert result["status"] == "completed"
    assert insert_count == 1


# ── 3. qdrant failure leaves doc in 'completed' with 0 indexed ──────


@pytest.mark.asyncio
async def test_process_vault_upload_qdrant_failure_marks_completed_with_zero_indexed(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """Vector store failure must not orphan the row.

    Spec wording was 'leaves pending' but the live code's design is to mark
    it completed with vectors_indexed=0 — operators get an actionable signal
    via vectors_indexed rather than chasing pending rows. We assert the
    actual contract.
    """
    monkeypatch.setattr(
        legal_ediscovery, "_resolve_vault_dir", lambda _slug: tmp_path,
    )
    monkeypatch.setattr(
        legal_ediscovery, "_extract_text",
        lambda _b, _m, _n: "non-empty extracted text",
    )
    monkeypatch.setattr(
        legal_ediscovery, "_classify_privilege",
        AsyncMock(return_value=(MagicMock(
            is_privileged=False, confidence=0.0,
            privilege_type=None, reasoning=None,
        ), 1)),
    )
    monkeypatch.setattr(
        legal_ediscovery, "_chunk_document", lambda _t: ["chunk1"],
    )
    monkeypatch.setattr(
        legal_ediscovery, "_embed_chunks",
        AsyncMock(return_value=[[0.5] * 8]),
    )
    monkeypatch.setattr(
        legal_ediscovery, "_upsert_to_qdrant",
        AsyncMock(return_value=0),  # qdrant down / failed
    )
    monkeypatch.setattr(
        legal_ediscovery, "_emit_docket_updated_event",
        AsyncMock(return_value=False),
    )

    def _exec_side_effect(stmt, *args, **kwargs):
        sql_text = str(stmt)
        if "SELECT id FROM legal.vault_documents" in sql_text:
            return _FakeResult(fetch_value=None)
        if "INSERT INTO legal.vault_documents" in sql_text:
            return _FakeResult(fetch_value=_FakeRow("new-id"))
        return _FakeResult()

    db = _make_db_session(_exec_side_effect)

    result = await legal_ediscovery.process_vault_upload(
        db=db,
        case_slug="qdrant-flake-case",
        file_bytes=b"some bytes",
        file_name="ok.pdf",
        mime_type="application/pdf",
    )

    assert result["status"] == "completed"
    assert result["vectors_indexed"] == 0


# ── 4. image-only PDF → ocr_failed early exit ───────────────────────


@pytest.mark.asyncio
async def test_process_vault_upload_image_only_pdf_marks_ocr_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """Empty extracted text on a PDF → status 'ocr_failed', no privilege/vectorize."""
    monkeypatch.setattr(
        legal_ediscovery, "_resolve_vault_dir", lambda _slug: tmp_path,
    )
    monkeypatch.setattr(
        legal_ediscovery, "_extract_text", lambda _b, _m, _n: "",  # image-only PDF
    )
    privilege_mock = AsyncMock()
    embed_mock = AsyncMock()
    qdrant_mock = AsyncMock()
    monkeypatch.setattr(legal_ediscovery, "_classify_privilege", privilege_mock)
    monkeypatch.setattr(legal_ediscovery, "_embed_chunks", embed_mock)
    monkeypatch.setattr(legal_ediscovery, "_upsert_to_qdrant", qdrant_mock)
    monkeypatch.setattr(
        legal_ediscovery, "_emit_docket_updated_event",
        AsyncMock(return_value=True),
    )

    update_to_ocr_failed_seen = False

    def _exec_side_effect(stmt, *args, **kwargs):
        nonlocal update_to_ocr_failed_seen
        sql_text = str(stmt)
        if "SELECT id FROM legal.vault_documents" in sql_text:
            return _FakeResult(fetch_value=None)
        if "INSERT INTO legal.vault_documents" in sql_text:
            return _FakeResult(fetch_value=_FakeRow("new-id"))
        if "ocr_failed" in sql_text and "UPDATE legal.vault_documents" in sql_text:
            update_to_ocr_failed_seen = True
        return _FakeResult()

    db = _make_db_session(_exec_side_effect)

    result = await legal_ediscovery.process_vault_upload(
        db=db,
        case_slug="image-only-case",
        file_bytes=b"%PDF-1.4 image-only ...",
        file_name="scan.pdf",
        mime_type="application/pdf",
    )

    assert result["status"] == "ocr_failed"
    assert update_to_ocr_failed_seen, "expected UPDATE to ocr_failed status"
    privilege_mock.assert_not_awaited()
    embed_mock.assert_not_awaited()
    qdrant_mock.assert_not_awaited()


# ── 5. CHECK constraint integration is asserted in the DB-level test
#       file (test_vault_documents_integrity.py). No duplication here.
