"""
backfill_vector_ids.py — Phase C/G of the Issue #228 fix.

Populates ``legal.vault_documents.vector_ids`` on pre-fix rows by scrolling
the Qdrant collections (``legal_ediscovery`` + ``legal_privileged_communications``)
for the supplied ``--case-slug``, grouping point UUIDs by ``payload.document_id``,
and UPDATE-ing matching rows where ``vector_ids IS NULL``.

Idempotency
-----------
UPDATE predicate is ``vector_ids IS NULL`` — re-running is a clean no-op for
rows that have already been backfilled (or that landed via the Phase B writer).

Audit
-----
``IngestRunTracker`` emits a single ``legal.ingest_runs`` row covering the
lifecycle. JSON manifest is written under ``/mnt/fortress_nas/audits/``.

Mirror behaviour
----------------
``legal.vault_documents`` is mirrored across ``fortress_db`` (LegacySession
target — what the FastAPI handlers read) and ``fortress_prod``. We UPDATE
both DBs in lock-step so the mirror does not drift on backfilled rows.

Usage
-----
::

    # Dry-run first — surfaces the planned UPDATE set without writing.
    python -m backend.scripts.backfill_vector_ids \\
        --case-slug 7il-v-knight-ndga --dry-run

    # Production run.
    python -m backend.scripts.backfill_vector_ids \\
        --case-slug 7il-v-knight-ndga

Issue #228 design note
----------------------
Pre-fix rows have ``chunk_count > 0`` (the upload pipeline produced N chunks)
but ``vector_ids IS NULL`` (no successful upsert UUIDs were ever recorded).
For rows that succeeded silently, the Qdrant points exist with payload
``case_slug``+``document_id`` set; we recover the UUIDs by scrolling.

For rows that genuinely lost their Qdrant points (true silent failures,
upsert never reached the server), the scroll yields nothing for that
``document_id`` — we record them in the manifest under ``unmatched_doc_ids``
so the operator can re-ingest them via ``vault_ingest_legal_case --no-resume``
or rollback+re-ingest the case.
"""
from __future__ import annotations

import argparse
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
from typing import Any

logger = logging.getLogger("backfill_vector_ids")

# ─── config ────────────────────────────────────────────────────────────────

ENV_PATH = Path("/home/admin/Fortress-Prime/fortress-guest-platform/.env")
AUDIT_DIR = Path("/mnt/fortress_nas/audits")

QDRANT_WORK_PRODUCT_COLLECTION = "legal_ediscovery"
QDRANT_PRIVILEGED_COLLECTION = "legal_privileged_communications"
QDRANT_SCROLL_BATCH = 512

# DBs that hold legal.vault_documents (kept in lock-step by vault ingestion).
TARGET_DBS = ("fortress_db", "fortress_prod")


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
                        f"apply Phase A migration n9a1b2c3d4e5 before backfill"
                    )
        finally:
            conn.close()


