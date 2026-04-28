"""PR G — 7IL restructure + privilege architecture tests.

Coverage targets:
  Schema (legal.cases new columns + legal.case_slug_aliases + FK deferrable):
    * test_legal_cases_has_new_columns
    * test_case_slug_aliases_table_present
    * test_fk_vault_documents_case_slug_now_deferrable
    * test_related_matters_jsonb_array_round_trip
    * test_privileged_counsel_domains_jsonb_array_round_trip
    * test_case_phase_column_round_trip
    * test_alias_fk_prevents_orphan_new_slug

  Alias resolution (transparent, with telemetry):
    * test_resolve_case_slug_returns_canonical_when_exists
    * test_resolve_case_slug_follows_alias_when_old_slug_queried
    * test_resolve_case_slug_returns_input_when_no_match
      (this is also "test_alias_resolution_handles_missing_alias")
    * test_resolve_case_slug_logs_each_alias_hit

  Council retrieval (env-var-gated, related-matters expansion, fail-soft):
    * test_council_retrieval_flags_default_true
    * test_council_retrieval_flags_disabled_via_env
    * test_council_retrieval_flags_read_at_call_time
    * test_resolve_related_matters_handles_jsonb_list
    * test_resolve_related_matters_excludes_self_reference
    * test_resolve_related_matters_handles_null_column
    * test_resolve_related_matters_handles_malformed_jsonb
    * test_freeze_privileged_context_targets_correct_collection
    * test_freeze_privileged_context_filters_by_case_slug
    * test_freeze_privileged_context_tags_chunks_with_privileged_marker
    * test_freeze_privileged_context_fail_soft_on_qdrant_error
      (covers the "what if collection doesn't exist" failure mode)

  Privileged ingestion routing (process_vault_upload):
    * test_process_vault_upload_routes_privileged_to_separate_collection
    * test_process_vault_upload_non_privileged_uses_work_product_collection
    * test_upsert_to_qdrant_privileged_uses_uuid5_deterministic_ids
    * test_privileged_collection_payload_dual_field_chunk_num_and_chunk_index
    * test_derive_privileged_counsel_domain_from_eml_headers
    * test_derive_privileged_counsel_domain_returns_none_when_no_match
    * test_role_for_counsel_domain_maps_correctly

Tests against fortress_shadow_test only — synthetic case slugs (test-case-i,
test-case-ii). No production data is read or modified.
"""
from __future__ import annotations

import os
import re
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid5

import psycopg2
import pytest

import run  # noqa: F401  — registers settings + sys.path
import backend.services.legal_ediscovery as legal_ediscovery
from backend.services.legal_ediscovery import (
    _DOMAIN_TO_ROLE,
    _QDRANT_PRIVILEGED_NS,
    QDRANT_COLLECTION,
    QDRANT_PRIVILEGED_COLLECTION,
    _derive_privileged_counsel_domain,
    _role_for_counsel_domain,
    _upsert_to_qdrant_privileged,
)


# ─── DB connection helpers ──────────────────────────────────────────


def _admin_test_dsn() -> dict:
    """fortress_admin connection (DDL access for schema tests)."""
    uri = os.environ.get("POSTGRES_ADMIN_URI", "")
    m = re.match(
        r"postgresql(?:\+\w+)?://([^:]+):([^@]+)@([^:/]+):?(\d+)?/[^?]+",
        uri,
    )
    if not m:
        pytest.skip("POSTGRES_ADMIN_URI not set; can't run DDL-required tests")
    user, pw, host, port = m.groups()
    return {"host": host, "port": int(port or 5432), "user": user,
            "password": pw, "dbname": "fortress_shadow_test"}


@pytest.fixture
def shadow_test_conn():
    """psycopg2 connection to fortress_shadow_test as fortress_admin (DDL access).
    Yields connection; rolls back at end so tests don't pollute the DB."""
    conn = psycopg2.connect(**_admin_test_dsn())
    conn.autocommit = False
    yield conn
    try:
        conn.rollback()
    finally:
        conn.close()


