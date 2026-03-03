"""
LEGAL API — Fortress JD (Sector S05, The Counselor)
=====================================================
Fortress Prime | API Router for the on-premise AI Law Firm.

Mounted at /v1/legal by the gateway (gateway/app.py).

Endpoints:
    POST /v1/legal/analyze         — Ask a legal question (OODA + RAG)
    POST /v1/legal/search          — Semantic search only (no LLM reasoning)
    POST /v1/legal/index           — Trigger Steward indexing run
    GET  /v1/legal/collection      — Qdrant legal_library stats
    GET  /v1/legal/matters         — List open legal matters
    GET  /v1/legal/matters/{id}    — Get a specific matter with docket

Sector Isolation (fortress_atlas.yaml):
    READ: ALL schemas (privileged for audit/compliance)
    WRITE: Only to public.legal_* tables

Data Sovereignty:
    All inference local. No cloud APIs for legal reasoning.
    All data stays on the Spark cluster or Synology NAS.

Governing Documents:
    CONSTITUTION.md  — Article I (zero cloud), Article IV
    fortress_atlas.yaml — S05 firewall rules
"""

import os
import sys
import logging
import time
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from gateway.auth import require_auth, require_role
except ImportError:
    # Fallback for standalone testing
    def require_auth():
        pass

    def require_role(*roles):
        def _dep():
            pass
        return _dep

logger = logging.getLogger("gateway.legal_api")

router = APIRouter(tags=["Legal"])


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================

class LegalAnalyzeRequest(BaseModel):
    """Request body for POST /v1/legal/analyze."""
    question: str = Field(..., min_length=5, description="The legal question to analyze")
    category: Optional[str] = Field(default=None, description="Filter by document category")
    top_k: int = Field(default=8, ge=1, le=20, description="Number of chunks to retrieve")
    brain: str = Field(default="auto", description="Brain routing: auto, captain, muscle, fast, titan")
    matter_id: Optional[str] = Field(default=None, description="Link to existing legal matter")


class LegalSearchRequest(BaseModel):
    """Request body for POST /v1/legal/search."""
    query: str = Field(..., min_length=3, description="Search query")
    category: Optional[str] = None
    top_k: int = Field(default=6, ge=1, le=20)


class StewardIndexRequest(BaseModel):
    """Request body for POST /v1/legal/index."""
    source_dir: str = Field(
        default="/mnt/fortress_nas/Corporate_Legal/",
        description="NAS directory to scan"
    )
    full_reindex: bool = Field(default=False, description="Re-index all files (ignore resume)")
    dry_run: bool = Field(default=False, description="Count and classify only")
    include_statutes: bool = Field(default=False, description="Also index GA statutes")


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/analyze")
def analyze_legal_question(
    req: LegalAnalyzeRequest,
    _auth=Depends(require_role("admin", "operator")),
):
    """
    Ask a legal question — full OODA RAG pipeline.

    Retrieves from Qdrant legal_library, reasons via local LLM,
    returns cited analysis with risk flags and OODA audit trail.

    Requires role: admin or operator.
    """
    try:
        from src.agents.legal_sentinel import analyze_legal_question as _analyze
        result = _analyze(
            question=req.question,
            category=req.category,
            top_k=req.top_k,
            brain=req.brain,
            matter_id=req.matter_id,
        )
        return result.model_dump()
    except Exception as e:
        logger.error(f"Legal analysis failed: {e}")
        raise HTTPException(500, detail=f"Legal analysis failed: {e}")


@router.post("/search")
def search_legal_documents(
    req: LegalSearchRequest,
    _auth=Depends(require_role("admin", "operator")),
):
    """
    Semantic search only — no LLM reasoning.

    Returns matching document chunks with scores and metadata.
    Fast lookup for known document discovery.

    Requires role: admin or operator.
    """
    try:
        import importlib.util
        qe_path = PROJECT_ROOT / "Modules" / "CF-03_CounselorCRM" / "query_engine.py"
        spec = importlib.util.spec_from_file_location("cf03_query", str(qe_path))
        qe_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qe_mod)

        t0 = time.time()
        chunks = qe_mod.retrieve(
            req.query,
            top_k=req.top_k,
            category=req.category,
        )
        elapsed = time.time() - t0

        return {
            "query": req.query,
            "category_filter": req.category,
            "results": chunks,
            "count": len(chunks),
            "retrieval_time_s": round(elapsed, 3),
        }
    except Exception as e:
        logger.error(f"Legal search failed: {e}")
        raise HTTPException(500, detail=f"Legal search failed: {e}")


