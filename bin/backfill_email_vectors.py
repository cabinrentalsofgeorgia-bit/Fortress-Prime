#!/usr/bin/env python3
"""
EMAIL VECTOR BACKFILL — Direct 4-GPU parallel embedding
=========================================================
Reads all unvectorized emails from email_archive, embeds them via
the 4-node Ollama/NIM cluster, and upserts into Qdrant email_embeddings.
Marks each email as is_vectorized=true on success.

Bypasses the Redis queue for a clean, one-shot batch operation.
"""

import os
import sys
import time
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import psycopg2
import psycopg2.extras
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_ollama_endpoints

env_file = Path(__file__).resolve().parent.parent / "fortress-guest-platform" / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

EMBED_NODES = get_ollama_endpoints()
EMBED_MODEL = "nomic-embed-text"
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = "email_embeddings"
DB_CFG = dict(
    host=os.getenv("FORTRESS_DB_HOST", "localhost"),
    port=int(os.getenv("FORTRESS_DB_PORT", "5432")),
    dbname=os.getenv("FORTRESS_DB_NAME", "fortress_db"),
    user=os.getenv("FORTRESS_DB_USER", "miner_bot"),
    password=os.getenv("FORTRESS_DB_PASS", ""),
)
BATCH_SIZE = 50

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BACKFILL] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")

stats = {"embedded": 0, "skipped": 0, "errors": 0}
stats_lock = threading.Lock()


def _check_embedding_warm(node_url: str) -> bool:
    """Quick pre-flight to detect if embedding model is loaded."""
    try:
        r = requests.get(f"{node_url}/api/tags", timeout=3)
        if r.status_code == 200:
            loaded = [m.get("name", "") for m in r.json().get("models", [])]
            return any(EMBED_MODEL in m for m in loaded)
    except Exception:
        pass
    return False


def get_embedding(text: str, node_idx: int, max_retries: int = 3) -> list:
    node_url = EMBED_NODES[node_idx % len(EMBED_NODES)]
    url = f"{node_url}/api/embeddings"

    is_warm = _check_embedding_warm(node_url)
    effective_timeout = 30 if is_warm else 90

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                url,
                json={"model": EMBED_MODEL, "prompt": text},
                timeout=effective_timeout,
            )
            resp.raise_for_status()
            return resp.json().get("embedding", [])
        except requests.exceptions.ReadTimeout:
            backoff = 2 ** attempt
            log.warning(
                "Embedding timeout on %s (attempt %d/%d, timeout=%ds), retrying in %ds",
                node_url, attempt + 1, max_retries, effective_timeout, backoff,
            )
            time.sleep(backoff)
            effective_timeout = 90
        except requests.exceptions.ConnectionError:
            backoff = 2 ** attempt
            log.warning(
                "Embedding connection refused on %s (attempt %d/%d), retrying in %ds",
                node_url, attempt + 1, max_retries, backoff,
            )
            time.sleep(backoff)
        except Exception as e:
            log.error("Embedding unexpected error on %s: %s", node_url, e)
            break

    log.error("Embedding failed after %d retries on %s", max_retries, node_url)
    return []


def process_email(row: dict, node_idx: int) -> dict:
    eid = row["id"]
    sender = (row["sender"] or "")[:100]
    subject = (row["subject"] or "")[:200]
    division = row["division"] or "UNKNOWN"
    content = row["content"] or ""
    clean = " ".join(content.split())[:1500]
    embed_text = f"From: {sender}\nSubject: {subject}\nDivision: {division}\n\n{clean}"

    if len(clean.strip()) < 50:
        return {"id": eid, "status": "skipped", "reason": "too_short"}

    embedding = get_embedding(embed_text, node_idx)
    if not embedding or len(embedding) != 768:
        return {"id": eid, "status": "error", "reason": "bad_embedding"}

    return {
        "id": eid,
        "status": "ok",
        "point": {
            "id": eid,
            "vector": embedding,
            "payload": {
                "email_id": eid,
                "sender": sender[:200],
                "subject": subject[:500],
                "division": division,
                "preview": content[:500],
            },
        },
    }


def upsert_batch(points: list):
    resp = requests.put(
        f"{QDRANT_URL}/collections/{COLLECTION}/points",
        json={"points": points},
        timeout=30,
    )
    resp.raise_for_status()


def mark_vectorized(ids: list):
    conn = psycopg2.connect(**DB_CFG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE email_archive SET is_vectorized = TRUE WHERE id = ANY(%s)",
                (ids,),
            )
        conn.commit()
    finally:
        conn.close()


def main():
    t0 = time.time()
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id, sender, subject, content, division
        FROM email_archive
        WHERE is_vectorized = false OR is_vectorized IS NULL
        ORDER BY id
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    total = len(rows)
    log.info(f"Found {total} unvectorized emails across {len(EMBED_NODES)} GPU nodes")

    if total == 0:
        log.info("Nothing to do.")
        return

    pending_points = []
    pending_ids = []
    done = 0

    with ThreadPoolExecutor(max_workers=len(EMBED_NODES) * 2) as pool:
        futures = {
            pool.submit(process_email, row, i): row["id"]
            for i, row in enumerate(rows)
        }
        for future in as_completed(futures):
            eid = futures[future]
            try:
                result = future.result()
                if result["status"] == "ok":
                    pending_points.append(result["point"])
                    pending_ids.append(result["id"])
                    with stats_lock:
                        stats["embedded"] += 1
                elif result["status"] == "skipped":
                    pending_ids.append(result["id"])
                    with stats_lock:
                        stats["skipped"] += 1
                else:
                    with stats_lock:
                        stats["errors"] += 1
            except Exception as exc:
                log.warning(f"Email {eid} failed: {exc}")
                with stats_lock:
                    stats["errors"] += 1

            if len(pending_points) >= BATCH_SIZE:
                upsert_batch(pending_points)
                mark_vectorized(pending_ids)
                done += len(pending_ids)
                log.info(f"  Progress: {done}/{total} ({100*done//total}%)")
                pending_points = []
                pending_ids = []

    if pending_points:
        upsert_batch(pending_points)
    if pending_ids:
        mark_vectorized(pending_ids)
        done += len(pending_ids)

    elapsed = round(time.time() - t0, 1)
    log.info(f"Backfill complete: {stats['embedded']} embedded, "
             f"{stats['skipped']} skipped, {stats['errors']} errors "
             f"in {elapsed}s ({total} total)")


if __name__ == "__main__":
    main()
