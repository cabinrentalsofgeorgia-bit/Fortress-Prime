"""
CourtListener → Qdrant — 11th Circuit federal-precedent ingest.

Fetches ca11 opinions from CourtListener API v4, caches them as a NAS
JSONL, then runs the same chunk/embed/upsert pipeline as the GA-state
sibling script (`ingest_courtlistener.py`). New target collection:
`legal_caselaw_federal` — kept distinct so 11th-Cir precedent doesn't
mix with the GA-state Phase 4 citation index.

Fetch + ingest are decoupled. The fetch step is idempotent: re-runs
skip opinions already in the NAS JSONL. The ingest step is idempotent
via the existing sqlite resume log + UUID5 deterministic point IDs.

Reuses, unmodified, from `ingest_courtlistener`:
  - `RealEmbedder` — nomic-embed-text via legal_ediscovery._embed_single
  - `DryRunEmbedder`, `DryRunSink` — explosive stubs proving --dry-run
  - `QdrantSink` — qdrant_client.QdrantClient wrapper
  - `chunk_by_words` — word-based 1500/150 chunker
  - `IngestState` — sqlite (opinion_id, chunks_upserted, run_id, completed_at)
  - `IngestStats` — counters

Adds:
  - `fetch_ca11_to_jsonl()` — paginated CourtListener API client
  - `build_point()` — 11th-Cir payload schema (jurisdiction='ca11',
    authored_judge if available)
  - `--since` flag for fetch date floor
  - Same CLI surface as the sibling: --reset --limit --batch-size
    --dry-run --source --log-every

Usage after merge:
    python -m backend.scripts.ingest_courtlistener_11th_cir --dry-run --limit 10
    python -m backend.scripts.ingest_courtlistener_11th_cir
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from backend.scripts.ingest_courtlistener import (
    DryRunEmbedder,
    DryRunSink,
    IngestState,
    IngestStats,
    QdrantSink,
    RealEmbedder,
    chunk_by_words,
)

logger = logging.getLogger("ingest_courtlistener_11th_cir")

# ──────────────────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_SOURCE = Path(
    "/mnt/fortress_nas/legal-corpus/courtlistener/opinions-ca11.jsonl"
)
DEFAULT_STATE_DB = Path(
    "/mnt/fortress_nas/legal-corpus/courtlistener/.ingest_state_ca11.db"
)

COLLECTION_NAME = "legal_caselaw_federal"
JURISDICTION_TAG = "ca11"
COURT_ID = "ca11"
VECTOR_DIM = 768
DEFAULT_SINCE = "2005-01-01"          # default 20-year horizon
DEFAULT_CHUNK_TOKENS = 1500
DEFAULT_OVERLAP_TOKENS = 150

CL_BASE_URL = "https://www.courtlistener.com/api/rest/v4"
CL_RATE_LIMIT_S = 0.5                 # be nice to CourtListener
CL_PAGE_SIZE = 100                    # CL max per page

# Same UUID5 namespace as the GA-state ingest — opinion_ids are globally
# unique within CourtListener so a cross-collection collision is impossible.
POINT_NS = uuid.UUID("7f2e1a6c-5d31-4b0a-9d4d-6a3e1a8c0f7e")


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class IngestConfig:
    source:           Path
    state_db:         Path
    collection:       str = COLLECTION_NAME
    batch_size:       int = 64
    limit:            int | None = None
    reset:            bool = False
    dry_run:          bool = False
    skip_fetch:       bool = False
    log_every:        int = 50
    chunk_tokens:     int = DEFAULT_CHUNK_TOKENS
    overlap_tokens:   int = DEFAULT_OVERLAP_TOKENS
    since:            str = DEFAULT_SINCE
    fetch_max:        int | None = None      # cap on API fetch per run
    run_id:           str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime(
            "ca11run-%Y%m%dT%H%M%SZ"
        )
    )


# ──────────────────────────────────────────────────────────────────────────────
# CourtListener API client (paginated, idempotent fetch → JSONL)
# ──────────────────────────────────────────────────────────────────────────────

def _cl_token() -> str:
    tok = os.environ.get("COURTLISTENER_API_TOKEN", "").strip()
    if not tok:
        raise RuntimeError(
            "COURTLISTENER_API_TOKEN is unset — required for ca11 fetch"
        )
    return tok


def _cl_get(url: str, token: str, http_get: Any | None = None) -> dict:
    """GET with auth header. http_get is injectable for tests."""
    if http_get is not None:
        return http_get(url, token)
    req = urllib.request.Request(
        url, headers={"Authorization": f"Token {token}"}
    )
    # CourtListener filtered list endpoints can take 10-30s on cold queries;
    # 90s gives headroom without making test failures slow (tests inject
    # http_get and never hit this branch).
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read())


def _existing_opinion_ids(jsonl: Path) -> set[str]:
    if not jsonl.exists():
        return set()
    seen: set[str] = set()
    with jsonl.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            oid = str(rec.get("opinion_id") or "").strip()
            if oid:
                seen.add(oid)
    return seen


def _normalize_cluster_record(cluster: dict, opinion: dict) -> dict:
    """Flatten a (cluster, opinion) pair into a JSONL record matching the
    schema the GA-state ingest reads."""
    text = (opinion.get("plain_text") or "").strip()
    if not text:
        # Fallback to html_with_citations stripped of tags
        html = opinion.get("html_with_citations") or opinion.get("html") or ""
        if html:
            import re
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
    citations = []
    for c in (cluster.get("citations") or []):
        # CourtListener cluster citations are dicts; render to a flat string.
        parts = [c.get(k) for k in ("volume", "reporter", "page") if c.get(k)]
        if parts:
            citations.append(" ".join(str(p) for p in parts))
    authored_judge = (
        opinion.get("author_str")
        or (opinion.get("author") or {}).get("name_full")
        or ""
    )
    if isinstance(authored_judge, dict):
        authored_judge = authored_judge.get("name_full") or ""
    return {
        "opinion_id":       str(opinion.get("id") or ""),
        "cluster_id":       str(cluster.get("id") or ""),
        "case_name":        cluster.get("case_name") or cluster.get("case_name_short") or "",
        "court":            "United States Court of Appeals for the Eleventh Circuit",
        "court_id":         COURT_ID,
        "date_filed":       cluster.get("date_filed") or "",
        "citation":         citations,
        "plain_text":       text,
        "plain_text_chars": len(text),
        "authored_judge":   str(authored_judge or ""),
        "fetched_at":       datetime.now(timezone.utc).isoformat(),
    }


def fetch_ca11_to_jsonl(
    jsonl: Path,
    since: str,
    fetch_max: int | None = None,
    http_get: Any | None = None,
    rate_limit_s: float = CL_RATE_LIMIT_S,
) -> tuple[int, int]:
    """
    Fetch ca11 clusters since `since` (YYYY-MM-DD), plus their first
    opinion's full text, and append unseen ones to `jsonl`. Returns
    (new_records, total_records_in_file).

    Idempotent: existing opinion_ids in `jsonl` are skipped.
    """
    token = _cl_token()
    seen = _existing_opinion_ids(jsonl)
    jsonl.parent.mkdir(parents=True, exist_ok=True)

    params = urllib.parse.urlencode({
        "docket__court__id":  COURT_ID,
        "date_filed__gte":    since,
        "page_size":          CL_PAGE_SIZE,
        "order_by":           "-date_filed",
    })
    url: str | None = f"{CL_BASE_URL}/clusters/?{params}"
    new = 0
    page = 0

    with jsonl.open("a", encoding="utf-8") as out:
        while url:
            page += 1
            try:
                data = _cl_get(url, token, http_get=http_get)
            except urllib.error.HTTPError as exc:
                logger.error(
                    "cl_http_error",
                    extra={"page": page, "status": exc.code, "url": url[:160]},
                )
                break
            except Exception as exc:
                logger.error(
                    "cl_fetch_failed",
                    extra={"page": page, "error": str(exc)[:200]},
                )
                break

            results = data.get("results") or []
            for cluster in results:
                if fetch_max is not None and new >= fetch_max:
                    return new, len(seen) + new

                # The cluster may carry an embedded list of opinions or a list
                # of URLs. Hit the first opinion endpoint to get plain_text.
                sub_ops = cluster.get("sub_opinions") or []
                if not sub_ops:
                    continue
                op_ref = sub_ops[0]
                if isinstance(op_ref, str):
                    if rate_limit_s:
                        time.sleep(rate_limit_s)
                    try:
                        op_data = _cl_get(op_ref, token, http_get=http_get)
                    except Exception as exc:
                        logger.warning(
                            "cl_opinion_fetch_failed",
                            extra={"url": op_ref[:160], "error": str(exc)[:200]},
                        )
                        continue
                else:
                    op_data = op_ref

                opinion_id = str(op_data.get("id") or "")
                if not opinion_id or opinion_id in seen:
                    continue
                rec = _normalize_cluster_record(cluster, op_data)
                if not rec.get("plain_text"):
                    # Skip empties — nothing to chunk/embed.
                    continue
                out.write(json.dumps(rec) + "\n")
                seen.add(opinion_id)
                new += 1
            url = data.get("next") or None
            if rate_limit_s:
                time.sleep(rate_limit_s)
    return new, len(seen)


# ──────────────────────────────────────────────────────────────────────────────
# Source iteration (single JSONL — dedup is via fetch step)
# ──────────────────────────────────────────────────────────────────────────────

def iter_opinions_jsonl(
    src: Path, limit: int | None = None,
) -> Iterator[dict]:
    if not src.exists():
        return
    yielded = 0
    with src.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not str(rec.get("opinion_id") or "").strip():
                continue
            yield rec
            yielded += 1
            if limit is not None and yielded >= limit:
                return


# ──────────────────────────────────────────────────────────────────────────────
# Point construction — ca11 payload schema
# ──────────────────────────────────────────────────────────────────────────────

def build_point(
    opinion: dict, chunk_index: int, chunk_text: str,
    vector: list[float], run_id: str,
) -> dict:
    opinion_id = str(opinion.get("opinion_id") or "")
    point_id = str(uuid.uuid5(POINT_NS, f"{opinion_id}:{chunk_index}"))
    return {
        "id":     point_id,
        "vector": vector,
        "payload": {
            "opinion_id":             opinion_id,
            "cluster_id":             str(opinion.get("cluster_id") or ""),
            "case_name":              opinion.get("case_name") or "",
            "court":                  opinion.get("court") or "",
            "date_filed":             opinion.get("date_filed") or "",
            "citation":               list(opinion.get("citation") or []),
            "chunk_index":            chunk_index,
            "text_chunk":             chunk_text,
            "plain_text_chars_total": int(opinion.get("plain_text_chars") or 0),
            "jurisdiction":           JURISDICTION_TAG,
            "authored_judge":         str(opinion.get("authored_judge") or ""),
            "ingested_at":            datetime.now(timezone.utc).isoformat(),
            "ingestion_run_id":       run_id,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Ingest driver (mirrors GA-state pattern)
# ──────────────────────────────────────────────────────────────────────────────

async def run_ingest(
    cfg: IngestConfig,
    state: IngestState,
    embedder: Any,
    sink: Any,
) -> IngestStats:
    stats = IngestStats()

    if cfg.reset:
        if not cfg.dry_run:
            sink.reset()
        state.reset()
        logger.info("collection_and_state_reset", extra={"run_id": cfg.run_id})

    if not cfg.dry_run:
        sink.ensure_collection(VECTOR_DIM)

    batch: list[dict] = []

    async def flush_batch() -> None:
        if not batch:
            return
        if not cfg.dry_run:
            sink.upsert(batch)
        stats.points_upserted += len(batch)
        batch.clear()

    for opinion in iter_opinions_jsonl(cfg.source, limit=cfg.limit):
        stats.opinions_seen += 1
        opinion_id = str(opinion.get("opinion_id") or "")

        if not cfg.reset and state.already_completed(opinion_id):
            stats.opinions_skipped_completed += 1
            continue

        text = opinion.get("plain_text") or ""
        chunks = chunk_by_words(
            text, size=cfg.chunk_tokens, overlap=cfg.overlap_tokens,
        )
        if not chunks:
            continue

        try:
            opinion_chunks_written = 0
            for idx, chunk in enumerate(chunks):
                if cfg.dry_run:
                    vec: list[float] = []
                else:
                    vec = await embedder.embed(chunk)
                    if not vec:
                        raise RuntimeError(
                            f"empty embedding for opinion {opinion_id} chunk {idx}"
                        )
                point = build_point(opinion, idx, chunk, vec, cfg.run_id)
                batch.append(point)
                stats.chunks_written += 1
                opinion_chunks_written += 1
                if len(batch) >= cfg.batch_size:
                    await flush_batch()
            stats.opinions_processed += 1
            if not cfg.dry_run:
                state.mark_completed(
                    opinion_id, opinion_chunks_written, cfg.run_id,
                )
        except Exception as exc:
            stats.errors += 1
            logger.error(
                "opinion_failed",
                extra={"opinion_id": opinion_id, "error": str(exc)[:200]},
            )
            batch.clear()

        if stats.opinions_processed and stats.opinions_processed % cfg.log_every == 0:
            eps = stats.chunks_written / max(1e-6, stats.elapsed())
            logger.info(
                "progress",
                extra={
                    "opinions_processed": stats.opinions_processed,
                    "chunks_written":     stats.chunks_written,
                    "points_upserted":    stats.points_upserted,
                    "embeddings_per_sec": round(eps, 2),
                },
            )

    await flush_batch()
    return stats


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="11th Circuit CourtListener → Qdrant ingest"
    )
    p.add_argument("--reset", action="store_true",
                   help="drop+recreate collection and state before ingest")
    p.add_argument("--limit", type=int, default=None,
                   help="process at most N opinions during ingest")
    p.add_argument("--batch-size", type=int, default=64,
                   help="points per qdrant upsert (default 64)")
    p.add_argument("--dry-run", action="store_true",
                   help="parse+chunk+count only; no embed or upsert")
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                   help="override JSONL source")
    p.add_argument("--log-every", type=int, default=50)
    p.add_argument("--state-db", type=Path, default=DEFAULT_STATE_DB)
    p.add_argument("--collection", type=str, default=COLLECTION_NAME)
    p.add_argument("--chunk-tokens", type=int, default=DEFAULT_CHUNK_TOKENS)
    p.add_argument("--overlap-tokens", type=int, default=DEFAULT_OVERLAP_TOKENS)
    p.add_argument("--since", type=str, default=DEFAULT_SINCE,
                   help="fetch ca11 clusters with date_filed >= this date")
    p.add_argument("--fetch-max", type=int, default=None,
                   help="cap on opinions fetched from CourtListener API")
    p.add_argument("--skip-fetch", action="store_true",
                   help="use existing JSONL only; do not call CourtListener")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])

    cfg = IngestConfig(
        source=args.source,
        state_db=args.state_db,
        collection=args.collection,
        batch_size=args.batch_size,
        limit=args.limit,
        reset=args.reset,
        dry_run=args.dry_run,
        skip_fetch=args.skip_fetch,
        log_every=args.log_every,
        chunk_tokens=args.chunk_tokens,
        overlap_tokens=args.overlap_tokens,
        since=args.since,
        fetch_max=args.fetch_max,
    )

    if not cfg.skip_fetch:
        # In --dry-run we still fetch (idempotent, JSONL-cached) so the
        # smoke test exercises the full pipeline; pass --fetch-max to bound
        # the API hit. With real CL token absent, we fall through to the
        # existing JSONL.
        try:
            new, total = fetch_ca11_to_jsonl(
                cfg.source, cfg.since, fetch_max=cfg.fetch_max or cfg.limit,
            )
            logger.info(
                "ca11_fetch_complete",
                extra={
                    "jsonl":          str(cfg.source),
                    "new_records":    new,
                    "total_records":  total,
                    "since":          cfg.since,
                    "fetch_max":      cfg.fetch_max or cfg.limit,
                },
            )
        except RuntimeError as exc:
            logger.error("ca11_fetch_skipped", extra={"reason": str(exc)})
            if not cfg.source.exists():
                logger.error("ca11_no_source_after_failed_fetch", extra={
                    "source": str(cfg.source),
                })
                return 2

    state = IngestState(cfg.state_db)
    try:
        if cfg.dry_run:
            embedder: Any = DryRunEmbedder()
            sink: Any = DryRunSink()
        else:
            embedder = RealEmbedder()
            sink = QdrantSink(collection=cfg.collection)
        stats = asyncio.run(run_ingest(cfg, state, embedder, sink))
    finally:
        state.close()

    logger.info(
        "ingest_complete",
        extra={
            "run_id":             cfg.run_id,
            "dry_run":            cfg.dry_run,
            "total_opinions":     stats.opinions_seen,
            "opinions_processed": stats.opinions_processed,
            "opinions_skipped":   stats.opinions_skipped_completed,
            "chunks_written":     stats.chunks_written,
            "points_upserted":    stats.points_upserted,
            "errors":             stats.errors,
            "duration_seconds":   round(stats.elapsed(), 2),
        },
    )
    return 0 if stats.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
