"""
Hybrid E-Discovery Vault — Enterprise legal search with metadata filtering,
semantic vector search, chain-of-custody audit logging, and CSV export.

Endpoints:
  POST /api/vault/search     — Hybrid search (Qdrant filter + vector)
  GET  /api/vault/export     — CSV export of a previous search
  GET  /api/vault/audit-log  — View search audit trail
"""
import csv
import io
from datetime import datetime
from typing import List, Optional
from uuid import UUID

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.models.vault_audit import VaultAuditLog

logger = structlog.get_logger(service="vault_ediscovery")
router = APIRouter()

QDRANT_COLLECTION = "email_embeddings"


# ── Pydantic Schemas ─────────────────────────────────────────────────────────


class VaultSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=2000)
    start_date: Optional[str] = Field(None, description="ISO date YYYY-MM-DD lower bound")
    end_date: Optional[str] = Field(None, description="ISO date YYYY-MM-DD upper bound")
    sender_domain: Optional[str] = Field(None, description="Filter by sender domain or substring")
    has_attachment: Optional[bool] = Field(None, description="Filter by attachment presence")
    limit: int = Field(default=30, ge=1, le=200)


class VaultSearchHit(BaseModel):
    score: float
    subject: str = ""
    sender: str = ""
    date: str = ""
    preview: str = ""
    source_file: str = ""
    chunk_index: int = 0


class VaultSearchResponse(BaseModel):
    query: str
    filters: dict
    total_results: int
    results: List[VaultSearchHit]
    audit_id: Optional[str] = None


class AuditLogEntry(BaseModel):
    id: str
    user_id: str
    user_email: Optional[str]
    action: str
    query_text: str
    filters_applied: dict
    result_count: int
    created_at: str


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _embed_query(text: str) -> Optional[List[float]]:
    """Get embedding vector from Ollama (nomic-embed-text)."""
    url = f"{settings.embed_base_url}/api/embeddings"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json={
                "model": settings.embed_model,
                "prompt": text,
            })
            resp.raise_for_status()
            return resp.json().get("embedding")
    except Exception as e:
        logger.error("vault_embedding_failed", error=str(e)[:300])
        return None


def _build_qdrant_filter(req: VaultSearchRequest) -> Optional[dict]:
    """
    Build a Qdrant payload filter from the search request.
    Filters are applied BEFORE vector similarity — guaranteeing exact metadata matches.
    """
    conditions = []

    if req.start_date:
        conditions.append({
            "key": "date",
            "range": {"gte": req.start_date},
        })

    if req.end_date:
        end_val = req.end_date
        if len(end_val) == 10:
            end_val += "T23:59:59"
        conditions.append({
            "key": "date",
            "range": {"lte": end_val},
        })

    if req.sender_domain:
        conditions.append({
            "key": "from",
            "match": {"text": req.sender_domain},
        })

    if not conditions:
        return None

    return {"must": conditions}


