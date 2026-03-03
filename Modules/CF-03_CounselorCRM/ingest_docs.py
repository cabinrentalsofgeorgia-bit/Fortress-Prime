#!/usr/bin/env python3
"""
Module CF-03: Counselor CRM — Document Ingestion Engine
=========================================================
Cabin Rentals of Georgia | Crog-Fortress-AI
Data Sovereignty: All embedding local via nomic-embed-text on DGX cluster.

Extracts text from PDF/DOCX/TXT/MD files, chunks them, embeds via the
4-GPU Ollama cluster, and upserts into the Qdrant ``legal_library``
collection with full CF-03 payload metadata.

PIPELINE:
    File -> Extract Text -> Chunk (1800/300 overlap) -> Embed (768-dim)
         -> Classify (rule-based) -> Qdrant Upsert (legal_library)

EXPORTS (consumed by api.py, legal_steward.py):
    discover_files, classify_document, ingest_file, ensure_collection,
    get_embedding, file_hash, get_indexed_hashes, get_collection_count,
    EMBED_MODEL, EMBED_DIM
"""

import hashlib
import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

_project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, _project_root)
from config import get_ollama_endpoints

logger = logging.getLogger("fortress.counselor_crm.ingest")

# ── Configuration ─────────────────────────────────────────────────

EMBED_NODES: List[str] = get_ollama_endpoints()
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_PORT}"
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_HEADERS: Dict[str, str] = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}
COLLECTION_NAME = os.getenv("COUNSELOR_COLLECTION", "legal_library")

CHUNK_SIZE = 1800
CHUNK_OVERLAP = 300
MAX_FILE_SIZE = 50_000_000  # 50 MB

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".rtf"}

QDRANT_BATCH_SIZE = 15

# ── Category Classification (rule-based) ─────────────────────────

_CATEGORY_RULES: List[tuple] = [
    (re.compile(r"management.?contract|pm.?agreement|property.?management", re.I), "management_contract"),
    (re.compile(r"lease|rental.?agreement|rental.?contract", re.I), "lease_agreement"),
    (re.compile(r"deed|warranty.?deed|quit.?claim|title", re.I), "property_deed"),
    (re.compile(r"easement|right.?of.?way", re.I), "easement"),
    (re.compile(r"insurance|policy|coverage|liability", re.I), "insurance"),
    (re.compile(r"tax|assessment|1099|w-?9", re.I), "tax_document"),
    (re.compile(r"permit|license|zoning|variance", re.I), "permit_license"),
    (re.compile(r"complaint|motion|order|summons|subpoena|pleading", re.I), "court_filing"),
    (re.compile(r"discovery|interrogator|production|request.?for", re.I), "discovery_material"),
    (re.compile(r"deposition|transcript|sworn", re.I), "deposition_transcript"),
    (re.compile(r"invoice|billing|fee.?statement|retainer", re.I), "billing_fees"),
    (re.compile(r"o\.?c\.?g\.?a|georgia.?code|statute", re.I), "georgia_statute"),
    (re.compile(r"ordinance|hoa|covenant|regulation", re.I), "local_regulation"),
    (re.compile(r"letter|notice|demand|correspondence", re.I), "correspondence"),
    (re.compile(r"contract|agreement|mou|memorandum", re.I), "contract"),
]


def classify_document(path: str) -> str:
    """Classify a document by its filename and parent directory path."""
    combined = f"{path} {Path(path).stem}"
    for pattern, category in _CATEGORY_RULES:
        if pattern.search(combined):
            return category
    return "general_legal"


# ── Text Extraction ──────────────────────────────────────────────

def _extract_pdf(path: str) -> str:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(path)
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n\n".join(pages)
    except ImportError:
        logger.warning("PyMuPDF not installed; falling back to pdftotext CLI for %s", path)
        try:
            import subprocess
            result = subprocess.run(
                ["pdftotext", "-layout", path, "-"],
                capture_output=True, text=True, timeout=60,
            )
            return result.stdout
        except Exception as e:
            logger.error("pdftotext fallback failed for %s: %s", path, e)
            return ""
    except Exception as e:
        logger.error("PDF extraction failed for %s: %s", path, e)
        return ""


