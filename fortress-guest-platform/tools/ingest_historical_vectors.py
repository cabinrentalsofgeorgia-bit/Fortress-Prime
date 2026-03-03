#!/usr/bin/env python3
"""
Ingest Historical Leads into Qdrant — Vector RAG Pipeline

Reads tests/fixtures/historical_leads.jsonl, embeds each record using
nomic-embed-text (768-dim via Ollama), and upserts into the Qdrant
`historical_quotes` collection.

Each point's payload stores the original guest message, staff response,
guest name, and reservation metadata so the AI can retrieve full context
during few-shot RAG generation.

Usage:
    python3 tools/ingest_historical_vectors.py
"""
import json
import sys
import time
import hashlib
from pathlib import Path
from uuid import uuid5, NAMESPACE_DNS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.config import settings
from backend.core.vector_db import (
    get_qdrant_client,
    ensure_collection,
    embed_text_sync,
    HISTORICAL_QUOTES_COLLECTION,
)
from qdrant_client.http import models as qmodels

JSONL_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "historical_leads.jsonl"


def build_semantic_text(record: dict) -> str:
    """
    Construct the unified semantic string for embedding.

    Combines the guest inquiry and staff response into a single passage
    that captures the conversational context for similarity search.
    """
    guest_msg = (record.get("guest_message") or "").strip()
    staff_resp = (record.get("staff_response") or "").strip()

    if not staff_resp:
        notes = record.get("staff_notes") or []
        note_texts = [n.get("message", "") for n in notes if n.get("message", "")]
        staff_resp = " | ".join(note_texts).strip()

    parts = []
    if guest_msg:
        parts.append(f"Guest Inquiry: {guest_msg}")
    if staff_resp:
        parts.append(f"Staff Response: {staff_resp}")

    guest_name = record.get("guest_name", "Unknown")
    property_name = record.get("property_name") or "unspecified property"
    check_in = record.get("check_in_date") or "unknown"
    check_out = record.get("check_out_date") or "unknown"
    num_guests = record.get("num_guests") or "?"
    num_pets = record.get("num_pets") or 0

    context_parts = [f"Guest: {guest_name}", f"Property: {property_name}"]
    if check_in != "unknown":
        context_parts.append(f"Dates: {check_in} to {check_out}")
    context_parts.append(f"Guests: {num_guests}")
    if num_pets:
        context_parts.append(f"Pets: {num_pets}")

    parts.append("Context: " + ", ".join(context_parts))

    return " | ".join(parts)


def build_payload(record: dict) -> dict:
    """Build the Qdrant point payload with sanitized metadata."""
    return {
        "guest_name": (record.get("guest_name") or "Unknown").strip(),
        "guest_message": (record.get("guest_message") or "").strip(),
        "staff_response": (record.get("staff_response") or "").strip(),
        "staff_notes": [
            {"author": n.get("author", ""), "message": n.get("message", ""), "date": n.get("date", "")}
            for n in (record.get("staff_notes") or [])
            if n.get("message")
        ],
        "streamline_reservation_id": record.get("streamline_reservation_id", ""),
        "guest_email": (record.get("guest_email") or "").strip(),
        "property_name": (record.get("property_name") or "").strip(),
        "check_in_date": record.get("check_in_date", ""),
        "check_out_date": record.get("check_out_date", ""),
        "num_guests": record.get("num_guests"),
        "num_pets": record.get("num_pets", 0),
        "total_amount": record.get("total_amount", ""),
        "source": record.get("source", ""),
        "has_staff_response": bool(record.get("staff_response")),
    }


def deterministic_uuid(text: str) -> str:
    """Generate a deterministic UUID from text so re-runs are idempotent."""
    return str(uuid5(NAMESPACE_DNS, text))


def main():
    print("=" * 72)
    print("VECTOR INGESTION PIPELINE — Historical Quotes")
    print("=" * 72)
    print(f"  Qdrant:     {settings.qdrant_url}")
    print(f"  Embedding:  {settings.embed_model} @ {settings.embed_base_url}")
    print(f"  Collection: {HISTORICAL_QUOTES_COLLECTION}")
    print(f"  Dimension:  {settings.embed_dim}")
    print(f"  Source:     {JSONL_PATH}")
    print()

    if not JSONL_PATH.exists():
        print(f"ERROR: {JSONL_PATH} not found")
        sys.exit(1)

    with open(JSONL_PATH) as f:
        records = [json.loads(line) for line in f if line.strip()]

    print(f"Loaded {len(records)} records from JSONL")

    ensure_collection(HISTORICAL_QUOTES_COLLECTION)
    client = get_qdrant_client()
    print(f"Collection '{HISTORICAL_QUOTES_COLLECTION}' ready\n")

    points = []
    skipped = 0
    t0 = time.time()

    for i, record in enumerate(records):
        semantic_text = build_semantic_text(record)

        if len(semantic_text) < 20:
            skipped += 1
            continue

        try:
            vector = embed_text_sync(semantic_text)
        except Exception as e:
            print(f"  [{i:2d}] EMBED ERROR for {record.get('guest_name','?')}: {e}")
            skipped += 1
            continue

        point_id = deterministic_uuid(
            record.get("streamline_reservation_id", "") + "|" + record.get("guest_name", "")
        )

        points.append(qmodels.PointStruct(
            id=point_id,
            vector=vector,
            payload=build_payload(record),
        ))

        guest = record.get("guest_name", "?")
        has_resp = "+" if record.get("staff_response") else "-"
        print(f"  [{i:2d}] {guest:25s} [{has_resp}resp]  dim={len(vector)}  text={len(semantic_text)} chars")

    print(f"\nEmbedded {len(points)} points ({skipped} skipped)")

    if points:
        BATCH_SIZE = 25
        for batch_start in range(0, len(points), BATCH_SIZE):
            batch = points[batch_start:batch_start + BATCH_SIZE]
            client.upsert(
                collection_name=HISTORICAL_QUOTES_COLLECTION,
                points=batch,
            )
            print(f"  Upserted batch {batch_start // BATCH_SIZE + 1}: {len(batch)} points")

    elapsed = time.time() - t0
    print(f"\nIngestion complete in {elapsed:.1f}s")

    info = client.get_collection(HISTORICAL_QUOTES_COLLECTION)
    print(f"Collection '{HISTORICAL_QUOTES_COLLECTION}': {info.points_count} vectors, dim={info.config.params.vectors.size}")

    print("\n" + "=" * 72)
    print("SEMANTIC SEARCH VALIDATION")
    print("=" * 72)

    test_queries = [
        "Looking for a pet friendly cabin for Thanksgiving",
        "anniversary weekend getaway with hot tub and mountain view",
        "large group cabin for New Years Eve celebration",
    ]

    for query in test_queries:
        print(f"\nQuery: \"{query}\"")
        query_vector = embed_text_sync(query)
        response = client.query_points(
            collection_name=HISTORICAL_QUOTES_COLLECTION,
            query=query_vector,
            limit=3,
        )
        for rank, hit in enumerate(response.points, 1):
            p = hit.payload
            guest = p.get("guest_name", "?")
            msg = (p.get("guest_message") or "")[:80]
            resp = (p.get("staff_response") or "")[:60]
            score = hit.score
            print(f"  #{rank} [{score:.4f}] {guest}: {msg}")
            if resp:
                print(f"         Response: {resp}...")

    print("\n" + "=" * 72)
    print("VECTOR POWERHOUSE ONLINE")
    print("=" * 72)


if __name__ == "__main__":
    main()
