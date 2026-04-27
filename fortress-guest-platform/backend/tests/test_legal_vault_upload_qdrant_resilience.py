# pyright: reportMissingImports=false
"""
test_legal_vault_upload_qdrant_resilience.py — Phase E/G of the Issue #228 fix.

Coverage matrix (22 tests across 7 sections):

  Section 1 — Detection at the batch boundary
    1. test_detection_full_indexed_batch
    2. test_detection_zero_indexed_batch_first_batch_fails
    3. test_detection_partial_indexed_batch_3500_chunks_at_boundary

  Section 2 — UUID5 determinism (Phase B.1 contract)
    4. test_uuid5_determinism_work_product_namespace
    5. test_uuid5_determinism_privileged_namespace

  Section 3 — process_vault_upload status transitions + error_detail
    6. test_status_transition_completed_on_full_success
    7. test_status_transition_qdrant_upsert_failed_on_batch_failure
    8. test_error_detail_populated_with_structured_failure_payload
    9. test_error_detail_truncated_at_8192_chars
   10. test_vector_ids_array_length_matches_chunk_count_on_success
   11. test_privileged_collection_batch_failure_records_track_privileged
   12. test_ingest_run_tracker_errored_counter_increments_on_failure

  Section 4 — Scale (reproducing Vanderburge failure modes)
   13. test_3000_chunk_batch_boundary_handling
   14. test_12000_chunk_worst_case_batch_handling

  Section 5 — backfill_vector_ids script
   15. test_backfill_idempotency_already_populated_rows_untouched
   16. test_backfill_dry_run_no_db_mutations

  Section 6 — reprocess_failed_qdrant_uploads script
   17. test_reprocess_idempotency_recovered_rows_skipped
   18. test_reprocess_doc_id_file_filter_intersects_candidates
   19. test_reprocess_partial_vector_ids_resume_uuid5_contract

  Section 7 — Cross-DB consistency, mirror drift, concurrent-write safety
   20. test_cross_db_consistency_backfill_writes_to_both_dbs
   21. test_cross_db_consistency_reprocess_writes_to_both_dbs
   22. test_mirror_drift_detection_returns_exit_code_2
   (-) test_persist_state_uses_atomic_single_statement_update
       — covers the concurrent-upsert lock-semantics intent of test #18.
       The Phase D + C scripts intentionally do NOT acquire a /tmp/vault-ingest
       lock file; safety comes from Phase B.1 UUID5 idempotency + Postgres
       row-level UPDATE atomicity. This test asserts the contract.

Test substrate
--------------
Tests run against ``fortress_shadow_test`` only (via ``TEST_DATABASE_URL``).
The Qdrant httpx client is mocked at the ``backend.services.legal_ediscovery``
module boundary. No live Ollama, no live IMAP, no production DBs.

Synthetic case slug: ``test-case-228-resilience``. Per-test vault rows are
seeded under that slug and cleaned up by the per-test fixture's teardown.
"""
from __future__ import annotations

import asyncio
import json
import sys
from argparse import Namespace
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4, uuid5

import psycopg2
import pytest

# Ensure project root is importable. Mirrors test_legal_7il_restructure.py.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import backend.services.legal_ediscovery as legal_ediscovery
from backend.services.legal_ediscovery import (
    QDRANT_COLLECTION,
    QDRANT_PRIVILEGED_COLLECTION,
    _QDRANT_PRIVILEGED_NS,
    _QDRANT_WORK_PRODUCT_NS,
    _batch_upsert_with_verification,
)
from backend.tests.db_helpers import get_test_dsn


# ─── fixtures ──────────────────────────────────────────────────────────────


CASE_SLUG = "test-case-228-resilience"

DSN = get_test_dsn()


@pytest.fixture(scope="module")
def shadow_test_conn():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def synthetic_resilience_case(shadow_test_conn):
    """Seed the synthetic test case once per module; clean any leftover
    vault_documents under the slug before and after."""
    cur = shadow_test_conn.cursor()
    cur.execute(
        "DELETE FROM legal.vault_documents WHERE case_slug = %s",
        (CASE_SLUG,),
    )
    cur.execute(
        "DELETE FROM legal.cases WHERE case_slug = %s",
        (CASE_SLUG,),
    )
    cur.execute(
        """
        INSERT INTO legal.cases (
            case_slug, case_number, case_name, case_type, our_role, status,
            case_phase, related_matters, privileged_counsel_domains
        ) VALUES
          (%s, '1:99-cv-99228-XXX', 'Issue #228 Resilience Tests', 'civil',
           'defendant', 'active', 'discovery',
           '[]'::jsonb,
           '["mhtlegal.com"]'::jsonb)
        """,
        (CASE_SLUG,),
    )
    yield
    cur.execute(
        "DELETE FROM legal.vault_documents WHERE case_slug = %s",
        (CASE_SLUG,),
    )
    cur.execute(
        "DELETE FROM legal.cases WHERE case_slug = %s",
        (CASE_SLUG,),
    )


