"""
vault_ingest_legal_case.py — case-scoped vault ingestion into legal.vault_documents.

Walks legal.cases.nas_layout for the supplied --case-slug, deduplicates physical
file paths (the same file referenced by two logical subdirs is processed once),
and runs each file through the canonical pipeline:

    process_vault_upload()
        ├── INSERT legal.vault_documents (status='pending', ON CONFLICT DO NOTHING)
        ├── privilege classifier — sets 'locked_privileged' when triggered
        ├── _extract_text — sets 'ocr_failed' when empty on a PDF
        ├── chunk → nomic embed → qdrant upsert
        └── UPDATE status to 'completed'

The vault_documents row is then mirrored to fortress_db so the UI's
LegacySession can read it.

Idempotency: a file_hash that already has a row in {complete, completed,
ocr_failed, locked_privileged} is skipped. Re-running this script is a clean
no-op for fully-ingested cases.

Atomicity: per-file try/except. One bad file does not abort the sweep.

Audit: IngestRunTracker (PR D-pre1) emits a single legal.ingest_runs row
covering the lifecycle. JSON manifest at /mnt/fortress_nas/audits/.

Concurrency control: lock file at /tmp/vault-ingest-{case_slug}.lock with
6 h staleness override (--force).

Rollback: --rollback deletes vault_documents rows for the case in BOTH
fortress_prod and fortress_db, plus Qdrant points whose payload.case_slug
matches. Requires explicit confirmation (type the case_slug back) unless
--force.

Usage (production 7IL run):

    python -m backend.scripts.vault_ingest_legal_case \\
        --case-slug 7il-v-knight-ndga --jobs 6
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import re
import socket
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("vault_ingest_legal_case")

# ─── config ────────────────────────────────────────────────────────────────

NAS_LEGAL_ROOT = "/mnt/fortress_nas/sectors/legal"
ENV_PATH = Path("/home/admin/Fortress-Prime/fortress-guest-platform/.env")
AUDIT_DIR = Path("/mnt/fortress_nas/audits")

LOCK_STALE_AFTER_S = 6 * 3600
HASH_STREAM_THRESHOLD_BYTES = 100 * 1024 * 1024  # 100 MB

DEFAULT_MAX_FILE_SIZE_MB = 500
DEFAULT_JOBS = 4

QDRANT_COLLECTION = "legal_ediscovery"
EXPECTED_VECTOR_SIZE = 768

# vault_documents statuses that we treat as "already done — skip".
TERMINAL_STATUSES_FOR_RESUME = (
    "complete", "completed", "ocr_failed", "locked_privileged",
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


# ─── pre-flight ────────────────────────────────────────────────────────────


class PreflightError(Exception):
    pass


def _preflight_case_exists(case_slug: str) -> dict[str, Any]:
    """case_slug must be present in BOTH fortress_prod and fortress_db. Return the
    fortress_prod row's nas_layout (dict) — the source of truth."""
    layouts: dict[str, Any] = {}
    for dbname in ("fortress_prod", "fortress_db"):
        try:
            conn = _connect(dbname)
        except Exception as exc:
            raise PreflightError(
                f"cannot connect to {dbname}: {type(exc).__name__}:{exc!s}"
            ) from exc
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT nas_layout FROM legal.cases WHERE case_slug = %s",
                    (case_slug,),
                )
                row = cur.fetchone()
            if row is None:
                raise PreflightError(
                    f"case_slug {case_slug!r} not found in {dbname}.legal.cases — "
                    f"run PR B for this case first"
                )
            layouts[dbname] = row[0]
        finally:
            conn.close()
    layout = layouts["fortress_prod"]
    if not layout:
        raise PreflightError(
            f"nas_layout is NULL for {case_slug!r} in fortress_prod. "
            f"Per PR A spec, non-canonical cases must declare a layout. "
            f"Set legal.cases.nas_layout for this case before re-running."
        )
    return _normalize_layout(layout)


def _preflight_paths_exist(layout: dict[str, Any]) -> None:
    root = layout["root"]
    if not root.is_dir():
        raise PreflightError(f"nas_layout.root does not exist on disk: {root}")
    missing: list[str] = []
    for logical, rel in layout["subdirs"].items():
        d = root / rel
        if not d.is_dir():
            missing.append(f"{logical} → {d}")
    if missing:
        raise PreflightError(
            "nas_layout subdirs missing from disk:\n  " + "\n  ".join(missing)
        )


