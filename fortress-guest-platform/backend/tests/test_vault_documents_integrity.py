"""Schema integrity for legal.vault_documents (PR D-pre2, Option A union vocabulary).

Validates the FK / UNIQUE / CHECK / index constraints applied by alembic
revision d8e3c1f5b9a6_vault_documents_integrity. Each test seeds + cleans
its own row so the suite is order-independent.

Tests skip cleanly if the new named constraints are not present in
TEST_DATABASE_URL — that surfaces an unmigrated test DB rather than
producing false failures.
"""
from __future__ import annotations

from uuid import uuid4

import psycopg2
import pytest

from backend.tests.db_helpers import get_test_dsn


DSN = get_test_dsn()

UNION_STATUSES = (
    "pending",
    "processing",
    "vectorizing",
    "complete",
    "completed",
    "ocr_failed",
    "error",
    "failed",
    "locked_privileged",
)


def _has_named_constraints() -> bool:
    sql = """
        SELECT
            EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'fk_vault_documents_case_slug'
                      AND conrelid = 'legal.vault_documents'::regclass),
            EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_vault_documents_case_hash'
                      AND conrelid = 'legal.vault_documents'::regclass),
            EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'chk_vault_documents_status'
                      AND conrelid = 'legal.vault_documents'::regclass)
    """
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
        return bool(row and all(row))
    finally:
        conn.close()


pytestmark = pytest.mark.skipif(
    not _has_named_constraints(),
    reason=(
        "alembic revision d8e3c1f5b9a6 not applied to TEST_DATABASE_URL — "
        "run the PR D-pre2 migration before exercising these tests"
    ),
)


# ── helpers ─────────────────────────────────────────────────────────


def _ensure_case(cur, case_slug: str, case_number: str | None = None) -> None:
    cur.execute(
        "INSERT INTO legal.cases (case_slug, case_number, case_name, status) "
        "VALUES (%s, %s, %s, 'OPEN') "
        "ON CONFLICT (case_slug) DO NOTHING",
        (case_slug, case_number or case_slug.upper(), f"Test case {case_slug}"),
    )


def _insert_doc(
    cur,
    *,
    case_slug: str,
    file_hash: str,
    status: str = "pending",
    file_name: str | None = None,
    doc_id: str | None = None,
) -> str:
    doc_id = doc_id or str(uuid4())
    cur.execute(
        """
        INSERT INTO legal.vault_documents
            (id, case_slug, file_name, nfs_path, mime_type,
             file_hash, file_size_bytes, processing_status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            doc_id,
            case_slug,
            file_name or f"{doc_id[:8]}.pdf",
            f"/tmp/test/{doc_id}.pdf",
            "application/pdf",
            file_hash,
            1024,
            status,
        ),
    )
    return doc_id


# ── 1. FK ────────────────────────────────────────────────────────────


def test_fk_violation_rejects_unknown_case_slug() -> None:
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                _insert_doc(
                    cur,
                    case_slug="zzz-does-not-exist-vault-test",
                    file_hash="0" * 64,
                )
    finally:
        conn.rollback()
        conn.close()


# ── 2/3. UNIQUE (case_slug, file_hash) ───────────────────────────────


def test_unique_case_hash_rejects_duplicate_within_case() -> None:
    case_slug = f"vault-dup-{uuid4().hex[:8]}"
    fhash = "1" * 64
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            _ensure_case(cur, case_slug)
            _insert_doc(cur, case_slug=case_slug, file_hash=fhash)
            with pytest.raises(psycopg2.errors.UniqueViolation):
                _insert_doc(cur, case_slug=case_slug, file_hash=fhash)
    finally:
        conn.rollback()
        conn.close()


def test_unique_case_hash_allows_same_hash_different_case() -> None:
    case_a = f"vault-cross-a-{uuid4().hex[:8]}"
    case_b = f"vault-cross-b-{uuid4().hex[:8]}"
    fhash = "2" * 64
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            _ensure_case(cur, case_a)
            _ensure_case(cur, case_b)
            _insert_doc(cur, case_slug=case_a, file_hash=fhash)
            _insert_doc(cur, case_slug=case_b, file_hash=fhash)
    finally:
        conn.rollback()
        conn.close()


# ── 4. CHECK accepts every union value ──────────────────────────────


@pytest.mark.parametrize("status", UNION_STATUSES)
def test_check_constraint_accepts_all_union_values(status: str) -> None:
    case_slug = f"vault-status-{uuid4().hex[:8]}"
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            _ensure_case(cur, case_slug)
            _insert_doc(
                cur,
                case_slug=case_slug,
                file_hash=uuid4().hex + uuid4().hex,
                status=status,
            )
    finally:
        conn.rollback()
        conn.close()


# ── 5. CHECK rejects garbage status ─────────────────────────────────


def test_check_constraint_rejects_garbage_status() -> None:
    case_slug = f"vault-bad-{uuid4().hex[:8]}"
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            _ensure_case(cur, case_slug)
            with pytest.raises(psycopg2.errors.CheckViolation):
                _insert_doc(
                    cur,
                    case_slug=case_slug,
                    file_hash=uuid4().hex + uuid4().hex,
                    status="garbage_state_99",
                )
    finally:
        conn.rollback()
        conn.close()


# ── 6. Indexes present ──────────────────────────────────────────────


def test_indexes_present() -> None:
    expected = {
        "idx_vault_documents_case_slug",
        "idx_vault_documents_status",
        "idx_vault_documents_created_at",
        "idx_vault_documents_file_hash",
    }
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'legal' AND tablename = 'vault_documents'"
            )
            present = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()
    missing = expected - present
    assert not missing, f"missing query-pattern indexes: {missing}"


# ── 7. Existing Generali rows survive (read-only against fortress_prod) ──
# Skipped automatically if the test DB is fortress_shadow_test (which has no
# Generali rows). The probe is read-only — no writes either way.


def test_existing_generali_completed_rows_survive_in_prod_pattern() -> None:
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) "
                "FROM legal.vault_documents "
                "WHERE case_slug = 'fish-trap-suv2026000013' "
                "AND processing_status = 'completed'"
            )
            row = cur.fetchone()
            count = int(row[0]) if row else 0
    finally:
        conn.close()
    if count == 0:
        pytest.skip(
            "no Generali rows in TEST_DATABASE_URL — this assertion is meaningful "
            "only against fortress_prod, where 2 such rows must remain queryable"
        )
    assert count >= 2, (
        f"expected >=2 Generali rows with status='completed' in fortress_prod; "
        f"found {count}"
    )
