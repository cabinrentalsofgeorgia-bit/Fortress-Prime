"""
CourtListener → Qdrant ingestion.

One-shot script. Reads opinion JSONL from the NAS legal corpus,
chunks each opinion's plain_text with citation-preserving overlap,
embeds each chunk via the existing nomic-embed-text wrapper, and
upserts into the `legal_caselaw` Qdrant collection.

Idempotent: opinion_id -> chunks_upserted state is tracked in a
sqlite file on the NAS; re-runs skip previously-completed opinions
unless --reset is passed. Point IDs are deterministic UUID5 derived
from (opinion_id, chunk_index), so re-running after a partial failure
upserts the same point IDs rather than duplicating.

Typical use after merge:
    # Smoke test (no network I/O):
    python -m backend.scripts.ingest_courtlistener --dry-run --limit 10
    # Full ingest:
    python -m backend.scripts.ingest_courtlistener
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

logger = logging.getLogger("ingest_courtlistener")

# ──────────────────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_SOURCE_FULL = Path(
    "/mnt/fortress_nas/legal-corpus/courtlistener/opinions-full.jsonl"
)
DEFAULT_SOURCE_EXPANDED = Path(
    "/mnt/fortress_nas/legal-corpus/courtlistener/opinions-expanded.jsonl"
)
DEFAULT_STATE_DB = Path(
    "/mnt/fortress_nas/legal-corpus/courtlistener/.ingest_state.db"
)

COLLECTION_NAME = "legal_caselaw"
VECTOR_DIM = 768  # matches nomic-embed-text dimensions everywhere else

# Opinion chunking — word-based. Legal opinions need generous overlap
# so a citation that straddles a chunk boundary is visible to both
# neighbouring vectors.
DEFAULT_CHUNK_TOKENS = 1500
DEFAULT_OVERLAP_TOKENS = 150

# UUID5 namespace: stable seed so reruns produce identical point IDs.
# Generated once; any UUID4 would work, don't change this or rerun
# idempotency breaks.
POINT_NS = uuid.UUID("7f2e1a6c-5d31-4b0a-9d4d-6a3e1a8c0f7e")


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class IngestConfig:
    sources: list[Path]
    state_db: Path
    collection: str = COLLECTION_NAME
    batch_size: int = 64
    limit: int | None = None
    reset: bool = False
    dry_run: bool = False
    log_every: int = 50
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS
    run_id: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime(
            "clrun-%Y%m%dT%H%M%SZ"
        )
    )


# ──────────────────────────────────────────────────────────────────────────────
# State DB (sqlite, one row per completed opinion_id)
# ──────────────────────────────────────────────────────────────────────────────

class IngestState:
    """
    Lightweight sqlite resume log. Records are written AFTER a successful
    Qdrant upsert for the opinion; failures leave no row so a rerun
    reprocesses from scratch for that opinion.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS ingest_state (
        opinion_id      TEXT PRIMARY KEY,
        chunks_upserted INTEGER NOT NULL,
        run_id          TEXT    NOT NULL,
        completed_at    TEXT    NOT NULL
    )
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.execute(self.SCHEMA)
        self._conn.commit()

    def already_completed(self, opinion_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM ingest_state WHERE opinion_id = ?",
            (opinion_id,),
        )
        return cur.fetchone() is not None

    def mark_completed(
        self, opinion_id: str, chunks_upserted: int, run_id: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO ingest_state (opinion_id, chunks_upserted, run_id, completed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(opinion_id) DO UPDATE SET
                chunks_upserted = excluded.chunks_upserted,
                run_id          = excluded.run_id,
                completed_at    = excluded.completed_at
            """,
            (
                opinion_id,
                chunks_upserted,
                run_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def reset(self) -> None:
        self._conn.execute("DELETE FROM ingest_state")
        self._conn.commit()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Source iteration + dedup
# ──────────────────────────────────────────────────────────────────────────────

def iter_opinions(
    sources: Sequence[Path], limit: int | None = None,
) -> Iterator[tuple[dict, str]]:
    """
    Yield (opinion, source_file_label) pairs from every source in order.
    Deduplicates on opinion_id — the first occurrence wins, so list the
    authoritative source (opinions-full) first.
    """
    seen: set[str] = set()
    yielded = 0
    for src in sources:
        label = src.stem  # e.g. 'opinions-full'
        if not src.exists():
            logger.warning("source_not_found", extra={"path": str(src)})
            continue
        with src.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    op = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning(
                        "malformed_jsonl",
                        extra={"path": str(src), "line": line_no},
                    )
                    continue
                opinion_id = str(op.get("opinion_id") or "").strip()
                if not opinion_id:
                    continue
                if opinion_id in seen:
                    continue
                seen.add(opinion_id)
                yield op, label
                yielded += 1
                if limit is not None and yielded >= limit:
                    return


# ──────────────────────────────────────────────────────────────────────────────
# Chunking — word-based with overlap
# ──────────────────────────────────────────────────────────────────────────────

def chunk_by_words(
    text: str, size: int = DEFAULT_CHUNK_TOKENS,
    overlap: int = DEFAULT_OVERLAP_TOKENS,
) -> list[str]:
    """
    Split text into chunks of roughly `size` whitespace-separated tokens
    with `overlap` tokens of context carried between neighbours.

    Tokens here are whitespace splits — an approximation for "words",
    which is itself an approximation for "LLM tokens" (~1.3× the word
    count). Citation context routinely spans 30-50 words, so overlap
    of 150 tokens comfortably brackets a citation on either side.
    """
    if size <= 0:
        raise ValueError("chunk size must be > 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be in [0, size)")
    words = text.split()
    if not words:
        return []
    if len(words) <= size:
        return [" ".join(words)]
    chunks: list[str] = []
    step = size - overlap
    start = 0
    while start < len(words):
        end = min(start + size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += step
    return chunks


# ──────────────────────────────────────────────────────────────────────────────
# Protocols for injectable embedder / Qdrant sink
# ──────────────────────────────────────────────────────────────────────────────

class DryRunEmbedder:
    """Dry-run: raise if called. Proves no network hit."""
    async def embed(self, text: str) -> list[float]:
        raise AssertionError("dry-run embed called unexpectedly")


class RealEmbedder:
    """Async wrapper around legal_ediscovery._embed_single."""
    async def embed(self, text: str) -> list[float]:
        # Imported lazily so the script loads even when the backend
        # package isn't on the path (tests that supply a fake embedder
        # never touch this code path).
        from backend.services.legal_ediscovery import _embed_single
        return await _embed_single(text)


class DryRunSink:
    """Dry-run: raise if called."""
    def ensure_collection(self, dim: int) -> None:
        raise AssertionError("dry-run ensure_collection called unexpectedly")

    def reset(self) -> None:
        raise AssertionError("dry-run reset called unexpectedly")

    def upsert(self, points: list[dict]) -> None:
        raise AssertionError("dry-run upsert called unexpectedly")


class QdrantSink:
    """Thin wrapper over qdrant_client.QdrantClient for this script only."""

    def __init__(self, collection: str) -> None:
        from backend.core.config import settings
        from qdrant_client import QdrantClient  # type: ignore[import-not-found]
        self._client = QdrantClient(
            url=settings.qdrant_url,
            api_key=(settings.qdrant_api_key or None),
            timeout=60,
        )
        self._collection = collection

    def ensure_collection(self, dim: int) -> None:
        from qdrant_client.http import models as qmodels  # type: ignore[import-not-found]
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection in existing:
            return
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=qmodels.VectorParams(
                size=dim, distance=qmodels.Distance.COSINE,
            ),
            on_disk_payload=True,
        )
        logger.info(
            "collection_created",
            extra={"collection": self._collection, "dim": dim},
        )

    def reset(self) -> None:
        from qdrant_client.http.exceptions import UnexpectedResponse  # type: ignore[import-not-found]
        try:
            self._client.delete_collection(self._collection)
        except UnexpectedResponse:
            pass

    def upsert(self, points: list[dict]) -> None:
        from qdrant_client.http import models as qmodels  # type: ignore[import-not-found]
        self._client.upsert(
            collection_name=self._collection,
            points=[
                qmodels.PointStruct(
                    id=p["id"], vector=p["vector"], payload=p["payload"],
                )
                for p in points
            ],
            wait=True,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Point construction
# ──────────────────────────────────────────────────────────────────────────────

def build_point(
    opinion: dict, chunk_index: int, chunk_text: str, vector: list[float],
    source_label: str, run_id: str,
) -> dict:
    opinion_id = str(opinion.get("opinion_id") or "")
    point_id = str(uuid.uuid5(POINT_NS, f"{opinion_id}:{chunk_index}"))
    return {
        "id": point_id,
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
            "source_file":            source_label,
            "ingested_at":            datetime.now(timezone.utc).isoformat(),
            "ingestion_run_id":       run_id,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Core ingest driver
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class IngestStats:
    opinions_seen: int = 0
    opinions_processed: int = 0
    opinions_skipped_dedup: int = 0
    opinions_skipped_completed: int = 0
    chunks_written: int = 0
    points_upserted: int = 0
    errors: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at


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

    for opinion, source_label in iter_opinions(cfg.sources, limit=cfg.limit):
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
                        # Embedding failed — skip this chunk, keep
                        # the opinion incomplete so a retry reprocesses.
                        raise RuntimeError(
                            f"empty embedding for opinion {opinion_id} chunk {idx}"
                        )
                point = build_point(
                    opinion, idx, chunk, vec, source_label, cfg.run_id,
                )
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
            batch.clear()  # drop the partial batch; resume handles it

        if stats.opinions_processed and stats.opinions_processed % cfg.log_every == 0:
            eps = stats.chunks_written / max(1e-6, stats.elapsed())
            remaining_opinions = (
                max(0, (cfg.limit or 10_000) - stats.opinions_processed)
                if cfg.limit else None
            )
            eta_s = (
                (remaining_opinions / max(1, stats.opinions_processed)) * stats.elapsed()
                if remaining_opinions else None
            )
            logger.info(
                "progress",
                extra={
                    "opinions_processed": stats.opinions_processed,
                    "chunks_written":     stats.chunks_written,
                    "points_upserted":    stats.points_upserted,
                    "embeddings_per_sec": round(eps, 2),
                    "eta_seconds":        round(eta_s, 1) if eta_s else None,
                },
            )

    await flush_batch()
    return stats


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CourtListener → Qdrant ingest")
    p.add_argument("--reset", action="store_true",
                   help="drop+recreate collection and state before ingest")
    p.add_argument("--limit", type=int, default=None,
                   help="process at most N opinions (smoke test)")
    p.add_argument("--batch-size", type=int, default=64,
                   help="points per qdrant upsert (default 64)")
    p.add_argument("--dry-run", action="store_true",
                   help="parse+chunk+count only; no embed or upsert")
    p.add_argument("--source", type=Path, action="append", default=None,
                   help="override input file (repeatable); defaults to full + expanded")
    p.add_argument("--log-every", type=int, default=50,
                   help="log a progress line every N processed opinions")
    p.add_argument("--state-db", type=Path, default=DEFAULT_STATE_DB,
                   help="path to sqlite resume-state file")
    p.add_argument("--collection", type=str, default=COLLECTION_NAME,
                   help="qdrant collection name (default legal_caselaw)")
    p.add_argument("--chunk-tokens", type=int, default=DEFAULT_CHUNK_TOKENS)
    p.add_argument("--overlap-tokens", type=int, default=DEFAULT_OVERLAP_TOKENS)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    sources = args.source or [DEFAULT_SOURCE_FULL, DEFAULT_SOURCE_EXPANDED]

    cfg = IngestConfig(
        sources=sources,
        state_db=args.state_db,
        collection=args.collection,
        batch_size=args.batch_size,
        limit=args.limit,
        reset=args.reset,
        dry_run=args.dry_run,
        log_every=args.log_every,
        chunk_tokens=args.chunk_tokens,
        overlap_tokens=args.overlap_tokens,
    )
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