@pytest.fixture
def synthetic_cases(shadow_test_conn):
    """Insert two synthetic case rows (test-case-i and test-case-ii) inside the
    test transaction. Auto-cleaned via the parent fixture's rollback."""
    cur = shadow_test_conn.cursor()
    # Wipe any leftover rows from prior failed runs — uses the same synthetic
    # slugs only.
    cur.execute("""
        DELETE FROM legal.case_slug_aliases
         WHERE old_slug IN ('test-old-slug', 'test-case-i') OR new_slug IN ('test-case-i','test-case-ii')
    """)
    cur.execute("""
        DELETE FROM legal.vault_documents
         WHERE case_slug IN ('test-case-i','test-case-ii')
    """)
    cur.execute("""
        DELETE FROM legal.cases
         WHERE case_slug IN ('test-case-i','test-case-ii','test-deleted-case')
    """)
    cur.execute("""
        INSERT INTO legal.cases (
            case_slug, case_number, case_name, case_type, our_role, status,
            case_phase, related_matters, privileged_counsel_domains
        ) VALUES
          ('test-case-i',  '1:99-cv-99999-XXX', 'Test Case I',  'civil',
           'defendant', 'closed_judgment_against', 'closed',
           '["test-case-ii"]'::jsonb,
           '["mhtlegal.com","fgplaw.com"]'::jsonb),
          ('test-case-ii', '1:99-cv-99998-XXX', 'Test Case II', 'civil',
           'defendant_pro_se', 'active', 'counsel_search',
           '["test-case-i"]'::jsonb,
           '[]'::jsonb)
    """)
    shadow_test_conn.commit()    # commit fixtures so other connections (helper queries) can see
    yield shadow_test_conn
    cur = shadow_test_conn.cursor()
    cur.execute("""
        DELETE FROM legal.case_slug_aliases
         WHERE old_slug IN ('test-old-slug') OR new_slug IN ('test-case-i','test-case-ii')
    """)
    cur.execute("""
        DELETE FROM legal.vault_documents
         WHERE case_slug IN ('test-case-i','test-case-ii')
    """)
    cur.execute("""
        DELETE FROM legal.cases
         WHERE case_slug IN ('test-case-i','test-case-ii','test-deleted-case')
    """)
    shadow_test_conn.commit()


# ════════════════════════════════════════════════════════════════════
# Schema migration verification (Phase B)
# ════════════════════════════════════════════════════════════════════


def test_legal_cases_has_new_columns(shadow_test_conn) -> None:
    """case_phase TEXT, related_matters JSONB, privileged_counsel_domains JSONB."""
    cur = shadow_test_conn.cursor()
    cur.execute("""
        SELECT column_name, data_type
          FROM information_schema.columns
         WHERE table_schema='legal' AND table_name='cases'
           AND column_name IN ('case_phase','related_matters','privileged_counsel_domains')
         ORDER BY column_name
    """)
    rows = cur.fetchall()
    assert ("case_phase", "text") in rows
    assert ("privileged_counsel_domains", "jsonb") in rows
    assert ("related_matters", "jsonb") in rows


def test_case_slug_aliases_table_present(shadow_test_conn) -> None:
    cur = shadow_test_conn.cursor()
    cur.execute(
        "SELECT to_regclass('legal.case_slug_aliases') IS NOT NULL"
    )
    assert cur.fetchone()[0] is True

    # PK on old_slug + FK on new_slug → legal.cases(case_slug)
    cur.execute("""
        SELECT a.attname, c.contype
          FROM pg_constraint c
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
         WHERE c.conrelid = 'legal.case_slug_aliases'::regclass
         ORDER BY c.contype, a.attname
    """)
    rows = cur.fetchall()
    # Should have a primary key constraint on old_slug and a foreign key on new_slug
    assert ("old_slug", "p") in rows  # primary
    assert ("new_slug", "f") in rows  # foreign


def test_fk_vault_documents_case_slug_now_deferrable(shadow_test_conn) -> None:
    """Phase B made the FK deferrable (default-immediate) so the rename
    transaction in Phase C could SET CONSTRAINTS DEFERRED."""
    cur = shadow_test_conn.cursor()
    cur.execute("""
        SELECT condeferrable
          FROM pg_constraint
         WHERE conname = 'fk_vault_documents_case_slug'
    """)
    row = cur.fetchone()
    assert row is not None
    assert row[0] is True


def test_related_matters_jsonb_array_round_trip(synthetic_cases) -> None:
    """A JSONB list survives INSERT → SELECT round-trip as a Python list."""
    cur = synthetic_cases.cursor()
    cur.execute(
        "SELECT related_matters FROM legal.cases WHERE case_slug=%s",
        ("test-case-i",),
    )
    val = cur.fetchone()[0]
    # psycopg2 auto-decodes jsonb to Python list/dict
    assert isinstance(val, list)
    assert val == ["test-case-ii"]


def test_privileged_counsel_domains_jsonb_array_round_trip(synthetic_cases) -> None:
    cur = synthetic_cases.cursor()
    cur.execute(
        "SELECT privileged_counsel_domains FROM legal.cases WHERE case_slug=%s",
        ("test-case-i",),
    )
    val = cur.fetchone()[0]
    assert isinstance(val, list)
    assert "mhtlegal.com" in val
    assert "fgplaw.com" in val
    assert len(val) == 2


def test_case_phase_column_round_trip(synthetic_cases) -> None:
    cur = synthetic_cases.cursor()
    cur.execute(
        "SELECT case_phase FROM legal.cases WHERE case_slug IN ('test-case-i','test-case-ii') ORDER BY case_slug"
    )
    rows = [r[0] for r in cur.fetchall()]
    assert rows == ["closed", "counsel_search"]


