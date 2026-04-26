"""
reprocess_failed_qdrant_uploads.py — Phase D/G of the Issue #228 fix.

Re-runs the (privilege classifier → chunker → embedder → batched upsert)
portion of ``process_vault_upload`` against existing ``legal.vault_documents``
rows that ended up in a Qdrant-failed state. The original NFS file is kept
in place; the row identity (``id``) is preserved.

Targets
-------
Candidate predicate (matches either branch)::

    processing_status = 'qdrant_upsert_failed'
    OR (vector_ids IS NULL AND chunk_count > 0)

Idempotency
-----------
Phase B.1 made both Qdrant collections deterministic — point IDs are
``uuid5(NS, f"{file_hash}:{chunk_index}")``. Re-running this script on a
row that has already been recovered is a clean no-op:

    * The candidate predicate excludes rows whose ``vector_ids`` is set and
      whose status is no longer ``qdrant_upsert_failed``.
    * Even if a partially-recovered row is re-attempted, the upsert PUT
      overwrites the same point IDs with the same payload — no orphan
      points, no duplicate embeddings.

Bilateral DB write
------------------
``process_vault_upload`` writes the row state to ``fortress_db`` (the
LegacySession target — what the FastAPI handlers and operator UI read).
This script mirrors the final row state to ``fortress_prod`` after each
successful per-row write, mirroring the contract used by
``vault_ingest_legal_case._mirror_row_db_to_prod``. Mirror drift (one DB
updated, the other already at terminal state) is tracked and surfaced as
exit code 2 so the operator can investigate.

Audit
-----
``IngestRunTracker`` emits a single ``legal.ingest_runs`` row with
``script_name='reprocess_failed_qdrant_uploads'``. The per-run JSON manifest
is written to ``/mnt/fortress_nas/audits/reprocess-{slug}-{ts}.json``.

Pipeline scope
--------------
The reprocess pipeline runs the upsert-relevant subset of
``process_vault_upload``:

    1. Read file bytes from ``nfs_path``.
    2. ``_extract_text`` for the original mime + name.
    3. ``_classify_privilege`` — if privileged at confidence ≥ 0.7, route to
       the privileged collection; otherwise to the work-product collection.
    4. ``_chunk_document`` → ``_embed_chunks`` → batched upsert (Phase B
       path, with Phase B.1 UUID5 IDs).
    5. UPDATE the existing row's terminal state in both DBs.

It does NOT re-run:

    * The fast-dup check (we are intentionally re-touching an existing row).
    * ``_log_privilege`` (the privilege-log row already exists for any row
      that was previously routed to the privileged track).
    * ``_emit_docket_updated_event`` (the docket event fires once per
      original upload — re-firing it on a reprocess would double-emit).
    * Email-CSV dedupe / threading (re-running the dedupe engine on the
      same archive is out of scope and would not fix a Qdrant failure).
    * Image-only-PDF guard (rows with ``chunk_count > 0`` already passed
      extraction; for the small set of rows where extraction now returns
      empty text on rerun, we record an ``empty_extraction`` skip rather
      than mutate the row to ``ocr_failed``).

Usage
-----
::

    # Dry-run first — surfaces the planned reprocess set without touching
    # Qdrant or the DBs.
    python -m backend.scripts.reprocess_failed_qdrant_uploads \\
        --case-slug 7il-v-knight-ndga --dry-run

    # Targeted: only the doc IDs in the file (one UUID per line).
    python -m backend.scripts.reprocess_failed_qdrant_uploads \\
        --case-slug 7il-v-knight-ndga \\
        --doc-id-file /tmp/vanderburge-228-failed-001.txt

    # Staged batch: cap at N candidates (then re-run for the next batch).
    python -m backend.scripts.reprocess_failed_qdrant_uploads \\
        --case-slug 7il-v-knight-ndga --limit 250
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import socket
import sys
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("reprocess_failed_qdrant_uploads")

# ─── config ────────────────────────────────────────────────────────────────

ENV_PATH = Path("/home/admin/Fortress-Prime/fortress-guest-platform/.env")
AUDIT_DIR = Path("/mnt/fortress_nas/audits")

QDRANT_WORK_PRODUCT_COLLECTION = "legal_ediscovery"
QDRANT_PRIVILEGED_COLLECTION = "legal_privileged_communications"

# DBs that hold legal.vault_documents (kept in lock-step by vault ingestion).
TARGET_DBS = ("fortress_db", "fortress_prod")

# Candidate predicate — Phase D scope.
_CANDIDATE_PREDICATE = (
    "case_slug = %s "
    "AND ("
    "  processing_status = 'qdrant_upsert_failed' "
    "  OR (vector_ids IS NULL AND chunk_count > 0)"
    ")"
)


# ─── env + DSN ────────────────────────────────────────────────────────────


def _read_env_pgs() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV_PATH.exists():
        return out
    for raw in ENV_PATH.read_text().splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _ensure_env_loaded() -> None:
    """Best-effort .env load — only sets vars that aren't already in environ."""
    for k, v in _read_env_pgs().items():
        os.environ.setdefault(k, v)


