#!/usr/bin/env python3
"""
Reindex a legacy 768-dim Qdrant legal collection to a 2048-dim _v2 collection
embedded via the LiteLLM gateway alias `legal-embed`
(llama-nemotron-embed-1b-v2 on spark-3:8102).

Caller contract (verified via PR #300 §9.5):
    model           = "legal-embed"
    input_type      = "passage"      # asymmetric encoder; passage for indexing
    encoding_format = "float"        # NIM rejects None default with HTTP 400

Field branch (verified via PR #301 audit §2):
    text_chunk : legal_caselaw, legal_library
    text       : legal_privileged_communications

Idempotent: source point IDs are preserved, so re-running over already-written
points is a no-op upsert. Resume state (last successful offset) is persisted to
/mnt/fortress_nas/fortress_data/reindex_state/<collection>.json.

Hard constraint compliance: this script reindexes by COPY — it never touches
the source collection. Source remains live throughout.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels


# ---- Configuration ----------------------------------------------------------

QDRANT_URL = os.environ.get("QDRANT_URL", "http://192.168.0.100:6333")
GATEWAY_URL = os.environ.get("LITELLM_URL", "http://localhost:8002")
TARGET_DIM = 2048
TARGET_DISTANCE = qmodels.Distance.COSINE

TEXT_FIELD = {
    "legal_caselaw": "text_chunk",
    "legal_library": "text_chunk",
    "legal_privileged_communications": "text",
}

STATE_DIR = Path("/mnt/fortress_nas/fortress_data/reindex_state")
LOG_DIR = Path("/var/log/fortress")


# ---- Logging ----------------------------------------------------------------

def setup_logging(collection: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"reindex-{collection}-{ts}.log"
    fmt = "%(asctime)s %(levelname)s %(message)s"
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(log_path)]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers, force=True)
    return log_path


# ---- State file -------------------------------------------------------------

@dataclass
class State:
    collection: str
    next_offset: Any  # opaque Qdrant cursor (None at start)
    processed: int
    errors: int
    started_at: str
    last_update_at: str

    @classmethod
    def load(cls, collection: str) -> "State":
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        p = STATE_DIR / f"{collection}.json"
        if p.exists():
            d = json.loads(p.read_text())
            return cls(**d)
        return cls(
            collection=collection,
            next_offset=None,
            processed=0,
            errors=0,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            last_update_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    def save(self) -> None:
        p = STATE_DIR / f"{self.collection}.json"
        self.last_update_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        p.write_text(json.dumps(self.__dict__, indent=2, default=str))


# ---- Embedding via gateway --------------------------------------------------

class Embedder:
    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0, concurrency: int = 4):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        self.sem = asyncio.Semaphore(concurrency)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        body = {
            "input": texts,
            "model": "legal-embed",
            "input_type": "passage",
            "encoding_format": "float",
        }
        async with self.sem:
            for attempt in range(3):
                try:
                    r = await self.client.post("/embeddings", json=body)
                    if r.status_code == 200:
                        data = r.json()
                        return [d["embedding"] for d in data["data"]]
                    # HTTP 400: caller-contract bug, NEVER retry blindly (per stop conditions)
                    if r.status_code == 400:
                        raise RuntimeError(
                            f"HTTP 400 from gateway — caller contract violated. "
                            f"Body sent (truncated): model={body['model']} input_type={body['input_type']} "
                            f"encoding_format={body['encoding_format']} n_texts={len(texts)}. "
                            f"Response: {r.text[:500]}"
                        )
                    # Other transient: backoff + retry
                    logging.warning("embed HTTP %s attempt %d: %s", r.status_code, attempt + 1, r.text[:200])
                    await asyncio.sleep(1.0 * (2 ** attempt))
                except httpx.RequestError as e:
                    logging.warning("embed RequestError attempt %d: %s", attempt + 1, e)
                    await asyncio.sleep(1.0 * (2 ** attempt))
            raise RuntimeError(f"embed_batch failed after 3 attempts (n_texts={len(texts)})")


# ---- Reindex worker ---------------------------------------------------------

@dataclass
class BatchResult:
    n_in: int
    n_out: int
    embed_seconds: float
    upsert_seconds: float
    errors: int


async def process_batch(
    embedder: Embedder,
    qclient: QdrantClient,
    target: str,
    points: list[qmodels.Record],
    text_field: str,
) -> BatchResult:
    # Filter to points that have non-empty text_field
    keep: list[qmodels.Record] = []
    skipped = 0
    for p in points:
        text = (p.payload or {}).get(text_field)
        if not isinstance(text, str) or not text.strip():
            skipped += 1
            continue
        keep.append(p)
    if not keep:
        return BatchResult(n_in=len(points), n_out=0, embed_seconds=0, upsert_seconds=0, errors=skipped)

    texts: list[str] = []
    for p in keep:
        assert p.payload is not None  # filtered above
        texts.append(p.payload[text_field])
    t0 = time.perf_counter()
    vectors = await embedder.embed_batch(texts)
    t1 = time.perf_counter()

    upsert_points = [
        qmodels.PointStruct(id=p.id, vector=v, payload=p.payload)
        for p, v in zip(keep, vectors)
    ]
    # Qdrant client is sync; run upsert in thread pool to avoid blocking the loop
    await asyncio.to_thread(qclient.upsert, collection_name=target, points=upsert_points, wait=True)
    t2 = time.perf_counter()

    return BatchResult(
        n_in=len(points),
        n_out=len(keep),
        embed_seconds=t1 - t0,
        upsert_seconds=t2 - t1,
        errors=skipped,
    )


async def run_reindex(args: argparse.Namespace, master_key: str) -> int:
    coll = args.collection
    target = f"{coll}_v2"
    text_field = TEXT_FIELD[coll]

    state = State.load(coll)
    qclient = QdrantClient(url=QDRANT_URL, timeout=60)

    # Verify _v2 collection exists at expected dim/metric
    info = qclient.get_collection(target)
    vparams = info.config.params.vectors
    if isinstance(vparams, dict):
        # Named vectors — pick the default unnamed if present, else first key
        v = vparams.get("") or next(iter(vparams.values()))
        actual_dim, actual_dist = v.size, v.distance
    elif vparams is None:
        raise RuntimeError(f"{target} has no vector params")
    else:
        actual_dim, actual_dist = vparams.size, vparams.distance
    if actual_dim != TARGET_DIM:
        raise RuntimeError(f"{target} dim={actual_dim} expected {TARGET_DIM}")
    if actual_dist != TARGET_DISTANCE:
        raise RuntimeError(f"{target} distance={actual_dist} expected {TARGET_DISTANCE}")
    logging.info("target collection %s verified: dim=%s distance=%s", target, actual_dim, actual_dist)

    # Source point count (for progress)
    src_info = qclient.get_collection(coll)
    src_total = src_info.points_count
    logging.info("source collection %s: %s points", coll, src_total)

    embedder = Embedder(GATEWAY_URL, master_key, timeout=args.timeout, concurrency=args.workers)

    started_wall = time.perf_counter()
    batches_done = 0
    total_embedded = state.processed
    total_errors = state.errors

    # Process a "window" of inflight_batches at a time. Within a window, batches
    # run concurrently via asyncio.gather; state is saved after each window.
    # Window-level checkpointing keeps resume logic simple while still giving
    # real parallelism — anything in the current window is re-done on resume,
    # but that is idempotent (point IDs preserved).
    window_size = max(1, args.inflight_batches)

    try:
        cur_offset = state.next_offset
        while True:
            # Collect up to window_size batches by scrolling (sequential — Qdrant
            # scroll returns its own next_offset cursor that must be threaded)
            window: list[list[qmodels.Record]] = []
            window_end_offset = cur_offset
            for _ in range(window_size):
                scroll_resp, next_offset = qclient.scroll(
                    collection_name=coll,
                    limit=args.batch_size,
                    offset=cur_offset,
                    with_payload=True,
                    with_vectors=False,
                )
                if not scroll_resp:
                    break
                window.append(scroll_resp)
                cur_offset = next_offset
                window_end_offset = next_offset
                if next_offset is None:
                    break
            if not window:
                logging.info("scroll exhausted")
                break

            if args.dry_run:
                logging.info("[dry-run] would process %d batches (skip embed/upsert)", len(window))
                window_results: list[BatchResult] = []
            else:
                window_results = await asyncio.gather(
                    *[process_batch(embedder, qclient, target, b, text_field) for b in window]
                )
                for i, br in enumerate(window_results, start=1):
                    total_embedded += br.n_out
                    total_errors += br.errors
                    batches_done += 1
                    elapsed = time.perf_counter() - started_wall
                    rate = total_embedded / elapsed if elapsed > 0 else 0
                    logging.info(
                        "batch %d (window slot %d/%d): in=%d out=%d skipped=%d embed=%.2fs upsert=%.2fs total_done=%d/%s rate=%.1f docs/s",
                        batches_done, i, len(window), br.n_in, br.n_out, br.errors,
                        br.embed_seconds, br.upsert_seconds,
                        total_embedded, src_total, rate,
                    )

            # Persist state at window boundary
            state.next_offset = window_end_offset
            state.processed = total_embedded
            state.errors = total_errors
            state.save()

            if window_end_offset is None:
                logging.info("reached end of source collection")
                break

            # Early termination check via env var (graceful shutdown signal)
            if os.environ.get("REINDEX_HALT") == "1":
                logging.warning("REINDEX_HALT=1 in env — graceful exit")
                break
    finally:
        await embedder.aclose()
        qclient.close()

    wall = time.perf_counter() - started_wall
    rate = total_embedded / wall if wall > 0 else 0
    logging.info(
        "DONE %s: processed=%d errors=%d wall=%.1fs rate=%.1f docs/s",
        coll, total_embedded, total_errors, wall, rate,
    )

    # Final summary as JSON for downstream tooling
    summary = {
        "collection": coll,
        "target": target,
        "source_total": src_total,
        "processed": total_embedded,
        "errors": total_errors,
        "wall_seconds": wall,
        "docs_per_sec": rate,
    }
    print("\nSUMMARY: " + json.dumps(summary))
    return 0


# ---- CLI --------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    desc = (__doc__ or "").splitlines()[1] if __doc__ else ""
    p = argparse.ArgumentParser(description=desc)
    p.add_argument("--collection", required=True, choices=sorted(TEXT_FIELD.keys()))
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--workers", type=int, default=4,
                   help="Max concurrent embed calls (semaphore on the embedder)")
    p.add_argument("--inflight-batches", type=int, default=4,
                   help="How many batches to process concurrently per window. State is "
                        "checkpointed at window boundaries; on resume, the current "
                        "window is re-processed (idempotent — point IDs preserved).")
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--resume-from", type=str, default=None,
                   help="Override saved state and resume from this point id (rare)")
    p.add_argument("--reset-state", action="store_true",
                   help="Delete saved state file before run")
    return p.parse_args()


def read_master_key() -> str:
    """Read master_key from active config (gitignored, plaintext on host)."""
    cfg_path = Path("/home/admin/Fortress-Prime/litellm_config.yaml")
    for line in cfg_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("master_key:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("master_key not found in litellm_config.yaml")


def main() -> int:
    args = parse_args()
    log_path = setup_logging(args.collection)
    logging.info("log file: %s", log_path)
    logging.info("args: %s", vars(args))

    if args.reset_state:
        sp = STATE_DIR / f"{args.collection}.json"
        if sp.exists():
            sp.unlink()
            logging.info("removed state file %s", sp)

    if args.resume_from:
        # Force state to resume from given offset
        state = State.load(args.collection)
        state.next_offset = args.resume_from
        state.save()
        logging.info("forced resume from offset %s", args.resume_from)

    master_key = read_master_key()
    return asyncio.run(run_reindex(args, master_key))


if __name__ == "__main__":
    sys.exit(main())