def test_alias_fk_prevents_orphan_new_slug(synthetic_cases) -> None:
    """legal.case_slug_aliases.new_slug FK → legal.cases(case_slug) blocks orphans."""
    cur = synthetic_cases.cursor()
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        cur.execute(
            "INSERT INTO legal.case_slug_aliases (old_slug, new_slug) "
            "VALUES (%s, %s)",
            ("test-old-slug", "nonexistent-case-slug"),
        )
        synthetic_cases.commit()
    synthetic_cases.rollback()


# ════════════════════════════════════════════════════════════════════
# Alias resolution (legal_cases.py::_resolve_case_slug)
# ════════════════════════════════════════════════════════════════════

# Import the resolver via the api module
from backend.api.legal_cases import _resolve_case_slug  # noqa: E402


class _FakeResult:
    """Minimal SQLAlchemy Result stand-in for resolver tests."""
    def __init__(self, value=None):
        self._value = value
    def fetchone(self):
        return (self._value,) if self._value is not None else None


def _make_session(query_results: list):
    """AsyncMock session whose execute() returns query_results in order."""
    db = AsyncMock()
    rs = list(query_results)
    async def _exec(_stmt, _params=None):
        return rs.pop(0) if rs else _FakeResult(None)
    db.execute = _exec
    return db


@pytest.mark.asyncio
async def test_resolve_case_slug_returns_canonical_when_exists() -> None:
    """Fast path — slug exists in legal.cases, no alias lookup needed."""
    db = _make_session([_FakeResult(value=1)])  # SELECT 1 hits the cases row
    out = await _resolve_case_slug(db, "test-case-i")
    assert out == "test-case-i"


@pytest.mark.asyncio
async def test_resolve_case_slug_follows_alias_when_old_slug_queried() -> None:
    """Cases lookup misses → alias lookup hits → return new_slug."""
    db = _make_session([
        _FakeResult(value=None),                    # cases miss
        _FakeResult(value="test-case-i"),           # alias points at -i
    ])
    out = await _resolve_case_slug(db, "test-old-slug")
    assert out == "test-case-i"


@pytest.mark.asyncio
async def test_resolve_case_slug_returns_input_when_no_match() -> None:
    """Both queries miss → return the original slug unchanged. (Caller will 404.)
    This exercises the 'alias points at deleted case_slug' edge case too:
    if the alias row was deleted but the bookmark remained, the resolver
    returns the original slug and the caller raises 404 on its own SELECT."""
    db = _make_session([
        _FakeResult(value=None),  # cases miss
        _FakeResult(value=None),  # alias miss
    ])
    out = await _resolve_case_slug(db, "totally-unknown-slug")
    assert out == "totally-unknown-slug"


@pytest.mark.asyncio
async def test_resolve_case_slug_logs_each_alias_hit() -> None:
    """Verify the case_slug_alias_hit log fires (so we can deprecate old slugs
    once usage drops to zero per spec)."""
    db = _make_session([
        _FakeResult(value=None),                     # cases miss
        _FakeResult(value="test-case-i"),            # alias hit
    ])
    with patch("backend.api.legal_cases.logger") as mock_logger:
        await _resolve_case_slug(db, "test-old-slug")
        mock_logger.info.assert_called_once()
        args, kwargs = mock_logger.info.call_args
        assert args[0] == "case_slug_alias_hit"
        assert kwargs.get("old_slug") == "test-old-slug"
        assert kwargs.get("new_slug") == "test-case-i"


@pytest.mark.asyncio
async def test_resolve_case_slug_does_not_log_on_canonical_path() -> None:
    """Canonical path (no alias used) must NOT emit case_slug_alias_hit
    or telemetry won't be meaningful."""
    db = _make_session([_FakeResult(value=1)])
    with patch("backend.api.legal_cases.logger") as mock_logger:
        await _resolve_case_slug(db, "test-case-i")
        for call in mock_logger.info.call_args_list:
            assert call.args[0] != "case_slug_alias_hit"


# ════════════════════════════════════════════════════════════════════
# Council retrieval flags + related_matters resolution
# ════════════════════════════════════════════════════════════════════

from backend.services.legal_council import (  # noqa: E402
    PRIVILEGED_COLLECTION as COUNCIL_PRIV_COLLECTION,
    _council_retrieval_flags,
    _resolve_related_matters_slugs,
    freeze_privileged_context,
)


def test_council_retrieval_flags_default_true(monkeypatch) -> None:
    """Both flags default to true when env vars are unset."""
    monkeypatch.delenv("COUNCIL_INCLUDE_PRIVILEGED_RETRIEVAL", raising=False)
    monkeypatch.delenv("COUNCIL_INCLUDE_RELATED_MATTERS", raising=False)
    incl_priv, incl_rel = _council_retrieval_flags()
    assert incl_priv is True
    assert incl_rel is True