@dataclass
class _DSN:
    host: str
    port: int
    user: str
    password: str
    db: str


def _parse_admin_dsn(dbname: str) -> _DSN:
    uri = os.environ.get("POSTGRES_ADMIN_URI", "")
    m = re.match(
        r"postgresql(?:\+\w+)?://([^:]+):([^@]+)@([^:/]+):?(\d+)?/[^?]+",
        uri,
    )
    if not m:
        raise SystemExit(
            "POSTGRES_ADMIN_URI not set or unparseable in environ; "
            "load .env first"
        )
    user, pw, host, port = m.groups()
    return _DSN(host=host, port=int(port or 5432), user=user, password=pw, db=dbname)


def _connect(dbname: str):
    import psycopg2
    dsn = _parse_admin_dsn(dbname)
    conn = psycopg2.connect(
        host=dsn.host, port=dsn.port, user=dsn.user,
        password=dsn.password, dbname=dsn.db,
    )
    conn.autocommit = True
    return conn


def _qdrant_url() -> str:
    url = os.environ.get("QDRANT_URL", "").rstrip("/")
    if not url:
        raise SystemExit("QDRANT_URL not set in environ; load .env first")
    return url


# ─── pre-flight ────────────────────────────────────────────────────────────


class PreflightError(Exception):
    pass


def _preflight_case_exists(case_slug: str) -> None:
    """case_slug must be present in BOTH target DBs."""
    for dbname in TARGET_DBS:
        conn = _connect(dbname)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM legal.cases WHERE case_slug = %s",
                    (case_slug,),
                )
                if cur.fetchone() is None:
                    raise PreflightError(
                        f"case_slug {case_slug!r} not found in {dbname}.legal.cases"
                    )
        finally:
            conn.close()


def _preflight_vector_ids_column() -> None:
    """Phase A migration must be applied (column + partial index)."""
    for dbname in TARGET_DBS:
        conn = _connect(dbname)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'legal' "
                    "AND table_name = 'vault_documents' "
                    "AND column_name = 'vector_ids'"
                )
                if cur.fetchone() is None:
                    raise PreflightError(
                        f"{dbname}.legal.vault_documents.vector_ids missing — "
                        f"apply Phase A migration n9a1b2c3d4e5"
                    )
        finally:
            conn.close()


def _preflight_status_constraint() -> None:
    """Phase A.1 must allow processing_status = 'qdrant_upsert_failed'."""
    test_value = "qdrant_upsert_failed"
    for dbname in TARGET_DBS:
        conn = _connect(dbname)
        try:
            with conn.cursor() as cur:
                # Probe the CHECK constraint by inspecting consrc text.
                # If qdrant_upsert_failed is not in the allowed set, this
                # text won't contain it.
                cur.execute(
                    "SELECT pg_get_constraintdef(c.oid) "
                    "FROM pg_constraint c "
                    "JOIN pg_class t ON c.conrelid = t.oid "
                    "JOIN pg_namespace n ON t.relnamespace = n.oid "
                    "WHERE n.nspname = 'legal' "
                    "AND t.relname = 'vault_documents' "
                    "AND c.conname = 'chk_vault_documents_status'"
                )
                row = cur.fetchone()
                if row is None:
                    raise PreflightError(
                        f"{dbname}.legal.vault_documents missing chk_vault_documents_status"
                    )
                if test_value not in (row[0] or ""):
                    raise PreflightError(
                        f"{dbname}.chk_vault_documents_status does not allow "
                        f"{test_value!r} — apply Phase A.1 migration"
                    )
        finally:
            conn.close()