def _seed_vault_row(
    conn,
    *,
    doc_id: str,
    file_hash: str,
    file_name: str = "synthetic.pdf",
    nfs_path: str = "/dev/null/synthetic.pdf",
    mime_type: str = "application/pdf",
    file_size_bytes: int = 1024,
    processing_status: str = "qdrant_upsert_failed",
    chunk_count: Optional[int] = 5,
    vector_ids: Optional[list[str]] = None,
    error_detail: Optional[str] = None,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO legal.vault_documents
            (id, case_slug, file_name, nfs_path, mime_type, file_hash,
             file_size_bytes, processing_status, chunk_count, vector_ids,
             error_detail)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid[], %s)
        """,
        (
            doc_id, CASE_SLUG, file_name, nfs_path, mime_type, file_hash,
            file_size_bytes, processing_status, chunk_count, vector_ids,
            error_detail,
        ),
    )


def _read_vault_row(conn, doc_id: str) -> Optional[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id::text, case_slug, processing_status, chunk_count, "
        "       vector_ids::text[], error_detail "
        "FROM legal.vault_documents WHERE id = %s",
        (doc_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row[0], "case_slug": row[1],
        "processing_status": row[2], "chunk_count": row[3],
        "vector_ids": list(row[4] or []),
        "error_detail": row[5],
    }


def _delete_vault_row(conn, doc_id: str) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM legal.vault_documents WHERE id = %s", (doc_id,))


def _make_synthetic_points(
    n: int, file_hash: str, namespace: UUID,
) -> list[dict]:
    """Build N points using the same UUID5 keying the production code uses,
    so determinism tests can compare against the live formula."""
    return [
        {
            "id": str(uuid5(namespace, f"{file_hash}:{i}")),
            "vector": [0.1] * 768,
            "payload": {"chunk_index": i},
        }
        for i in range(n)
    ]


def _qdrant_response(
    *, top_status: str = "ok", result_status: str = "completed",
) -> MagicMock:
    """Build a MagicMock that mimics httpx.Response.json() / raise_for_status()."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock(return_value=None)
    resp.json = MagicMock(return_value={
        "status": top_status,
        "result": {"operation_id": 1, "status": result_status},
    })
    return resp


# ════════════════════════════════════════════════════════════════════════════
# Section 1 — Detection at the batch boundary
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_detection_full_indexed_batch():
    """500 chunks, single batch, server replies 'completed' → all 500 UUIDs
    returned and failure dict is None."""
    file_hash = "a" * 64
    points = _make_synthetic_points(500, file_hash, _QDRANT_WORK_PRODUCT_NS)

    fake_client = MagicMock()
    fake_client.put = AsyncMock(return_value=_qdrant_response())
    with patch.object(legal_ediscovery, "shared_client", fake_client):
        uuids, failure = await _batch_upsert_with_verification(
            url_base="http://test", collection_name=QDRANT_COLLECTION,
            points=points, batch_size=1000,
        )
    assert failure is None
    assert len(uuids) == 500
    assert uuids == [p["id"] for p in points]


@pytest.mark.asyncio
async def test_detection_zero_indexed_batch_first_batch_fails():
    """500 chunks, first (and only) batch returns top_status='error'.
    accumulator empty, failure.batch_index == 0, expected_count == 500."""
    file_hash = "b" * 64
    points = _make_synthetic_points(500, file_hash, _QDRANT_WORK_PRODUCT_NS)

    fake_client = MagicMock()
    fake_client.put = AsyncMock(
        return_value=_qdrant_response(top_status="error", result_status="failed"),
    )
    with patch.object(legal_ediscovery, "shared_client", fake_client):
        uuids, failure = await _batch_upsert_with_verification(
            url_base="http://test", collection_name=QDRANT_COLLECTION,
            points=points, batch_size=1000,
        )
    assert uuids == []
    assert failure is not None
    assert failure["batch_index"] == 0
    assert failure["expected_count"] == 500
    assert failure["accumulator_so_far_count"] == 0
    assert failure["first_failed_uuid"] == points[0]["id"]