def test_council_retrieval_flags_disabled_via_env(monkeypatch) -> None:
    """false / 0 / no / off all disable the flag (case-insensitive)."""
    for falsy in ("false", "0", "no", "off", "False", "FALSE", "Off"):
        monkeypatch.setenv("COUNCIL_INCLUDE_PRIVILEGED_RETRIEVAL", falsy)
        monkeypatch.setenv("COUNCIL_INCLUDE_RELATED_MATTERS", falsy)
        incl_priv, incl_rel = _council_retrieval_flags()
        assert incl_priv is False, f"expected false for {falsy!r}"
        assert incl_rel is False, f"expected false for {falsy!r}"


def test_council_retrieval_flags_read_at_call_time(monkeypatch) -> None:
    """Per spec — must be readable mid-flight without a restart."""
    monkeypatch.setenv("COUNCIL_INCLUDE_PRIVILEGED_RETRIEVAL", "true")
    assert _council_retrieval_flags()[0] is True
    monkeypatch.setenv("COUNCIL_INCLUDE_PRIVILEGED_RETRIEVAL", "false")
    assert _council_retrieval_flags()[0] is False
    monkeypatch.setenv("COUNCIL_INCLUDE_PRIVILEGED_RETRIEVAL", "true")
    assert _council_retrieval_flags()[0] is True


@pytest.mark.asyncio
async def test_resolve_related_matters_handles_jsonb_list(monkeypatch) -> None:
    """Happy path — column has a JSON array of slugs, returns the list."""
    fake_session = AsyncMock()
    async def _exec(_stmt, _params):
        return _FakeResult(value=["test-case-ii", "test-case-iii"])
    fake_session.execute = _exec
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr(
        "backend.services.ediscovery_agent.LegacySession",
        lambda: fake_session,
    )
    out = await _resolve_related_matters_slugs("test-case-i")
    assert out == ["test-case-ii", "test-case-iii"]


@pytest.mark.asyncio
async def test_resolve_related_matters_excludes_self_reference(monkeypatch) -> None:
    """A misconfigured row that lists the case's own slug — filtered out."""
    fake_session = AsyncMock()
    async def _exec(_stmt, _params):
        return _FakeResult(value=["test-case-i", "test-case-ii"])
    fake_session.execute = _exec
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "backend.services.ediscovery_agent.LegacySession",
        lambda: fake_session,
    )
    out = await _resolve_related_matters_slugs("test-case-i")
    assert "test-case-i" not in out
    assert out == ["test-case-ii"]


@pytest.mark.asyncio
async def test_resolve_related_matters_handles_null_column(monkeypatch) -> None:
    """NULL or empty JSONB → empty list (not crash)."""
    fake_session = AsyncMock()
    async def _exec(_stmt, _params):
        return _FakeResult(value=None)
    fake_session.execute = _exec
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "backend.services.ediscovery_agent.LegacySession",
        lambda: fake_session,
    )
    out = await _resolve_related_matters_slugs("test-case-i")
    assert out == []


@pytest.mark.asyncio
async def test_resolve_related_matters_handles_malformed_jsonb(monkeypatch) -> None:
    """Non-list values (dict, scalar, None-in-list) → empty / filtered, no crash."""
    for bad_value in ({"not": "a list"}, "scalar string", 42):
        fake_session = AsyncMock()
        async def _exec(_stmt, _params, _v=bad_value):
            return _FakeResult(value=_v)
        fake_session.execute = _exec
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(
            "backend.services.ediscovery_agent.LegacySession",
            lambda fs=fake_session: fs,
        )
        out = await _resolve_related_matters_slugs("test-case-i")
        assert out == [], f"malformed value {bad_value!r} should yield []"


@pytest.mark.asyncio
async def test_resolve_related_matters_returns_empty_on_db_error(monkeypatch) -> None:
    """DB connection error → empty list, never propagate, never crash deliberation."""
    def _broken_session():
        raise RuntimeError("simulated DB outage")
    monkeypatch.setattr(
        "backend.services.ediscovery_agent.LegacySession",
        _broken_session,
    )
    out = await _resolve_related_matters_slugs("test-case-i")
    assert out == []


# ════════════════════════════════════════════════════════════════════
# freeze_privileged_context — the privileged retrieval helper
# ════════════════════════════════════════════════════════════════════


class _FakeQdrantResp:
    def __init__(self, points: list):
        self._points = points
    def raise_for_status(self):
        return None
    def json(self):
        return {"result": self._points}