def _preflight_qdrant_reachable() -> None:
    base = _qdrant_url()
    # Work-product collection is mandatory; privileged is optional on
    # clusters that have never run a privileged-track upload.
    for col, mandatory in (
        (QDRANT_WORK_PRODUCT_COLLECTION, True),
        (QDRANT_PRIVILEGED_COLLECTION, False),
    ):
        try:
            with urllib.request.urlopen(f"{base}/collections/{col}", timeout=10) as r:
                r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                if mandatory:
                    raise PreflightError(
                        f"qdrant collection {col!r} not found at {base}"
                    ) from exc
                logger.info(
                    "preflight_qdrant_collection_absent collection=%s "
                    "(privileged-track reprocess will be skipped if needed)", col,
                )
            else:
                raise PreflightError(
                    f"qdrant collection {col!r} reachable but errored: {exc.code}"
                ) from exc
        except Exception as exc:
            raise PreflightError(
                f"qdrant unreachable at {base}: {type(exc).__name__}:{exc!s}"
            ) from exc


def run_preflight(case_slug: str) -> None:
    _preflight_case_exists(case_slug)
    _preflight_vector_ids_column()
    _preflight_status_constraint()
    _preflight_qdrant_reachable()


# ─── candidate selection ─────────────────────────────────────────────────


@dataclass
class _Candidate:
    doc_id: str
    file_name: str
    nfs_path: str
    mime_type: str
    file_hash: str
    chunk_count: int
    processing_status: str