def _preflight_postgres_writable() -> None:
    for dbname in ("fortress_prod", "fortress_db"):
        try:
            conn = _connect(dbname)
        except Exception as exc:
            raise PreflightError(f"{dbname} connect failed: {exc!s}") from exc
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                if cur.fetchone() != (1,):
                    raise PreflightError(f"{dbname} SELECT 1 unexpected result")
        finally:
            conn.close()
    # ingest_runs writability — fail-fast inside fortress_db (tracker target)
    try:
        conn = _connect("fortress_db")
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO legal.ingest_runs (case_slug, script_name, status) "
                "VALUES ('__preflight__', '__preflight__', 'running') RETURNING id"
            )
            row = cur.fetchone()
            if row is None:
                raise PreflightError("preflight ingest_runs INSERT returned no id")
            cur.execute(
                "DELETE FROM legal.ingest_runs WHERE id = %s", (row[0],),
            )
        conn.close()
    except Exception as exc:
        raise PreflightError(
            f"fortress_db.legal.ingest_runs not writable: {exc!s}"
        ) from exc


def _preflight_schema_constraints() -> None:
    """Verify PR D-pre2 constraints are present on fortress_prod and fortress_db."""
    required = {
        "fk_vault_documents_case_slug",
        "uq_vault_documents_case_hash",
        "chk_vault_documents_status",
    }
    for dbname in ("fortress_prod", "fortress_db"):
        conn = _connect(dbname)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'legal.vault_documents'::regclass "
                    "AND conname = ANY(%s)",
                    (list(required),),
                )
                present = {r[0] for r in cur.fetchall()}
        finally:
            conn.close()
        missing = required - present
        if missing:
            raise PreflightError(
                f"{dbname} missing PR D-pre2 constraints: {sorted(missing)} — "
                f"apply alembic d8e3c1f5b9a6 before ingesting"
            )