@pytest.mark.asyncio
async def test_freeze_privileged_context_targets_correct_collection(monkeypatch) -> None:
    """URL ends with /collections/legal_privileged_communications/points/search."""
    seen_url: list[str] = []

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, url, **kwargs):
            seen_url.append(url)
            return _FakeQdrantResp(points=[])

    monkeypatch.setattr("backend.services.legal_council.httpx.AsyncClient",
                        lambda timeout=15: _FakeClient())
    monkeypatch.setattr("backend.services.legal_council._embed_text",
                        AsyncMock(return_value=[0.1] * 768))

    await freeze_privileged_context("brief", top_k=5, case_slug="test-case-i")

    assert seen_url, "no httpx.post call observed"
    assert seen_url[0].endswith(
        f"/collections/{COUNCIL_PRIV_COLLECTION}/points/search"
    )


@pytest.mark.asyncio
async def test_freeze_privileged_context_filters_by_case_slug(monkeypatch) -> None:
    """The body must include filter.must with case_slug match."""
    seen_body: list[dict] = []

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, url, **kwargs):
            seen_body.append(kwargs.get("json"))
            return _FakeQdrantResp(points=[])

    monkeypatch.setattr("backend.services.legal_council.httpx.AsyncClient",
                        lambda timeout=15: _FakeClient())
    monkeypatch.setattr("backend.services.legal_council._embed_text",
                        AsyncMock(return_value=[0.1] * 768))

    await freeze_privileged_context("brief", top_k=5, case_slug="test-case-i")

    assert len(seen_body) == 1
    body = seen_body[0]
    assert "filter" in body
    must = body["filter"]["must"]
    assert any(
        c.get("key") == "case_slug" and c.get("match", {}).get("value") == "test-case-i"
        for c in must
    )


@pytest.mark.asyncio
async def test_freeze_privileged_context_tags_chunks_with_privileged_marker(monkeypatch) -> None:
    """Returned chunks start with `[PRIVILEGED · domain · role] [source] text`."""
    points = [{
        "id": "11111111-2222-3333-4444-555555555555",
        "payload": {
            "case_slug": "test-case-i",
            "file_name": "argo-letter.eml",
            "text": "the body of the privileged communication",
            "privileged_counsel_domain": "dralaw.com",
            "role": "post_judgment_closing_counsel",
            "privileged": True,
        },
    }]

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, url, **kwargs):
            return _FakeQdrantResp(points=points)

    monkeypatch.setattr("backend.services.legal_council.httpx.AsyncClient",
                        lambda timeout=15: _FakeClient())
    monkeypatch.setattr("backend.services.legal_council._embed_text",
                        AsyncMock(return_value=[0.1] * 768))

    vector_ids, chunks = await freeze_privileged_context(
        "brief", top_k=5, case_slug="test-case-i",
    )
    assert len(chunks) == 1
    assert chunks[0].startswith("[PRIVILEGED · dralaw.com · post_judgment_closing_counsel]")
    assert "[argo-letter.eml]" in chunks[0]
    assert "the body of the privileged communication" in chunks[0]
    assert vector_ids == ["11111111-2222-3333-4444-555555555555"]


@pytest.mark.asyncio
async def test_freeze_privileged_context_fail_soft_on_qdrant_error(monkeypatch) -> None:
    """If the privileged collection doesn't exist or Qdrant is down — return
    ([], []) and do not crash the deliberation."""
    class _BoomClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, url, **kwargs):
            raise ConnectionError("qdrant unreachable")

    monkeypatch.setattr("backend.services.legal_council.httpx.AsyncClient",
                        lambda timeout=15: _BoomClient())
    monkeypatch.setattr("backend.services.legal_council._embed_text",
                        AsyncMock(return_value=[0.1] * 768))

    vector_ids, chunks = await freeze_privileged_context(
        "brief", top_k=5, case_slug="test-case-i",
    )
    assert vector_ids == []
    assert chunks == []


# ════════════════════════════════════════════════════════════════════
# process_vault_upload privileged routing
# ════════════════════════════════════════════════════════════════════


def _make_db_session_for_pipeline(execute_side_effect) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.commit = AsyncMock()
    return db


def _exec_factory_inserts_succeed():
    """Side-effect that lets the INSERT 'go through' (returns a fake id)."""
    state = {"insert_done": False, "fastdup_done": False}
    def _eff(stmt, *args, **kwargs):
        sql = str(stmt)
        if "SELECT id FROM legal.vault_documents" in sql and not state["fastdup_done"]:
            state["fastdup_done"] = True
            r = MagicMock()
            r.fetchone = MagicMock(return_value=None)  # no dup
            return r
        if "INSERT INTO legal.vault_documents" in sql and not state["insert_done"]:
            state["insert_done"] = True
            r = MagicMock()
            r.fetchone = MagicMock(return_value=("inserted-id",))
            return r
        # Any other (UPDATE, etc.) — pass-through
        r = MagicMock()
        r.fetchone = MagicMock(return_value=None)
        r.mappings = MagicMock(return_value=MagicMock(
            first=MagicMock(return_value=None),
        ))
        return r
    return _eff