def _list_candidates(
    case_slug: str,
    doc_id_filter: Optional[set[str]],
    limit: Optional[int],
) -> list[_Candidate]:
    """Read candidate rows from fortress_db.

    The fortress_prod mirror is updated row-for-row at write time, so its
    candidate set is identical by construction.
    """
    conn = _connect("fortress_db")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id::text, file_name, nfs_path, mime_type, "
                "       file_hash, COALESCE(chunk_count, 0), processing_status "
                "FROM legal.vault_documents "
                f"WHERE {_CANDIDATE_PREDICATE} "
                "ORDER BY created_at NULLS LAST, id",
                (case_slug,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    candidates = [
        _Candidate(
            doc_id=r[0], file_name=str(r[1] or ""), nfs_path=str(r[2] or ""),
            mime_type=str(r[3] or ""), file_hash=str(r[4] or ""),
            chunk_count=int(r[5]), processing_status=str(r[6] or ""),
        )
        for r in rows
    ]

    if doc_id_filter is not None:
        candidates = [c for c in candidates if c.doc_id in doc_id_filter]

    if limit is not None and limit > 0:
        candidates = candidates[:limit]

    return candidates


def _read_doc_id_file(path: Path) -> set[str]:
    """One UUID per line; ignore blanks and lines starting with #."""
    out: set[str] = set()
    if not path.exists():
        raise SystemExit(f"--doc-id-file does not exist: {path}")
    for raw in path.read_text().splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        out.add(s)
    if not out:
        raise SystemExit(f"--doc-id-file {path} contained no doc IDs")
    return out


# ─── per-row reprocess ───────────────────────────────────────────────────


@dataclass
class _RowOutcome:
    doc_id: str
    file_name: str
    track: str = ""        # "work_product" | "privileged" | "" (unrun)
    terminal_status: str = ""
    chunks: int = 0
    vectors_indexed: int = 0
    error: str = ""        # short reason ("missing_nfs", "empty_extraction", ...)
    mirror_drift: bool = False


async def _reprocess_one(case_slug: str, cand: _Candidate) -> _RowOutcome:
    """Re-run the upsert-relevant pipeline against a single existing row.

    Imports the helpers from ``legal_ediscovery`` directly so the production
    privilege classifier, chunker, embedder, and Phase B/B.1 batched upsert
    are reused. No DB writes are performed in this coroutine — the caller
    persists the outcome via ``_apply_outcome``.
    """
    from backend.services.legal_ediscovery import (
        _extract_text,
        _classify_privilege,
        _chunk_document,
        _embed_chunks,
        _upsert_to_qdrant,
        _upsert_to_qdrant_privileged,
        _derive_privileged_counsel_domain,
        _role_for_counsel_domain,
    )

    out = _RowOutcome(doc_id=cand.doc_id, file_name=cand.file_name)

    nfs = Path(cand.nfs_path)
    if not cand.nfs_path or not nfs.is_file():
        out.error = f"missing_nfs_file:{cand.nfs_path}"
        return out

    try:
        file_bytes = nfs.read_bytes()
    except OSError as exc:
        out.error = f"read_failed:{type(exc).__name__}:{str(exc)[:120]}"
        return out

    raw_text = _extract_text(file_bytes, cand.mime_type, cand.file_name)
    if not (raw_text or "").strip():
        out.error = "empty_extraction"
        return out

    classification, _ = await _classify_privilege(raw_text, cand.file_name)

    is_privileged = bool(
        classification.is_privileged and (classification.confidence or 0.0) >= 0.7
    )

    if is_privileged:
        out.track = "privileged"
        counsel_domain = _derive_privileged_counsel_domain(
            file_bytes=file_bytes,
            file_name=cand.file_name,
            mime_type=cand.mime_type,
            raw_text=raw_text,
        )
        role_tag = _role_for_counsel_domain(counsel_domain)

        priv_chunks = _chunk_document(raw_text)
        priv_vectors = await _embed_chunks(priv_chunks)
        out.chunks = len(priv_chunks)
        uuids, failure = await _upsert_to_qdrant_privileged(
            doc_id=cand.doc_id,
            case_slug=case_slug,
            file_name=cand.file_name,
            file_hash=cand.file_hash,
            privileged_counsel_domain=counsel_domain,
            role=role_tag,
            privilege_type=classification.privilege_type,
            chunks=priv_chunks,
            vectors=priv_vectors,
        )
        out.vectors_indexed = len(uuids)
        if failure is not None:
            out.terminal_status = "qdrant_upsert_failed"
            out.error = (
                f"batch_index={failure.get('batch_index')} "
                f"qdrant_error={str(failure.get('qdrant_error_payload'))[:200]}"
            )
            written = await _persist_failure_state(
                cand, "privileged", uuids, priv_chunks, failure,
            )
        else:
            out.terminal_status = "locked_privileged"
            written = await _persist_success_state(
                cand, "locked_privileged", uuids, priv_chunks,
            )
        out.mirror_drift = (written != len(TARGET_DBS))
        return out

    out.track = "work_product"
    chunks = _chunk_document(raw_text)
    vectors = await _embed_chunks(chunks)
    out.chunks = len(chunks)
    uuids, failure = await _upsert_to_qdrant(
        doc_id=cand.doc_id,
        case_slug=case_slug,
        file_name=cand.file_name,
        file_hash=cand.file_hash,
        chunks=chunks,
        vectors=vectors,
    )
    out.vectors_indexed = len(uuids)
    if failure is not None:
        out.terminal_status = "qdrant_upsert_failed"
        out.error = (
            f"batch_index={failure.get('batch_index')} "
            f"qdrant_error={str(failure.get('qdrant_error_payload'))[:200]}"
        )
        written = await _persist_failure_state(
            cand, "work_product", uuids, chunks, failure,
        )
    else:
        out.terminal_status = "completed"
        written = await _persist_success_state(
            cand, "completed", uuids, chunks,
        )
    out.mirror_drift = (written != len(TARGET_DBS))
    return out


# ─── DB writes ───────────────────────────────────────────────────────────


async def _persist_success_state(
    cand: _Candidate,
    terminal_status: str,
    point_uuids: list[str],
    chunks: list[str],
) -> int:
    """UPDATE both DBs to the success terminal state. Returns count of DBs
    whose rowcount==1. The caller flags mirror_drift if not equal to 2."""
    written = 0
    for dbname in TARGET_DBS:
        conn = _connect(dbname)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE legal.vault_documents "
                    "SET processing_status = %s, "
                    "    chunk_count = %s, "
                    "    vector_ids = %s::uuid[], "
                    "    error_detail = NULL "
                    "WHERE id = %s",
                    (terminal_status, len(chunks), point_uuids, cand.doc_id),
                )
                if (cur.rowcount or 0) == 1:
                    written += 1
        finally:
            conn.close()
    return written