def _extract_user(request: Request) -> tuple:
    """Pull user identity from the JWT-decoded request state or headers."""
    user_id = "anonymous"
    user_email = None
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            from backend.core.security import decode_token
            payload = decode_token(auth[7:])
            user_id = payload.get("sub", "anonymous")
            user_email = payload.get("email")
        except Exception:
            pass
    return user_id, user_email


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/search", response_model=VaultSearchResponse)
async def vault_search(
    body: VaultSearchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Hybrid E-Discovery search: exact metadata filtering + semantic vector search.

    1. Embed the query via Ollama nomic-embed-text
    2. Build Qdrant payload filter from date/sender constraints
    3. Execute filtered vector search against email_embeddings
    4. Log the search to vault_audit_logs (chain of custody)
    5. Return scored results
    """
    vector = await _embed_query(body.query)
    if not vector:
        raise HTTPException(502, "Embedding service unavailable — cannot execute search")

    qdrant_filter = _build_qdrant_filter(body)

    search_payload: dict = {
        "vector": vector,
        "limit": body.limit,
        "with_payload": True,
        "score_threshold": 0.15,
    }
    if qdrant_filter:
        search_payload["filter"] = qdrant_filter

    qdrant_url = settings.qdrant_url.rstrip("/")
    headers = {}
    if settings.qdrant_api_key:
        headers["api-key"] = settings.qdrant_api_key

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{qdrant_url}/collections/{QDRANT_COLLECTION}/points/search",
                json=search_payload,
                headers=headers,
            )
            resp.raise_for_status()
            raw_results = resp.json().get("result", [])
    except httpx.ConnectError:
        raise HTTPException(502, "Qdrant vector database unreachable")
    except Exception as e:
        logger.error("vault_qdrant_search_failed", error=str(e)[:300])
        raise HTTPException(502, f"Vector search failed: {str(e)[:200]}")

    hits: List[VaultSearchHit] = []
    for point in raw_results:
        p = point.get("payload", {})
        hits.append(VaultSearchHit(
            score=round(point.get("score", 0.0), 4),
            subject=p.get("subject", ""),
            sender=p.get("from", ""),
            date=p.get("date", ""),
            preview=p.get("preview", p.get("body", ""))[:500],
            source_file=p.get("source_file", ""),
            chunk_index=p.get("chunk_index", 0),
        ))

    filters_dict = {}
    if body.start_date:
        filters_dict["start_date"] = body.start_date
    if body.end_date:
        filters_dict["end_date"] = body.end_date
    if body.sender_domain:
        filters_dict["sender_domain"] = body.sender_domain
    if body.has_attachment is not None:
        filters_dict["has_attachment"] = body.has_attachment

    user_id, user_email = _extract_user(request)
    audit_entry = VaultAuditLog(
        user_id=user_id,
        user_email=user_email,
        action="search",
        query_text=body.query,
        filters_applied=filters_dict,
        result_count=len(hits),
        top_score=str(hits[0].score) if hits else None,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:500],
    )
    db.add(audit_entry)
    await db.commit()
    await db.refresh(audit_entry)

    logger.info(
        "vault_search_executed",
        user=user_id,
        query=body.query[:80],
        filters=filters_dict,
        results=len(hits),
        audit_id=str(audit_entry.id),
    )

    return VaultSearchResponse(
        query=body.query,
        filters=filters_dict,
        total_results=len(hits),
        results=hits,
        audit_id=str(audit_entry.id),
    )


@router.post("/export")
async def vault_export_csv(
    body: VaultSearchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Execute the same hybrid search and return results as a downloadable CSV.
    Also logs the export action to the audit trail.
    """
    search_resp = await vault_search(body, request, db)

    user_id, user_email = _extract_user(request)
    export_audit = VaultAuditLog(
        user_id=user_id,
        user_email=user_email,
        action="export",
        query_text=body.query,
        filters_applied=search_resp.filters,
        result_count=search_resp.total_results,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:500],
    )
    db.add(export_audit)
    await db.commit()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Relevance", "Date", "Sender", "Subject", "Preview", "Source File", "Chunk"])
    for hit in search_resp.results:
        writer.writerow([
            hit.score, hit.date, hit.sender, hit.subject,
            hit.preview[:300], hit.source_file, hit.chunk_index,
        ])

    output.seek(0)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"vault_ediscovery_{timestamp}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/audit-log", response_model=List[AuditLogEntry])
async def list_audit_logs(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Return recent vault search audit entries for compliance review."""
    result = await db.execute(
        select(VaultAuditLog)
        .order_by(desc(VaultAuditLog.created_at))
        .limit(min(limit, 200))
    )
    rows = result.scalars().all()
    return [
        AuditLogEntry(
            id=str(r.id),
            user_id=r.user_id,
            user_email=r.user_email,
            action=r.action,
            query_text=r.query_text,
            filters_applied=r.filters_applied or {},
            result_count=r.result_count,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]