@pytest.mark.asyncio
async def test_process_vault_upload_routes_privileged_to_separate_collection(
    monkeypatch, tmp_path,
) -> None:
    """Privileged path must call _upsert_to_qdrant_privileged and NOT _upsert_to_qdrant."""
    monkeypatch.setattr(legal_ediscovery, "_resolve_vault_dir",
                        lambda _slug: tmp_path)
    monkeypatch.setattr(legal_ediscovery, "_extract_text",
                        lambda _b, _m, _n: "privileged content from MHT counsel mhtlegal.com")
    monkeypatch.setattr(
        legal_ediscovery, "_classify_privilege",
        AsyncMock(return_value=(MagicMock(
            is_privileged=True, confidence=0.95,
            privilege_type="attorney_client", reasoning="counsel match",
        ), 5)),
    )
    monkeypatch.setattr(legal_ediscovery, "_log_privilege",
                        AsyncMock(return_value=None))
    monkeypatch.setattr(legal_ediscovery, "_chunk_document",
                        lambda _t: ["chunk1", "chunk2"])
    monkeypatch.setattr(
        legal_ediscovery, "_embed_chunks",
        AsyncMock(return_value=[[0.1] * 8, [0.2] * 8]),
    )

    work_product_calls: list = []
    # Both upsert helpers now return tuple[list[str], Optional[dict]] per Issue
    # #228 (partial-failure recovery). Mocks return (["uuid-a","uuid-b"], None)
    # for the success path so callers can len() the successful list.
    monkeypatch.setattr(
        legal_ediscovery, "_upsert_to_qdrant",
        AsyncMock(side_effect=lambda *a, **kw: work_product_calls.append((a, kw)) or (["u1", "u2"], None)),
    )
    privileged_calls: list = []
    monkeypatch.setattr(
        legal_ediscovery, "_upsert_to_qdrant_privileged",
        AsyncMock(side_effect=lambda **kw: privileged_calls.append(kw) or (["u1", "u2"], None)),
    )
    monkeypatch.setattr(legal_ediscovery, "_emit_docket_updated_event",
                        AsyncMock(return_value=False))

    db = _make_db_session_for_pipeline(_exec_factory_inserts_succeed())
    result = await legal_ediscovery.process_vault_upload(
        db=db,
        case_slug="test-case-i",
        file_bytes=b"some bytes from a privileged email between Gary and his attorney",
        file_name="from-mhtlegal.eml",
        mime_type="message/rfc822",
    )

    assert result["status"] == "locked_privileged"
    assert len(privileged_calls) == 1, "privileged upsert must be called once"
    assert work_product_calls == [], "non-privileged upsert must NOT be called on privileged docs"


@pytest.mark.asyncio
async def test_process_vault_upload_non_privileged_uses_work_product_collection(
    monkeypatch, tmp_path,
) -> None:
    """Mirror test: non-privileged → _upsert_to_qdrant called, privileged not called."""
    monkeypatch.setattr(legal_ediscovery, "_resolve_vault_dir",
                        lambda _slug: tmp_path)
    monkeypatch.setattr(legal_ediscovery, "_extract_text",
                        lambda _b, _m, _n: "ordinary case correspondence — no counsel")
    monkeypatch.setattr(
        legal_ediscovery, "_classify_privilege",
        AsyncMock(return_value=(MagicMock(
            is_privileged=False, confidence=0.0,
            privilege_type=None, reasoning=None,
        ), 1)),
    )
    monkeypatch.setattr(legal_ediscovery, "_chunk_document",
                        lambda _t: ["chunk1"])
    monkeypatch.setattr(
        legal_ediscovery, "_embed_chunks",
        AsyncMock(return_value=[[0.3] * 8]),
    )

    work_product_calls: list = []
    monkeypatch.setattr(
        legal_ediscovery, "_upsert_to_qdrant",
        AsyncMock(side_effect=lambda *a, **kw: work_product_calls.append((a, kw)) or (["u1"], None)),
    )
    privileged_calls: list = []
    monkeypatch.setattr(
        legal_ediscovery, "_upsert_to_qdrant_privileged",
        AsyncMock(side_effect=lambda **kw: privileged_calls.append(kw) or (["u1"], None)),
    )
    monkeypatch.setattr(legal_ediscovery, "_emit_docket_updated_event",
                        AsyncMock(return_value=False))

    db = _make_db_session_for_pipeline(_exec_factory_inserts_succeed())
    result = await legal_ediscovery.process_vault_upload(
        db=db,
        case_slug="test-case-i",
        file_bytes=b"non-privileged content",
        file_name="random.pdf",
        mime_type="application/pdf",
    )
    assert result["status"] == "completed"
    assert len(work_product_calls) == 1
    assert privileged_calls == []


