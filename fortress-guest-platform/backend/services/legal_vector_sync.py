"""
Legal Vector Sync Daemon (Step 1.2)

Standalone ingestion worker intended for cron/background execution.
Scans NAS legal vault, computes file hashes for idempotency, extracts text,
chunks content, embeds via local NIM endpoint, upserts vectors into Qdrant,
and binds evidence metadata into legal.case_evidence.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from uuid import UUID, uuid4, uuid5

import httpx
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Allow direct script execution: `python backend/services/legal_vector_sync.py`
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.config import settings

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NAS_VAULT_ROOT = Path("/mnt/fortress_nas/legal_vault")
EMBEDDING_URL = "http://192.168.0.100/v1/embeddings"
EMBEDDING_MODEL = "nomic-embed-text"
QDRANT_COLLECTION = "legal_library"
VECTOR_SIZE = 768
SUPPORTED_SUFFIXES = {".pdf", ".txt"}
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100
EMBED_BATCH_SIZE = 32

LOGGER = logging.getLogger("legal_vector_sync")


@dataclass
class IngestionStats:
    scanned_files: int = 0
    skipped_existing_hash: int = 0
    skipped_empty_text: int = 0
    ingested_files: int = 0
    failed_files: int = 0


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _to_sync_db_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def build_engine() -> Engine:
    return create_engine(_to_sync_db_url(settings.database_url), pool_pre_ping=True)


def iter_candidate_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".pdf":
        text_value = ""
        # Try native text extraction first.
        try:
            from PyPDF2 import PdfReader  # type: ignore

            reader = PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
            text_value = "\n\n".join(pages).strip()
        except Exception as pypdf_exc:
            LOGGER.warning("pdf_extract_pypdf2_failed", extra={"file": str(path), "error": str(pypdf_exc)})

        if not text_value:
            try:
                from pdfminer.high_level import extract_text as pdfminer_extract_text  # type: ignore

                text_value = (pdfminer_extract_text(str(path)) or "").strip()
            except Exception as pdfminer_exc:
                LOGGER.warning("pdf_extract_pdfminer_failed", extra={"file": str(path), "error": str(pdfminer_exc)})

        if not text_value:
            try:
                import fitz  # type: ignore

                doc = fitz.open(str(path))
                pages = [page.get_text() or "" for page in doc]
                doc.close()
                text_value = "\n\n".join(pages).strip()
            except Exception as fitz_exc:
                LOGGER.warning("pdf_extract_fitz_failed", extra={"file": str(path), "error": str(fitz_exc)})

        if _looks_garbage_text(text_value):
            LOGGER.info("pdf_routed_to_ocr", extra={"file": str(path)})
            text_value = _extract_pdf_text_ocr(path)

        return text_value.strip()

    return ""


def _looks_garbage_text(text_value: str) -> bool:
    content = (text_value or "").strip()
    if not content:
        return True
    if content.startswith("%PDF"):
        return True
    if len(content) < 50:
        return True

    alpha_count = sum(ch.isalpha() for ch in content)
    if alpha_count < 20:
        return True
    ratio = alpha_count / max(1, len(content))
    return ratio < 0.05


def _extract_pdf_text_ocr(path: Path) -> str:
    try:
        import pytesseract  # type: ignore
        from pdf2image import convert_from_path  # type: ignore
        pages = convert_from_path(str(path), dpi=300)
        ocr_parts: list[str] = []
        for page in pages:
            ocr_parts.append(pytesseract.image_to_string(page) or "")

        ocr_text = "\n\n".join(ocr_parts).strip()
        if _looks_garbage_text(ocr_text):
            raise RuntimeError(f"OCR produced unusable text for {path}")
        return ocr_text
    except Exception:
        # Fallback to CLI OCR so python3 environments without pip packages can still ingest.
        with tempfile.TemporaryDirectory(prefix="legal_ocr_") as tmp:
            prefix = Path(tmp) / "page"
            try:
                subprocess.run(
                    ["pdftoppm", "-r", "300", "-png", str(path), str(prefix)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except Exception as exc:
                raise RuntimeError(
                    "OCR dependencies missing. Install with: "
                    "brew install tesseract poppler && pip install pytesseract pdf2image"
                ) from exc

            pngs = sorted(Path(tmp).glob("page-*.png"))
            if not pngs:
                raise RuntimeError(f"OCR conversion produced no images for {path}")

            parts: list[str] = []
            for png in pngs:
                out = subprocess.run(
                    ["tesseract", str(png), "stdout"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                parts.append(out.stdout or "")

            ocr_text = "\n\n".join(parts).strip()
            if _looks_garbage_text(ocr_text):
                raise RuntimeError(f"OCR produced unusable text for {path}")
            return ocr_text


def chunk_text(text_value: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    clean = (text_value or "").strip()
    if not clean:
        return []
    if len(clean) <= chunk_size:
        return [clean]

    chunks: list[str] = []
    step = max(1, chunk_size - overlap)
    start = 0
    while start < len(clean):
        end = min(len(clean), start + chunk_size)
        segment = clean[start:end].strip()
        if segment:
            chunks.append(segment)
        if end >= len(clean):
            break
        start += step
    return chunks


def _extract_vectors_from_response(payload: dict) -> list[list[float]]:
    data = payload.get("data")
    if isinstance(data, list) and data:
        vectors = [row.get("embedding") for row in data if isinstance(row, dict)]
        return [vec for vec in vectors if isinstance(vec, list) and vec]

    # Some local gateways return {"embedding": [...]} for single input.
    single = payload.get("embedding")
    if isinstance(single, list) and single:
        return [single]
    return []


def _request_embeddings(client: httpx.Client, inputs: list[str]) -> list[list[float]]:
    try:
        resp = client.post(
            EMBEDDING_URL,
            json={"model": EMBEDDING_MODEL, "input": inputs},
            timeout=120.0,
        )
    except Exception as exc:
        raise RuntimeError(
            f"HARDWARE FAILURE: embedding endpoint unreachable ({EMBEDDING_URL}, model={EMBEDDING_MODEL}): {exc}"
        ) from exc

    if resp.status_code >= 400:
        raise RuntimeError(
            f"HARDWARE FAILURE: embedding endpoint returned {resp.status_code} "
            f"for model={EMBEDDING_MODEL} at {EMBEDDING_URL}: {resp.text[:300]}"
        )

    parsed = _extract_vectors_from_response(resp.json())
    if len(parsed) != len(inputs):
        raise RuntimeError(f"Embedding count mismatch: expected={len(inputs)} got={len(parsed)}")
    LOGGER.info("embedding_endpoint_selected", extra={"endpoint": EMBEDDING_URL, "model": EMBEDDING_MODEL})
    return parsed


def detect_embedding_dim(client: httpx.Client) -> int:
    vectors = _request_embeddings(client, ["dimension probe"])
    if not vectors or not isinstance(vectors[0], list):
        raise RuntimeError("HARDWARE FAILURE: could not detect embedding vector dimension")
    dim = len(vectors[0])
    if dim != VECTOR_SIZE:
        raise RuntimeError(
            f"HARDWARE FAILURE: expected vector size {VECTOR_SIZE} for {EMBEDDING_MODEL}, got {dim}"
        )
    LOGGER.info("embedding_dim_detected", extra={"dim": dim, "model": EMBEDDING_MODEL})
    return dim


def reset_relational_state(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE legal.case_evidence RESTART IDENTITY CASCADE"))
    LOGGER.warning("case_evidence_table_reset", extra={"table": "legal.case_evidence"})


def reset_qdrant_collection(qdrant: QdrantClient) -> None:
    try:
        qdrant.delete_collection(QDRANT_COLLECTION)
        LOGGER.warning("qdrant_collection_deleted", extra={"collection": QDRANT_COLLECTION})
    except Exception:
        pass

    qdrant.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config=qmodels.VectorParams(size=VECTOR_SIZE, distance=qmodels.Distance.COSINE),
    )
    LOGGER.info(
        "qdrant_collection_created",
        extra={"collection": QDRANT_COLLECTION, "vector_size": VECTOR_SIZE},
    )


def embed_chunks(client: httpx.Client, chunks: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[i : i + EMBED_BATCH_SIZE]
        batch_vectors = _request_embeddings(client, batch)
        if len(batch_vectors) != len(batch):
            raise RuntimeError(f"Embedding count mismatch: expected={len(batch)} got={len(batch_vectors)}")
        for vec in batch_vectors:
            if not isinstance(vec, list) or not vec:
                raise RuntimeError("Received invalid embedding vector from NIM endpoint")
            vectors.append(vec)
    return vectors


def parse_case_slug(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    if len(rel.parts) >= 2:
        return rel.parts[0]
    # If file is directly at vault root, use parent folder name.
    return path.parent.name or "unassigned-case"


def evidence_hash_exists(conn, sha_hash: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM legal.case_evidence WHERE sha256_hash = :sha LIMIT 1"),
        {"sha": sha_hash},
    ).first()
    return row is not None


def ingest_file(
    engine: Engine,
    qdrant: QdrantClient,
    emb_client: httpx.Client,
    file_path: Path,
    root: Path,
) -> bool:
    file_hash = sha256_file(file_path)
    file_name = file_path.name
    nas_path = str(file_path)
    case_slug = parse_case_slug(file_path, root)

    with engine.connect() as conn:
        if evidence_hash_exists(conn, file_hash):
            LOGGER.info("file_skipped_existing_hash", extra={"file": nas_path, "sha256_hash": file_hash})
            return False

    extracted_text = extract_text(file_path)
    chunks = chunk_text(extracted_text)
    if not chunks:
        LOGGER.warning("file_skipped_no_text", extra={"file": nas_path})
        raise ValueError("No extractable text")

    vectors = embed_chunks(emb_client, chunks)
    if len(vectors) != len(chunks):
        raise RuntimeError("Vector/chunk count mismatch after embedding")

    file_point_uuid = uuid4()
    point_ids: list[UUID] = [uuid5(file_point_uuid, str(idx)) for idx in range(len(chunks))]
    points = [
        qmodels.PointStruct(
            id=pid,
            vector=vec,
            payload={
                "case_slug": case_slug,
                "file_name": file_name,
                "nas_path": nas_path,
                "chunk_index": idx,
                "text_chunk": chunk,
                "qdrant_point_group": str(file_point_uuid),
                "sha256_hash": file_hash,
            },
        )
        for idx, (pid, vec, chunk) in enumerate(zip(point_ids, vectors, chunks))
    ]

    # DB transaction + Qdrant side effects in one guarded block.
    # If Postgres insert fails after Qdrant upsert, delete points to avoid orphaned vectors.
    with engine.begin() as conn:
        try:
            qdrant.upsert(collection_name=QDRANT_COLLECTION, points=points, wait=True)
            conn.execute(
                text(
                    """
                    INSERT INTO legal.case_evidence
                        (id, case_slug, entity_id, file_name, nas_path, qdrant_point_id, sha256_hash, uploaded_at)
                    VALUES
                        (:id, :case_slug, NULL, :file_name, :nas_path, :qdrant_point_id, :sha256_hash, NOW())
                    """
                ),
                {
                    "id": str(uuid4()),
                    "case_slug": case_slug,
                    "file_name": file_name,
                    "nas_path": nas_path,
                    "qdrant_point_id": str(file_point_uuid),
                    "sha256_hash": file_hash,
                },
            )
        except Exception:
            try:
                qdrant.delete(collection_name=QDRANT_COLLECTION, points_selector=qmodels.PointIdsList(points=point_ids), wait=True)
            except Exception as cleanup_exc:
                LOGGER.error(
                    "qdrant_cleanup_failed",
                    extra={"file": nas_path, "error": str(cleanup_exc)},
                )
            raise

    LOGGER.info(
        "file_ingested",
        extra={
            "file": nas_path,
            "case_slug": case_slug,
            "chunks": len(chunks),
            "qdrant_point_id": str(file_point_uuid),
            "sha256_hash": file_hash,
        },
    )
    return True


def run_sync() -> int:
    configure_logging()

    if not NAS_VAULT_ROOT.exists():
        LOGGER.error("nas_vault_missing", extra={"path": str(NAS_VAULT_ROOT)})
        return 2

    stats = IngestionStats()
    engine = build_engine()
    qdrant = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)

    with httpx.Client() as emb_client:
        detect_embedding_dim(emb_client)
        reset_qdrant_collection(qdrant)
        reset_relational_state(engine)

        for file_path in iter_candidate_files(NAS_VAULT_ROOT):
            stats.scanned_files += 1
            try:
                ingested = ingest_file(engine, qdrant, emb_client, file_path, NAS_VAULT_ROOT)
                if ingested:
                    stats.ingested_files += 1
                else:
                    stats.skipped_existing_hash += 1
            except ValueError:
                stats.skipped_empty_text += 1
            except Exception as exc:
                stats.failed_files += 1
                LOGGER.error("file_ingest_failed", extra={"file": str(file_path), "error": str(exc)})

    LOGGER.info(
        "legal_vector_sync_complete",
        extra={
            "scanned_files": stats.scanned_files,
            "ingested_files": stats.ingested_files,
            "skipped_existing_hash": stats.skipped_existing_hash,
            "skipped_empty_text": stats.skipped_empty_text,
            "failed_files": stats.failed_files,
        },
    )
    return 0 if stats.failed_files == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run_sync())

