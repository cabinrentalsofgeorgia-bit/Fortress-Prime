#!/usr/bin/env python3
"""
Quality probe: run a fixed set of Case II queries against a Qdrant
collection and print top-5 (score, source key, file_name, snippet)
per query. Used to validate retrieval after a reindex.
"""

import argparse
import json

import requests

QUERIES = [
    "What did Knight argue about easement timing?",
    "Section 8 financial breakdown for Q3 2025",
    "Thor James grantor warranty deed",
    "Motion to dismiss analysis on §4 claims",
    "Procedural posture on counsel hire deadline",
]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--qdrant-url", default="http://localhost:6333")
    p.add_argument("--collection", required=True)
    p.add_argument("--embed-endpoint",
                   default="http://192.168.0.105:8102/v1")
    p.add_argument("--embed-model",
                   default="nvidia/llama-nemotron-embed-1b-v2")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--json", action="store_true",
                   help="Emit JSON instead of human text")
    return p.parse_args()


def embed(endpoint, model, text):
    r = requests.post(
        f"{endpoint}/embeddings",
        json={"model": model, "input": [text], "input_type": "query"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]


def main():
    args = parse_args()
    out = {"collection": args.collection, "queries": []}

    for q in QUERIES:
        vec = embed(args.embed_endpoint, args.embed_model, q)
        r = requests.post(
            f"{args.qdrant_url}/collections/{args.collection}/points/search",
            json={"vector": vec, "limit": args.limit, "with_payload": True},
            timeout=30,
        )
        r.raise_for_status()
        results = r.json()["result"]
        entry = {"query": q, "results": []}
        for h in results:
            p = h.get("payload") or {}
            entry["results"].append({
                "score": round(h.get("score", 0), 4),
                "id": h.get("id"),
                "file_name": p.get("file_name"),
                "case_slug": p.get("case_slug"),
                "document_id": p.get("document_id"),
                "snippet": (p.get("text") or "")[:160].replace("\n", " "),
            })
        out["queries"].append(entry)

    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return

    for entry in out["queries"]:
        print(f"\nQUERY: {entry['query']}")
        for r in entry["results"]:
            print(f"  score={r['score']:.4f}  file={r['file_name']}  "
                  f"case={r['case_slug']}")
            print(f"    snippet: {r['snippet']}")


if __name__ == "__main__":
    main()