async def _persist_failure_state(
    cand: _Candidate,
    track: str,
    partial_uuids: list[str],
    chunks: list[str],
    failure: dict,
) -> int:
    """UPDATE both DBs to the qdrant_upsert_failed terminal state. Same shape
    as the Phase B writer's failure branch in ``process_vault_upload``."""
    err_payload = json.dumps({
        **failure,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "track": track,
        "doc_id": cand.doc_id,
        "case_slug": "",   # filled by caller-supplied row context if needed
        "file_name": cand.file_name,
        "accumulator_so_far": partial_uuids,
        "source": "reprocess_failed_qdrant_uploads",
    })
    written = 0
    for dbname in TARGET_DBS:
        conn = _connect(dbname)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE legal.vault_documents "
                    "SET processing_status = 'qdrant_upsert_failed', "
                    "    chunk_count = %s, "
                    "    vector_ids = %s::uuid[], "
                    "    error_detail = %s "
                    "WHERE id = %s",
                    (
                        len(chunks),
                        partial_uuids if partial_uuids else None,
                        err_payload[:8192],
                        cand.doc_id,
                    ),
                )
                if (cur.rowcount or 0) == 1:
                    written += 1
        finally:
            conn.close()
    return written


# ─── manifest ────────────────────────────────────────────────────────────


@dataclass
class ReprocessManifest:
    case_slug: str
    started_at: str
    finished_at: str = ""
    runtime_seconds: float = 0.0
    args: dict[str, Any] = field(default_factory=dict)
    host: str = ""
    pid: int = 0
    ingest_run_id: str | None = None
    candidates_count: int = 0
    attempted: int = 0
    recovered: int = 0
    still_failed: int = 0
    skipped_missing_nfs: int = 0
    skipped_empty_extraction: int = 0
    skipped_other: int = 0
    by_track: dict[str, int] = field(default_factory=dict)
    mirror_drift_doc_ids: list[str] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)


def write_manifest(case_slug: str, manifest: ReprocessManifest) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = AUDIT_DIR / f"reprocess-{case_slug}-{ts}.json"
    out.write_text(json.dumps(asdict(manifest), indent=2, default=str))
    return out


# ─── orchestrator ────────────────────────────────────────────────────────


