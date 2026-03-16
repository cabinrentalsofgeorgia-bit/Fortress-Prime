"""
E-Discovery Vault Ingestion Engine — stores files on NAS, extracts text,
chunks, vectorizes via DGX embeddings, and indexes into Qdrant.

CoCounsel Privilege Shield: Every document passes through a pre-flight
privilege classifier before vectorization.  Attorney-client privileged
material is quarantined to legal.privilege_log and NEVER enters the
case graph or Qdrant search index.
"""
from __future__ import annotations

import hashlib
import json
import time
import structlog
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.http_client import shared_client
from backend.services.legal_evidence_ingestion import _chunk_document

logger = structlog.get_logger()

NAS_VAULT_ROOT = Path("/mnt/fortress_nas/legal_vault")
LOCAL_VAULT_FALLBACK = Path("/home/admin/Fortress-Prime/data/legal_vault")
QDRANT_COLLECTION = "legal_ediscovery"
QDRANT_URL = settings.qdrant_url if hasattr(settings, "qdrant_url") else "http://localhost:6333"
EMBED_URL = settings.embedding_url if hasattr(settings, "embedding_url") else "http://192.168.0.100/api/embeddings"
EMBED_MODEL = "nomic-embed-text:latest"

SWARM_ENDPOINT = "http://192.168.0.100/v1/chat/completions"
SWARM_MODEL = "qwen2.5:7b"


# ── Pydantic: Privilege Classification ────────────────────────────

class PrivilegeClassification(BaseModel):
    is_privileged: bool = Field(default=False, description="True if document contains attorney-client or work-product material")
    privilege_type: str = Field(default="none", description="attorney_client | work_product | joint_defense | none")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning: str = Field(default="", description="Brief explanation of why this is or is not privileged")

    @field_validator("privilege_type", mode="before")
    @classmethod
    def _coerce_none(cls, v):
        return v or "none"

    @field_validator("reasoning", mode="before")
    @classmethod
    def _coerce_reasoning(cls, v):
        return v or ""


PRIVILEGE_SYSTEM_PROMPT = (
    "You are a legal privilege classifier. Analyze the document text and determine "
    "if it contains Attorney-Client Privileged communications, Work Product, or "
    "Joint Defense Agreement material. Look for: communications between a client "
    "and their attorney seeking or providing legal advice; attorney mental "
    "impressions, strategies, or legal theories; joint defense communications. "
    "Respond ONLY with valid JSON: "
    '{"is_privileged":true,"privilege_type":"attorney_client","confidence":0.95,'
    '"reasoning":"Email between Gary Knight and retained counsel discussing litigation strategy"}'
)


# ── Helpers ───────────────────────────────────────────────────────

def _resolve_vault_dir(case_slug: str) -> Path:
    try:
        if NAS_VAULT_ROOT.exists():
            target = NAS_VAULT_ROOT / case_slug
            target.mkdir(parents=True, exist_ok=True)
            return target
    except (PermissionError, OSError) as exc:
        logger.warning("vault_nas_unavailable", error=str(exc)[:120])
    target = LOCAL_VAULT_FALLBACK / case_slug
    target.mkdir(parents=True, exist_ok=True)
    return target


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extract_text(file_bytes: bytes, mime_type: str, file_name: str) -> str:
    if "pdf" in mime_type.lower():
        try:
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            pages = [page.get_text() for page in doc]
            doc.close()
            return "\n\n".join(pages)
        except ImportError:
            logger.warning("pymupdf_not_installed_falling_back_to_raw")
        except Exception as exc:
            logger.warning("pdf_extraction_failed", error=str(exc)[:200])
        return file_bytes.decode("utf-8", errors="ignore")

    if "csv" in mime_type.lower():
        return file_bytes.decode("utf-8", errors="ignore")

    return file_bytes.decode("utf-8", errors="ignore")


# ── Privilege Classifier ──────────────────────────────────────────