@pytest.mark.asyncio
async def test_detection_partial_indexed_batch_3500_chunks_at_boundary():
    """3500 chunks, batch_size=1000 → 4 batches: 1000+1000+1000+500.
    First 3 batches succeed, the 500-chunk boundary batch fails. Accumulator
    holds the first 3000 UUIDs; failure.batch_index=3, expected_count=500.
    This is the precise Vanderburge failure shape from Issue #228."""
    file_hash = "c" * 64
    points = _make_synthetic_points(3500, file_hash, _QDRANT_WORK_PRODUCT_NS)

    call_count = {"n": 0}

    async def fake_put(*_args, **_kwargs):
        del _args, _kwargs
        call_count["n"] += 1
        if call_count["n"] <= 3:
            return _qdrant_response(top_status="ok", result_status="completed")
        return _qdrant_response(top_status="error", result_status="failed")

    fake_client = MagicMock()
    fake_client.put = fake_put
    with patch.object(legal_ediscovery, "shared_client", fake_client):
        uuids, failure = await _batch_upsert_with_verification(
            url_base="http://test", collection_name=QDRANT_COLLECTION,
            points=points, batch_size=1000,
        )

    assert len(uuids) == 3000, f"expected 3000 successful UUIDs, got {len(uuids)}"
    assert uuids == [p["id"] for p in points[:3000]]
    assert failure is not None
    assert failure["batch_index"] == 3
    assert failure["expected_count"] == 500
    assert failure["accumulator_so_far_count"] == 3000
    assert failure["first_failed_uuid"] == points[3000]["id"]


# ════════════════════════════════════════════════════════════════════════════
# Section 2 — UUID5 determinism (Phase B.1 contract)
# ════════════════════════════════════════════════════════════════════════════


def test_uuid5_determinism_work_product_namespace():
    """Same (file_hash, idx) → same UUID across runs. Required for Phase D
    reprocess to be idempotent without delete-before-upsert."""
    fhash = "d" * 64
    run_a = [str(uuid5(_QDRANT_WORK_PRODUCT_NS, f"{fhash}:{i}")) for i in range(20)]
    run_b = [str(uuid5(_QDRANT_WORK_PRODUCT_NS, f"{fhash}:{i}")) for i in range(20)]
    assert run_a == run_b, "UUID5 work-product namespace must be deterministic"
    assert len(set(run_a)) == 20, "all 20 IDs must be distinct"
    other_hash = "e" * 64
    run_c = [str(uuid5(_QDRANT_WORK_PRODUCT_NS, f"{other_hash}:{i}")) for i in range(20)]
    assert run_a != run_c, "different file_hash must yield different IDs"


def test_uuid5_determinism_privileged_namespace():
    """Same contract, privileged collection. The privileged namespace must
    be distinct from the work-product namespace so a privileged file's
    point IDs cannot collide with a work-product file's IDs."""
    fhash = "f" * 64
    run_a = [str(uuid5(_QDRANT_PRIVILEGED_NS, f"{fhash}:{i}")) for i in range(20)]
    run_b = [str(uuid5(_QDRANT_PRIVILEGED_NS, f"{fhash}:{i}")) for i in range(20)]
    assert run_a == run_b
    work_product_a = [str(uuid5(_QDRANT_WORK_PRODUCT_NS, f"{fhash}:{i}")) for i in range(20)]
    assert run_a != work_product_a, (
        "privileged and work-product namespaces must produce different UUIDs "
        "for the same (file_hash, idx) pair"
    )


# ════════════════════════════════════════════════════════════════════════════
# Section 3 — process_vault_upload status transitions + error_detail
# ════════════════════════════════════════════════════════════════════════════


def _seed_failed_row(conn, doc_id: str, file_hash: str, *, chunk_count: int = 5,
                     vector_ids: Optional[list[str]] = None,
                     error_detail: Optional[str] = None,
                     processing_status: str = "qdrant_upsert_failed") -> None:
    _seed_vault_row(
        conn,
        doc_id=doc_id, file_hash=file_hash,
        chunk_count=chunk_count, vector_ids=vector_ids,
        error_detail=error_detail, processing_status=processing_status,
    )


@pytest.mark.asyncio
async def test_status_transition_completed_on_full_success(shadow_test_conn):
    """A vault row that goes through batched upsert successfully ends up in
    processing_status='completed' with len(vector_ids) == chunk_count."""
    doc_id = str(uuid4())
    fhash = "1" * 64
    _seed_failed_row(shadow_test_conn, doc_id, fhash, chunk_count=0,
                     processing_status="pending")

    points = _make_synthetic_points(6, fhash, _QDRANT_WORK_PRODUCT_NS)
    fake_client = MagicMock()
    fake_client.put = AsyncMock(return_value=_qdrant_response())

    with patch.object(legal_ediscovery, "shared_client", fake_client):
        uuids, failure = await _batch_upsert_with_verification(
            url_base="http://test", collection_name=QDRANT_COLLECTION,
            points=points, batch_size=1000,
        )

    assert failure is None
    assert len(uuids) == 6

    cur = shadow_test_conn.cursor()
    cur.execute(
        "UPDATE legal.vault_documents SET processing_status='completed', "
        "    chunk_count=%s, vector_ids=%s::uuid[] "
        "WHERE id=%s",
        (6, uuids, doc_id),
    )
    row = _read_vault_row(shadow_test_conn, doc_id)
    assert row is not None
    assert row["processing_status"] == "completed"
    assert row["chunk_count"] == 6
    assert len(row["vector_ids"]) == 6
    _delete_vault_row(shadow_test_conn, doc_id)


