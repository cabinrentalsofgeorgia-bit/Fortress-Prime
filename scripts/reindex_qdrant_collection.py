#!/usr/bin/env python3
"""
Reindex Qdrant collection against a new embedding model.

Reads source chunks via the scroll API, re-embeds via OpenAI-compatible
endpoint (NIM compatible), upserts to target. Resumable via offset
checkpoint file. Logs progress every --progress-every points.

NIM-specific quirks handled:
- Asymmetric models require `input_type` ("passage" for indexing,
  "query" for search). Defaults to "passage".
- The model name registered in NIM is the full hub id
  (e.g. nvidia/llama-nemotron-embed-1b-v2), not a bare alias.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--qdrant-url", default="http://localhost:6333")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--embed-endpoint", required=True,
                   help="OpenAI-compatible base, e.g. http://host:port/v1")
    p.add_argument("--embed-model", required=True)
    p.add_argument("--input-type", default="passage",
                   choices=["passage", "query"],
                   help="NIM asymmetric input_type for the embedding call")
    p.add_argument("--text-key", default="text",
                   help="Payload key holding the chunk text")
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--scroll-batch", type=int, default=256)
    p.add_argument("--resume-from", default="/tmp/reindex-resume.json")
    p.add_argument("--audit-log",
                   default="/mnt/fortress_nas/audits/qdrant-reindex.log")
    p.add_argument("--progress-every", type=int, default=10000,
                   help="Emit a PROGRESS line every N upserted points")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-points", type=int, default=0,
                   help="If >0, stop after this many points (smoke runs)")
    return p.parse_args()


def embed_batch(endpoint, model, texts, input_type):
    response = requests.post(
        f"{endpoint}/embeddings",
        json={"model": model, "input": texts, "input_type": input_type},
        timeout=180,
    )
    response.raise_for_status()
    return [d["embedding"] for d in response.json()["data"]]


def main():
    args = parse_args()
    client = QdrantClient(url=args.qdrant_url, timeout=120)

    resume_path = Path(args.resume_from)
    next_offset = None
    points_done = 0
    if resume_path.exists():
        state = json.loads(resume_path.read_text())
        next_offset = state.get("next_offset")
        points_done = state.get("points_done", 0)
        print(f"RESUME from offset={next_offset} points_done={points_done}",
              flush=True)

    Path(args.audit_log).parent.mkdir(parents=True, exist_ok=True)
    audit = open(args.audit_log, "a")
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    audit.write(f"\n=== REINDEX START {ts} ===\n")
    audit.write(f"src={args.source} tgt={args.target}\n")
    audit.write(f"embed={args.embed_model} @ {args.embed_endpoint} "
                f"input_type={args.input_type}\n")
    audit.write(f"batch={args.batch_size} scroll={args.scroll_batch}\n")
    audit.flush()

    skipped = 0
    last_progress_milestone = (points_done // args.progress_every) * args.progress_every
    start = time.time()

    while True:
        scroll_response = client.scroll(
            collection_name=args.source,
            limit=args.scroll_batch,
            offset=next_offset,
            with_payload=True,
            with_vectors=False,
        )
        points, next_offset = scroll_response
        if not points:
            break

        for i in range(0, len(points), args.batch_size):
            batch = points[i:i + args.batch_size]
            texts, ids, payloads = [], [], []
            for pt in batch:
                payload = pt.payload or {}
                t = payload.get(args.text_key)
                if not t or not isinstance(t, str) or not t.strip():
                    skipped += 1
                    audit.write(f"SKIP {pt.id}: empty/missing {args.text_key}\n")
                    continue
                # NIM truncates at model max; sending oversized strings just
                # wastes bandwidth. 32K chars is well above any sane chunk.
                texts.append(t[:32000])
                ids.append(pt.id)
                payloads.append(payload)

            if not texts:
                continue

            try:
                vectors = embed_batch(args.embed_endpoint, args.embed_model,
                                      texts, args.input_type)
            except Exception as e:
                msg = f"ERROR embed batch starting id={ids[0]}: {e}"
                print(msg, flush=True)
                audit.write(msg + "\n")
                resume_path.write_text(json.dumps({
                    "next_offset": next_offset,
                    "points_done": points_done,
                }))
                audit.close()
                sys.exit(1)

            if not args.dry_run:
                client.upsert(
                    collection_name=args.target,
                    points=[
                        PointStruct(id=ids[j], vector=vectors[j],
                                    payload=payloads[j])
                        for j in range(len(vectors))
                    ],
                )

            points_done += len(vectors)

            # Progress every N points
            if (points_done // args.progress_every) > (last_progress_milestone // args.progress_every):
                last_progress_milestone = (points_done // args.progress_every) * args.progress_every
                elapsed = time.time() - start
                rate = points_done / elapsed if elapsed > 0 else 0
                eta_remaining = (738918 - points_done) / rate if rate > 0 else 0
                msg = (f"PROGRESS points={points_done} "
                       f"rate={rate:.1f}/s elapsed={elapsed:.0f}s "
                       f"skipped={skipped} eta={eta_remaining:.0f}s")
                print(msg, flush=True)
                audit.write(msg + "\n")
                audit.flush()

            if args.max_points and points_done >= args.max_points:
                print(f"max-points {args.max_points} reached", flush=True)
                next_offset = None
                break

        resume_path.write_text(json.dumps({
            "next_offset": str(next_offset) if next_offset else None,
            "points_done": points_done,
        }))
        audit.flush()

        if next_offset is None:
            break

    elapsed = time.time() - start
    rate = points_done / elapsed if elapsed > 0 else 0
    audit.write(f"=== REINDEX COMPLETE points={points_done} "
                f"skipped={skipped} wall={elapsed:.0f}s rate={rate:.1f}/s ===\n")
    audit.close()

    if not args.dry_run and resume_path.exists() and not args.max_points:
        resume_path.unlink()

    print(f"DONE points={points_done} skipped={skipped} "
          f"wall={elapsed:.0f}s rate={rate:.1f}/s", flush=True)


if __name__ == "__main__":
    main()