@router.post("/index")
def trigger_steward_index(
    req: StewardIndexRequest,
    _auth=Depends(require_role("admin")),
):
    """
    Trigger the Legal Steward to index documents from NAS.

    Scans the source directory, extracts text, generates embeddings,
    and pushes to Qdrant legal_library. Incremental by default.

    Requires role: admin only (writes to vector database).
    """
    try:
        from src.agents.legal_steward import run_steward
        report = run_steward(
            source_dir=req.source_dir,
            full_reindex=req.full_reindex,
            dry_run=req.dry_run,
            include_statutes=req.include_statutes,
        )
        return report.model_dump()
    except Exception as e:
        logger.error(f"Steward indexing failed: {e}")
        raise HTTPException(500, detail=f"Steward indexing failed: {e}")


@router.get("/collection")
def get_collection_stats(
    _auth=Depends(require_auth),
):
    """
    Get Qdrant legal_library collection statistics.

    Returns vector count, collection status, and metadata.
    Any authenticated user may view.
    """
    import requests as http_requests
    qdrant_host = os.getenv("QDRANT_HOST", "localhost")
    qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
    qdrant_url = f"http://{qdrant_host}:{qdrant_port}"
    qdrant_api_key = os.getenv("QDRANT_API_KEY", "")
    qdrant_headers = {"api-key": qdrant_api_key} if qdrant_api_key else {}
    collection = os.getenv("COUNSELOR_COLLECTION", "legal_library")

    try:
        resp = http_requests.get(f"{qdrant_url}/collections/{collection}", headers=qdrant_headers, timeout=10)
        if resp.status_code == 200:
            info = resp.json().get("result", {})
            return {
                "collection": collection,
                "points_count": info.get("points_count", 0),
                "vectors_count": info.get("vectors_count", 0),
                "segments_count": info.get("segments_count", 0),
                "status": info.get("status", "unknown"),
                "qdrant_url": qdrant_url,
            }
        else:
            raise HTTPException(503, detail=f"Qdrant returned {resp.status_code}")
    except http_requests.exceptions.ConnectionError:
        raise HTTPException(503, detail=f"Qdrant unreachable at {qdrant_url}")


@router.get("/matters")
def list_legal_matters(
    status: Optional[str] = Query(default=None, description="Filter by status"),
    limit: int = Query(default=50, ge=1, le=200),
    _auth=Depends(require_role("admin", "operator")),
):
    """
    List legal matters from public.legal_matters.

    Returns matters sorted by priority (descending) and created_at.
    """
    try:
        from gateway.db import get_pool
        pool = get_pool()
        conn = pool.getconn()
        try:
            cur = conn.cursor()
            sql = """
                SELECT m.matter_id, m.title, m.practice_area, m.status,
                       m.priority, m.created_at,
                       c.name AS client_name
                FROM public.legal_matters m
                LEFT JOIN public.legal_clients c ON m.client_id = c.client_id
            """
            params = []
            if status:
                sql += " WHERE m.status = %s"
                params.append(status)
            sql += " ORDER BY m.priority DESC, m.created_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
            cur.close()
            return {"matters": rows, "count": len(rows)}
        finally:
            pool.putconn(conn)
    except Exception as e:
        logger.error(f"Failed to list legal matters: {e}")
        raise HTTPException(500, detail=f"Failed to list matters: {e}")


@router.get("/matters/{matter_id}")
def get_legal_matter(
    matter_id: str,
    _auth=Depends(require_role("admin", "operator")),
):
    """
    Get a specific legal matter with its docket (documents) and notes.
    """
    try:
        from gateway.db import get_pool
        pool = get_pool()
        conn = pool.getconn()
        try:
            cur = conn.cursor()

            # Matter details
            cur.execute("""
                SELECT m.*, c.name AS client_name, c.industry, c.contact_info
                FROM public.legal_matters m
                LEFT JOIN public.legal_clients c ON m.client_id = c.client_id
                WHERE m.matter_id = %s
            """, (matter_id,))
            columns = [desc[0] for desc in cur.description]
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, detail=f"Matter {matter_id} not found")
            matter = dict(zip(columns, row))

            # Docket (documents)
            cur.execute("""
                SELECT doc_id, doc_type, title, status, version, created_at
                FROM public.legal_docket
                WHERE matter_id = %s
                ORDER BY created_at DESC
            """, (matter_id,))
            cols2 = [desc[0] for desc in cur.description]
            docket = [dict(zip(cols2, r)) for r in cur.fetchall()]

            # Notes
            cur.execute("""
                SELECT note_id, agent, content, note_type, created_at
                FROM public.legal_matter_notes
                WHERE matter_id = %s
                ORDER BY created_at DESC
            """, (matter_id,))
            cols3 = [desc[0] for desc in cur.description]
            notes = [dict(zip(cols3, r)) for r in cur.fetchall()]

            cur.close()
            return {
                "matter": matter,
                "docket": docket,
                "docket_count": len(docket),
                "notes": notes,
                "notes_count": len(notes),
            }
        finally:
            pool.putconn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get matter {matter_id}: {e}")
        raise HTTPException(500, detail=f"Failed to get matter: {e}")