def _preflight_qdrant_reachable() -> None:
    import urllib.error
    import urllib.request
    qdrant_url = os.environ.get("QDRANT_URL", "").rstrip("/")
    if not qdrant_url:
        raise PreflightError("QDRANT_URL not set in environ")
    try:
        with urllib.request.urlopen(
            f"{qdrant_url}/collections/{QDRANT_COLLECTION}", timeout=10,
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise PreflightError(
                f"qdrant collection {QDRANT_COLLECTION!r} not found at {qdrant_url} — "
                f"create it with vector_size={EXPECTED_VECTOR_SIZE} distance=Cosine"
            ) from exc
        raise PreflightError(f"qdrant reachable but errored: {exc.code}") from exc
    except Exception as exc:
        raise PreflightError(
            f"qdrant unreachable at {qdrant_url}: {type(exc).__name__}:{exc!s}"
        ) from exc

    cfg = (data.get("result") or {}).get("config", {}).get("params", {}).get("vectors", {})
    size = cfg.get("size") if isinstance(cfg, dict) else None
    if size is not None and int(size) != EXPECTED_VECTOR_SIZE:
        raise PreflightError(
            f"qdrant collection vector size is {size}, expected {EXPECTED_VECTOR_SIZE}"
        )


def _preflight_pipeline_importable() -> None:
    try:
        from backend.services.legal_ediscovery import process_vault_upload  # noqa: F401
    except Exception as exc:
        raise PreflightError(
            f"process_vault_upload not importable: {type(exc).__name__}:{exc!s}"
        ) from exc


def run_preflight(case_slug: str) -> dict[str, Any]:
    """Run every pre-flight gate. Raises PreflightError on the first failure."""
    layout = _preflight_case_exists(case_slug)
    _preflight_paths_exist(layout)
    _preflight_postgres_writable()
    _preflight_schema_constraints()
    _preflight_qdrant_reachable()
    _preflight_pipeline_importable()
    return layout


# ─── nas_layout ───────────────────────────────────────────────────────────


def _normalize_layout(raw: Any) -> dict[str, Any]:
    """nas_layout column may be dict, str, or None (caught above)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = None
    if not raw:
        raise PreflightError("nas_layout is empty after normalize")
    root = Path(str(raw.get("root") or "")).expanduser()
    subs = raw.get("subdirs") or {}
    if not isinstance(subs, dict):
        subs = {}
    subdirs = {
        str(k): str(v) for k, v in subs.items() if v not in (None, "")
    }
    return {
        "root": root,
        "subdirs": subdirs,
        "recursive": bool(raw.get("recursive")),
    }


# ─── physical-path dedup walk ─────────────────────────────────────────────


def walk_unique_physical_files(layout: dict[str, Any]):
    """Yield (canonical_path, logical_subdir) for every unique physical file
    referenced from any logical subdir. Skips Synology @eaDir + dotfiles."""
    root: Path = layout["root"]
    recursive: bool = layout["recursive"]
    seen: set[Path] = set()
    for logical, rel in layout["subdirs"].items():
        walk_root = root / rel
        if not walk_root.is_dir():
            continue
        candidates = walk_root.rglob("*") if recursive else walk_root.iterdir()
        for p in candidates:
            try:
                if not p.is_file():
                    continue
            except OSError:
                continue
            if any(part == "@eaDir" or part.startswith(".") for part in p.parts):
                continue
            try:
                canonical = p.resolve()
            except OSError:
                continue
            if canonical in seen:
                continue
            seen.add(canonical)
            yield canonical, logical


# ─── hashing + mime ───────────────────────────────────────────────────────


def file_sha256(path: Path) -> str:
    """SHA-256 of file contents. Streams when > HASH_STREAM_THRESHOLD_BYTES."""
    size = path.stat().st_size
    h = hashlib.sha256()
    if size <= HASH_STREAM_THRESHOLD_BYTES:
        h.update(path.read_bytes())
        return h.hexdigest()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_mime_type(path: Path) -> str:
    """Best-effort mime from extension + magic-bytes peek for PDF/email."""
    by_ext, _ = mimetypes.guess_type(str(path))
    if by_ext:
        return by_ext
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return "application/octet-stream"
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head.startswith(b"From "):
        return "message/rfc822"
    return "application/octet-stream"


# ─── lock file ────────────────────────────────────────────────────────────


def _lock_path(case_slug: str) -> Path:
    return Path(f"/tmp/vault-ingest-{case_slug}.lock")


def acquire_lock(case_slug: str, force: bool) -> Path:
    lp = _lock_path(case_slug)
    if lp.exists():
        try:
            mtime = lp.stat().st_mtime
        except OSError:
            mtime = 0.0
        age = time.time() - mtime
        if force and age > LOCK_STALE_AFTER_S:
            lp.unlink()
        elif force:
            raise SystemExit(
                f"--force given but lock at {lp} is only {int(age)}s old "
                f"(needs > {LOCK_STALE_AFTER_S}s to override)"
            )
        else:
            raise SystemExit(
                f"another vault ingest run appears active (lock at {lp}); "
                f"after confirming no other run, pass --force"
            )
    lp.write_text(f"{os.getpid()}\n{datetime.now(timezone.utc).isoformat()}\n")
    return lp


def release_lock(lp: Path) -> None:
    try:
        lp.unlink()
    except Exception:
        pass


# ─── per-file ingestion ───────────────────────────────────────────────────


@dataclass
class FileOutcome:
    path: str
    logical_subdir: str
    file_hash: str
    file_size_bytes: int
    mime_type: str
    status: str  # completed | ocr_failed | locked_privileged | failed | skipped | duplicate
    document_id: str | None = None
    chunks: int = 0
    vectors_indexed: int = 0
    error: str | None = None
    skipped_reason: str | None = None


async def _ingest_one(
    *,
    physical_path: Path,
    logical_subdir: str,
    case_slug: str,
    max_size_bytes: int,
    skip_status_set: frozenset[str],
    resume: bool,
    dry_run: bool,
    semaphore: asyncio.Semaphore,
) -> FileOutcome:
    async with semaphore:
        return await _ingest_one_inner(
            physical_path=physical_path,
            logical_subdir=logical_subdir,
            case_slug=case_slug,
            max_size_bytes=max_size_bytes,
            skip_status_set=skip_status_set,
            resume=resume,
            dry_run=dry_run,
        )


async def _ingest_one_inner(
    *,
    physical_path: Path,
    logical_subdir: str,
    case_slug: str,
    max_size_bytes: int,
    skip_status_set: frozenset[str],
    resume: bool,
    dry_run: bool,
) -> FileOutcome:
    try:
        size = physical_path.stat().st_size
    except OSError as exc:
        return FileOutcome(
            path=str(physical_path), logical_subdir=logical_subdir,
            file_hash="", file_size_bytes=0, mime_type="",
            status="failed", error=f"stat_failed:{exc!s}",
        )

    if size > max_size_bytes:
        return FileOutcome(
            path=str(physical_path), logical_subdir=logical_subdir,
            file_hash="", file_size_bytes=size,
            mime_type=detect_mime_type(physical_path),
            status="skipped",
            skipped_reason=f"exceeds_max_size_mb:{size // (1024*1024)}MB",
        )

    fhash = file_sha256(physical_path)
    mime = detect_mime_type(physical_path)

    if resume:
        existing_status = _check_existing_row("fortress_prod", case_slug, fhash)
        if existing_status in skip_status_set:
            return FileOutcome(
                path=str(physical_path), logical_subdir=logical_subdir,
                file_hash=fhash, file_size_bytes=size, mime_type=mime,
                status="skipped",
                skipped_reason=f"already_ingested:{existing_status}",
            )

    if dry_run:
        return FileOutcome(
            path=str(physical_path), logical_subdir=logical_subdir,
            file_hash=fhash, file_size_bytes=size, mime_type=mime,
            status="skipped", skipped_reason="dry_run",
        )

    try:
        file_bytes = physical_path.read_bytes()
    except OSError as exc:
        return FileOutcome(
            path=str(physical_path), logical_subdir=logical_subdir,
            file_hash=fhash, file_size_bytes=size, mime_type=mime,
            status="failed", error=f"read_failed:{exc!s}",
        )

    from backend.core.database import AsyncSessionLocal
    from backend.services.legal_ediscovery import process_vault_upload

    try:
        async with AsyncSessionLocal() as db:
            result = await process_vault_upload(
                db=db,
                case_slug=case_slug,
                file_bytes=file_bytes,
                file_name=physical_path.name,
                mime_type=mime,
            )
    except Exception as exc:
        return FileOutcome(
            path=str(physical_path), logical_subdir=logical_subdir,
            file_hash=fhash, file_size_bytes=size, mime_type=mime,
            status="failed",
            error=f"{type(exc).__name__}:{str(exc)[:200]}",
        )

    status = result.get("status", "failed")
    doc_id = result.get("document_id")

    if status in {"completed", "ocr_failed", "locked_privileged"} and doc_id:
        try:
            _mirror_row_to_fortress_db(case_slug=case_slug, doc_id=doc_id)
        except Exception as exc:
            return FileOutcome(
                path=str(physical_path), logical_subdir=logical_subdir,
                file_hash=fhash, file_size_bytes=size, mime_type=mime,
                status="failed", document_id=doc_id,
                error=f"mirror_failed:{type(exc).__name__}:{str(exc)[:200]}",
            )

    return FileOutcome(
        path=str(physical_path), logical_subdir=logical_subdir,
        file_hash=fhash, file_size_bytes=size, mime_type=mime,
        status=status, document_id=doc_id,
        chunks=int(result.get("chunks") or 0),
        vectors_indexed=int(result.get("vectors_indexed") or 0),
        error=str(result.get("error")) if status == "failed" else None,
    )


def _check_existing_row(dbname: str, case_slug: str, file_hash: str) -> str | None:
    conn = _connect(dbname)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT processing_status FROM legal.vault_documents "
                "WHERE case_slug = %s AND file_hash = %s",
                (case_slug, file_hash),
            )
            row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _mirror_row_to_fortress_db(*, case_slug: str, doc_id: str) -> None:
    """After process_vault_upload writes to fortress_prod, copy the row to
    fortress_db so the UI's LegacySession reads the same data."""
    src = _connect("fortress_prod")
    try:
        with src.cursor() as cur:
            cur.execute(
                "SELECT id, case_slug, file_name, nfs_path, mime_type, "
                "file_hash, file_size_bytes, processing_status, "
                "chunk_count, error_detail, created_at "
                "FROM legal.vault_documents WHERE id = %s AND case_slug = %s",
                (doc_id, case_slug),
            )
            row = cur.fetchone()
        if row is None:
            raise RuntimeError(
                f"row {doc_id} missing in fortress_prod for case {case_slug!r} "
                f"— cannot mirror"
            )
    finally:
        src.close()

    dst = _connect("fortress_db")
    try:
        with dst.cursor() as cur:
            cur.execute(
                "INSERT INTO legal.vault_documents "
                "(id, case_slug, file_name, nfs_path, mime_type, file_hash, "
                " file_size_bytes, processing_status, chunk_count, error_detail, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT ON CONSTRAINT uq_vault_documents_case_hash DO UPDATE SET "
                "  processing_status = EXCLUDED.processing_status, "
                "  chunk_count = EXCLUDED.chunk_count, "
                "  error_detail = EXCLUDED.error_detail",
                row,
            )
    finally:
        dst.close()


# ─── manifest ─────────────────────────────────────────────────────────────


@dataclass
class IngestManifest:
    case_slug: str
    started_at: str
    finished_at: str = ""
    runtime_seconds: float = 0.0
    args: dict[str, Any] = field(default_factory=dict)
    host: str = ""
    pid: int = 0
    ingest_run_id: str | None = None
    layout_root: str = ""
    layout_recursive: bool = False
    layout_subdirs: dict[str, str] = field(default_factory=dict)
    total_unique_files: int = 0
    processed: int = 0
    skipped: int = 0
    errored: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    by_logical_subdir: dict[str, int] = field(default_factory=dict)
    by_mime_type: dict[str, int] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    qdrant_points_estimate: int = 0
    vault_documents_inserted: int = 0


def write_manifest(case_slug: str, manifest: IngestManifest) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = AUDIT_DIR / f"vault-ingest-{case_slug}-{ts}.json"
    out.write_text(json.dumps(asdict(manifest), indent=2, default=str))
    return out


def _summarize_outcomes(outcomes: list[FileOutcome], manifest: IngestManifest) -> None:
    for o in outcomes:
        manifest.by_status[o.status] = manifest.by_status.get(o.status, 0) + 1
        if o.logical_subdir:
            manifest.by_logical_subdir[o.logical_subdir] = (
                manifest.by_logical_subdir.get(o.logical_subdir, 0) + 1
            )
        if o.mime_type:
            manifest.by_mime_type[o.mime_type] = (
                manifest.by_mime_type.get(o.mime_type, 0) + 1
            )
        if o.status == "failed":
            manifest.errored += 1
            manifest.errors.append({
                "path": o.path, "logical_subdir": o.logical_subdir,
                "error": o.error or "", "file_hash": o.file_hash,
            })
        elif o.status == "skipped":
            manifest.skipped += 1
        else:
            manifest.processed += 1
        if o.status in {"completed", "ocr_failed", "locked_privileged"}:
            manifest.vault_documents_inserted += 1
        if o.status == "completed":
            manifest.qdrant_points_estimate += o.vectors_indexed


# ─── orchestrator ─────────────────────────────────────────────────────────


def run_ingestion(args: argparse.Namespace) -> int:
    layout = run_preflight(args.case_slug)
    lock = acquire_lock(args.case_slug, force=bool(args.force))

    physical_files = list(walk_unique_physical_files(layout))
    if args.limit is not None:
        physical_files = physical_files[: args.limit]

    print(
        f"# vault ingest: case={args.case_slug} "
        f"unique_physical_files={len(physical_files)} dry_run={args.dry_run}",
        flush=True,
    )

    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    manifest = IngestManifest(
        case_slug=args.case_slug,
        started_at=started.isoformat(),
        args={k: v for k, v in vars(args).items() if k != "force"},
        host=socket.gethostname(),
        pid=os.getpid(),
        layout_root=str(layout["root"]),
        layout_recursive=layout["recursive"],
        layout_subdirs=dict(layout["subdirs"]),
        total_unique_files=len(physical_files),
    )

    skip_status_set = frozenset(s.strip() for s in args.skip_status.split(","))

    from backend.services.ingest_run_tracker import IngestRunTracker

    try:
        with IngestRunTracker(
            args.case_slug, "vault_ingest_legal_case",
            args=manifest.args,
        ) as tracker:
            tracker.set_total_files(len(physical_files))
            manifest.ingest_run_id = (
                str(tracker.run_id) if tracker.run_id is not None else None
            )

            outcomes = asyncio.run(
                _drive_async_loop(
                    physical_files=physical_files,
                    case_slug=args.case_slug,
                    max_size_bytes=args.max_file_size_mb * 1024 * 1024,
                    skip_status_set=skip_status_set,
                    resume=args.resume,
                    dry_run=args.dry_run,
                    jobs=args.jobs,
                    tracker=tracker,
                )
            )
            _summarize_outcomes(outcomes, manifest)
            manifest.finished_at = datetime.now(timezone.utc).isoformat()
            manifest.runtime_seconds = round(time.monotonic() - t0, 2)
            manifest_path = write_manifest(args.case_slug, manifest)
            tracker.set_manifest_path(manifest_path)

            print(
                f"# done: total={manifest.total_unique_files} "
                f"processed={manifest.processed} skipped={manifest.skipped} "
                f"errored={manifest.errored} "
                f"by_status={dict(manifest.by_status)} "
                f"runtime={manifest.runtime_seconds:.1f}s "
                f"manifest={manifest_path}",
                flush=True,
            )
            return 0 if manifest.errored == 0 else 1
    finally:
        release_lock(lock)


async def _drive_async_loop(
    *,
    physical_files: list[tuple[Path, str]],
    case_slug: str,
    max_size_bytes: int,
    skip_status_set: frozenset[str],
    resume: bool,
    dry_run: bool,
    jobs: int,
    tracker,
) -> list[FileOutcome]:
    semaphore = asyncio.Semaphore(max(1, jobs))
    coros = [
        _ingest_one(
            physical_path=p,
            logical_subdir=logical,
            case_slug=case_slug,
            max_size_bytes=max_size_bytes,
            skip_status_set=skip_status_set,
            resume=resume,
            dry_run=dry_run,
            semaphore=semaphore,
        )
        for p, logical in physical_files
    ]
    outcomes: list[FileOutcome] = []
    total = len(coros)
    for n, fut in enumerate(asyncio.as_completed(coros), start=1):
        o = await fut
        outcomes.append(o)
        if o.status == "failed":
            tracker.inc_errored()
        elif o.status == "skipped":
            tracker.inc_skipped()
        else:
            tracker.inc_processed()
        if n % 25 == 0 or o.status == "failed":
            print(
                f"  [{n}/{total}] {o.status:<18s} "
                f"{Path(o.path).name[:60]}",
                flush=True,
            )
    return outcomes


# ─── rollback ─────────────────────────────────────────────────────────────


def run_rollback(args: argparse.Namespace) -> int:
    """Delete every vault_documents row for the case in both DBs and every Qdrant
    point with payload.case_slug == case_slug. Confirmation required unless --force."""
    case_slug = args.case_slug
    if not args.force:
        print(
            f"This will DELETE all legal.vault_documents rows for "
            f"case_slug '{case_slug}' in fortress_prod AND fortress_db, "
            f"plus all Qdrant points in {QDRANT_COLLECTION} where "
            f"payload.case_slug = '{case_slug}'.",
            flush=True,
        )
        try:
            typed = input(f"Type the case_slug ({case_slug}) to confirm: ").strip()
        except EOFError:
            typed = ""
        if typed != case_slug:
            print("rollback cancelled — confirmation did not match", flush=True)
            return 2

    pre_counts: dict[str, int] = {}
    for dbname in ("fortress_prod", "fortress_db"):
        conn = _connect(dbname)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM legal.vault_documents WHERE case_slug = %s",
                    (case_slug,),
                )
                row = cur.fetchone()
                pre_counts[dbname] = int(row[0]) if row else 0
        finally:
            conn.close()
    qdrant_pre = _count_qdrant_points(case_slug)
    pre_counts["qdrant"] = qdrant_pre

    print(f"# pre-rollback counts: {pre_counts}", flush=True)

    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    deleted = {"fortress_prod": 0, "fortress_db": 0, "qdrant": 0}

    from backend.services.ingest_run_tracker import IngestRunTracker
    with IngestRunTracker(
        case_slug, "vault_ingest_legal_case",
        args={"rollback": True, "force": bool(args.force)},
    ) as tracker:
        for dbname in ("fortress_prod", "fortress_db"):
            conn = _connect(dbname)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM legal.vault_documents WHERE case_slug = %s",
                        (case_slug,),
                    )
                    deleted[dbname] = cur.rowcount or 0
            finally:
                conn.close()

        deleted["qdrant"] = _delete_qdrant_points(case_slug)
        post_qdrant = _count_qdrant_points(case_slug)

        post_counts: dict[str, int] = {}
        for dbname in ("fortress_prod", "fortress_db"):
            conn = _connect(dbname)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT count(*) FROM legal.vault_documents WHERE case_slug = %s",
                        (case_slug,),
                    )
                    r = cur.fetchone()
                    post_counts[dbname] = int(r[0]) if r else 0
            finally:
                conn.close()
        post_counts["qdrant"] = post_qdrant

        manifest = {
            "case_slug": case_slug,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "runtime_seconds": round(time.monotonic() - t0, 2),
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "ingest_run_id": str(tracker.run_id) if tracker.run_id is not None else None,
            "operation": "rollback",
            "pre_counts": pre_counts,
            "deleted": deleted,
            "post_counts": post_counts,
        }
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = AUDIT_DIR / f"vault-rollback-{case_slug}-{ts}.json"
        out.write_text(json.dumps(manifest, indent=2, default=str))
        tracker.set_manifest_path(out)
        print(f"# rollback complete: {manifest}", flush=True)
        if any(v != 0 for v in post_counts.values()):
            print(
                f"WARNING: post-rollback counts non-zero: {post_counts} — "
                f"investigate concurrent writers",
                flush=True,
            )
            return 1
        return 0


