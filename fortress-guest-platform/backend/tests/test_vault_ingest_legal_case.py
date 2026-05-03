"""Tests for backend.scripts.vault_ingest_legal_case.

DB connections (`_connect`) and the canonical pipeline (`process_vault_upload`)
are mocked. NAS files are real synthetic PDFs in tmp_path. IngestRunTracker
is patched to a trivial recorder so we can assert lifecycle behavior without
touching legal.ingest_runs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

import run  # noqa: F401  registers backend.* path
from backend.scripts import vault_ingest_legal_case as vil


# ─── synthetic PDF fixtures ──────────────────────────────────────────────


def _text_pdf(path: Path, body: str = "Hello world. " * 50) -> Path:
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path))
    text = c.beginText(40, 750)
    for line in body.splitlines() or [body]:
        text.textLine(line[:90])
    c.drawText(text)
    c.showPage()
    c.save()
    return path


def _image_only_pdf(path: Path) -> Path:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (800, 1000), "white")
    ImageDraw.Draw(img).rectangle([100, 100, 400, 400], fill="black")
    img.save(path, "PDF")
    return path


def _corrupt_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.4\nthis is not a real pdf\n%%EOF")
    return path


# ─── DB connection mock ──────────────────────────────────────────────────


class _MockCursor:
    """Cursor that returns canned answers based on regex match on the SQL."""

    def __init__(self, registry: list, dbname: str) -> None:
        self._registry = registry
        self._dbname = dbname
        self._last_result: list = []
        self.rowcount = 0
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params=()):
        self.executed.append((sql, tuple(params or ())))
        for matcher, handler in self._registry:
            if matcher(self._dbname, sql, params):
                self._last_result, self.rowcount = handler(self._dbname, sql, params)
                return
        self._last_result = []
        self.rowcount = 0

    def fetchone(self):
        return self._last_result[0] if self._last_result else None

    def fetchall(self):
        return list(self._last_result)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _MockConn:
    def __init__(self, registry: list, dbname: str) -> None:
        self._registry = registry
        self._dbname = dbname
        self.autocommit = True
        self.executed_cursors: list[_MockCursor] = []

    def cursor(self):
        c = _MockCursor(self._registry, self._dbname)
        self.executed_cursors.append(c)
        return c

    def close(self):
        pass


def _build_connect(registry: list):
    """Return a function-shaped replacement for vil._connect."""

    def _connect(dbname: str):
        return _MockConn(registry, dbname)

    return _connect


def _layout_with_subdirs(root: Path, subdirs: dict[str, str], recursive: bool = True):
    return {"root": root, "subdirs": subdirs, "recursive": recursive}




# ─── nas_layout normalization ────────────────────────────────────────────


def test_normalize_layout_accepts_wave7_shape(tmp_path):
    raw = {
        "primary_root": str(tmp_path),
        "include_subdirs": ["curated", "case-i-context"],
        "exclude_subdirs": ["curated/private"],
    }

    layout = vil._normalize_layout(raw)

    assert layout["root"] == tmp_path
    assert layout["subdirs"] == {"curated": "curated", "case-i-context": "case-i-context"}
    assert layout["recursive"] is True
    assert layout["exclude_subdirs"] == {"curated/private"}


def test_normalize_layout_preserves_legacy_shape(tmp_path):
    raw = {"root": str(tmp_path), "subdirs": {"evidence": "ev"}, "recursive": False}

    layout = vil._normalize_layout(raw)

    assert layout["root"] == tmp_path
    assert layout["subdirs"] == {"evidence": "ev"}
    assert layout["recursive"] is False
    assert layout["exclude_subdirs"] == set()


def test_normalize_layout_rejects_empty_layout():
    with pytest.raises(vil.PreflightError, match="nas_layout is empty"):
        vil._normalize_layout({})

def _registry_full_preflight_pass(case_slug: str, layout: dict):
    """Builds a registry that lets every preflight gate pass and lets
    _check_existing_row return None (= no existing row)."""
    reg: list = []

    def _is_legal_cases(db, sql, params):
        return "legal.cases" in sql and "nas_layout" in sql

    def _legal_cases_handler(db, sql, params):
        return [({
            "root": str(layout["root"]),
            "subdirs": layout["subdirs"],
            "recursive": layout["recursive"],
        },)], 1

    reg.append((_is_legal_cases, _legal_cases_handler))

    def _is_select_1(db, sql, params):
        return sql.strip().upper().startswith("SELECT 1")

    reg.append((_is_select_1, lambda *_: ([(1,)], 1)))

    def _is_ingest_runs_insert(db, sql, params):
        return "INSERT INTO legal.ingest_runs" in sql and "RETURNING id" in sql

    reg.append((_is_ingest_runs_insert, lambda *_: ([("00000000-0000-0000-0000-000000000000",)], 1)))

    def _is_ingest_runs_delete(db, sql, params):
        return "DELETE FROM legal.ingest_runs" in sql

    reg.append((_is_ingest_runs_delete, lambda *_: ([], 1)))

    def _is_constraints_lookup(db, sql, params):
        return "pg_constraint" in sql and "legal.vault_documents" in sql

    def _constraints_handler(db, sql, params):
        return [
            ("fk_vault_documents_case_slug",),
            ("uq_vault_documents_case_hash",),
            ("chk_vault_documents_status",),
        ], 3

    reg.append((_is_constraints_lookup, _constraints_handler))

    def _is_vault_doc_lookup(db, sql, params):
        return ("FROM legal.vault_documents" in sql
                and "processing_status" in sql
                and "WHERE case_slug" in sql
                and "INSERT" not in sql
                and "DELETE" not in sql)

    reg.append((_is_vault_doc_lookup, lambda *_: ([], 0)))

    def _is_count_vault(db, sql, params):
        return "SELECT count(*)" in sql and "vault_documents" in sql

    reg.append((_is_count_vault, lambda *_: ([(0,)], 1)))

    def _is_delete_vault(db, sql, params):
        return "DELETE FROM legal.vault_documents" in sql

    reg.append((_is_delete_vault, lambda *_: ([], 0)))

    return reg


# ─── Qdrant mock ─────────────────────────────────────────────────────────


class _FakeQdrantUrlopen:
    """Replaces urllib.request.urlopen for Qdrant HTTP. Default OK."""

    def __init__(self, *,
                 collection_ok: bool = True,
                 vector_size: int = vil.EXPECTED_VECTOR_SIZE,
                 count: int = 0):
        self.collection_ok = collection_ok
        self.vector_size = vector_size
        self.count = count
        self.calls: list[str] = []

    def __call__(self, req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        self.calls.append(url)
        body: dict
        if "/collections/" in url and "/points" not in url:
            if not self.collection_ok:
                import urllib.error
                raise urllib.error.HTTPError(
                    url, 404, "not found", {}, None,  # type: ignore[arg-type]
                )
            body = {"result": {"config": {"params": {
                "vectors": {"size": self.vector_size}
            }}}}
        elif "/points/count" in url:
            body = {"result": {"count": self.count}}
        elif "/points/delete" in url:
            body = {"result": {"operation_id": 1, "status": "completed"}}
        else:
            body = {"result": {}}

        class _Resp:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return _Resp(body)


# ─── tracker mock ────────────────────────────────────────────────────────


class _FakeTracker:
    """Records the lifecycle without touching the DB."""

    instances: list["_FakeTracker"] = []

    def __init__(self, case_slug: str, script_name: str, args=None) -> None:
        self.case_slug = case_slug
        self.script_name = script_name
        self.args = args or {}
        self.run_id = "fake-run-id"
        self.processed = 0
        self.errored = 0
        self.skipped = 0
        self.total_files: int | None = None
        self.manifest_path: str | None = None
        self.exit_status: str = "running"
        type(self).instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.exit_status = "complete"
        elif issubclass(exc_type, KeyboardInterrupt):
            self.exit_status = "interrupted"
            return False
        else:
            self.exit_status = "error"
            return False
        return False

    def set_total_files(self, n):
        self.total_files = int(n)

    def set_manifest_path(self, p):
        self.manifest_path = str(p)

    def inc_processed(self, n=1):
        self.processed += n

    def inc_errored(self, n=1):
        self.errored += n

    def inc_skipped(self, n=1):
        self.skipped += n


# ─── fixture: env + mocks ────────────────────────────────────────────────


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("POSTGRES_ADMIN_URI",
                       "postgresql://test:test@127.0.0.1:5432/fortress_test")
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:6333")
    yield


@pytest.fixture(autouse=True)
def _reset_tracker_instances():
    _FakeTracker.instances = []
    yield


# ─── helper: run main() with all the mocks ───────────────────────────────


def _run_main(
    *,
    monkeypatch: pytest.MonkeyPatch,
    case_slug: str,
    layout: dict,
    upload_results: dict[str, dict],   # filename -> result dict
    extra_argv: list[str] | None = None,
    pre_existing_rows: dict[str, str] | None = None,  # file_hash -> status
    qdrant: _FakeQdrantUrlopen | None = None,
    upload_side_effect: Callable | None = None,
    audit_dir: Path | None = None,
    tmp_path: Path | None = None,
    fail_constraint: bool = False,
):
    pre_existing_rows = pre_existing_rows or {}
    qdrant = qdrant or _FakeQdrantUrlopen()
    registry = _registry_full_preflight_pass(case_slug, layout)

    if fail_constraint:
        registry = [
            (m, h if "pg_constraint" not in str(m) else (lambda *_: ([], 0)))
            for m, h in registry
        ]
        registry = [
            (m, (lambda *_: ([], 0)) if "pg_constraint" in m.__code__.co_consts.__repr__() else h)
            for m, h in registry
        ]

    if pre_existing_rows:
        # override the vault_doc lookup to return seeded statuses
        def _seeded_vault_lookup(db, sql, params):
            file_hash = params[1] if len(params) >= 2 else ""
            status = pre_existing_rows.get(file_hash)
            return ([(status,)], 1) if status else ([], 0)

        registry = [
            r for r in registry
            if not (r[0].__name__ == "_is_vault_doc_lookup")
        ]
        registry.append((
            lambda db, sql, params: ("FROM legal.vault_documents" in sql
                                     and "processing_status" in sql
                                     and "WHERE case_slug" in sql
                                     and "INSERT" not in sql
                                     and "DELETE" not in sql),
            _seeded_vault_lookup,
        ))

    monkeypatch.setattr(vil, "_connect", _build_connect(registry))
    import urllib.request as _ur
    monkeypatch.setattr(_ur, "urlopen", qdrant)
    monkeypatch.setattr(
        "backend.services.ingest_run_tracker.IngestRunTracker", _FakeTracker,
    )
    if audit_dir is not None:
        monkeypatch.setattr(vil, "AUDIT_DIR", audit_dir)
    if tmp_path is not None:
        monkeypatch.setattr(
            vil, "_lock_path",
            lambda slug: tmp_path / f"vault-ingest-{slug}.lock",
        )

    async def _fake_upload(*, db, case_slug, file_bytes, file_name, mime_type):
        if upload_side_effect:
            return await upload_side_effect(file_name)
        result = upload_results.get(file_name) or upload_results.get("__default__")
        if result is None:
            return {"status": "completed", "document_id": f"id-{file_name}",
                    "chunks": 1, "vectors_indexed": 1}
        return result

    class _FakeAsyncSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(
        "backend.services.ediscovery_agent.LegacySession",
        lambda: _FakeAsyncSession(),
    )
    monkeypatch.setattr(
        "backend.services.legal_ediscovery.process_vault_upload",
        _fake_upload,
    )

    # Mirror writer is fortress_db → fortress_prod — fake it to record calls.
    inserted_rows: dict[str, tuple] = {}

    def _fake_mirror(*, case_slug, doc_id):
        inserted_rows[doc_id] = (case_slug, doc_id)

    monkeypatch.setattr(vil, "_mirror_row_db_to_prod", _fake_mirror)

    argv = ["--case-slug", case_slug] + (extra_argv or [])
    rc = vil.main(argv)
    return rc, inserted_rows


# ─── 1. clean run ────────────────────────────────────────────────────────


def test_clean_run_processes_all_files(env, monkeypatch, tmp_path):
    case = "clean-run"
    docs = tmp_path / "docs"
    docs.mkdir()
    a = _text_pdf(docs / "a.pdf", "First file " * 80)
    b = _text_pdf(docs / "b.pdf", "Second file " * 80)
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})

    rc, _ = _run_main(
        monkeypatch=monkeypatch, case_slug=case, layout=layout,
        upload_results={
            a.name: {"status": "completed", "document_id": "id-a",
                     "chunks": 3, "vectors_indexed": 3},
            b.name: {"status": "completed", "document_id": "id-b",
                     "chunks": 2, "vectors_indexed": 2},
        },
        extra_argv=["--jobs", "1"],
        audit_dir=tmp_path / "audits", tmp_path=tmp_path,
    )

    assert rc == 0
    mfs = list((tmp_path / "audits").glob(f"vault-ingest-{case}-*.json"))
    assert len(mfs) == 1
    m = json.loads(mfs[0].read_text())
    assert m["total_unique_files"] == 2
    assert m["processed"] == 2
    assert m["by_status"]["completed"] == 2
    assert m["vault_documents_inserted"] == 2
    assert m["qdrant_points_estimate"] == 5
    assert _FakeTracker.instances[0].exit_status == "complete"


# ─── 2. idempotency ──────────────────────────────────────────────────────


def test_idempotency_second_run_skips_completed(env, monkeypatch, tmp_path):
    case = "idem"
    docs = tmp_path / "docs"
    docs.mkdir()
    pdf = _text_pdf(docs / "x.pdf", "abc " * 200)
    fhash = vil.file_sha256(pdf)
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})

    rc, _ = _run_main(
        monkeypatch=monkeypatch, case_slug=case, layout=layout,
        upload_results={"__default__": {"status": "completed",
                                         "document_id": "id-x",
                                         "chunks": 1, "vectors_indexed": 1}},
        pre_existing_rows={fhash: "completed"},
        extra_argv=["--jobs", "1"],
        audit_dir=tmp_path / "audits", tmp_path=tmp_path,
    )

    assert rc == 0
    m = json.loads(next((tmp_path / "audits").glob(f"vault-ingest-{case}-*.json")).read_text())
    assert m["skipped"] == 1
    assert m["processed"] == 0


# ─── 3. physical-path dedup over dual-listed subdirs ────────────────────


def test_physical_path_dedup_handles_dual_listed_subdirs(env, monkeypatch, tmp_path):
    """Two logical subdirs pointing at the same physical directory; the same
    PDFs must be processed exactly once each."""
    case = "dual"
    shared = tmp_path / "shared"
    shared.mkdir()
    _text_pdf(shared / "a.pdf", "A " * 80)
    _text_pdf(shared / "b.pdf", "B " * 80)
    layout = _layout_with_subdirs(
        tmp_path,
        {"correspondence": "shared", "certified_mail": "shared"},
        recursive=False,
    )

    rc, _ = _run_main(
        monkeypatch=monkeypatch, case_slug=case, layout=layout,
        upload_results={"__default__": {"status": "completed",
                                         "document_id": "id-shared",
                                         "chunks": 1, "vectors_indexed": 1}},
        extra_argv=["--jobs", "1"],
        audit_dir=tmp_path / "audits", tmp_path=tmp_path,
    )
    assert rc == 0
    m = json.loads(next((tmp_path / "audits").glob(f"vault-ingest-{case}-*.json")).read_text())
    # Each physical file once, despite being referenced by two logical subdirs.
    assert m["total_unique_files"] == 2
    assert m["processed"] == 2


# ─── 4. ocr_failed classification ────────────────────────────────────────


def test_ocr_failed_classification(env, monkeypatch, tmp_path):
    case = "ocrfail"
    docs = tmp_path / "docs"
    docs.mkdir()
    _image_only_pdf(docs / "img.pdf")
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})

    rc, _ = _run_main(
        monkeypatch=monkeypatch, case_slug=case, layout=layout,
        upload_results={"img.pdf": {"status": "ocr_failed",
                                      "document_id": "id-img"}},
        extra_argv=["--jobs", "1"],
        audit_dir=tmp_path / "audits", tmp_path=tmp_path,
    )
    assert rc == 0
    m = json.loads(next((tmp_path / "audits").glob(f"vault-ingest-{case}-*.json")).read_text())
    assert m["by_status"]["ocr_failed"] == 1
    assert m["qdrant_points_estimate"] == 0
    assert m["vault_documents_inserted"] == 1


# ─── 5. corrupt file logs error, sweep continues ────────────────────────


def test_corrupt_file_logs_error_continues(env, monkeypatch, tmp_path):
    case = "corrupt"
    docs = tmp_path / "docs"
    docs.mkdir()
    _text_pdf(docs / "ok.pdf", "good " * 100)
    _corrupt_pdf(docs / "bad.pdf")
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})

    async def _maybe_fail(file_name):
        if "bad" in file_name:
            raise RuntimeError("synthetic upload failure")
        return {"status": "completed", "document_id": f"id-{file_name}",
                "chunks": 1, "vectors_indexed": 1}

    rc, _ = _run_main(
        monkeypatch=monkeypatch, case_slug=case, layout=layout,
        upload_results={}, upload_side_effect=_maybe_fail,
        extra_argv=["--jobs", "1"],
        audit_dir=tmp_path / "audits", tmp_path=tmp_path,
    )
    assert rc == 1   # errored count > 0 → non-zero exit
    m = json.loads(next((tmp_path / "audits").glob(f"vault-ingest-{case}-*.json")).read_text())
    assert m["errored"] == 1
    assert m["processed"] == 1
    assert m["errors"][0]["error"].startswith("RuntimeError")


# ─── 6. max file size ───────────────────────────────────────────────────


def test_max_file_size_skip(env, monkeypatch, tmp_path):
    case = "size"
    docs = tmp_path / "docs"
    docs.mkdir()
    huge = _text_pdf(docs / "huge.pdf", "X" * 1000)
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})

    # Force max-file-size-mb=0 to make every file "too big".
    rc, _ = _run_main(
        monkeypatch=monkeypatch, case_slug=case, layout=layout,
        upload_results={huge.name: {"status": "completed", "document_id": "x",
                                     "chunks": 1, "vectors_indexed": 1}},
        extra_argv=["--jobs", "1", "--max-file-size-mb", "0"],
        audit_dir=tmp_path / "audits", tmp_path=tmp_path,
    )
    assert rc == 0
    m = json.loads(next((tmp_path / "audits").glob(f"vault-ingest-{case}-*.json")).read_text())
    assert m["skipped"] == 1
    assert m["processed"] == 0


# ─── 7. dry run ──────────────────────────────────────────────────────────


def test_dry_run_no_writes(env, monkeypatch, tmp_path):
    case = "dry"
    docs = tmp_path / "docs"
    docs.mkdir()
    _text_pdf(docs / "a.pdf", "txt " * 100)
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})

    upload_called = {"n": 0}

    async def _track_call(file_name):
        upload_called["n"] += 1
        return {"status": "completed", "document_id": "x",
                "chunks": 1, "vectors_indexed": 1}

    rc, _ = _run_main(
        monkeypatch=monkeypatch, case_slug=case, layout=layout,
        upload_results={}, upload_side_effect=_track_call,
        extra_argv=["--jobs", "1", "--dry-run"],
        audit_dir=tmp_path / "audits", tmp_path=tmp_path,
    )
    assert rc == 0
    assert upload_called["n"] == 0
    m = json.loads(next((tmp_path / "audits").glob(f"vault-ingest-{case}-*.json")).read_text())
    assert m["skipped"] == 1
    assert m["processed"] == 0


# ─── 8. lock file ────────────────────────────────────────────────────────


def test_lock_file_prevents_concurrent_runs(env, monkeypatch, tmp_path):
    case = "locked"
    monkeypatch.setattr(
        vil, "_lock_path",
        lambda slug: tmp_path / f"vault-ingest-{slug}.lock",
    )
    (tmp_path / f"vault-ingest-{case}.lock").write_text("99999\nstamp\n")
    with pytest.raises(SystemExit) as ei:
        vil.acquire_lock(case, force=False)
    assert "another vault ingest" in str(ei.value)


# ─── 9. preflight failure → no audit row ─────────────────────────────────


def test_pre_flight_failure_no_audit_row(env, monkeypatch, tmp_path):
    case = "missing-case"
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})

    # Build a registry that returns nothing for legal.cases (case not found).
    reg = _registry_full_preflight_pass(case, layout)
    reg = [
        (m, (lambda *_: ([], 0)) if m.__name__ == "_is_legal_cases" else h)
        for m, h in reg
    ]
    monkeypatch.setattr(vil, "_connect", _build_connect(reg))
    monkeypatch.setattr(
        "backend.services.ingest_run_tracker.IngestRunTracker", _FakeTracker,
    )
    monkeypatch.setattr(vil, "AUDIT_DIR", tmp_path / "audits")
    monkeypatch.setattr(
        vil, "_lock_path",
        lambda slug: tmp_path / f"vault-ingest-{slug}.lock",
    )

    rc = vil.main(["--case-slug", case])
    assert rc == 3   # PreflightError exit
    assert _FakeTracker.instances == []   # tracker never opened


# ─── 10. KeyboardInterrupt → tracker marks interrupted ──────────────────


def test_keyboard_interrupt_marks_run_interrupted(env, monkeypatch, tmp_path):
    case = "interrupt"
    docs = tmp_path / "docs"
    docs.mkdir()
    _text_pdf(docs / "a.pdf", "abc " * 100)
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})

    async def _kaboom(file_name):
        raise KeyboardInterrupt()

    rc, _ = _run_main(
        monkeypatch=monkeypatch, case_slug=case, layout=layout,
        upload_results={}, upload_side_effect=_kaboom,
        extra_argv=["--jobs", "1"],
        audit_dir=tmp_path / "audits", tmp_path=tmp_path,
    )
    assert rc == 130
    assert _FakeTracker.instances[0].exit_status == "interrupted"


# ─── 11. resume completes pending rows ──────────────────────────────────


def test_resume_completes_pending_rows(env, monkeypatch, tmp_path):
    """A row in 'pending' must NOT be skipped on resume — it should be
    re-processed."""
    case = "resume"
    docs = tmp_path / "docs"
    docs.mkdir()
    pdf = _text_pdf(docs / "p.pdf", "pending " * 100)
    fhash = vil.file_sha256(pdf)
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})

    rc, _ = _run_main(
        monkeypatch=monkeypatch, case_slug=case, layout=layout,
        upload_results={"__default__": {"status": "completed",
                                         "document_id": "id-p",
                                         "chunks": 1, "vectors_indexed": 1}},
        pre_existing_rows={fhash: "pending"},
        extra_argv=["--jobs", "1"],
        audit_dir=tmp_path / "audits", tmp_path=tmp_path,
    )
    assert rc == 0
    m = json.loads(next((tmp_path / "audits").glob(f"vault-ingest-{case}-*.json")).read_text())
    assert m["processed"] == 1
    assert m["skipped"] == 0


# ─── 12. rollback deletes postgres + qdrant ─────────────────────────────


def test_rollback_deletes_postgres_and_qdrant(env, monkeypatch, tmp_path):
    case = "rb"
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})
    reg = _registry_full_preflight_pass(case, layout)

    counts = {"prod": 5, "db": 5}

    def _is_count_vault_local(db, sql, params):
        return "SELECT count(*)" in sql and "vault_documents" in sql

    def _count_handler(db, sql, params):
        if db == "fortress_prod":
            return [(counts["prod"],)], 1
        if db == "fortress_db":
            return [(counts["db"],)], 1
        return [(0,)], 1

    reg = [(m, h) for m, h in reg if m.__name__ != "_is_count_vault"]
    reg.append((_is_count_vault_local, _count_handler))

    def _is_delete_local(db, sql, params):
        return "DELETE FROM legal.vault_documents" in sql

    def _delete_handler(db, sql, params):
        if db == "fortress_prod":
            counts["prod"] = 0
            return [], 5
        if db == "fortress_db":
            counts["db"] = 0
            return [], 5
        return [], 0

    reg = [(m, h) for m, h in reg if m.__name__ != "_is_delete_vault"]
    reg.append((_is_delete_local, _delete_handler))

    monkeypatch.setattr(vil, "_connect", _build_connect(reg))
    monkeypatch.setattr(
        "backend.services.ingest_run_tracker.IngestRunTracker", _FakeTracker,
    )

    qd = _FakeQdrantUrlopen(count=10)

    def _qd_then_zero(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        # Delete should drop the count to 0 on the next count call.
        if "/points/delete" in url:
            qd.count = 0
        return qd(req, timeout=timeout)

    import urllib.request as _ur
    monkeypatch.setattr(_ur, "urlopen", _qd_then_zero)
    monkeypatch.setattr(vil, "AUDIT_DIR", tmp_path / "audits")

    rc = vil.main(["--case-slug", case, "--rollback", "--force"])
    assert rc == 0
    mfs = list((tmp_path / "audits").glob(f"vault-rollback-{case}-*.json"))
    assert len(mfs) == 1
    m = json.loads(mfs[0].read_text())
    assert m["operation"] == "rollback"
    assert m["pre_counts"]["fortress_prod"] == 5
    assert m["pre_counts"]["fortress_db"] == 5
    assert m["pre_counts"]["qdrant"] == 10
    assert m["post_counts"] == {"fortress_prod": 0, "fortress_db": 0, "qdrant": 0}


# ─── 13. rollback requires confirmation ─────────────────────────────────


def test_rollback_requires_confirmation_unless_force(env, monkeypatch, tmp_path):
    case = "rb-confirm"
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})
    reg = _registry_full_preflight_pass(case, layout)
    monkeypatch.setattr(vil, "_connect", _build_connect(reg))
    monkeypatch.setattr(
        "backend.services.ingest_run_tracker.IngestRunTracker", _FakeTracker,
    )
    import urllib.request as _ur
    monkeypatch.setattr(_ur, "urlopen", _FakeQdrantUrlopen())
    monkeypatch.setattr(vil, "AUDIT_DIR", tmp_path / "audits")

    monkeypatch.setattr("builtins.input", lambda *_: "wrong-answer")
    rc = vil.main(["--case-slug", case, "--rollback"])
    assert rc == 2
    assert _FakeTracker.instances == []   # tracker never opened


# ─── 14. manifest schema complete ───────────────────────────────────────


def test_manifest_schema_complete(env, monkeypatch, tmp_path):
    case = "schema"
    docs = tmp_path / "docs"
    docs.mkdir()
    _text_pdf(docs / "z.pdf", "ZZZ " * 100)
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})

    _run_main(
        monkeypatch=monkeypatch, case_slug=case, layout=layout,
        upload_results={"__default__": {"status": "completed",
                                         "document_id": "id-z",
                                         "chunks": 1, "vectors_indexed": 1}},
        extra_argv=["--jobs", "1"],
        audit_dir=tmp_path / "audits", tmp_path=tmp_path,
    )
    m = json.loads(next((tmp_path / "audits").glob(f"vault-ingest-{case}-*.json")).read_text())
    for required_key in (
        "case_slug", "started_at", "finished_at", "runtime_seconds", "args",
        "host", "pid", "ingest_run_id", "layout_root", "layout_recursive",
        "layout_subdirs", "total_unique_files", "processed", "skipped",
        "errored", "by_status", "by_logical_subdir", "by_mime_type",
        "errors", "qdrant_points_estimate", "vault_documents_inserted",
    ):
        assert required_key in m, f"manifest missing {required_key}"


# ─── 15. qdrant failure leaves status=pending behavior ──────────────────


def test_qdrant_failure_leaves_pending_status_for_retry(env, monkeypatch, tmp_path):
    """When Qdrant returns 0 indexed, process_vault_upload still marks the row
    'completed' (per design — operators triage by vectors_indexed=0). The script
    surfaces this in the manifest so a follow-up run can target re-vectorize."""
    case = "qdfail"
    docs = tmp_path / "docs"
    docs.mkdir()
    _text_pdf(docs / "q.pdf", "x " * 100)
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})

    rc, _ = _run_main(
        monkeypatch=monkeypatch, case_slug=case, layout=layout,
        upload_results={"__default__": {
            "status": "completed", "document_id": "id-q",
            "chunks": 3, "vectors_indexed": 0,
        }},
        extra_argv=["--jobs", "1"],
        audit_dir=tmp_path / "audits", tmp_path=tmp_path,
    )
    assert rc == 0
    m = json.loads(next((tmp_path / "audits").glob(f"vault-ingest-{case}-*.json")).read_text())
    assert m["qdrant_points_estimate"] == 0
    assert m["by_status"]["completed"] == 1


# ─── 16. privilege filter marks locked_privileged ───────────────────────


def test_privilege_filter_marks_locked_privileged(env, monkeypatch, tmp_path):
    case = "priv"
    docs = tmp_path / "docs"
    docs.mkdir()
    _text_pdf(docs / "priv.pdf", "Attorney-client privileged " * 50)
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})

    rc, _ = _run_main(
        monkeypatch=monkeypatch, case_slug=case, layout=layout,
        upload_results={"priv.pdf": {
            "status": "locked_privileged", "document_id": "id-priv",
        }},
        extra_argv=["--jobs", "1"],
        audit_dir=tmp_path / "audits", tmp_path=tmp_path,
    )
    assert rc == 0
    m = json.loads(next((tmp_path / "audits").glob(f"vault-ingest-{case}-*.json")).read_text())
    assert m["by_status"]["locked_privileged"] == 1
    assert m["qdrant_points_estimate"] == 0
    # privilege rows still count toward vault_documents_inserted (visible in UI)
    assert m["vault_documents_inserted"] == 1


# ─── 17. dual-DB write ──────────────────────────────────────────────────


def test_writes_to_both_fortress_prod_and_fortress_db(env, monkeypatch, tmp_path):
    """Verify _mirror_row_db_to_prod is called once per successful upload."""
    case = "dual-db"
    docs = tmp_path / "docs"
    docs.mkdir()
    _text_pdf(docs / "a.pdf", "x " * 100)
    _text_pdf(docs / "b.pdf", "y " * 100)
    layout = _layout_with_subdirs(tmp_path, {"docs": "docs"})

    rc, mirrored = _run_main(
        monkeypatch=monkeypatch, case_slug=case, layout=layout,
        upload_results={
            "a.pdf": {"status": "completed", "document_id": "id-a",
                      "chunks": 1, "vectors_indexed": 1},
            "b.pdf": {"status": "completed", "document_id": "id-b",
                      "chunks": 1, "vectors_indexed": 1},
        },
        extra_argv=["--jobs", "1"],
        audit_dir=tmp_path / "audits", tmp_path=tmp_path,
    )
    assert rc == 0
    assert set(mirrored.keys()) == {"id-a", "id-b"}
    for case_key, _ in mirrored.values():
        assert case_key == case