def _extract_docx(path: str) -> str:
    try:
        from docx import Document
        doc = Document(path)
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        logger.warning("python-docx not installed; cannot extract %s", path)
        return ""
    except Exception as e:
        logger.error("DOCX extraction failed for %s: %s", path, e)
        return ""


def _extract_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        logger.error("Text read failed for %s: %s", path, e)
        return ""


def extract_text(path: str) -> str:
    """Extract text from a file based on its extension."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return _extract_pdf(path)
    elif ext in (".docx", ".doc"):
        return _extract_docx(path)
    elif ext in (".txt", ".md", ".rtf"):
        return _extract_text(path)
    else:
        logger.warning("Unsupported extension %s for %s", ext, path)
        return ""


# ── Chunking ─────────────────────────────────────────────────────

def chunk_text(text: str) -> List[str]:
    """Split text into overlapping chunks of CHUNK_SIZE with CHUNK_OVERLAP."""
    if not text or not text.strip():
        return []
    if len(text) <= CHUNK_SIZE:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ── File Hashing ─────────────────────────────────────────────────

def file_hash(path: str) -> str:
    """SHA-256 hash of file contents for deduplication."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


# ── Embedding (Circuit-Breaker Round-Robin) ──────────────────────

_node_idx = 0
_node_failures: Dict[str, int] = {}
_node_tripped_until: Dict[str, float] = {}
_CB_THRESHOLD = 5
_CB_COOLDOWN_SEC = 60

_embed_session = requests.Session()
_embed_adapter = requests.adapters.HTTPAdapter(
    pool_connections=max(len(EMBED_NODES), 1),
    pool_maxsize=64,
    max_retries=0,
)
_embed_session.mount("http://", _embed_adapter)


def _is_node_healthy(node: str) -> bool:
    now = time.monotonic()
    tripped = _node_tripped_until.get(node, 0)
    if now < tripped:
        return False
    if now >= tripped and tripped > 0:
        _node_tripped_until.pop(node, None)
        _node_failures[node] = 0
    return True


def _record_failure(node: str):
    _node_failures[node] = _node_failures.get(node, 0) + 1
    if _node_failures[node] >= _CB_THRESHOLD:
        _node_tripped_until[node] = time.monotonic() + _CB_COOLDOWN_SEC
        logger.warning(
            "CIRCUIT BREAKER OPEN: %s tripped after %d failures. Bypassing %ds.",
            node, _node_failures[node], _CB_COOLDOWN_SEC,
        )


def _record_success(node: str):
    _node_failures[node] = 0
    _node_tripped_until.pop(node, None)


def _next_healthy_node() -> Optional[str]:
    global _node_idx
    n = len(EMBED_NODES)
    if n == 0:
        return None
    for _ in range(n):
        node = EMBED_NODES[_node_idx % n]
        _node_idx += 1
        if _is_node_healthy(node):
            return node
    return None


def get_embedding(text: str, retries: int = 3) -> Optional[List[float]]:
    """Embed text via round-robin Ollama cluster with circuit-breaker retry."""
    for attempt in range(retries):
        node = _next_healthy_node()
        if not node:
            logger.error("ALL embed nodes tripped. Waiting %ds for cooldown.", _CB_COOLDOWN_SEC)
            time.sleep(_CB_COOLDOWN_SEC)
            node = _next_healthy_node()
            if not node:
                return None
        try:
            resp = _embed_session.post(
                f"{node}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text[:8000]},
                timeout=10,
            )
            if resp.status_code == 200:
                emb = resp.json().get("embedding")
                if emb and len(emb) == EMBED_DIM:
                    _record_success(node)
                    return emb
            logger.warning("Embed node %s returned %d on attempt %d", node, resp.status_code, attempt + 1)
            _record_failure(node)
        except requests.exceptions.Timeout:
            logger.warning("Embed node %s TIMEOUT on attempt %d", node, attempt + 1)
            _record_failure(node)
        except requests.exceptions.ConnectionError:
            logger.warning("Embed node %s CONNECTION REFUSED on attempt %d", node, attempt + 1)
            _record_failure(node)
        except Exception as e:
            logger.warning("Embed node %s error on attempt %d: %s", node, attempt + 1, e)
            _record_failure(node)
        time.sleep(0.3 * (attempt + 1))
    return None