def run_reprocess(args: argparse.Namespace) -> int:
    case_slug = args.case_slug
    run_preflight(case_slug)

    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    manifest = ReprocessManifest(
        case_slug=case_slug,
        started_at=started.isoformat(),
        args={k: v for k, v in vars(args).items()},
        host=socket.gethostname(),
        pid=os.getpid(),
    )

    doc_id_filter: Optional[set[str]] = None
    if args.doc_id_file:
        doc_id_filter = _read_doc_id_file(Path(args.doc_id_file))

    candidates = _list_candidates(
        case_slug=case_slug,
        doc_id_filter=doc_id_filter,
        limit=args.limit,
    )
    manifest.candidates_count = len(candidates)

    print(
        f"# reprocess_failed_qdrant_uploads: case={case_slug} "
        f"candidates={len(candidates)} "
        f"doc_id_file={'set' if doc_id_filter else 'none'} "
        f"limit={args.limit} dry_run={args.dry_run}",
        flush=True,
    )

    if args.dry_run:
        for n, cand in enumerate(candidates, start=1):
            print(
                f"  [{n}/{len(candidates)}] would_reprocess "
                f"doc_id={cand.doc_id} status={cand.processing_status} "
                f"chunk_count={cand.chunk_count} file={cand.file_name[:60]}",
                flush=True,
            )
        manifest.finished_at = datetime.now(timezone.utc).isoformat()
        manifest.runtime_seconds = round(time.monotonic() - t0, 2)
        manifest_path = write_manifest(case_slug, manifest)
        print(
            f"# dry-run done: candidates={manifest.candidates_count} "
            f"runtime={manifest.runtime_seconds:.1f}s manifest={manifest_path}",
            flush=True,
        )
        return 0

    from backend.services.ingest_run_tracker import IngestRunTracker

    with IngestRunTracker(
        case_slug, "reprocess_failed_qdrant_uploads",
        args=manifest.args,
    ) as tracker:
        tracker.set_total_files(len(candidates))
        manifest.ingest_run_id = (
            str(tracker.run_id) if tracker.run_id is not None else None
        )

        outcomes = asyncio.run(_drive_async_loop(case_slug, candidates))

        for n, out in enumerate(outcomes, start=1):
            if out.error and not out.terminal_status:
                # Skipped (no pipeline run).
                if out.error.startswith("missing_nfs"):
                    manifest.skipped_missing_nfs += 1
                elif out.error == "empty_extraction":
                    manifest.skipped_empty_extraction += 1
                else:
                    manifest.skipped_other += 1
                tracker.inc_skipped()
            else:
                manifest.attempted += 1
                manifest.by_track[out.track] = manifest.by_track.get(out.track, 0) + 1
                if out.terminal_status == "qdrant_upsert_failed":
                    manifest.still_failed += 1
                    manifest.failures.append({
                        "doc_id": out.doc_id,
                        "track": out.track,
                        "chunks": out.chunks,
                        "vectors_indexed": out.vectors_indexed,
                        "error": out.error,
                    })
                    tracker.inc_errored()
                else:
                    manifest.recovered += 1
                    tracker.inc_processed()
                if out.mirror_drift:
                    manifest.mirror_drift_doc_ids.append(out.doc_id)

            if n % 25 == 0 or out.terminal_status == "qdrant_upsert_failed":
                print(
                    f"  [{n}/{len(outcomes)}] "
                    f"track={out.track or '-':<12s} "
                    f"status={out.terminal_status or 'skipped':<22s} "
                    f"vectors={out.vectors_indexed}/{out.chunks} "
                    f"file={out.file_name[:60]}",
                    flush=True,
                )

        manifest.finished_at = datetime.now(timezone.utc).isoformat()
        manifest.runtime_seconds = round(time.monotonic() - t0, 2)
        manifest_path = write_manifest(case_slug, manifest)
        tracker.set_manifest_path(manifest_path)

        print(
            f"# done: candidates={manifest.candidates_count} "
            f"attempted={manifest.attempted} "
            f"recovered={manifest.recovered} "
            f"still_failed={manifest.still_failed} "
            f"skipped_missing_nfs={manifest.skipped_missing_nfs} "
            f"skipped_empty_extraction={manifest.skipped_empty_extraction} "
            f"skipped_other={manifest.skipped_other} "
            f"by_track={dict(manifest.by_track)} "
            f"mirror_drift={len(manifest.mirror_drift_doc_ids)} "
            f"runtime={manifest.runtime_seconds:.1f}s "
            f"manifest={manifest_path}",
            flush=True,
        )

    if manifest.still_failed > 0:
        return 1
    if manifest.mirror_drift_doc_ids:
        return 2
    return 0


async def _drive_async_loop(
    case_slug: str, candidates: list[_Candidate],
) -> list[_RowOutcome]:
    """Sequential per-row processing — keeps the embed/upsert pipeline behind
    its existing rate limits and avoids hammering the privilege classifier
    with parallelism that could OOM the inference service."""
    outcomes: list[_RowOutcome] = []
    for cand in candidates:
        try:
            out = await _reprocess_one(case_slug, cand)
        except Exception as exc:
            out = _RowOutcome(
                doc_id=cand.doc_id, file_name=cand.file_name,
                error=f"{type(exc).__name__}:{str(exc)[:200]}",
            )
        outcomes.append(out)
    return outcomes


# ─── CLI ─────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Re-run the upsert-relevant pipeline against vault rows "
                    "that ended up in a Qdrant-failed state.",
    )
    p.add_argument("--case-slug", required=True)
    p.add_argument(
        "--doc-id-file", default=None,
        help="optional path to a file with one doc UUID per line; restricts "
             "the candidate set to those IDs intersected with the predicate",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="surface the planned reprocess set without touching Qdrant or "
             "the DBs",
    )
    p.add_argument(
        "--limit", type=int, default=None,
        help="cap on candidates processed (after doc-id-file filtering); "
             "useful for staged retries",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _ensure_env_loaded()
    args = _parse_args(argv)
    try:
        return run_reprocess(args)
    except PreflightError as exc:
        print(f"PREFLIGHT FAILED: {exc}", file=sys.stderr, flush=True)
        return 3
    except KeyboardInterrupt:
        print("\n# interrupted by operator", file=sys.stderr, flush=True)
        return 130
    except Exception as exc:
        traceback.print_exc()
        print(f"FATAL: {type(exc).__name__}:{exc!s}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