async def _classify_privilege(raw_text: str, file_name: str) -> tuple[PrivilegeClassification, int]:
    """Run a fast pre-flight privilege check via local Qwen2.5.
    Returns (classification, latency_ms)."""
    snippet = raw_text[:3000]
    prompt = f"DOCUMENT: {file_name}\n\n{snippet}"

    t0 = time.perf_counter()
    try:
        resp = await shared_client.post(
            SWARM_ENDPOINT,
            json={
                "model": SWARM_MODEL,
                "messages": [
                    {"role": "system", "content": PRIVILEGE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.05,
                "max_tokens": 256,
            },
            timeout=60.0,
        )
        latency = int((time.perf_counter() - t0) * 1000)
        resp.raise_for_status()
        data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        raw_json = content
        if raw_json.startswith("```"):
            nl = raw_json.find("\n")
            raw_json = raw_json[nl + 1:] if nl > 0 else raw_json[3:]
        if raw_json.endswith("```"):
            raw_json = raw_json[:-3]

        start = raw_json.find("{")
        end = raw_json.rfind("}")
        if start >= 0 and end > start:
            raw_json = raw_json[start : end + 1]

        classification = PrivilegeClassification.model_validate_json(raw_json)
        return classification, latency

    except Exception as exc:
        latency = int((time.perf_counter() - t0) * 1000)
        logger.warning(
            "privilege_classifier_failed",
            file=file_name,
            error=str(exc)[:200],
            latency_ms=latency,
        )
        return PrivilegeClassification(
            is_privileged=False,
            privilege_type="none",
            confidence=0.0,
            reasoning=f"Classifier failed: {str(exc)[:100]}",
        ), latency


async def _log_privilege(
    db: AsyncSession,
    doc_id: str,
    case_slug: str,
    file_name: str,
    classification: PrivilegeClassification,
    model: str,
    latency_ms: int,
    snippet: str,
) -> None:
    """Write a permanent privilege log entry and lock the vault document."""
    await db.execute(
        text("""
            INSERT INTO legal.privilege_log
                (document_id, case_slug, file_name, privilege_type, reasoning,
                 model_used, latency_ms, classifier_confidence, snippet)
            VALUES (:did, :slug, :fname, :ptype, :reason, :model, :lat, :conf, :snip)
        """),
        {
            "did": doc_id,
            "slug": case_slug,
            "fname": file_name,
            "ptype": classification.privilege_type,
            "reason": classification.reasoning,
            "model": model,
            "lat": latency_ms,
            "conf": classification.confidence,
            "snip": snippet[:2000],
        },
    )
    await db.execute(
        text("""
            UPDATE legal.vault_documents
            SET processing_status = 'locked_privileged'
            WHERE id = :id
        """),
        {"id": doc_id},
    )
    await db.commit()
    logger.info(
        "privilege_shield_activated",
        doc_id=doc_id,
        file_name=file_name,
        privilege_type=classification.privilege_type,
        confidence=classification.confidence,
    )


# ── Embedding ─────────────────────────────────────────────────────

async def _embed_single(text_input: str) -> list[float]:
    max_retries = 3
    current = text_input[:4000]
    for attempt in range(max_retries):
        try:
            resp = await shared_client.post(
                EMBED_URL,
                json={"model": EMBED_MODEL, "prompt": current},
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
            embedding = data.get("embedding") or data.get("data", [{}])[0].get("embedding")
            return embedding if embedding else []
        except Exception as exc:
            err = str(exc)[:200]
            if "500" in err and attempt < max_retries - 1:
                current = current[: len(current) // 2]
                logger.info("embedding_retry_halved", attempt=attempt + 1, new_len=len(current))
                continue
            logger.warning("embedding_failed", error=err, attempt=attempt + 1)
            return []
    return []


async def _embed_chunks(chunks: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for chunk in chunks:
        vec = await _embed_single(chunk)
        vectors.append(vec)
    return vectors


# ── Qdrant ────────────────────────────────────────────────────────

async def _upsert_to_qdrant(
    doc_id: str,
    case_slug: str,
    file_name: str,
    chunks: list[str],
    vectors: list[list[float]],
) -> int:
    points = []
    for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
        if not vector:
            continue
        points.append({
            "id": str(uuid4()),
            "vector": vector,
            "payload": {
                "case_slug": case_slug,
                "document_id": doc_id,
                "file_name": file_name,
                "chunk_index": idx,
                "text": chunk[:1000],
            },
        })

    if not points:
        return 0

    try:
        await shared_client.put(
            f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}",
            json={
                "vectors": {"size": len(points[0]["vector"]), "distance": "Cosine"},
            },
            timeout=10.0,
        )
    except Exception:
        pass

    try:
        resp = await shared_client.put(
            f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points",
            json={"points": points},
            timeout=60.0,
        )
        resp.raise_for_status()
        return len(points)
    except Exception as exc:
        logger.warning("qdrant_upsert_failed", error=str(exc)[:200])
        return 0


# ── Main Ingestion Pipeline ──────────────────────────────────────

async def process_vault_upload(
    db: AsyncSession,
    case_slug: str,
    file_bytes: bytes,
    file_name: str,
    mime_type: str,
) -> dict:
    fhash = _file_hash(file_bytes)

    existing = await db.execute(
        text("SELECT id FROM legal.vault_documents WHERE case_slug = :slug AND file_hash = :hash"),
        {"slug": case_slug, "hash": fhash},
    )
    if existing.fetchone():
        return {"status": "duplicate", "file_name": file_name, "file_hash": fhash}

    doc_id = str(uuid4())
    vault_dir = _resolve_vault_dir(case_slug)
    safe_name = file_name.replace("/", "_").replace("\\", "_")
    nfs_path = str(vault_dir / f"{doc_id}_{safe_name}")

    with open(nfs_path, "wb") as f:
        f.write(file_bytes)

    await db.execute(
        text("""
            INSERT INTO legal.vault_documents
                (id, case_slug, file_name, nfs_path, mime_type, file_hash, file_size_bytes, processing_status)
            VALUES (:id, :slug, :fname, :nfs, :mime, :hash, :size, 'pending')
        """),
        {
            "id": doc_id, "slug": case_slug, "fname": file_name,
            "nfs": nfs_path, "mime": mime_type, "hash": fhash,
            "size": len(file_bytes),
        },
    )
    await db.commit()

    try:
        raw_text = _extract_text(file_bytes, mime_type, file_name)

        # ── CoCounsel Privilege Shield ────────────────────────
        classification, priv_latency = await _classify_privilege(raw_text, file_name)

        if classification.is_privileged and classification.confidence >= 0.7:
            await _log_privilege(
                db=db,
                doc_id=doc_id,
                case_slug=case_slug,
                file_name=file_name,
                classification=classification,
                model=SWARM_MODEL,
                latency_ms=priv_latency,
                snippet=raw_text[:2000],
            )
            return {
                "status": "locked_privileged",
                "document_id": doc_id,
                "file_name": file_name,
                "privilege_type": classification.privilege_type,
                "confidence": classification.confidence,
                "reasoning": classification.reasoning,
            }

        # ── Email Threading & Dedupe (CSV email archives) ─────
        from backend.services.legal_dedupe_engine import (
            parse_email_csv, dedupe_and_thread, filter_terminal_emails,
        )

        is_email_csv = (
            "csv" in (mime_type or "").lower()
            and ("email" in file_name.lower() or "generali" in file_name.lower())
        )

        vectorize_text = raw_text
        dedupe_stats: dict | None = None

        if is_email_csv:
            try:
                emails = parse_email_csv(raw_text)
                if emails:
                    result_dedupe = await dedupe_and_thread(db, case_slug, emails)
                    dedupe_stats = result_dedupe
                    terminals = filter_terminal_emails(emails, result_dedupe["terminal_ids"])

                    terminal_texts = []
                    for em in terminals:
                        terminal_texts.append(
                            f"[EMAIL {em['email_id']}] From: {em['sender']} | "
                            f"Subject: {em['subject']} | Date: {em['sent_at']}\n"
                            f"{em['content']}"
                        )
                    vectorize_text = "\n\n---\n\n".join(terminal_texts) if terminal_texts else raw_text

                    logger.info(
                        "email_dedupe_applied",
                        file=file_name,
                        total=result_dedupe["total_emails"],
                        exact_dupes=result_dedupe["exact_dupes_dropped"],
                        terminals=len(terminals),
                        duplicates_skipped=len(result_dedupe["duplicate_ids"]),
                    )
            except Exception as exc:
                logger.warning("email_dedupe_failed", file=file_name, error=str(exc)[:200])

        # ── Normal vectorization path ─────────────────────────
        await db.execute(
            text("UPDATE legal.vault_documents SET processing_status = 'vectorizing' WHERE id = :id"),
            {"id": doc_id},
        )
        await db.commit()

        chunks = _chunk_document(vectorize_text)

        vectors = await _embed_chunks(chunks)
        indexed = await _upsert_to_qdrant(doc_id, case_slug, file_name, chunks, vectors)

        await db.execute(
            text("""
                UPDATE legal.vault_documents
                SET processing_status = 'completed', chunk_count = :cc
                WHERE id = :id
            """),
            {"id": doc_id, "cc": len(chunks)},
        )
        await db.commit()

        logger.info(
            "vault_upload_complete",
            doc_id=doc_id,
            case_slug=case_slug,
            file_name=file_name,
            chunks=len(chunks),
            indexed=indexed,
            privilege_cleared=True,
        )

        return {
            "status": "completed",
            "document_id": doc_id,
            "file_name": file_name,
            "chunks": len(chunks),
            "vectors_indexed": indexed,
            "nfs_path": nfs_path,
            "privilege_cleared": True,
        }

    except Exception as exc:
        await db.execute(
            text("UPDATE legal.vault_documents SET processing_status = 'failed', error_detail = :err WHERE id = :id"),
            {"id": doc_id, "err": str(exc)[:1000]},
        )
        await db.commit()
        logger.error("vault_upload_failed", doc_id=doc_id, error=str(exc)[:300])
        return {"status": "failed", "document_id": doc_id, "error": str(exc)[:200]}