def _qdrant_url() -> str:
    return os.environ["QDRANT_URL"].rstrip("/")


def _count_qdrant_points(case_slug: str) -> int:
    """Cheap probe: scroll up to 1 point with the case_slug filter, read total."""
    import urllib.request
    payload = {
        "filter": {"must": [
            {"key": "case_slug", "match": {"value": case_slug}}
        ]},
        "limit": 1,
        "with_payload": False,
        "with_vector": False,
    }
    req = urllib.request.Request(
        f"{_qdrant_url()}/collections/{QDRANT_COLLECTION}/points/count",
        data=json.dumps({
            "filter": payload["filter"], "exact": True,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return int((data.get("result") or {}).get("count") or 0)
    except Exception:
        return 0


def _delete_qdrant_points(case_slug: str) -> int:
    """Delete all points where payload.case_slug == case_slug. Returns count
    deleted (best-effort — qdrant returns operation_id, not count, so we use
    pre-/post-count delta)."""
    import urllib.request
    pre = _count_qdrant_points(case_slug)
    body = {
        "filter": {"must": [
            {"key": "case_slug", "match": {"value": case_slug}}
        ]},
    }
    req = urllib.request.Request(
        f"{_qdrant_url()}/collections/{QDRANT_COLLECTION}/points/delete?wait=true",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            resp.read()
    except Exception as exc:
        logger.warning("qdrant_delete_failed err=%s", str(exc)[:200])
        return 0
    post = _count_qdrant_points(case_slug)
    return max(0, pre - post)


# ─── CLI ──────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Case-scoped vault ingestion into legal.vault_documents",
    )
    p.add_argument("--case-slug", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None,
                   help="cap on unique physical files processed")
    p.add_argument("--rollback", action="store_true",
                   help="delete vault_documents rows + Qdrant points for the case")
    p.add_argument("--max-file-size-mb", type=int, default=DEFAULT_MAX_FILE_SIZE_MB)
    p.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                   help="bounded concurrency for per-file processing")
    p.add_argument(
        "--skip-status", default=",".join(TERMINAL_STATUSES_FOR_RESUME),
        help="comma-separated processing_status values to skip on re-run "
             "(default: complete,completed,ocr_failed,locked_privileged)",
    )
    p.add_argument("--resume", action="store_true", default=True,
                   help="skip files whose row already has a terminal status (default on)")
    p.add_argument("--no-resume", dest="resume", action="store_false")
    p.add_argument("--force", action="store_true",
                   help="override stale lock (>6h) or skip rollback confirmation prompt")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _ensure_env_loaded()
    args = _parse_args(argv)

    if args.rollback:
        return run_rollback(args)

    try:
        return run_ingestion(args)
    except PreflightError as exc:
        print(f"PREFLIGHT FAILED: {exc}", file=sys.stderr, flush=True)
        return 3
    except KeyboardInterrupt:
        print("\n# interrupted by operator — in-flight rows left for resume",
              file=sys.stderr, flush=True)
        return 130
    except Exception as exc:
        traceback.print_exc()
        print(f"FATAL: {type(exc).__name__}:{exc!s}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
