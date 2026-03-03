"""
Sovereign Wealth Knowledge Ingestion — Qdrant Vector Vault Pipeline

Ingests Fannin County Environmental Health septic regulations, local zoning
laws, surveyor site plans, and Certified Financial Planning (CFP) literature
into the ``cfp_wealth_vault`` Qdrant collection for RAG retrieval by the
Wealth Swarm (src/wealth_swarm_graph.py).

Usage:
    1. Place PDFs in data/wealth_docs/
    2. python tools/ingest_wealth_docs.py

Embedding: nomic-embed-text (768-dim) round-robined across DGX Spark nodes.
Chunking:  2000 chars / 400 overlap (Fortress Sentinel standard).
Batching:  100 vectors per Qdrant upsert.
"""

import os
import sys
import uuid
import itertools
import logging
import httpx
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-28s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("wealth_ingestion")

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = "cfp_wealth_vault"
VECTOR_DIM = 768
EMBED_MODEL = "nomic-embed-text"
DOCS_DIR = os.getenv("WEALTH_DOCS_DIR", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "wealth_docs"
))
CHUNK_SIZE = 2000
CHUNK_OVERLAP = 400
BATCH_SIZE = 100


def _get_embed_endpoints() -> list[str]:
    """Resolve embedding endpoints: prefer config.py multi-node, fall back to localhost."""
    try:
        from config import get_swarm_node_endpoints
        return [f"{ep}/api/embeddings" for ep in get_swarm_node_endpoints()]
    except Exception:
        return ["http://localhost:11434/api/embeddings"]


def get_embedding(text: str, endpoint: str) -> list[float]:
    """Generate a 768-dim embedding via nomic-embed-text on a DGX node."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(endpoint, json={"model": EMBED_MODEL, "prompt": text[:8000]})
        resp.raise_for_status()
        vec = resp.json().get("embedding", [])
        if len(vec) != VECTOR_DIM:
            raise ValueError(f"Expected {VECTOR_DIM}-dim vector, got {len(vec)}")
        return vec


def ensure_collection(client: QdrantClient) -> None:
    """Create cfp_wealth_vault if it doesn't already exist."""
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION in existing:
        log.info("Collection '%s' already exists — skipping creation.", COLLECTION)
        return
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=qmodels.VectorParams(
            size=VECTOR_DIM,
            distance=qmodels.Distance.COSINE,
        ),
    )
    log.info("Created Qdrant collection '%s' (dim=%d, Cosine).", COLLECTION, VECTOR_DIM)


def classify_source(filepath: str) -> str:
    """Heuristic source-type tag based on filename keywords."""
    name = Path(filepath).stem.lower()
    if any(k in name for k in ("septic", "environmental", "health", "permit")):
        return "septic_permit"
    if any(k in name for k in ("zoning", "ordinance", "land_use", "subdivision")):
        return "zoning"
    if any(k in name for k in ("survey", "site_plan", "plat", "topo")):
        return "site_plan"
    if any(k in name for k in ("cfp", "tax", "capex", "depreciation", "irs", "1031")):
        return "cfp_literature"
    return "general"


def main() -> None:
    if not os.path.exists(DOCS_DIR):
        os.makedirs(DOCS_DIR, exist_ok=True)
        log.warning(
            "Created %s — place Fannin County/CFP PDFs there and rerun.", DOCS_DIR
        )
        return

    pdf_count = sum(1 for f in os.listdir(DOCS_DIR) if f.lower().endswith(".pdf"))
    if pdf_count == 0:
        log.warning("No PDFs found in %s. Aborting ingestion.", DOCS_DIR)
        return

    log.info("Loading %d PDF(s) from %s ...", pdf_count, DOCS_DIR)
    loader = PyPDFDirectoryLoader(DOCS_DIR)
    docs = loader.load()
    if not docs:
        log.warning("PyPDF returned 0 pages. Check PDF readability.")
        return

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    chunks = splitter.split_documents(docs)
    log.info("Split %d pages into %d chunks (%d/%d).", len(docs), len(chunks), CHUNK_SIZE, CHUNK_OVERLAP)

    q_client = QdrantClient(url=QDRANT_URL)
    ensure_collection(q_client)

    endpoints = _get_embed_endpoints()
    endpoint_cycle = itertools.cycle(endpoints)
    log.info("Embedding via %d node(s): %s", len(endpoints), endpoints)

    points: list[qmodels.PointStruct] = []
    failed = 0

    for i, chunk in enumerate(chunks):
        ep = next(endpoint_cycle)
        try:
            vector = get_embedding(chunk.page_content, ep)
        except Exception as e:
            log.error("Embed failed on chunk %d (%s): %s", i, ep, e)
            failed += 1
            continue

        source_file = chunk.metadata.get("source", "unknown")
        points.append(qmodels.PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                "text": chunk.page_content,
                "source": source_file,
                "source_type": classify_source(source_file),
                "page": chunk.metadata.get("page", 0),
            },
        ))

        if len(points) >= BATCH_SIZE:
            q_client.upsert(collection_name=COLLECTION, points=points)
            log.info("Upserted batch (%d vectors so far, %d/%d chunks).", i + 1 - failed, i + 1, len(chunks))
            points.clear()

        if (i + 1) % 50 == 0:
            log.info("Progress: %d / %d chunks embedded.", i + 1, len(chunks))

    if points:
        q_client.upsert(collection_name=COLLECTION, points=points)

    total = len(chunks) - failed
    log.info(
        "INGESTION COMPLETE: %d vectors vaulted into '%s'. Failures: %d.",
        total, COLLECTION, failed,
    )
    q_client.close()


if __name__ == "__main__":
    main()