# ════════════════════════════════════════════════════════════════════
# _upsert_to_qdrant_privileged — payload shape + UUID5 idempotency
# ════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_upsert_to_qdrant_privileged_uses_uuid5_deterministic_ids(monkeypatch) -> None:
    """Same (file_hash, chunk_index) MUST produce the same point id across runs.
    Re-runs of the same physical file must NOT duplicate Qdrant points."""
    captured = []
    # Per Issue #228, _batch_upsert_with_verification now reads the response
    # body and requires status=ok + result.status=completed (or acknowledged).
    # Mock has to honor that contract.
    class _FakeResp:
        def raise_for_status(self): return None
        def json(self):
            return {"result": {"operation_id": 1, "status": "completed"},
                    "status": "ok", "time": 0.001}
    fake_client = MagicMock()
    fake_client.put = AsyncMock(side_effect=lambda url, **kw: (captured.append(kw.get("json")), _FakeResp())[1])
    monkeypatch.setattr(legal_ediscovery, "shared_client", fake_client)

    # Function now returns tuple[list[str], Optional[dict]]
    # — (successful_uuids, batch_failure_descriptor_or_None) per Issue #228.
    # First run
    successful_1, failure_1 = await _upsert_to_qdrant_privileged(
        doc_id="doc-A", case_slug="test-case-i", file_name="x.eml",
        file_hash="hashAAA", privileged_counsel_domain="mhtlegal.com",
        role="case_i_phase_1_filing_to_depositions",
        privilege_type="attorney_client",
        chunks=["a", "b"],
        vectors=[[0.1] * 4, [0.2] * 4],
    )
    # Second run — *same* file_hash, simulating a re-ingest. doc_id is
    # different (a new uuid4 from the INSERT) but file_hash + idx are stable.
    successful_2, failure_2 = await _upsert_to_qdrant_privileged(
        doc_id="doc-B-different",
        case_slug="test-case-i", file_name="x.eml",
        file_hash="hashAAA", privileged_counsel_domain="mhtlegal.com",
        role="case_i_phase_1_filing_to_depositions",
        privilege_type="attorney_client",
        chunks=["a", "b"],
        vectors=[[0.1] * 4, [0.2] * 4],
    )
    assert len(successful_1) == 2 and len(successful_2) == 2
    assert failure_1 is None and failure_2 is None
    ids_run1 = sorted(p["id"] for p in captured[0]["points"])
    ids_run2 = sorted(p["id"] for p in captured[1]["points"])
    assert ids_run1 == ids_run2, (
        "deterministic UUID5 must produce identical point IDs on re-run "
        "with the same file_hash+chunk_index"
    )
    # Successful uuids returned should match the captured-points uuids.
    assert sorted(successful_1) == ids_run1

    # Sanity: ids really come from uuid5
    expected_a = str(uuid5(_QDRANT_PRIVILEGED_NS, "hashAAA:0"))
    expected_b = str(uuid5(_QDRANT_PRIVILEGED_NS, "hashAAA:1"))
    assert set(ids_run1) == {expected_a, expected_b}


@pytest.mark.asyncio
async def test_privileged_collection_payload_dual_field_chunk_num_and_chunk_index(
    monkeypatch,
) -> None:
    """File 1 spec divergence — payload includes BOTH chunk_num and chunk_index
    so Council retrieval can use either field name. Both must be present and equal."""
    captured = []
    # Per Issue #228, _batch_upsert_with_verification now reads the response
    # body and requires status=ok + result.status=completed (or acknowledged).
    # Mock has to honor that contract.
    class _FakeResp:
        def raise_for_status(self): return None
        def json(self):
            return {"result": {"operation_id": 1, "status": "completed"},
                    "status": "ok", "time": 0.001}
    fake_client = MagicMock()
    fake_client.put = AsyncMock(side_effect=lambda url, **kw: (captured.append(kw.get("json")), _FakeResp())[1])
    monkeypatch.setattr(legal_ediscovery, "shared_client", fake_client)

    successful, failure = await _upsert_to_qdrant_privileged(
        doc_id="d1", case_slug="test-case-i", file_name="x.eml",
        file_hash="h1", privileged_counsel_domain="fgplaw.com",
        role="case_i_phase_2_trial_and_general_counsel",
        privilege_type="attorney_client",
        chunks=["chunk-zero", "chunk-one", "chunk-two"],
        vectors=[[0.1] * 4, [0.2] * 4, [0.3] * 4],
    )
    assert failure is None
    assert len(successful) == 3
    points = captured[0]["points"]
    assert len(points) == 3
    for i, p in enumerate(points):
        payload = p["payload"]
        assert "chunk_num" in payload, f"chunk_num missing from payload[{i}]"
        assert "chunk_index" in payload, f"chunk_index missing from payload[{i}]"
        assert payload["chunk_num"] == i
        assert payload["chunk_index"] == i
        assert payload["chunk_num"] == payload["chunk_index"]
        # Spec-listed fields all present:
        for key in (
            "case_slug", "document_id", "file_name", "file_hash",
            "text", "privileged", "privileged_counsel_domain",
            "role", "privilege_type", "ingested_at",
        ):
            assert key in payload, f"required field {key} missing"
        assert payload["privileged"] is True
        assert payload["privileged_counsel_domain"] == "fgplaw.com"
        assert payload["role"] == "case_i_phase_2_trial_and_general_counsel"