def _preflight_qdrant_reachable() -> None:
    base = _qdrant_url()
    for col in (QDRANT_WORK_PRODUCT_COLLECTION, QDRANT_PRIVILEGED_COLLECTION):
        try:
            with urllib.request.urlopen(f"{base}/collections/{col}", timeout=10) as r:
                r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                # Privileged collection may not exist on every cluster — only
                # hard-fail on the work-product collection.
                if col == QDRANT_WORK_PRODUCT_COLLECTION:
                    raise PreflightError(
                        f"qdrant collection {col!r} not found at {base}"
                    ) from exc
                logger.info(
                    "preflight_qdrant_collection_absent collection=%s "
                    "(privileged track will be skipped)", col,
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
    _preflight_qdrant_reachable()


# ─── candidate selection ─────────────────────────────────────────────────


@dataclass
class _Candidate:
    doc_id: str
    chunk_count: int
    processing_status: str


def _list_candidates(case_slug: str) -> list[_Candidate]:
    """Rows that need backfill: chunk_count > 0 AND vector_ids IS NULL.

    Source DB = fortress_db (LegacySession target — UI source of truth).
    The fortress_prod mirror is updated row-for-row at write time, so its
    candidate set is identical by construction.
    """
    conn = _connect("fortress_db")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id::text, chunk_count, processing_status "
                "FROM legal.vault_documents "
                "WHERE case_slug = %s "
                "  AND chunk_count > 0 "
                "  AND vector_ids IS NULL",
                (case_slug,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [_Candidate(doc_id=r[0], chunk_count=int(r[1] or 0),
                       processing_status=str(r[2] or "")) for r in rows]


# ─── Qdrant scroll ───────────────────────────────────────────────────────


def _scroll_collection_for_case(
    collection: str, case_slug: str,
) -> tuple[dict[str, list[str]], int]:
    """Scroll every point in ``collection`` whose payload.case_slug matches
    and group point UUIDs by payload.document_id.

    Returns ``(grouped, scrolled_total)`` where ``grouped`` is
    ``{document_id: [point_uuid, ...]}`` and ``scrolled_total`` is the count
    of points walked (for manifest accounting).

    If the collection is absent (HTTP 404), returns ``({}, 0)`` — Issue #228
    pre-fix data on this cluster simply did not include privileged points.
    """
    base = _qdrant_url()
    body: dict[str, Any] = {
        "filter": {"must": [
            {"key": "case_slug", "match": {"value": case_slug}}
        ]},
        "limit": QDRANT_SCROLL_BATCH,
        "with_payload": ["document_id"],
        "with_vector": False,
    }
    grouped: dict[str, list[str]] = {}
    total = 0
    next_offset: Any = None
    while True:
        if next_offset is not None:
            body["offset"] = next_offset
        req = urllib.request.Request(
            f"{base}/collections/{collection}/points/scroll",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {}, 0
            raise
        result = data.get("result") or {}
        points = result.get("points") or []
        for p in points:
            point_id = p.get("id")
            payload = p.get("payload") or {}
            doc_id = payload.get("document_id")
            if not point_id or not doc_id:
                continue
            grouped.setdefault(str(doc_id), []).append(str(point_id))
            total += 1
        next_offset = result.get("next_page_offset")
        if not next_offset:
            break
    return grouped, total


# ─── update ──────────────────────────────────────────────────────────────


def _update_vector_ids(doc_id: str, point_uuids: list[str]) -> int:
    """UPDATE both target DBs WHERE id=:id AND vector_ids IS NULL.

    Returns the count of DBs whose rowcount was 1 (typically 0, 1, or 2).
    """
    written = 0
    for dbname in TARGET_DBS:
        conn = _connect(dbname)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE legal.vault_documents "
                    "SET vector_ids = %s::uuid[] "
                    "WHERE id = %s "
                    "  AND vector_ids IS NULL",
                    (point_uuids, doc_id),
                )
                if (cur.rowcount or 0) == 1:
                    written += 1
        finally:
            conn.close()
    return written


# ─── manifest ────────────────────────────────────────────────────────────


@dataclass
class BackfillManifest:
    case_slug: str
    started_at: str
    finished_at: str = ""
    runtime_seconds: float = 0.0
    args: dict[str, Any] = field(default_factory=dict)
    host: str = ""
    pid: int = 0
    ingest_run_id: str | None = None
    candidates_count: int = 0
    qdrant_scrolled: dict[str, int] = field(default_factory=dict)
    docs_with_points: int = 0
    rows_updated: int = 0
    rows_partially_updated: int = 0
    rows_skipped_no_points: int = 0
    rows_skipped_already_set: int = 0
    unmatched_doc_ids: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


def write_manifest(case_slug: str, manifest: BackfillManifest) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = AUDIT_DIR / f"backfill-vector-ids-{case_slug}-{ts}.json"
    out.write_text(json.dumps(asdict(manifest), indent=2, default=str))
    return out


# ─── orchestrator ────────────────────────────────────────────────────────


def run_backfill(args: argparse.Namespace) -> int:
    case_slug = args.case_slug
    run_preflight(case_slug)

    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    manifest = BackfillManifest(
        case_slug=case_slug,
        started_at=started.isoformat(),
        args={k: v for k, v in vars(args).items()},
        host=socket.gethostname(),
        pid=os.getpid(),
    )

    candidates = _list_candidates(case_slug)
    manifest.candidates_count = len(candidates)
    cand_index: dict[str, _Candidate] = {c.doc_id: c for c in candidates}

    print(
        f"# backfill_vector_ids: case={case_slug} "
        f"candidates={len(candidates)} dry_run={args.dry_run}",
        flush=True,
    )

    # Scroll both collections — each doc_id lives in exactly one collection,
    # so the merged dict has no key collisions.
    merged: dict[str, list[str]] = {}
    for col in (QDRANT_WORK_PRODUCT_COLLECTION, QDRANT_PRIVILEGED_COLLECTION):
        grouped, total = _scroll_collection_for_case(col, case_slug)
        manifest.qdrant_scrolled[col] = total
        for doc_id, uuids in grouped.items():
            if doc_id in merged:
                # Defensive: same doc shouldn't appear in both collections.
                logger.warning(
                    "doc_id_in_both_collections doc_id=%s "
                    "first_collection_count=%d second_collection_count=%d",
                    doc_id, len(merged[doc_id]), len(uuids),
                )
                merged[doc_id].extend(uuids)
            else:
                merged[doc_id] = uuids
        print(
            f"  scrolled {col}: {total} points, "
            f"{len(grouped)} distinct document_id keys",
            flush=True,
        )

    manifest.docs_with_points = sum(
        1 for d in cand_index if d in merged
    )

    from backend.services.ingest_run_tracker import IngestRunTracker

    with IngestRunTracker(
        case_slug, "backfill_vector_ids",
        args=manifest.args,
    ) as tracker:
        tracker.set_total_files(len(candidates))
        manifest.ingest_run_id = (
            str(tracker.run_id) if tracker.run_id is not None else None
        )

        for cand in candidates:
            uuids = merged.get(cand.doc_id)
            if not uuids:
                manifest.rows_skipped_no_points += 1
                manifest.unmatched_doc_ids.append(cand.doc_id)
                tracker.inc_skipped()
                continue

            if args.dry_run:
                manifest.rows_updated += 1     # planned
                tracker.inc_processed()
                continue

            try:
                wrote = _update_vector_ids(cand.doc_id, uuids)
            except Exception as exc:
                manifest.errors.append({
                    "doc_id": cand.doc_id,
                    "error": f"{type(exc).__name__}:{str(exc)[:200]}",
                })
                tracker.inc_errored()
                continue

            if wrote == len(TARGET_DBS):
                manifest.rows_updated += 1
                tracker.inc_processed()
            elif wrote == 0:
                # Predicate (vector_ids IS NULL) didn't match either DB —
                # row was already backfilled by a concurrent run.
                manifest.rows_skipped_already_set += 1
                tracker.inc_skipped()
            else:
                # Partial — one DB updated, one already set. Record so the
                # operator can investigate mirror drift.
                manifest.rows_partially_updated += 1
                tracker.inc_processed()

        manifest.finished_at = datetime.now(timezone.utc).isoformat()
        manifest.runtime_seconds = round(time.monotonic() - t0, 2)
        manifest_path = write_manifest(case_slug, manifest)
        tracker.set_manifest_path(manifest_path)

        print(
            f"# done: candidates={manifest.candidates_count} "
            f"docs_with_points={manifest.docs_with_points} "
            f"updated={manifest.rows_updated} "
            f"partial={manifest.rows_partially_updated} "
            f"skipped_no_points={manifest.rows_skipped_no_points} "
            f"skipped_already_set={manifest.rows_skipped_already_set} "
            f"errored={len(manifest.errors)} "
            f"runtime={manifest.runtime_seconds:.1f}s "
            f"manifest={manifest_path}",
            flush=True,
        )

    if manifest.errors:
        return 1
    if manifest.rows_partially_updated > 0:
        return 2
    return 0


# ─── CLI ─────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Backfill legal.vault_documents.vector_ids by scrolling "
                    "Qdrant for the supplied case.",
    )
    p.add_argument("--case-slug", required=True)
    p.add_argument(
        "--dry-run", action="store_true",
        help="surface the planned UPDATE set without writing",
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
        return run_backfill(args)
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