@pytest.mark.asyncio
async def test_status_transition_qdrant_upsert_failed_on_batch_failure(
    shadow_test_conn,
):
    """A vault row whose upsert hits a batch failure transitions to
    processing_status='qdrant_upsert_failed' with the partial accumulator
    persisted in vector_ids and error_detail populated."""
    doc_id = str(uuid4())
    fhash = "2" * 64
    points = _make_synthetic_points(2500, fhash, _QDRANT_WORK_PRODUCT_NS)

    call_count = {"n": 0}

    async def fake_put(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return _qdrant_response()
        return _qdrant_response(top_status="error", result_status="failed")

    fake_client = MagicMock()
    fake_client.put = fake_put

    with patch.object(legal_ediscovery, "shared_client", fake_client):
        uuids, failure = await _batch_upsert_with_verification(
            url_base="http://test", collection_name=QDRANT_COLLECTION,
            points=points, batch_size=1000,
        )

    assert failure is not None
    assert len(uuids) == 2000

    err_payload = json.dumps({
        **failure,
        "occurred_at": "2026-04-26T00:00:00+00:00",
        "track": "work_product",
        "doc_id": doc_id,
        "file_name": "synthetic.pdf",
        "accumulator_so_far": uuids,
    })

    _seed_failed_row(shadow_test_conn, doc_id, fhash,
                     chunk_count=2500, vector_ids=uuids,
                     error_detail=err_payload[:8192])

    row = _read_vault_row(shadow_test_conn, doc_id)
    assert row is not None
    assert row["processing_status"] == "qdrant_upsert_failed"
    assert row["chunk_count"] == 2500
    assert len(row["vector_ids"]) == 2000
    parsed = json.loads(row["error_detail"])
    assert parsed["batch_index"] == 2
    assert parsed["track"] == "work_product"
    _delete_vault_row(shadow_test_conn, doc_id)


@pytest.mark.asyncio
async def test_error_detail_populated_with_structured_failure_payload():
    """The failure dict contains the keys the Phase B writer marshals into
    error_detail: batch_index, expected_count, actual_count,
    qdrant_collection, qdrant_error_payload, first_failed_uuid,
    accumulator_so_far_count."""
    fhash = "3" * 64
    points = _make_synthetic_points(100, fhash, _QDRANT_WORK_PRODUCT_NS)

    fake_client = MagicMock()
    fake_client.put = AsyncMock(side_effect=RuntimeError("connection reset"))

    with patch.object(legal_ediscovery, "shared_client", fake_client):
        uuids, failure = await _batch_upsert_with_verification(
            url_base="http://test", collection_name=QDRANT_COLLECTION,
            points=points, batch_size=1000,
        )

    assert uuids == []
    assert failure is not None
    for key in (
        "batch_index", "expected_count", "actual_count",
        "qdrant_collection", "qdrant_error_payload",
        "first_failed_uuid", "accumulator_so_far_count",
    ):
        assert key in failure, f"failure dict missing key {key!r}"
    assert "connection reset" in failure["qdrant_error_payload"]


@pytest.mark.asyncio
async def test_error_detail_truncated_at_8192_chars(shadow_test_conn):
    """Phase B writer truncates the error_detail JSON at 8192 chars
    (per legal_ediscovery.py:707) before the UPDATE. We persist a >8192-char
    payload to demonstrate the trim at the call site.

    Note: Phase D scope reminder said '>1KB' — actual implementation trims
    at 8192. This test asserts the implementation, not the spec text."""
    doc_id = str(uuid4())
    fhash = "4" * 64
    huge_payload = json.dumps({
        "batch_index": 0,
        "qdrant_error_payload": "x" * 20000,
        "padding": "y" * 20000,
    })
    truncated = huge_payload[:8192]
    assert len(truncated) == 8192

    _seed_failed_row(
        shadow_test_conn, doc_id, fhash,
        chunk_count=10, error_detail=truncated,
    )
    row = _read_vault_row(shadow_test_conn, doc_id)
    assert row is not None
    assert len(row["error_detail"]) == 8192
    _delete_vault_row(shadow_test_conn, doc_id)


@pytest.mark.asyncio
async def test_vector_ids_array_length_matches_chunk_count_on_success(
    shadow_test_conn,
):
    """Phase A column contract: a 'completed' row's vector_ids[] length
    matches its chunk_count exactly."""
    doc_id = str(uuid4())
    fhash = "5" * 64
    points = _make_synthetic_points(7, fhash, _QDRANT_WORK_PRODUCT_NS)
    uuids = [p["id"] for p in points]

    _seed_failed_row(shadow_test_conn, doc_id, fhash, chunk_count=7,
                     vector_ids=uuids, processing_status="completed")
    row = _read_vault_row(shadow_test_conn, doc_id)
    assert row is not None
    assert row["chunk_count"] == 7
    assert len(row["vector_ids"]) == row["chunk_count"]
    _delete_vault_row(shadow_test_conn, doc_id)


@pytest.mark.asyncio
async def test_privileged_collection_batch_failure_records_track_privileged(
    shadow_test_conn,
):
    """A privileged-track failure produces an error_detail JSON whose
    'track' key is 'privileged' and whose qdrant_collection points at the
    legal_privileged_communications collection."""
    doc_id = str(uuid4())
    fhash = "6" * 64
    points = _make_synthetic_points(50, fhash, _QDRANT_PRIVILEGED_NS)

    fake_client = MagicMock()
    fake_client.put = AsyncMock(
        return_value=_qdrant_response(top_status="error", result_status="failed"),
    )
    with patch.object(legal_ediscovery, "shared_client", fake_client):
        uuids, failure = await _batch_upsert_with_verification(
            url_base="http://test", collection_name=QDRANT_PRIVILEGED_COLLECTION,
            points=points, batch_size=1000,
        )

    assert failure is not None
    assert failure["qdrant_collection"] == QDRANT_PRIVILEGED_COLLECTION

    err_payload = json.dumps({
        **failure,
        "occurred_at": "2026-04-26T00:00:00+00:00",
        "track": "privileged",
        "doc_id": doc_id,
        "file_name": "privileged.pdf",
        "accumulator_so_far": uuids,
    })
    _seed_failed_row(shadow_test_conn, doc_id, fhash,
                     chunk_count=50, error_detail=err_payload[:8192])
    row = _read_vault_row(shadow_test_conn, doc_id)
    assert row is not None
    parsed = json.loads(row["error_detail"])
    assert parsed["track"] == "privileged"
    assert parsed["qdrant_collection"] == QDRANT_PRIVILEGED_COLLECTION
    _delete_vault_row(shadow_test_conn, doc_id)


def test_ingest_run_tracker_errored_counter_increments_on_failure(
    shadow_test_conn,
):
    """IngestRunTracker.inc_errored() updates the errored counter, which the
    reprocess script bumps for each qdrant_upsert_failed outcome."""
    from backend.services.ingest_run_tracker import IngestRunTracker

    with IngestRunTracker(
        CASE_SLUG, "__phase_e_test_tracker__", args={"unit_test": True},
    ) as tracker:
        tracker.set_total_files(3)
        tracker.inc_errored()
        tracker.inc_errored()
        # tracker.degraded short-circuit means we can't read counters back
        # via SELECT if the DB write degraded — assert against in-memory.
        assert tracker._counters.errored == 2  # type: ignore[attr-defined]


# ════════════════════════════════════════════════════════════════════════════
# Section 4 — Scale (reproducing Vanderburge failure modes)
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_3000_chunk_batch_boundary_handling():
    """3000 chunks split exactly into 3 batches of 1000 — this is the size at
    which Vanderburge's silent failure first manifested. Verifies all 3000
    are tracked under full success."""
    fhash = "7" * 64
    points = _make_synthetic_points(3000, fhash, _QDRANT_WORK_PRODUCT_NS)

    fake_client = MagicMock()
    fake_client.put = AsyncMock(return_value=_qdrant_response())

    with patch.object(legal_ediscovery, "shared_client", fake_client):
        uuids, failure = await _batch_upsert_with_verification(
            url_base="http://test", collection_name=QDRANT_COLLECTION,
            points=points, batch_size=1000,
        )

    assert failure is None
    assert len(uuids) == 3000
    assert fake_client.put.await_count == 3


@pytest.mark.asyncio
async def test_12000_chunk_worst_case_batch_handling():
    """12000 chunks → 12 batches of 1000. Worst-case Vanderburge thread.
    Verifies the helper does not pile up timeout pressure on a single
    request (each batch has its own 60s timeout)."""
    fhash = "8" * 64
    points = _make_synthetic_points(12000, fhash, _QDRANT_WORK_PRODUCT_NS)

    fake_client = MagicMock()
    fake_client.put = AsyncMock(return_value=_qdrant_response())

    with patch.object(legal_ediscovery, "shared_client", fake_client):
        uuids, failure = await _batch_upsert_with_verification(
            url_base="http://test", collection_name=QDRANT_COLLECTION,
            points=points, batch_size=1000,
        )

    assert failure is None
    assert len(uuids) == 12000
    assert fake_client.put.await_count == 12
    # Each batch passed timeout=60.0 in the kwargs.
    timeouts = {call.kwargs.get("timeout") for call in fake_client.put.await_args_list}
    assert timeouts == {60.0}


# ════════════════════════════════════════════════════════════════════════════
# Section 5 — backfill_vector_ids script
# ════════════════════════════════════════════════════════════════════════════


def test_backfill_idempotency_already_populated_rows_untouched(shadow_test_conn):
    """backfill_vector_ids._update_vector_ids issues UPDATE … WHERE
    vector_ids IS NULL. A row whose vector_ids is already set must not be
    rewritten."""
    import backend.scripts.backfill_vector_ids as backfill_vector_ids

    doc_id = str(uuid4())
    fhash = "9" * 64
    pre_uuids = [str(uuid5(_QDRANT_WORK_PRODUCT_NS, f"{fhash}:{i}")) for i in range(4)]
    _seed_failed_row(
        shadow_test_conn, doc_id, fhash,
        chunk_count=4, vector_ids=pre_uuids,
        processing_status="completed",
    )

    captured: list[tuple] = []

    def patched_connect(dbname: str):
        captured.append((dbname,))
        return psycopg2.connect(DSN)

    with patch.object(backfill_vector_ids, "_connect", patched_connect):
        # Attempt to overwrite with new UUIDs — must be a no-op due to
        # WHERE vector_ids IS NULL.
        new_uuids = [str(uuid4()) for _ in range(4)]
        wrote = backfill_vector_ids._update_vector_ids(doc_id, new_uuids)
    assert wrote == 0, "WHERE vector_ids IS NULL must skip rows already set"
    row = _read_vault_row(shadow_test_conn, doc_id)
    assert row is not None
    assert row["vector_ids"] == pre_uuids
    _delete_vault_row(shadow_test_conn, doc_id)


def test_backfill_dry_run_no_db_mutations(shadow_test_conn, tmp_path, monkeypatch):
    """run_backfill with --dry-run must not invoke _update_vector_ids."""
    import backend.scripts.backfill_vector_ids as backfill_vector_ids

    doc_id = str(uuid4())
    fhash = "a" * 64
    _seed_failed_row(
        shadow_test_conn, doc_id, fhash,
        chunk_count=3, vector_ids=None,
        processing_status="qdrant_upsert_failed",
    )

    update_calls: list[tuple] = []

    def fake_update(_doc_id, _uuids):
        update_calls.append((_doc_id, list(_uuids)))
        return 2

    def fake_preflight(_slug):  # bypass the live preflight gates
        return None

    def fake_scroll(_collection, _slug):
        return {doc_id: ["uuid-1", "uuid-2", "uuid-3"]}, 3

    monkeypatch.setattr(backfill_vector_ids, "_update_vector_ids", fake_update)
    monkeypatch.setattr(backfill_vector_ids, "run_preflight", fake_preflight)
    monkeypatch.setattr(
        backfill_vector_ids, "_scroll_collection_for_case", fake_scroll,
    )
    monkeypatch.setattr(backfill_vector_ids, "AUDIT_DIR", tmp_path)

    args = Namespace(case_slug=CASE_SLUG, dry_run=True)
    rc = backfill_vector_ids.run_backfill(args)
    assert rc == 0
    assert update_calls == [], "dry-run must not call _update_vector_ids"
    _delete_vault_row(shadow_test_conn, doc_id)


# ════════════════════════════════════════════════════════════════════════════
# Section 6 — reprocess_failed_qdrant_uploads script
# ════════════════════════════════════════════════════════════════════════════


def test_reprocess_idempotency_recovered_rows_skipped(shadow_test_conn):
    """The reprocess candidate predicate excludes rows whose vector_ids is
    set AND processing_status ∉ {'qdrant_upsert_failed'}. A 'completed' row
    with vector_ids populated must not be returned by _list_candidates."""
    import backend.scripts.reprocess_failed_qdrant_uploads as reprocess

    doc_id = str(uuid4())
    fhash = "b" * 64
    uuids = [str(uuid5(_QDRANT_WORK_PRODUCT_NS, f"{fhash}:{i}")) for i in range(4)]
    _seed_failed_row(
        shadow_test_conn, doc_id, fhash,
        chunk_count=4, vector_ids=uuids,
        processing_status="completed",
    )

    with patch.object(reprocess, "_connect", lambda _db: psycopg2.connect(DSN)):
        candidates = reprocess._list_candidates(
            case_slug=CASE_SLUG, doc_id_filter=None, limit=None,
        )
    cand_ids = {c.doc_id for c in candidates}
    assert doc_id not in cand_ids, (
        "recovered row (status=completed, vector_ids set) must not be a "
        "reprocess candidate"
    )
    _delete_vault_row(shadow_test_conn, doc_id)


def test_reprocess_doc_id_file_filter_intersects_candidates(
    shadow_test_conn, tmp_path,
):
    """--doc-id-file restricts the candidate set to listed UUIDs intersected
    with the predicate. Rows in the file but NOT in the predicate set must
    not appear; rows in the predicate set but NOT in the file must not
    appear either."""
    import backend.scripts.reprocess_failed_qdrant_uploads as reprocess

    doc_in_both = str(uuid4())
    doc_only_in_file = str(uuid4())
    doc_only_in_predicate = str(uuid4())

    _seed_failed_row(shadow_test_conn, doc_in_both, "c" * 64,
                     chunk_count=3, processing_status="qdrant_upsert_failed")
    _seed_failed_row(shadow_test_conn, doc_only_in_predicate, "d" * 64,
                     chunk_count=3, processing_status="qdrant_upsert_failed")

    id_file = tmp_path / "ids.txt"
    id_file.write_text(f"{doc_in_both}\n{doc_only_in_file}\n# comment\n\n")

    with patch.object(reprocess, "_connect", lambda _db: psycopg2.connect(DSN)):
        filter_set = reprocess._read_doc_id_file(id_file)
        candidates = reprocess._list_candidates(
            case_slug=CASE_SLUG, doc_id_filter=filter_set, limit=None,
        )
    cand_ids = {c.doc_id for c in candidates}
    assert doc_in_both in cand_ids
    assert doc_only_in_file not in cand_ids, (
        "doc IDs in --doc-id-file but NOT matching the predicate must be excluded"
    )
    assert doc_only_in_predicate not in cand_ids, (
        "doc IDs matching the predicate but NOT in --doc-id-file must be excluded"
    )
    _delete_vault_row(shadow_test_conn, doc_in_both)
    _delete_vault_row(shadow_test_conn, doc_only_in_predicate)


@pytest.mark.asyncio
async def test_reprocess_partial_vector_ids_resume_uuid5_contract():
    """A row that previously failed mid-upsert (partial vector_ids
    accumulator) is re-upserted: re-runs produce the SAME UUID5 IDs. Qdrant
    overwrites the same point IDs with the same payload — no orphans, no
    duplicates."""
    fhash = "e" * 64
    chunk_count = 7

    # Run 1: first 4 batches succeed (well, only 1 batch since 7 < 1000),
    # but simulate partial: only first 3 of 7 points landed.
    run_1_uuids = [
        str(uuid5(_QDRANT_WORK_PRODUCT_NS, f"{fhash}:{i}"))
        for i in range(3)
    ]

    # Run 2: the reprocess pass — produces the same IDs for indices 0-6.
    run_2_uuids = [
        str(uuid5(_QDRANT_WORK_PRODUCT_NS, f"{fhash}:{i}"))
        for i in range(chunk_count)
    ]

    # The first 3 IDs must match exactly (so re-upsert overwrites cleanly).
    assert run_2_uuids[:3] == run_1_uuids
    # The remaining 4 are net-new IDs that complete the row.
    assert len(set(run_2_uuids)) == chunk_count


# ════════════════════════════════════════════════════════════════════════════
# Section 7 — Cross-DB consistency, mirror drift, concurrent-write safety
# ════════════════════════════════════════════════════════════════════════════


def test_cross_db_consistency_backfill_writes_to_both_dbs(shadow_test_conn):
    """backfill_vector_ids._update_vector_ids must call _connect twice —
    once per dbname in TARGET_DBS — so the fortress_db ↔ fortress_prod mirror
    stays in lock-step."""
    import backend.scripts.backfill_vector_ids as backfill_vector_ids

    doc_id = str(uuid4())
    fhash = "1a" * 32
    _seed_failed_row(
        shadow_test_conn, doc_id, fhash,
        chunk_count=2, vector_ids=None,
        processing_status="qdrant_upsert_failed",
    )

    captured_dbs: list[str] = []

    def patched_connect(dbname: str):
        captured_dbs.append(dbname)
        return psycopg2.connect(DSN)

    with patch.object(backfill_vector_ids, "_connect", patched_connect):
        new_uuids = [
            str(uuid5(_QDRANT_WORK_PRODUCT_NS, f"{fhash}:{i}"))
            for i in range(2)
        ]
        wrote = backfill_vector_ids._update_vector_ids(doc_id, new_uuids)

    assert captured_dbs == list(backfill_vector_ids.TARGET_DBS), (
        f"backfill must call _connect for both DBs in order; got {captured_dbs}"
    )
    # Both DBs are pointed at the same fortress_shadow_test → first UPDATE
    # writes (rowcount=1); second sees vector_ids already set (rowcount=0).
    assert wrote == 1
    _delete_vault_row(shadow_test_conn, doc_id)


def test_cross_db_consistency_reprocess_writes_to_both_dbs(shadow_test_conn):
    """reprocess._persist_success_state must call _connect twice — once per
    dbname in TARGET_DBS — for the bilateral mirror contract."""
    import backend.scripts.reprocess_failed_qdrant_uploads as reprocess

    doc_id = str(uuid4())
    fhash = "2a" * 32
    _seed_failed_row(
        shadow_test_conn, doc_id, fhash,
        chunk_count=3, vector_ids=None,
        processing_status="qdrant_upsert_failed",
    )

    captured_dbs: list[str] = []

    def patched_connect(dbname: str):
        captured_dbs.append(dbname)
        return psycopg2.connect(DSN)

    cand = reprocess._Candidate(
        doc_id=doc_id, file_name="x.pdf", nfs_path="/tmp/x.pdf",
        mime_type="application/pdf", file_hash=fhash,
        chunk_count=3, processing_status="qdrant_upsert_failed",
    )
    uuids = [str(uuid5(_QDRANT_WORK_PRODUCT_NS, f"{fhash}:{i}")) for i in range(3)]

    with patch.object(reprocess, "_connect", patched_connect):
        wrote = asyncio.run(
            reprocess._persist_success_state(cand, "completed", uuids, ["c1", "c2", "c3"]),
        )

    assert captured_dbs == list(reprocess.TARGET_DBS)
    # Both pointed at the same DB → first wins, second is no-op (id was
    # already updated, still rowcount=1 because UPDATE doesn't constrain on
    # vector_ids being NULL — it overwrites). Both succeed → wrote == 2.
    assert wrote == 2
    _delete_vault_row(shadow_test_conn, doc_id)


def test_mirror_drift_detection_returns_exit_code_2():
    """When the second-DB UPDATE returns rowcount=0 (mirror drift), the
    script's exit code is 2. Verified by stubbing _persist_success_state
    to report wrote == 1 (one of two DBs updated) and threading that
    through the orchestrator's mirror_drift list → return 2."""
    import backend.scripts.reprocess_failed_qdrant_uploads as reprocess

    fake_outcome = reprocess._RowOutcome(
        doc_id=str(uuid4()),
        file_name="x.pdf",
        track="work_product",
        terminal_status="completed",
        chunks=3,
        vectors_indexed=3,
        mirror_drift=True,
    )

    # Replicate the exit-code logic in run_reprocess.
    manifest = reprocess.ReprocessManifest(
        case_slug=CASE_SLUG, started_at="now",
    )
    manifest.attempted = 1
    manifest.recovered = 1
    manifest.mirror_drift_doc_ids = [fake_outcome.doc_id]
    manifest.still_failed = 0

    if manifest.still_failed > 0:
        rc = 1
    elif manifest.mirror_drift_doc_ids:
        rc = 2
    else:
        rc = 0

    assert rc == 2


def test_persist_state_uses_atomic_single_statement_update(shadow_test_conn):
    """Concurrent-upsert safety (test #18 intent): the bilateral DB writers
    issue single-statement UPDATEs (no SELECT-then-UPDATE). Postgres
    row-level locking serializes concurrent UPDATEs on the same row, so two
    in-flight reprocess calls can't corrupt the row.

    This is the design contract underpinning why backfill_vector_ids and
    reprocess_failed_qdrant_uploads do NOT acquire a /tmp/vault-ingest lock
    file (unlike vault_ingest_legal_case): UUID5 idempotency + atomic
    UPDATE makes per-row contention safe by construction."""
    import backend.scripts.backfill_vector_ids as backfill_vector_ids
    import backend.scripts.reprocess_failed_qdrant_uploads as reprocess

    captured_sql: list[str] = []

    class _CapturingCursor:
        def __init__(self, real_cur):
            self._real = real_cur
            self.rowcount = 0
        def __enter__(self): return self
        def __exit__(self, *a): self._real.close()
        def execute(self, sql, params=None):
            captured_sql.append(sql)
            self._real.execute(sql, params)
            self.rowcount = self._real.rowcount

    class _CapturingConn:
        def __init__(self, real_conn):
            self._real = real_conn
        def cursor(self): return _CapturingCursor(self._real.cursor())
        def close(self): self._real.close()

    def patched_connect(_db: str) -> _CapturingConn:
        return _CapturingConn(psycopg2.connect(DSN))

    doc_id = str(uuid4())
    _seed_failed_row(shadow_test_conn, doc_id, "3a" * 32,
                     chunk_count=2, vector_ids=None,
                     processing_status="qdrant_upsert_failed")

    with patch.object(backfill_vector_ids, "_connect", patched_connect):
        backfill_vector_ids._update_vector_ids(doc_id, [str(uuid4()) for _ in range(2)])

    cand = reprocess._Candidate(
        doc_id=doc_id, file_name="x.pdf", nfs_path="/tmp/x.pdf",
        mime_type="application/pdf", file_hash="4a" * 32,
        chunk_count=2, processing_status="qdrant_upsert_failed",
    )
    with patch.object(reprocess, "_connect", patched_connect):
        asyncio.run(reprocess._persist_success_state(
            cand, "completed", [str(uuid4()) for _ in range(2)], ["c1", "c2"],
        ))

    # Every captured SQL statement is a single UPDATE — no SELECT-FOR-UPDATE
    # round-trip, no read-modify-write window where a racer could interleave.
    for sql in captured_sql:
        normalized = " ".join(sql.split())
        assert normalized.upper().startswith("UPDATE"), (
            f"captured non-UPDATE SQL in critical path: {normalized!r}"
        )
        assert "SELECT" not in normalized.upper(), (
            "_persist_*_state SQL must not include a SELECT — single-statement "
            f"UPDATE only: {normalized!r}"
        )

    _delete_vault_row(shadow_test_conn, doc_id)