# ════════════════════════════════════════════════════════════════════
# Domain → role + counsel-domain extraction helpers
# ════════════════════════════════════════════════════════════════════


def test_role_for_counsel_domain_maps_correctly() -> None:
    """Every domain in _DOMAIN_TO_ROLE round-trips."""
    for domain, expected_role in _DOMAIN_TO_ROLE.items():
        assert _role_for_counsel_domain(domain) == expected_role


def test_role_for_counsel_domain_returns_none_for_unknown() -> None:
    assert _role_for_counsel_domain("unknown-firm.com") is None
    assert _role_for_counsel_domain("") is None
    assert _role_for_counsel_domain(None) is None


def test_role_for_counsel_domain_is_case_insensitive() -> None:
    """A domain with mixed case still resolves (defensive against header parsing)."""
    assert _role_for_counsel_domain("MHTLEGAL.COM") == _DOMAIN_TO_ROLE["mhtlegal.com"]
    assert _role_for_counsel_domain("MhtLegal.COM") == _DOMAIN_TO_ROLE["mhtlegal.com"]


def test_derive_privileged_counsel_domain_from_eml_headers() -> None:
    """An .eml with mhtlegal.com in From → derived as mhtlegal.com."""
    eml_bytes = (
        b"From: Counsel Smith <counsel@mhtlegal.com>\r\n"
        b"To: Gary Knight <gary@cabin-rentals-of-georgia.com>\r\n"
        b"Subject: case strategy\r\n"
        b"\r\n"
        b"Body of privileged communication.\r\n"
    )
    out = _derive_privileged_counsel_domain(
        file_bytes=eml_bytes,
        file_name="incoming.eml",
        mime_type="message/rfc822",
        raw_text="extracted body",
    )
    assert out == "mhtlegal.com"


def test_derive_privileged_counsel_domain_from_to_header() -> None:
    """Outbound — Gary → counsel. domain matches via To header."""
    eml_bytes = (
        b"From: Gary Knight <gary@cabin-rentals-of-georgia.com>\r\n"
        b"To: Frank Podesta <fpodesta@fgplaw.com>\r\n"
        b"Subject: question about case\r\n"
        b"\r\n"
        b"Need your advice.\r\n"
    )
    out = _derive_privileged_counsel_domain(
        file_bytes=eml_bytes,
        file_name="outbound.eml",
        mime_type="message/rfc822",
        raw_text="Need your advice.",
    )
    assert out == "fgplaw.com"


def test_derive_privileged_counsel_domain_falls_back_to_text_scan() -> None:
    """Non-email file (PDF) — domain mention in body text triggers detection."""
    raw = (
        "Letter from counsel discussing case. Please reply to "
        "alicia@dralaw.com for further discussion."
    )
    out = _derive_privileged_counsel_domain(
        file_bytes=b"%PDF-1.4 not really pdf",
        file_name="memo.pdf",
        mime_type="application/pdf",
        raw_text=raw,
    )
    assert out == "dralaw.com"


def test_derive_privileged_counsel_domain_returns_none_when_no_match() -> None:
    """No known domain anywhere — derivation returns None (caller writes None to payload)."""
    out = _derive_privileged_counsel_domain(
        file_bytes=b"nothing about counsel",
        file_name="random.txt",
        mime_type="text/plain",
        raw_text="nothing about counsel — just business correspondence",
    )
    assert out is None


# ════════════════════════════════════════════════════════════════════
# Module-level constants — privileged collection name + warning text
# ════════════════════════════════════════════════════════════════════


def test_legal_privileged_communications_collection_constant() -> None:
    """The new collection name must match Phase C's PUT call exactly."""
    assert QDRANT_PRIVILEGED_COLLECTION == "legal_privileged_communications"
    assert COUNCIL_PRIV_COLLECTION == "legal_privileged_communications"
    # And it must be different from the work-product collection.
    assert QDRANT_PRIVILEGED_COLLECTION != QDRANT_COLLECTION


def test_for_your_eyes_only_warning_text_matches_spec() -> None:
    """If this string changes, the UI rendering + the in-band consensus_summary
    warning + the runbook all need to be updated together. Test catches drift."""
    from backend.services.legal_council import FOR_YOUR_EYES_ONLY_WARNING
    assert FOR_YOUR_EYES_ONLY_WARNING.startswith("⚠️ FOR YOUR EYES ONLY ⚠️")
    assert "attorney-client privileged communications" in FOR_YOUR_EYES_ONLY_WARNING
    assert "court filings" in FOR_YOUR_EYES_ONLY_WARNING
    assert "internal work product" in FOR_YOUR_EYES_ONLY_WARNING