# ── Qdrant Operations ────────────────────────────────────────────

def ensure_collection() -> bool:
    """Create the legal_library collection if it doesn't exist."""
    try:
        resp = requests.get(
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}",
            headers=QDRANT_HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            return True
    except Exception:
        pass

    try:
        resp = requests.put(
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}",
            json={
                "vectors": {
                    "size": EMBED_DIM,
                    "distance": "Cosine",
                },
            },
            headers=QDRANT_HEADERS,
            timeout=30,
        )
        if resp.status_code in (200, 201):
            logger.info("Created Qdrant collection: %s", COLLECTION_NAME)
            return True
        logger.error("Failed to create collection %s: %s", COLLECTION_NAME, resp.text[:300])
        return False
    except Exception as e:
        logger.error("Qdrant collection creation error: %s", e)
        return False


def _qdrant_upsert(points: List[Dict]) -> bool:
    """Upsert points into legal_library in sub-batches."""
    for i in range(0, len(points), QDRANT_BATCH_SIZE):
        batch = points[i:i + QDRANT_BATCH_SIZE]
        try:
            resp = requests.put(
                f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points",
                json={"points": batch},
                headers=QDRANT_HEADERS,
                timeout=60,
                params={"wait": "true"},
            )
            if resp.status_code not in (200, 201):
                logger.error("Qdrant upsert failed (%d pts): %s", len(batch), resp.text[:300])
                return False
        except Exception as e:
            logger.error("Qdrant upsert exception: %s", e)
            return False
    return True


def get_collection_count() -> int:
    """Return the number of points in the legal_library collection."""
    try:
        resp = requests.get(
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}",
            headers=QDRANT_HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("result", {}).get("points_count", 0)
    except Exception as e:
        logger.error("Failed to get collection count: %s", e)
    return 0


def get_indexed_hashes() -> Dict[str, str]:
    """Retrieve all stored file hashes from Qdrant for dedup.

    Returns a mapping of source_file -> file_hash for points that
    have a ``file_hash`` payload field.  Uses scroll API to page
    through the entire collection.
    """
    hashes: Dict[str, str] = {}
    offset = None
    try:
        while True:
            body: Dict[str, Any] = {
                "limit": 100,
                "with_payload": ["source_file", "file_hash"],
                "with_vector": False,
            }
            if offset is not None:
                body["offset"] = offset
            resp = requests.post(
                f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points/scroll",
                json=body,
                headers=QDRANT_HEADERS,
                timeout=30,
            )
            if resp.status_code != 200:
                break
            data = resp.json().get("result", {})
            points = data.get("points", [])
            for pt in points:
                payload = pt.get("payload", {})
                src = payload.get("source_file")
                fh = payload.get("file_hash")
                if src and fh:
                    hashes[src] = fh
            next_offset = data.get("next_page_offset")
            if next_offset is None or not points:
                break
            offset = next_offset
    except Exception as e:
        logger.error("Error scrolling indexed hashes: %s", e)
    return hashes


# ── File Discovery ───────────────────────────────────────────────

def discover_files(source_dir: str) -> List[str]:
    """Walk source_dir and return all ingestable file paths."""
    found = []
    if not os.path.isdir(source_dir):
        logger.warning("Source directory does not exist: %s", source_dir)
        return found
    for root, _dirs, files in os.walk(source_dir):
        for fname in files:
            ext = Path(fname).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            full_path = os.path.join(root, fname)
            if os.path.getsize(full_path) > MAX_FILE_SIZE:
                logger.warning("Skipping oversized file (%d bytes): %s", os.path.getsize(full_path), full_path)
                continue
            found.append(full_path)
    return sorted(found)


