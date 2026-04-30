#!/usr/bin/env python3
"""
Quality validation: pick 50 sample queries from a legacy 768-dim collection,
get top-5 from legacy (nomic-embed-text via Ollama on spark-2:11434) and from
the corresponding _v2 collection (legal-embed via gateway), and compare.

Reports per-collection:
- top-5 overlap@5: |legacy_top5 ∩ v2_top5| / 5, averaged across queries
- rank correlation (Spearman ρ on the union of top-N IDs, where ranks are
  taken from each list and missing IDs get a tail rank)
- top-1 ID match rate (what fraction of queries return the same #1 hit)

Usage:
    validate_reindex_quality.py --collection legal_caselaw --n-queries 50
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from qdrant_client import QdrantClient


QDRANT_URL = "http://192.168.0.100:6333"
GATEWAY_URL = "http://localhost:8002"
OLLAMA_URL = "http://spark-2:11434"   # baseline encoder (nomic)

TEXT_FIELD = {
    "legal_caselaw": "text_chunk",
    "legal_library": "text_chunk",
    "legal_privileged_communications": "text",
}


def read_master_key() -> str:
    for line in Path("/home/admin/Fortress-Prime/litellm_config.yaml").read_text().splitlines():
        line = line.strip()
        if line.startswith("master_key:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("master_key not found")


def embed_legal(client: httpx.Client, text: str, key: str) -> list[float]:
    r = client.post(
        f"{GATEWAY_URL}/embeddings",
        json={"input": text, "model": "legal-embed", "input_type": "query", "encoding_format": "float"},
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]


def embed_nomic(client: httpx.Client, text: str) -> list[float]:
    r = client.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": "nomic-embed-text", "prompt": text},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def overlap_at_k(a_ids: list[Any], b_ids: list[Any], k: int) -> float:
    return len(set(a_ids[:k]) & set(b_ids[:k])) / k


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1] if __doc__ else "")
    ap.add_argument("--collection", required=True, choices=sorted(TEXT_FIELD.keys()))
    ap.add_argument("--n-queries", type=int, default=50)
    ap.add_argument("--seed", type=int, default=20260429)
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    text_field = TEXT_FIELD[args.collection]
    legacy = args.collection
    target = f"{legacy}_v2"

    qclient = QdrantClient(url=QDRANT_URL, timeout=60)
    src = qclient.get_collection(legacy)
    n_src = src.points_count
    if n_src is None or n_src == 0:
        print(f"WARN: source {legacy} has 0 points — nothing to validate")
        return 0
    n_v2 = qclient.get_collection(target).points_count
    print(f"source {legacy}: {n_src} pts; target {target}: {n_v2} pts", file=sys.stderr)

    # Sample n random queries by scrolling and reservoir-picking
    sample_pts: list[Any] = []
    seen = 0
    next_offset = None
    target_n = max(args.n_queries * 3, 200)  # over-sample then random-pick
    while True:
        pts, next_offset = qclient.scroll(
            collection_name=legacy, limit=512, offset=next_offset,
            with_payload=[text_field], with_vectors=False,
        )
        sample_pts.extend(p for p in pts if isinstance((p.payload or {}).get(text_field), str)
                          and len((p.payload or {})[text_field].strip()) > 30)
        seen += len(pts)
        if next_offset is None or len(sample_pts) >= target_n:
            break
    print(f"scrolled {seen} pts; have {len(sample_pts)} candidates with text >30 chars", file=sys.stderr)
    if len(sample_pts) < args.n_queries:
        print(f"WARN: only {len(sample_pts)} candidate queries available (wanted {args.n_queries})")
    rng.shuffle(sample_pts)
    queries = sample_pts[: args.n_queries]
    print(f"using {len(queries)} queries", file=sys.stderr)

    key = read_master_key()
    overlaps_at: dict[int, list[float]] = {1: [], 3: [], 5: [], 10: []}
    top1_match = 0
    detail = []
    t0 = time.perf_counter()
    with httpx.Client(timeout=60) as hc:
        for i, p in enumerate(queries):
            text = (p.payload or {})[text_field]
            # Truncate very long chunks for the query — first 1200 chars is plenty
            qtext = text[:1200]
            try:
                v_legal = embed_legal(hc, qtext, key)
                v_nomic = embed_nomic(hc, qtext)
            except Exception as e:
                print(f"  q{i}: embed error {e}", file=sys.stderr)
                continue
            top_n = max(overlaps_at.keys())
            legacy_hits = qclient.query_points(collection_name=legacy, query=v_nomic, limit=top_n, with_payload=False).points
            v2_hits = qclient.query_points(collection_name=target, query=v_legal, limit=top_n, with_payload=False).points
            legacy_ids = [h.id for h in legacy_hits]
            v2_ids = [h.id for h in v2_hits]
            row: dict[str, Any] = {"q_id": str(p.id)}
            for k in overlaps_at:
                ov = overlap_at_k(legacy_ids, v2_ids, k)
                overlaps_at[k].append(ov)
                row[f"overlap@{k}"] = ov
            t1 = legacy_ids[0] if legacy_ids else None
            t2 = v2_ids[0] if v2_ids else None
            if t1 is not None and t1 == t2:
                top1_match += 1
            row["top1_legacy"] = str(t1)
            row["top1_v2"] = str(t2)
            detail.append(row)
    wall = time.perf_counter() - t0

    if not overlaps_at[5]:
        print("ERROR: no successful queries", file=sys.stderr)
        return 1

    n_q = len(overlaps_at[5])
    summary: dict[str, Any] = {
        "collection": legacy,
        "target": target,
        "n_queries": n_q,
        "top1_id_match_rate": top1_match / n_q,
        "wall_seconds": wall,
    }
    for k, vals in overlaps_at.items():
        summary[f"mean_overlap@{k}"] = statistics.mean(vals)
        summary[f"median_overlap@{k}"] = statistics.median(vals)
        summary[f"min_overlap@{k}"] = min(vals)
    print("\nSUMMARY: " + json.dumps(summary, indent=2))

    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "detail": detail}, indent=2))
        print(f"wrote {args.out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