# ── Core Ingestion Pipeline ──────────────────────────────────────

def ingest_file(
    path: str,
    category: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full pipeline: extract -> chunk -> embed -> upsert to Qdrant.

    Args:
        path: Absolute path to the document file.
        category: Override category (auto-classified if None).
        extra_metadata: Additional payload fields merged into each point
                        (e.g. ``{"owner_id": "123"}``).

    Returns:
        Summary dict with status, chunk count, and collection point count.
    """
    result: Dict[str, Any] = {
        "path": path,
        "status": "error",
        "chunks": 0,
        "collection_count": 0,
    }

    if not os.path.isfile(path):
        result["error"] = "File not found"
        logger.error("File not found: %s", path)
        return result

    ensure_collection()

    cat = category or classify_document(path)
    fhash = file_hash(path)
    file_name = Path(path).name
    parent_dir = str(Path(path).parent)

    text = extract_text(path)
    if not text or not text.strip():
        result["error"] = "No text extracted"
        logger.warning("No text extracted from %s", path)
        return result

    chunks = chunk_text(text)
    if not chunks:
        result["error"] = "No chunks produced"
        return result

    logger.info(
        "Ingesting %s: %d chunks, category=%s, hash=%s",
        file_name, len(chunks), cat, fhash[:12],
    )

    points = []
    failed_embeds = 0
    for i, chunk in enumerate(chunks):
        embedding = get_embedding(chunk)
        if embedding is None:
            failed_embeds += 1
            logger.warning("Embedding failed for chunk %d/%d of %s", i + 1, len(chunks), file_name)
            continue

        payload: Dict[str, Any] = {
            "text": chunk,
            "source_file": path,
            "file_name": file_name,
            "category": cat,
            "parent_dir": parent_dir,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "file_hash": fhash,
            "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if extra_metadata:
            payload.update(extra_metadata)

        points.append({
            "id": str(uuid.uuid4()),
            "vector": embedding,
            "payload": payload,
        })

    if not points:
        result["error"] = f"All {failed_embeds} embeddings failed"
        return result

    success = _qdrant_upsert(points)
    if success:
        result["status"] = "ok"
        result["chunks"] = len(points)
        result["failed_embeds"] = failed_embeds
        result["category"] = cat
        result["file_hash"] = fhash
        result["collection_count"] = get_collection_count()
        logger.info(
            "Ingested %s: %d/%d chunks into %s",
            file_name, len(points), len(chunks), COLLECTION_NAME,
        )
    else:
        result["error"] = "Qdrant upsert failed"

    return result


# ── CLI ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="CF-03 Document Ingestion Engine — ingest legal docs into Qdrant",
    )
    parser.add_argument("path", help="File or directory to ingest")
    parser.add_argument("--category", default=None, help="Override document category")
    parser.add_argument("--dry-run", action="store_true", help="Discover + classify only, no ingestion")
    args = parser.parse_args()

    target = args.path
    if os.path.isdir(target):
        files = discover_files(target)
        print(f"Discovered {len(files)} files in {target}")
        if args.dry_run:
            for f in files:
                cat = classify_document(f)
                print(f"  [{cat:25s}] {f}")
        else:
            ensure_collection()
            for f in files:
                res = ingest_file(f, category=args.category)
                print(f"  [{res['status']:5s}] {res['chunks']:3d} chunks — {f}")
    elif os.path.isfile(target):
        if args.dry_run:
            cat = classify_document(target)
            print(f"Category: {cat}")
            print(f"Hash:     {file_hash(target)}")
        else:
            res = ingest_file(target, category=args.category)
            print(f"Status: {res['status']}")
            print(f"Chunks: {res['chunks']}")
            if res.get("error"):
                print(f"Error:  {res['error']}")
            print(f"Collection count: {res['collection_count']}")
    else:
        print(f"Path not found: {target}")
        sys.exit(1)
