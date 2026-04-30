"""
FORTRESS INTELLIGENCE CONSOLE — Agentic Streaming Orchestrator
================================================================

POST /api/intelligence/stream — Multi-step OODA loop with tool calling.

Architecture:
    1. User query → SWARM (qwen2.5:7b) with tool definitions.
    2. LLM decides intent by choosing which tools to call (no regex).
    3. Backend executes tools against Postgres / Qdrant.
    4. Tool results fed back → LLM streams a GROUNDED response.
    5. Generative UI: tool data emitted as component events for inline
       React rendering (CaseCard, DeadlineTable, etc.).

Event protocol (text/event-stream):
    {"type": "status",    "agent": "...", "message": "..."}
    {"type": "thought",   "content": "..."}          ← R1 reasoning tokens
    {"type": "token",     "content": "..."}          ← final answer tokens
    {"type": "component", "name": "CaseCard", "props": {...}}
    {"type": "done",      "model": "...", "tokens": N, ...}

Abort chain:
    Browser AbortController → Next.js BFF signal → FastAPI cancel
    → httpx close → NIM severed → GPU freed in milliseconds.
"""

import asyncio
import hashlib
import json
import os
import re
import time
from calendar import monthrange
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx
import psycopg2
import psycopg2.extras
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import get_current_user, require_manager_or_admin
from backend.models.staff import StaffUser
from backend.services.council_orchestrator import (
    council_orchestrator,
    run_council_orchestration,
)

logger = structlog.get_logger()
router = APIRouter()

# ── Inference Endpoints (LiteLLM gateway — RAG, vision lane, failover, telemetry) ──
_LITELLM_BASE = getattr(settings, "litellm_base_url", "http://127.0.0.1:4000/v1").rstrip("/")
SWARM_URL = f"{_LITELLM_BASE}/chat/completions"
_HYDRA_BASE = os.getenv("LITELLM_HYDRA_BASE_URL", "").rstrip("/")
HYDRA_URL = f"{_HYDRA_BASE}/chat/completions" if _HYDRA_BASE else SWARM_URL
SWARM_MODEL = getattr(settings, "ollama_fast_model", "qwen2.5:7b")
HYDRA_MODEL = getattr(settings, "ollama_deep_model", "deepseek-r1:70b")

# ── Service / DB Endpoints ───────────────────────────────────────────
QDRANT_URL = getattr(settings, "qdrant_url", "http://localhost:6333")

DB_CFG = dict(
    host=os.getenv("FORTRESS_DB_HOST", "localhost"),
    port=int(os.getenv("FORTRESS_DB_PORT", "5432")),
    dbname=os.getenv("FORTRESS_DB_NAME", "fortress_db"),
    user=os.getenv("FORTRESS_DB_USER", "miner_bot"),
    password=os.getenv("FORTRESS_DB_PASS", ""),
)

HTTPX_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=10.0, pool=10.0)
MARKET_SNAPSHOT_PATH = Path(
    os.getenv(
        "MARKET_SNAPSHOT_PATH",
        "/mnt/fortress_nas/fortress_data/ai_brain/analytics/market_snapshot.json",
    )
)
MARKET_SHADOW_BOARD_PATH = Path(
    os.getenv(
        "MARKET_SHADOW_BOARD_PATH",
        "/mnt/fortress_nas/fortress_data/ai_brain/analytics/market_shadow_board.json",
    )
)
_SOVEREIGN_BASE = os.getenv("SOVEREIGN_VLLM_URL", settings.dgx_memory_url).rstrip("/")
SOVEREIGN_CHAT_URL = (
    f"{_SOVEREIGN_BASE}/chat/completions"
    if _SOVEREIGN_BASE.endswith("/v1")
    else f"{_SOVEREIGN_BASE}/v1/chat/completions"
)
SOVEREIGN_MODELS_URL = (
    f"{_SOVEREIGN_BASE}/models"
    if _SOVEREIGN_BASE.endswith("/v1")
    else f"{_SOVEREIGN_BASE}/v1/models"
)
_CANARY_FALLBACK_BASE = os.getenv("SOVEREIGN_CANARY_FALLBACK_URL", "http://192.168.0.100/v1").rstrip("/")
_CANARY_FALLBACK_CHAT_URL = (
    f"{_CANARY_FALLBACK_BASE}/chat/completions"
    if _CANARY_FALLBACK_BASE.endswith("/v1")
    else f"{_CANARY_FALLBACK_BASE}/v1/chat/completions"
)
_CANARY_FALLBACK_MODELS_URL = (
    f"{_CANARY_FALLBACK_BASE}/models"
    if _CANARY_FALLBACK_BASE.endswith("/v1")
    else f"{_CANARY_FALLBACK_BASE}/v1/models"
)
SOVEREIGN_MODEL = os.getenv("SOVEREIGN_MODEL", settings.dgx_memory_model or "deepseek-r1:70b")
_SOVEREIGN_MODEL_CACHE_TTL_SECONDS = int(os.getenv("SOVEREIGN_MODEL_CACHE_TTL_SECONDS", "60"))
_SOVEREIGN_MODEL_CACHE: Dict[str, Any] = {
    "expires_at": 0.0,
    "models": [],
}
_SOVEREIGN_MODEL_PREFERENCES = tuple(
    dict.fromkeys(
        [
            (os.getenv("SOVEREIGN_MODEL") or "").strip(),
            (settings.dgx_memory_model or "").strip(),
            "deepseek-r1:70b",
            "qwen2.5:7b",
            "qwen2.5-7b-instruct",
            "qwen2.5-7b-instruct-1m",
        ]
    )
)
SHADOW_BOARD_ALLOWED_ROLES = {"super_admin", "manager", "reviewer"}
SHADOW_CHANNEL_DEFAULT_ADJUSTMENTS: Dict[str, float] = {
    "vrbo": 8.0,
    "direct": -5.0,
}

SYSTEM_PROMPT = """\
You are the Fortress Intelligence Console, an enterprise AI assistant for \
Cabin Rentals of Georgia's Fortress Prime system.

RULES — you MUST follow these without exception:
1. ALWAYS use the provided tools to look up real data before answering \
   questions about legal cases, deadlines, or the knowledge base.
2. NEVER fabricate case numbers, dates, dollar amounts, or court rulings.
3. If a tool returns no results, state clearly "No matching data found."
4. Cite the source of every factual claim (e.g., "Per the legal database…").
5. Use Markdown for structured output (tables, headers, bold for key facts).
6. When showing legal deadlines, include the due_date, status, and review_status.
7. ALWAYS call search_legal_cases FIRST to find the real case_slug before \
   calling get_case_detail or get_case_deadlines. Do NOT guess slugs.

KNOWN CASE SLUGS (use these exact values for get_case_detail/get_case_deadlines):
- "fish-trap-suv2026000013" — Generali Global Assistance v. Cabin Rentals of Georgia
- "prime-trust-23-11161" — Prime Core Technologies / Prime Trust Bankruptcy
"""

# ═══════════════════════════════════════════════════════════════════════
# TOOL DEFINITIONS (OpenAI-compatible function calling)
# ═══════════════════════════════════════════════════════════════════════

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_legal_cases",
            "description": (
                "Search the legal database for cases matching a query. "
                "Returns case metadata including case_slug, case_name, court, "
                "our_role, risk_score, status, critical_date, and extracted_entities."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term — a party name, case number, keyword, or topic (e.g., 'Generali', 'bankruptcy', 'Prime Trust')",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_case_detail",
            "description": (
                "Get the full detail of a specific legal case including "
                "all columns, plus recent actions, deadlines, evidence, "
                "and watchdog terms."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "case_slug": {
                        "type": "string",
                        "description": "The URL-friendly case slug (e.g., 'fish-trap-suv2026000013', 'prime-trust-23-11161')",
                    }
                },
                "required": ["case_slug"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_case_deadlines",
            "description": (
                "Retrieve all deadlines for a legal case. Includes due_date, "
                "status (pending/completed/extended), review_status "
                "(pending_review/approved/rejected), and whether auto_extracted by AI."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "case_slug": {
                        "type": "string",
                        "description": "The URL-friendly case slug",
                    }
                },
                "required": ["case_slug"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Semantic search across the Fortress knowledge base (Qdrant). "
                "Returns the top 5 most relevant document chunks with scores. "
                "Use for general knowledge queries, policy lookups, or when "
                "legal case tools return no results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query",
                    }
                },
                "required": ["query"],
            },
        },
    },
]

# ═══════════════════════════════════════════════════════════════════════
# PYDANTIC RESPONSE SCHEMAS — strict contracts against the Postgres schema
# ═══════════════════════════════════════════════════════════════════════

import datetime
from decimal import Decimal
from typing import Union


class _JsonSafeModel(BaseModel):
    """Base with custom serializer for date/Decimal types from psycopg2."""
    model_config = {"from_attributes": True}


class CaseSummary(_JsonSafeModel):
    case_slug: str
    case_number: str
    case_name: str
    court: Optional[str] = None
    our_role: Optional[str] = None
    status: Optional[str] = None
    risk_score: Optional[int] = None
    critical_date: Optional[datetime.date] = None
    case_type: Optional[str] = None
    opposing_counsel: Optional[str] = None
    extracted_entities: Optional[Dict] = None
    extraction_status: Optional[str] = None


class CaseSearchResponse(_JsonSafeModel):
    cases: List[CaseSummary]
    total: int


class CaseDetail(_JsonSafeModel):
    id: int
    case_slug: str
    case_number: str
    case_name: str
    court: Optional[str] = None
    judge: Optional[str] = None
    case_type: Optional[str] = None
    our_role: Optional[str] = None
    status: Optional[str] = None
    critical_date: Optional[datetime.date] = None
    critical_note: Optional[str] = None
    plan_admin: Optional[str] = None
    plan_admin_email: Optional[str] = None
    plan_admin_address: Optional[str] = None
    fiduciary: Optional[str] = None
    opposing_counsel: Optional[str] = None
    our_claim_basis: Optional[str] = None
    petition_date: Optional[datetime.date] = None
    notes: Optional[str] = None
    risk_score: Optional[int] = None
    extraction_status: Optional[str] = None
    extracted_entities: Optional[Dict] = None
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None


class DeadlineRow(_JsonSafeModel):
    id: int
    description: str
    due_date: datetime.date
    deadline_type: str
    status: Optional[str] = None
    review_status: Optional[str] = None
    auto_extracted: Optional[bool] = None
    extended_to: Optional[datetime.date] = None
    extension_reason: Optional[str] = None
    source_document: Optional[str] = None
    content_hash: Optional[str] = None


class DeadlinesResponse(_JsonSafeModel):
    deadlines: List[DeadlineRow]
    case_slug: str
    total: int


class ActionRow(_JsonSafeModel):
    id: int
    action_type: str
    description: str
    status: Optional[str] = None
    tracking_number: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime.datetime] = None


class EvidenceRow(_JsonSafeModel):
    id: int
    evidence_type: str
    description: str
    relevance: Optional[str] = None
    file_path: Optional[str] = None
    is_critical: Optional[bool] = None
    discovered_at: Optional[datetime.datetime] = None


class CaseDetailResponse(_JsonSafeModel):
    case: CaseDetail
    deadlines: List[DeadlineRow]
    recent_actions: List[ActionRow]
    evidence: List[EvidenceRow]


class KnowledgeResult(_JsonSafeModel):
    score: float
    content: str
    source: str
    collection: str


class KnowledgeSearchResponse(_JsonSafeModel):
    results: List[KnowledgeResult]
    total: int
    collections_searched: List[str]


class ToolError(_JsonSafeModel):
    tool_error: str
    details: str


# ═══════════════════════════════════════════════════════════════════════
# TOOL EXECUTORS (Pydantic-validated, error-bounded)
# ═══════════════════════════════════════════════════════════════════════


def _db_query(sql: str, params: tuple = ()) -> List[Dict]:
    """Run a read-only query against fortress_db, return list of dicts."""
    conn = psycopg2.connect(**DB_CFG)
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()


def _model_dump(model: BaseModel) -> Dict:
    """Serialize a Pydantic model to a JSON-safe dict."""
    return json.loads(model.model_dump_json())


def _normalize_name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def _load_property_catalog(limit: int = 200) -> List[Dict[str, Any]]:
    try:
        rows = _db_query(
            """
            SELECT id::text AS internal_id, name, slug, streamline_property_id
            FROM properties
            ORDER BY created_at DESC NULLS LAST
            LIMIT %s
            """,
            (limit,),
        )
    except Exception as exc:
        logger.warning("market_snapshot_property_catalog_unavailable", error=str(exc)[:240])
        return []
    catalog: List[Dict[str, Any]] = []
    for row in rows:
        streamline_id = str(row.get("streamline_property_id") or "").strip()
        internal_id = str(row.get("internal_id") or "").strip()
        slug = str(row.get("slug") or "").strip()
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        catalog.append(
            {
                "property_id": streamline_id or internal_id,
                "internal_id": internal_id,
                "property_name": name,
                "slug": slug,
            }
        )
    return catalog


async def _load_property_catalog_async(db: AsyncSession, limit: int = 200) -> List[Dict[str, Any]]:
    try:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT id::text AS internal_id, name, slug, streamline_property_id
                    FROM properties
                    ORDER BY created_at DESC NULLS LAST
                    LIMIT :limit
                    """
                ),
                {"limit": int(limit)},
            )
        ).mappings().all()
    except Exception as exc:
        logger.warning("market_snapshot_property_catalog_unavailable_async", error=str(exc)[:240])
        return []

    catalog: List[Dict[str, Any]] = []
    for row in rows:
        streamline_id = str(row.get("streamline_property_id") or "").strip()
        internal_id = str(row.get("internal_id") or "").strip()
        slug = str(row.get("slug") or "").strip()
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        catalog.append(
            {
                "property_id": streamline_id or internal_id,
                "internal_id": internal_id,
                "property_name": name,
                "slug": slug,
            }
        )
    return catalog


async def _exec_search_legal_cases(query: str) -> Dict:
    try:
        q = f"%{query}%"
        rows = await asyncio.to_thread(
            _db_query,
            """
            SELECT case_slug, case_number, case_name, court, our_role,
                   status, risk_score, critical_date, case_type,
                   opposing_counsel, extracted_entities, extraction_status
            FROM legal.cases
            WHERE case_name   ILIKE %s
               OR case_number ILIKE %s
               OR case_slug   ILIKE %s
               OR court       ILIKE %s
               OR notes       ILIKE %s
               OR our_role    ILIKE %s
            ORDER BY risk_score DESC NULLS LAST
            """,
            (q, q, q, q, q, q),
        )
        cases = [CaseSummary(**r) for r in rows]
        return _model_dump(CaseSearchResponse(cases=cases, total=len(cases)))
    except Exception as exc:
        logger.exception("tool_search_legal_cases_error", error=str(exc))
        return _model_dump(ToolError(
            tool_error="Database query failed in search_legal_cases",
            details=str(exc),
        ))


async def _exec_get_case_detail(case_slug: str) -> Dict:
    try:
        cases = await asyncio.to_thread(
            _db_query,
            """SELECT id, case_slug, case_number, case_name, court, judge,
                      case_type, our_role, status, critical_date, critical_note,
                      plan_admin, plan_admin_email, plan_admin_address,
                      fiduciary, opposing_counsel, our_claim_basis,
                      petition_date, notes, risk_score, extraction_status,
                      extracted_entities, created_at, updated_at
               FROM legal.cases WHERE case_slug = %s""",
            (case_slug,),
        )
        if not cases:
            return {"error": f"Case '{case_slug}' not found"}
        case = CaseDetail(**cases[0])

        deadline_rows = await asyncio.to_thread(
            _db_query,
            """SELECT id, description, due_date, deadline_type, status,
                      review_status, auto_extracted, extended_to,
                      extension_reason, source_document, content_hash
               FROM legal.deadlines WHERE case_id = %s ORDER BY due_date""",
            (cases[0]["id"],),
        )

        action_rows = await asyncio.to_thread(
            _db_query,
            """SELECT id, action_type, description, status,
                      tracking_number, notes, created_at
               FROM legal.case_actions WHERE case_id = %s
               ORDER BY created_at DESC LIMIT 20""",
            (cases[0]["id"],),
        )

        evidence_rows = await asyncio.to_thread(
            _db_query,
            """SELECT id, evidence_type, description, relevance,
                      file_path, is_critical, discovered_at
               FROM legal.case_evidence WHERE case_id = %s
               ORDER BY discovered_at DESC LIMIT 20""",
            (cases[0]["id"],),
        )

        return _model_dump(CaseDetailResponse(
            case=case,
            deadlines=[DeadlineRow(**r) for r in deadline_rows],
            recent_actions=[ActionRow(**r) for r in action_rows],
            evidence=[EvidenceRow(**r) for r in evidence_rows],
        ))
    except Exception as exc:
        logger.exception("tool_get_case_detail_error", error=str(exc))
        return _model_dump(ToolError(
            tool_error="Database query failed in get_case_detail",
            details=str(exc),
        ))


async def _exec_get_case_deadlines(case_slug: str) -> Dict:
    try:
        rows = await asyncio.to_thread(
            _db_query,
            """
            SELECT d.id, d.description, d.due_date, d.deadline_type,
                   d.status, d.review_status, d.auto_extracted,
                   d.extended_to, d.extension_reason,
                   d.source_document, d.content_hash
            FROM legal.deadlines d
            JOIN legal.cases c ON c.id = d.case_id
            WHERE c.case_slug = %s
            ORDER BY d.due_date
            """,
            (case_slug,),
        )
        deadlines = [DeadlineRow(**r) for r in rows]
        return _model_dump(DeadlinesResponse(
            deadlines=deadlines, case_slug=case_slug, total=len(deadlines),
        ))
    except Exception as exc:
        logger.exception("tool_get_case_deadlines_error", error=str(exc))
        return _model_dump(ToolError(
            tool_error="Database query failed in get_case_deadlines",
            details=str(exc),
        ))


# Phase A PR #2 (2026-04-30): legal_library cut over to legal_library_v2 on the
# 2048-dim sovereign legal-embed encoder. The other two collections in this
# federated search ride nomic-embed-text at 768-dim. Each collection's row
# below carries its own encoder marker so the federated search embeds the
# query once per encoder rather than once globally.
_ENCODER_NOMIC = "nomic"
_ENCODER_LEGAL = "legal-embed"

_QDRANT_COLLECTIONS = {
    "fortress_knowledge": {
        "content_field": "text",
        "source_field": "source_file",
        "encoder": _ENCODER_NOMIC,
    },
    "email_embeddings": {
        "content_field": "preview",
        "source_field": "subject",
        "encoder": _ENCODER_NOMIC,
    },
    "legal_library_v2": {
        "content_field": "text_chunk",
        "source_field": "file_name",
        "encoder": _ENCODER_LEGAL,
    },
}


async def _search_single_collection(
    client: httpx.AsyncClient,
    collection: str,
    embedding: List[float],
    limit: int,
) -> List[KnowledgeResult]:
    """Search one Qdrant collection and extract content using the correct field names."""
    schema = _QDRANT_COLLECTIONS[collection]
    resp = await client.post(
        f"{QDRANT_URL}/collections/{collection}/points/search",
        json={"vector": embedding, "limit": limit, "with_payload": True},
    )
    resp.raise_for_status()
    hits = resp.json().get("result", [])
    results = []
    for r in hits:
        payload = r.get("payload", {})
        content = str(
            payload.get(schema["content_field"])
            or payload.get("content")
            or payload.get("text")
            or payload.get("body")
            or ""
        )[:800]
        source = str(
            payload.get(schema["source_field"])
            or payload.get("source")
            or payload.get("file_name")
            or "unknown"
        )[:200]
        if not content.strip():
            continue
        results.append(KnowledgeResult(
            score=round(r["score"], 4),
            content=content,
            source=source,
            collection=collection,
        ))
    return results


async def _exec_search_knowledge_base(query: str) -> Dict:
    """Federated search across fortress_knowledge, email_embeddings, and legal_library_v2.

    Embeds the query separately per encoder family — nomic-embed-text for
    fortress_knowledge + email_embeddings, sovereign legal-embed (2048-dim,
    PR #300 §9.5 caller contract) for legal_library_v2 — then dispatches one
    search per collection with the matching vector.
    """
    try:
        from backend.core.vector_db import embed_legal_query as _embed_legal
        from backend.core.vector_db import embed_text as _embed_text

        truncated = query[:8000]
        nomic_vec = await _embed_text(truncated)
        if not nomic_vec:
            return _model_dump(ToolError(
                tool_error="Embedding generation failed",
                details="nomic-embed-text returned no vector",
            ))
        try:
            legal_vec = await _embed_legal(truncated)
        except Exception as e:
            logger.warning("federated_legal_embed_failed", error=str(e)[:200])
            legal_vec = None

        encoder_vec = {_ENCODER_NOMIC: nomic_vec, _ENCODER_LEGAL: legal_vec}

        async with httpx.AsyncClient(timeout=20.0) as client:
            per_collection = 5
            search_tasks = []
            scheduled_collections: List[str] = []
            for coll, schema in _QDRANT_COLLECTIONS.items():
                vec = encoder_vec.get(schema["encoder"])
                if vec is None:
                    logger.warning(
                        "federated_search_skip_collection_no_encoder_vec",
                        collection=coll, encoder=schema["encoder"],
                    )
                    continue
                search_tasks.append(_search_single_collection(client, coll, vec, per_collection))
                scheduled_collections.append(coll)
            collection_results = await asyncio.gather(
                *search_tasks, return_exceptions=True,
            )

            merged: List[KnowledgeResult] = []
            searched: List[str] = list(scheduled_collections)
            for coll_name, result in zip(scheduled_collections, collection_results):
                if isinstance(result, Exception):
                    logger.warning(
                        "federated_search_collection_error",
                        collection=coll_name,
                        error=str(result),
                    )
                    continue
                merged.extend(result)

            merged.sort(key=lambda r: r.score, reverse=True)
            top_results = merged[:8]

            return _model_dump(KnowledgeSearchResponse(
                results=top_results,
                total=len(top_results),
                collections_searched=searched,
            ))
    except Exception as exc:
        logger.warning("knowledge_base_search_error", error=str(exc))
        return _model_dump(ToolError(
            tool_error="Knowledge base search failed",
            details=str(exc),
        ))


TOOL_DISPATCH = {
    "search_legal_cases": _exec_search_legal_cases,
    "get_case_detail": _exec_get_case_detail,
    "get_case_deadlines": _exec_get_case_deadlines,
    "search_knowledge_base": _exec_search_knowledge_base,
}


async def _execute_tool(name: str, raw_args: str) -> Dict:
    """Parse tool arguments and dispatch."""
    try:
        args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON arguments: {raw_args[:200]}"}

    fn = TOOL_DISPATCH.get(name)
    if not fn:
        return {"error": f"Unknown tool: {name}"}

    try:
        return await fn(**args)
    except Exception as exc:
        logger.exception("tool_execution_error", tool=name, error=str(exc))
        return {"error": f"Tool execution failed: {exc}"}


# ═══════════════════════════════════════════════════════════════════════
# COMPONENT EVENT HELPERS (Generative UI)
# ═══════════════════════════════════════════════════════════════════════


def _tool_result_to_component(name: str, result: Dict) -> Optional[str]:
    """If a tool result is visual, emit a Generative UI component event."""
    if name == "search_legal_cases" and result.get("cases"):
        for case in result["cases"][:3]:
            return _sse("component", {
                "name": "CaseCard",
                "props": {
                    "case_name": case.get("case_name"),
                    "case_number": case.get("case_number"),
                    "court": case.get("court"),
                    "our_role": case.get("our_role"),
                    "risk_score": case.get("risk_score"),
                    "critical_date": case.get("critical_date"),
                    "status": case.get("status"),
                    "case_slug": case.get("case_slug"),
                },
            })

    if name == "get_case_detail" and result.get("case"):
        c = result["case"]
        return _sse("component", {
            "name": "CaseCard",
            "props": {
                "case_name": c.get("case_name"),
                "case_number": c.get("case_number"),
                "court": c.get("court"),
                "our_role": c.get("our_role"),
                "risk_score": c.get("risk_score"),
                "critical_date": c.get("critical_date"),
                "status": c.get("status"),
                "case_slug": c.get("case_slug"),
            },
        })

    return None


# ═══════════════════════════════════════════════════════════════════════
# SSE HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _sse(event_type: str, data: dict) -> str:
    payload = {"type": event_type, **data}
    return f"data: {json.dumps(payload)}\n\n"


# ═══════════════════════════════════════════════════════════════════════
# STREAMING OODA LOOP
# ═══════════════════════════════════════════════════════════════════════


class _StreamResult:
    """Accumulator for tool calls and token count from _stream_llm."""
    __slots__ = ("tool_calls", "token_count")

    def __init__(self):
        self.tool_calls: List[Dict] = []
        self.token_count: int = 0


async def _stream_llm(
    request: Request,
    url: str,
    payload: dict,
    result: _StreamResult,
):
    """
    Stream an LLM call. Yields SSE frames for tokens.

    Tool calls and token count are written to the `result` accumulator
    so the caller can read them after the generator is exhausted.

    Uses an asyncio.Queue + background task to emit SSE heartbeats
    every 10s, even during the initial HTTP handshake phase when
    HYDRA may take 60-180s to return response headers (prompt processing).
    """
    HEARTBEAT_INTERVAL = 10.0
    raw_tool_calls: Dict[int, Dict] = {}
    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    async def _producer():
        """Connect to LLM, parse stream, push frames into the queue."""
        try:
            async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        logger.error("llm_stream_error", status=resp.status_code, body=body[:500])
                        await queue.put(_sse("status", {
                            "agent": "Error",
                            "message": f"Inference returned HTTP {resp.status_code}",
                        }))
                        return

                    async for line in resp.aiter_lines():
                        if await request.is_disconnected():
                            logger.info("client_disconnected", tokens=result.token_count)
                            return

                        line = line.strip()
                        if not line:
                            continue
                        if line == "data: [DONE]":
                            break
                        if not line.startswith("data: "):
                            continue

                        try:
                            chunk = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue

                        choice = chunk.get("choices", [{}])[0]
                        delta = choice.get("delta", {})
                        finish = choice.get("finish_reason")

                        if "tool_calls" in delta:
                            for tc in delta["tool_calls"]:
                                idx = tc.get("index", 0)
                                if idx not in raw_tool_calls:
                                    raw_tool_calls[idx] = {
                                        "id": tc.get("id", f"call_{idx}"),
                                        "name": "",
                                        "arguments": "",
                                    }
                                fn = tc.get("function", {})
                                if "name" in fn and fn["name"]:
                                    raw_tool_calls[idx]["name"] = fn["name"]
                                if "arguments" in fn:
                                    raw_tool_calls[idx]["arguments"] += fn["arguments"]

                        reasoning = delta.get("reasoning", "")
                        if reasoning:
                            await queue.put(
                                _sse("thought", {"content": reasoning})
                            )

                        content = delta.get("content", "")
                        if content:
                            result.token_count += 1
                            await queue.put(_sse("token", {"content": content}))

                        if finish in ("tool_calls", "stop"):
                            break
        except httpx.ConnectError as exc:
            logger.error("llm_connect_error", url=url, error=str(exc))
            await queue.put(_sse("status", {
                "agent": "Error",
                "message": "Cannot reach inference cluster. Is NIM running?",
            }))
        except httpx.ReadTimeout:
            logger.error("llm_read_timeout", url=url, tokens=result.token_count)
            await queue.put(_sse("status", {
                "agent": "Error",
                "message": "Inference timeout — the model took too long.",
            }))
        except Exception as exc:
            logger.exception("llm_stream_error", url=url, error=str(exc))
            await queue.put(_sse("status", {
                "agent": "Error",
                "message": f"Stream error: {type(exc).__name__}: {exc}",
            }))
        finally:
            result.tool_calls = list(raw_tool_calls.values())
            await queue.put(_SENTINEL)

    producer_task = asyncio.create_task(_producer())

    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue

            if item is _SENTINEL:
                break
            yield item
    finally:
        if not producer_task.done():
            producer_task.cancel()
            try:
                await producer_task
            except asyncio.CancelledError:
                pass


class StreamRequest(BaseModel):
    messages: List[Dict[str, str]]
    model: str = Field(default="auto", description="auto | swarm | hydra")
    max_tokens: int = Field(default=2048, ge=1, le=8192)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    system_prompt: Optional[str] = None


class CouncilExecuteRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Raw user request for the council DAG")
    timeout_seconds: int = Field(default=30, ge=1, le=120)


class MarketSnapshotCanaryRequest(BaseModel):
    last_payload_hash: Optional[str] = None
    force: bool = False
    prompt_override: Optional[str] = None
    max_tokens: int = Field(default=900, ge=128, le=4096)
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)


class ShadowBoardApplyRequest(BaseModel):
    snapshot_hash: str
    model: str
    recommendation_json: Dict[str, Any]
    recommendation_raw: Optional[str] = None
    actor: str = "admin@crog-ai.com"
    note: Optional[str] = None


class ShadowBoardDecisionRequest(BaseModel):
    actor: str = "admin@crog-ai.com"
    note: Optional[str] = None
    final_channel_adjustments: Optional[List["ShadowBoardChannelAdjustmentInput"]] = None


class ShadowBoardChannelAdjustmentInput(BaseModel):
    channel_code: str = Field(min_length=1, max_length=50)
    adjustment_pct: float = Field(ge=-30, le=30)
    adjustment_type: str = Field(default="percent")
    applies_to: str = Field(default="nightly")
    source: Optional[str] = None


class SovereignUnderperformer(BaseModel):
    property_id: str
    property_name: str
    anomaly_summary: str
    recommended_base_rate: Optional[float] = Field(default=None, gt=0)
    dynamic_rate_adjustment_pct: float = Field(ge=-25, le=25)
    google_ads_headline: str = Field(min_length=1, max_length=90)
    nextjs_seo_summary: str = Field(min_length=1, max_length=320)
    confidence: float = Field(ge=0, le=1)


class SovereignCanaryResponseModel(BaseModel):
    generated_at_utc: str
    snapshot_hash: str
    underperformers: list[SovereignUnderperformer]
    portfolio_actions: list[str] = Field(default_factory=list)
    method_notes: list[str] = Field(default_factory=list)


def _normalize_canary_contract(
    candidate: Dict[str, Any],
    snapshot_hash: str,
    global_adr: Optional[float] = None,
    property_catalog: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Tolerate minor model drift (e.g., confidence as 95 instead of 0.95)
    while preserving strict schema validation downstream.
    """
    if not isinstance(candidate, dict):
        return {}

    normalized = dict(candidate)
    normalized["snapshot_hash"] = snapshot_hash
    catalog_rows = property_catalog or []
    by_ref: Dict[str, Dict[str, Any]] = {}
    by_name_key: Dict[str, Dict[str, Any]] = {}
    for row in catalog_rows:
        if not isinstance(row, dict):
            continue
        ref_keys = {
            str(row.get("property_id") or "").strip().lower(),
            str(row.get("internal_id") or "").strip().lower(),
            str(row.get("slug") or "").strip().lower(),
        }
        for ref in ref_keys:
            if ref:
                by_ref[ref] = row
        name_key = _normalize_name_key(str(row.get("property_name") or ""))
        if name_key:
            by_name_key[name_key] = row

    underperformers = normalized.get("underperformers")
    if not isinstance(underperformers, list):
        normalized["underperformers"] = []
        underperformers = []

    fixed_underperformers: list[Dict[str, Any]] = []
    for item in underperformers:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        raw_property_id = str(row.get("property_id") or "").strip().lower()
        raw_property_name = str(row.get("property_name") or "")
        mapped = by_ref.get(raw_property_id)
        if mapped is None and raw_property_name:
            mapped = by_name_key.get(_normalize_name_key(raw_property_name))
        if catalog_rows and mapped is None:
            # Strict mode when catalog exists: skip synthetic/non-canonical properties.
            continue
        if mapped is not None:
            row["property_id"] = str(mapped.get("property_id") or row.get("property_id"))
            row["property_name"] = str(mapped.get("property_name") or row.get("property_name"))

        confidence_raw = row.get("confidence")
        try:
            confidence = float(confidence_raw)
            if confidence > 1.0 and confidence <= 100.0:
                confidence = confidence / 100.0
            row["confidence"] = max(0.0, min(confidence, 1.0))
        except Exception:
            row["confidence"] = 0.0

        recommended_rate = row.get("recommended_base_rate")
        try:
            recommended_rate = float(recommended_rate) if recommended_rate is not None else None
        except Exception:
            recommended_rate = None
        if recommended_rate is None and global_adr is not None:
            try:
                dynamic_pct = float(row.get("dynamic_rate_adjustment_pct", 0.0))
            except Exception:
                dynamic_pct = 0.0
            computed = float(global_adr) * (1.0 + (dynamic_pct / 100.0))
            recommended_rate = max(round(computed, 2), 1.0)
            row["method_note"] = "recommended_base_rate_filled_from_snapshot_global_adr"
        if recommended_rate is not None:
            row["recommended_base_rate"] = round(float(recommended_rate), 2)

        fixed_underperformers.append(row)

    normalized["underperformers"] = fixed_underperformers
    if not isinstance(normalized.get("portfolio_actions"), list):
        normalized["portfolio_actions"] = []
    if not isinstance(normalized.get("method_notes"), list):
        normalized["method_notes"] = []
    return normalized


async def _fetch_models(client: httpx.AsyncClient, models_url: str) -> list[str]:
    try:
        resp = await client.get(models_url)
        if resp.status_code != 200:
            logger.warning(
                "market_snapshot_models_probe_failed",
                status=resp.status_code,
                detail=resp.text[:240],
                models_url=models_url,
            )
            return []
        payload = resp.json()
    except Exception as exc:
        logger.warning("market_snapshot_models_probe_error", error=str(exc)[:240], models_url=models_url)
        return []

    data = payload.get("data", [])
    if not isinstance(data, list):
        return []

    model_ids: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if model_id:
            model_ids.append(model_id)
    return model_ids


async def _resolve_sovereign_model(client: httpx.AsyncClient) -> tuple[str, str]:
    configured_model = (SOVEREIGN_MODEL or "").strip() or "deepseek-r1:70b"
    now = time.time()
    cached_models = _SOVEREIGN_MODEL_CACHE.get("models", [])
    cache_expiry = float(_SOVEREIGN_MODEL_CACHE.get("expires_at", 0.0))

    if now < cache_expiry and isinstance(cached_models, list):
        available_models = [str(m).strip() for m in cached_models if str(m).strip()]
    else:
        available_models = await _fetch_models(client, SOVEREIGN_MODELS_URL)
        _SOVEREIGN_MODEL_CACHE["models"] = available_models
        _SOVEREIGN_MODEL_CACHE["expires_at"] = now + max(_SOVEREIGN_MODEL_CACHE_TTL_SECONDS, 10)

    if not available_models:
        return configured_model, SOVEREIGN_CHAT_URL

    if configured_model in available_models:
        return configured_model, SOVEREIGN_CHAT_URL

    for preferred in _SOVEREIGN_MODEL_PREFERENCES:
        if preferred and preferred in available_models:
            logger.warning(
                "market_snapshot_model_auto_fallback",
                requested_model=configured_model,
                resolved_model=preferred,
            )
            return preferred, SOVEREIGN_CHAT_URL

    resolved_model = available_models[0]
    if resolved_model == "meta/llama-3.1-8b-instruct":
        fallback_models = await _fetch_models(client, _CANARY_FALLBACK_MODELS_URL)
        if fallback_models:
            for preferred in _SOVEREIGN_MODEL_PREFERENCES:
                if preferred and preferred in fallback_models:
                    logger.warning(
                        "market_snapshot_endpoint_fallback",
                        requested_model=configured_model,
                        primary_model=resolved_model,
                        resolved_model=preferred,
                        fallback_url=_CANARY_FALLBACK_CHAT_URL,
                    )
                    return preferred, _CANARY_FALLBACK_CHAT_URL
            logger.warning(
                "market_snapshot_endpoint_fallback",
                requested_model=configured_model,
                primary_model=resolved_model,
                resolved_model=fallback_models[0],
                fallback_url=_CANARY_FALLBACK_CHAT_URL,
            )
            return fallback_models[0], _CANARY_FALLBACK_CHAT_URL
    logger.warning(
        "market_snapshot_model_auto_fallback",
        requested_model=configured_model,
        resolved_model=resolved_model,
    )
    return resolved_model, SOVEREIGN_CHAT_URL


def _extract_json_from_model_text(raw_text: str) -> Dict[str, Any]:
    """
    Extract JSON object from model text output.
    Accepts plain JSON or markdown-fenced JSON.
    """
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("Model returned empty content")

    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Model output does not contain a JSON object")

    candidate = text[start : end + 1]
    return json.loads(candidate)


async def _repair_canary_json(
    chat_url: str,
    model: str,
    snapshot_hash: str,
    raw_output: str,
) -> Optional[Dict[str, Any]]:
    """
    Second-pass sanitizer for models that answer with prose instead of JSON.
    """
    repair_prompt = (
        "Convert the following model output into STRICT JSON only.\n"
        "Return exactly one JSON object with this shape and no markdown:\n"
        "{"
        "\"generated_at_utc\":\"ISO8601\","
        "\"snapshot_hash\":\"string\","
        "\"underperformers\":[{"
        "\"property_id\":\"string\","
        "\"property_name\":\"string\","
        "\"anomaly_summary\":\"string\","
        "\"dynamic_rate_adjustment_pct\":number,"
        "\"google_ads_headline\":\"string\","
        "\"nextjs_seo_summary\":\"string\","
        "\"confidence\":number"
        "}],"
        "\"portfolio_actions\":[\"string\"],"
        "\"method_notes\":[\"string\"]"
        "}\n"
        f"Set snapshot_hash to: {snapshot_hash}\n"
        "If the source content is missing fields, use conservative defaults and empty arrays.\n\n"
        "SOURCE_OUTPUT:\n"
        f"{(raw_output or '')[:6000]}"
    )
    repair_payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a JSON sanitizer. "
                    "Output valid JSON only. "
                    "No markdown, no prose, no explanations."
                ),
            },
            {"role": "user", "content": repair_prompt},
        ],
        "temperature": 0,
        "max_tokens": 900,
        "stream": False,
    }
    try:
        timeout = httpx.Timeout(connect=10.0, read=90.0, write=10.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as repair_client:
            resp = await repair_client.post(chat_url, json=repair_payload)
            if resp.status_code != 200:
                logger.warning(
                    "market_snapshot_canary_repair_upstream_error",
                    status=resp.status_code,
                    detail=resp.text[:240],
                )
                return None
            data = resp.json()
            repaired_text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            return _extract_json_from_model_text(repaired_text)
    except Exception as exc:
        logger.warning("market_snapshot_canary_repair_failed", error=str(exc)[:240])
        return None


def _read_shadow_board() -> Dict[str, Any]:
    if not MARKET_SHADOW_BOARD_PATH.exists():
        return {"entries": []}
    try:
        payload = json.loads(MARKET_SHADOW_BOARD_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {"entries": []}
        entries = payload.get("entries", [])
        if not isinstance(entries, list):
            entries = []
        return {"entries": entries}
    except Exception:
        return {"entries": []}


def _write_shadow_board(payload: Dict[str, Any]) -> None:
    MARKET_SHADOW_BOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = MARKET_SHADOW_BOARD_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(MARKET_SHADOW_BOARD_PATH)


def _require_shadow_board_role(user: StaffUser) -> None:
    role = (user.role or "").strip().lower()
    if role not in SHADOW_BOARD_ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="shadow_board_access_denied",
        )


def _actor_from_user(user: StaffUser) -> str:
    email = (user.email or "").strip().lower()
    return email or str(user.id)


def _parse_shadow_date(value: Optional[str]) -> Optional[datetime.date]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(raw[:10])
    except Exception:
        return None


def _parse_month_window(summary: str) -> Optional[tuple[datetime.date, datetime.date]]:
    text_summary = summary or ""
    ym_match = re.search(r"(20\d{2})-(0[1-9]|1[0-2])", text_summary)
    if ym_match:
        year = int(ym_match.group(1))
        month = int(ym_match.group(2))
        end_day = monthrange(year, month)[1]
        return (
            datetime.date(year, month, 1),
            datetime.date(year, month, end_day),
        )

    # Quarter hints such as "Q3" or "Q4 2026"
    quarter_match = re.search(r"\bq([1-4])(?:\s*(?:-|/)?\s*(20\d{2}))?\b", text_summary, flags=re.I)
    if quarter_match:
        quarter = int(quarter_match.group(1))
        year = int(quarter_match.group(2)) if quarter_match.group(2) else datetime.datetime.now().year
        month_start = ((quarter - 1) * 3) + 1
        month_end = month_start + 2
        end_day = monthrange(year, month_end)[1]
        return (
            datetime.date(year, month_start, 1),
            datetime.date(year, month_end, end_day),
        )

    # Month name hints such as "December" or "September 2026"
    month_lookup = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    month_match = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b(?:\s*(20\d{2}))?",
        text_summary,
        flags=re.I,
    )
    if month_match:
        month = month_lookup[month_match.group(1).lower()]
        year = int(month_match.group(2)) if month_match.group(2) else datetime.datetime.now().year
        end_day = monthrange(year, month)[1]
        return (
            datetime.date(year, month, 1),
            datetime.date(year, month, end_day),
        )
    return None


def _extract_rate_candidate(underperformer: Dict[str, Any]) -> Optional[Decimal]:
    keys = (
        "recommended_base_rate",
        "recommended_base_rate_usd",
        "target_base_rate",
        "base_rate",
        "nightly_rate",
    )
    for key in keys:
        value = underperformer.get(key)
        if value is None or value == "":
            continue
        try:
            return Decimal(str(value)).quantize(Decimal("0.01"))
        except Exception:
            continue

    adjustment_pct = underperformer.get("dynamic_rate_adjustment_pct")
    baseline_rate = underperformer.get("baseline_rate")
    if adjustment_pct is not None and baseline_rate is not None:
        try:
            base = Decimal(str(baseline_rate))
            pct = Decimal(str(adjustment_pct))
            return (base * (Decimal("1") + (pct / Decimal("100")))).quantize(Decimal("0.01"))
        except Exception:
            return None
    return None


async def _resolve_property_id_for_underperformer(
    db: AsyncSession,
    underperformer: Dict[str, Any],
) -> Optional[str]:
    property_ref = str(underperformer.get("property_id") or "").strip()
    property_name = str(underperformer.get("property_name") or "").strip()
    if not property_ref and not property_name:
        return None

    if property_ref:
        query = text(
            """
            SELECT id::text
            FROM properties
            WHERE id::text = :property_ref
               OR streamline_property_id = :property_ref
               OR slug = :property_ref
            ORDER BY created_at DESC NULLS LAST
            LIMIT 1
            """
        )
        row = (await db.execute(query, {"property_ref": property_ref})).first()
        if row and row[0]:
            return str(row[0])

    if property_name:
        query = text(
            """
            SELECT id::text
            FROM properties
            WHERE lower(name) = lower(:property_name)
               OR lower(name) LIKE lower(:property_name_like)
               OR lower(slug) = lower(:property_name_slug)
            ORDER BY created_at DESC NULLS LAST
            LIMIT 1
            """
        )
        row = (
            await db.execute(
                query,
                {
                    "property_name": property_name,
                    "property_name_like": f"%{property_name}%",
                    "property_name_slug": property_name.replace(" ", "-"),
                },
            )
        ).first()
        if row and row[0]:
            return str(row[0])
    return None


def _collect_ai_channel_adjustments(entry: Dict[str, Any]) -> Dict[str, float]:
    recommendation_json = entry.get("recommendation_json") or {}
    collected: Dict[str, float] = {}

    raw_adjustments = recommendation_json.get("channel_adjustments")
    if isinstance(raw_adjustments, list):
        for item in raw_adjustments:
            if not isinstance(item, dict):
                continue
            code = str(item.get("channel_code") or item.get("channel") or "").strip().lower()
            if not code:
                continue
            pct = item.get("adjustment_pct")
            try:
                collected[code] = float(pct)
            except Exception:
                continue

    underperformers = recommendation_json.get("underperformers")
    if isinstance(underperformers, list):
        for item in underperformers:
            if not isinstance(item, dict):
                continue
            local_adjustments = item.get("channel_adjustments")
            if not isinstance(local_adjustments, list):
                continue
            for adj in local_adjustments:
                if not isinstance(adj, dict):
                    continue
                code = str(adj.get("channel_code") or adj.get("channel") or "").strip().lower()
                if not code:
                    continue
                pct = adj.get("adjustment_pct")
                try:
                    collected[code] = float(pct)
                except Exception:
                    continue
    return collected


def _resolve_final_channel_adjustments(
    entry: Dict[str, Any],
    overrides: Optional[List["ShadowBoardChannelAdjustmentInput"]],
) -> List[Dict[str, Any]]:
    ai_adjustments = _collect_ai_channel_adjustments(entry)
    merged: Dict[str, float] = dict(SHADOW_CHANNEL_DEFAULT_ADJUSTMENTS)
    merged.update(ai_adjustments)

    if overrides:
        for item in overrides:
            code = item.channel_code.strip().lower()
            if not code:
                continue
            merged[code] = float(item.adjustment_pct)

    output: List[Dict[str, Any]] = []
    for code, pct in merged.items():
        source = "global_default"
        if code in ai_adjustments:
            source = "ai_tactical_overlay"
        if overrides and any(o.channel_code.strip().lower() == code for o in overrides):
            source = "human_override"
        output.append(
            {
                "channel_code": code,
                "adjustment_pct": float(pct),
                "adjustment_type": "percent",
                "applies_to": "nightly",
                "source": source,
            }
        )
    return output


async def _get_or_create_channel_id(db: AsyncSession, channel_code: str) -> str:
    code = channel_code.strip().lower()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid_channel_code",
        )

    existing = await db.execute(
        text("SELECT id::text FROM channels WHERE lower(code) = :code LIMIT 1"),
        {"code": code},
    )
    row = existing.first()
    if row and row[0]:
        return str(row[0])

    new_id = str(uuid4())
    display = code.replace("_", " ").title()
    inserted = await db.execute(
        text(
            """
            INSERT INTO channels (id, code, display_name, is_active, created_at, updated_at)
            VALUES (CAST(:id AS uuid), :code, :display_name, true, now(), now())
            RETURNING id::text
            """
        ),
        {"id": new_id, "code": code, "display_name": display},
    )
    row = inserted.first()
    return str(row[0] if row and row[0] else new_id)


async def _upsert_property_base_rate(
    db: AsyncSession,
    property_id: str,
    date_start: datetime.date,
    date_end: datetime.date,
    base_rate: Decimal,
    rate_plan: str = "BAR",
    priority: int = 100,
) -> str:
    update_query = text(
        """
        UPDATE property_base_rates
        SET base_nightly_rate = :base_rate,
            priority = :priority,
            is_active = true,
            updated_at = now()
        WHERE property_id = CAST(:property_id AS uuid)
          AND date_start = :date_start
          AND date_end = :date_end
          AND rate_plan = :rate_plan
        RETURNING id::text
        """
    )
    updated = await db.execute(
        update_query,
        {
            "property_id": property_id,
            "date_start": date_start,
            "date_end": date_end,
            "rate_plan": rate_plan,
            "base_rate": base_rate,
            "priority": priority,
        },
    )
    row = updated.first()
    if row and row[0]:
        return str(row[0])

    new_id = str(uuid4())
    insert_query = text(
        """
        INSERT INTO property_base_rates (
            id,
            property_id,
            date_start,
            date_end,
            rate_plan,
            base_nightly_rate,
            priority,
            is_active,
            created_at,
            updated_at
        ) VALUES (
            CAST(:id AS uuid),
            CAST(:property_id AS uuid),
            :date_start,
            :date_end,
            :rate_plan,
            :base_rate,
            :priority,
            true,
            now(),
            now()
        )
        RETURNING id::text
        """
    )
    inserted = await db.execute(
        insert_query,
        {
            "id": new_id,
            "property_id": property_id,
            "date_start": date_start,
            "date_end": date_end,
            "rate_plan": rate_plan,
            "base_rate": base_rate,
            "priority": priority,
        },
    )
    row = inserted.first()
    return str(row[0] if row and row[0] else new_id)


async def _upsert_property_channel_rate_adjustment(
    db: AsyncSession,
    property_id: str,
    channel_id: str,
    date_start: datetime.date,
    date_end: datetime.date,
    adjustment_pct: float,
    source_label: str,
    priority: int = 100,
) -> str:
    update_query = text(
        """
        UPDATE property_channel_rate_adjustments
        SET adjustment_value = :adjustment_value,
            rule_name = :rule_name,
            priority = :priority,
            is_active = true,
            updated_at = now()
        WHERE property_id = CAST(:property_id AS uuid)
          AND channel_id = CAST(:channel_id AS uuid)
          AND date_start = :date_start
          AND date_end = :date_end
          AND adjustment_type = 'percent'
          AND applies_to = 'nightly'
        RETURNING id::text
        """
    )
    updated = await db.execute(
        update_query,
        {
            "property_id": property_id,
            "channel_id": channel_id,
            "date_start": date_start,
            "date_end": date_end,
            "adjustment_value": Decimal(str(adjustment_pct)).quantize(Decimal("0.0001")),
            "rule_name": source_label[:120],
            "priority": priority,
        },
    )
    row = updated.first()
    if row and row[0]:
        return str(row[0])

    new_id = str(uuid4())
    inserted = await db.execute(
        text(
            """
            INSERT INTO property_channel_rate_adjustments (
                id,
                property_id,
                channel_id,
                date_start,
                date_end,
                adjustment_type,
                adjustment_value,
                applies_to,
                rule_name,
                priority,
                is_active,
                created_at,
                updated_at
            ) VALUES (
                CAST(:id AS uuid),
                CAST(:property_id AS uuid),
                CAST(:channel_id AS uuid),
                :date_start,
                :date_end,
                'percent',
                :adjustment_value,
                'nightly',
                :rule_name,
                :priority,
                true,
                now(),
                now()
            )
            RETURNING id::text
            """
        ),
        {
            "id": new_id,
            "property_id": property_id,
            "channel_id": channel_id,
            "date_start": date_start,
            "date_end": date_end,
            "adjustment_value": Decimal(str(adjustment_pct)).quantize(Decimal("0.0001")),
            "rule_name": source_label[:120],
            "priority": priority,
        },
    )
    row = inserted.first()
    return str(row[0] if row and row[0] else new_id)


async def _actuate_shadow_board_entry(
    db: AsyncSession,
    entry: Dict[str, Any],
    actor: str,
    overrides: Optional[List["ShadowBoardChannelAdjustmentInput"]],
) -> Dict[str, Any]:
    recommendation_json = entry.get("recommendation_json") or {}
    underperformers = recommendation_json.get("underperformers") or []
    if not isinstance(underperformers, list) or not underperformers:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="shadow_board_actuation_missing_underperformers",
        )

    final_adjustments = _resolve_final_channel_adjustments(entry, overrides)
    if not final_adjustments:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="shadow_board_actuation_missing_channel_adjustments",
        )

    applied_base_rates: List[Dict[str, Any]] = []
    applied_channel_adjustments: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    snapshot_global_adr: Optional[Decimal] = None
    try:
        snapshot_payload, _ = _snapshot_payload_and_hash()
        global_adr_raw = (snapshot_payload.get("summary") or {}).get("global_adr")
        if global_adr_raw is not None:
            snapshot_global_adr = Decimal(str(global_adr_raw)).quantize(Decimal("0.01"))
    except Exception:
        snapshot_global_adr = None

    for item in underperformers:
        if not isinstance(item, dict):
            skipped.append({"reason": "invalid_underperformer_payload"})
            continue

        property_id = await _resolve_property_id_for_underperformer(db, item)
        if not property_id:
            skipped.append(
                {
                    "property_ref": item.get("property_id"),
                    "property_name": item.get("property_name"),
                    "reason": "property_not_found",
                }
            )
            continue

        date_start = _parse_shadow_date(
            str(item.get("date_start") or item.get("target_date_start") or item.get("effective_start_date") or "")
        )
        date_end = _parse_shadow_date(
            str(item.get("date_end") or item.get("target_date_end") or item.get("effective_end_date") or "")
        )
        if date_start is None or date_end is None:
            month_window = _parse_month_window(str(item.get("anomaly_summary") or ""))
            if month_window:
                date_start, date_end = month_window

        if date_start is None or date_end is None:
            skipped.append(
                {
                    "property_ref": item.get("property_id"),
                    "reason": "date_window_not_resolved",
                }
            )
            continue

        rate = _extract_rate_candidate(item)
        if rate is None and snapshot_global_adr is not None:
            dynamic_pct = item.get("dynamic_rate_adjustment_pct")
            if dynamic_pct is not None:
                try:
                    rate = (
                        snapshot_global_adr
                        * (Decimal("1") + (Decimal(str(dynamic_pct)) / Decimal("100")))
                    ).quantize(Decimal("0.01"))
                except Exception:
                    rate = snapshot_global_adr
            else:
                rate = snapshot_global_adr
        if rate is None:
            skipped.append(
                {
                    "property_ref": item.get("property_id"),
                    "reason": "recommended_rate_not_resolved",
                }
            )
            continue

        base_rate_row_id = await _upsert_property_base_rate(
            db=db,
            property_id=property_id,
            date_start=date_start,
            date_end=date_end,
            base_rate=rate,
            rate_plan="BAR",
            priority=100,
        )
        applied_base_rates.append(
            {
                "property_id": property_id,
                "date_start": date_start.isoformat(),
                "date_end": date_end.isoformat(),
                "base_nightly_rate": str(rate),
                "property_base_rate_id": base_rate_row_id,
            }
        )

        for adjustment in final_adjustments:
            channel_code = str(adjustment.get("channel_code") or "").strip().lower()
            pct = float(adjustment.get("adjustment_pct") or 0.0)
            source = str(adjustment.get("source") or "computed")
            channel_id = await _get_or_create_channel_id(db, channel_code)
            adj_row_id = await _upsert_property_channel_rate_adjustment(
                db=db,
                property_id=property_id,
                channel_id=channel_id,
                date_start=date_start,
                date_end=date_end,
                adjustment_pct=pct,
                source_label=source,
                priority=100,
            )
            effective_rate = (rate * (Decimal("1") + (Decimal(str(pct)) / Decimal("100")))).quantize(
                Decimal("0.01")
            )
            applied_channel_adjustments.append(
                {
                    "property_id": property_id,
                    "channel_code": channel_code,
                    "adjustment_pct": pct,
                    "effective_rate": str(effective_rate),
                    "property_channel_rate_adjustment_id": adj_row_id,
                    "source": source,
                }
            )

    if not applied_base_rates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "shadow_board_actuation_failed",
                "reason": "no_entries_upserted",
                "skipped": skipped[:10],
            },
        )

    logger.info(
        "shadow_board_actuation_applied",
        actor=actor,
        entry_id=entry.get("id"),
        base_rate_count=len(applied_base_rates),
        channel_adjustment_count=len(applied_channel_adjustments),
        skipped_count=len(skipped),
    )
    return {
        "base_rates": applied_base_rates,
        "channel_adjustments": applied_channel_adjustments,
        "final_channel_adjustments": final_adjustments,
        "skipped": skipped,
    }


def _snapshot_payload_and_hash() -> tuple[dict, str]:
    candidate_paths = [
        MARKET_SNAPSHOT_PATH,
        Path("/tmp/fortress_analytics/market_snapshot.json"),
        Path("/tmp/market_snapshot.json"),
    ]
    for path in candidate_paths:
        try:
            if not path.exists():
                continue
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            payload_hash = hashlib.sha256(canonical).hexdigest()
            payload["_resolved_snapshot_path"] = str(path)
            return payload, payload_hash
        except Exception:
            continue
    raise FileNotFoundError(
        "Snapshot not found in any known path: "
        + ", ".join(str(p) for p in candidate_paths)
    )


@router.post("/stream")
async def stream_intelligence(
    request: Request,
    body: StreamRequest,
    _user=Depends(require_manager_or_admin),
):
    """Agentic streaming endpoint with tool calling and GPU abort protection.

    OODA Loop:
    1. Observe  — send user query + tools to SWARM
    2. Orient   — LLM classifies intent via tool selection (no regex)
    3. Decide   — execute tools, fetch grounded data
    4. Act      — stream grounded synthesis to the user
    """

    async def generate():
        start = time.perf_counter()
        total_tokens = 0

        try:
            # ── Phase 1: Tool-calling pass with SWARM ────────────────
            # SWARM (qwen2.5:7b) supports native tool calling and is fast.
            # If user explicitly chose hydra, we still use SWARM for the
            # tool-calling step, then HYDRA for the grounded synthesis.
            synthesis_url = SWARM_URL
            synthesis_model = SWARM_MODEL
            synthesis_label = "SWARM"

            if body.model == "hydra":
                synthesis_url = HYDRA_URL
                synthesis_model = HYDRA_MODEL
                synthesis_label = "HYDRA"

            yield _sse("status", {
                "agent": "Router",
                "message": "Analyzing intent with SWARM tool-calling agent…",
            })

            messages = [
                {"role": "system", "content": body.system_prompt or SYSTEM_PROMPT},
            ]
            messages.extend(body.messages)

            tool_payload = {
                "model": SWARM_MODEL,
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "stream": True,
                "max_tokens": body.max_tokens,
                "temperature": body.temperature,
            }

            yield _sse("status", {
                "agent": "SWARM",
                "message": "Connecting to inference cluster…",
            })

            # ── Multi-round OODA loop (max 3 rounds) ────────────────
            # The LLM may need multiple tool calls: search first to find
            # a slug, then fetch detail. Each round: call LLM → if tools
            # requested, execute and feed context → repeat.
            MAX_ROUNDS = 3
            all_tool_results: List[Dict] = []
            all_tools_used: List[str] = []
            is_legal = False
            direct_response = False

            for round_num in range(MAX_ROUNDS):
                round_result = _StreamResult()

                async for frame in _stream_llm(request, SWARM_URL, tool_payload, round_result):
                    yield frame

                tool_calls = round_result.tool_calls
                total_tokens += round_result.token_count

                if not tool_calls:
                    direct_response = True
                    break

                tools_this_round = [tc["name"] for tc in tool_calls]
                all_tools_used.extend(tools_this_round)
                if any("legal" in n or "case" in n for n in tools_this_round):
                    is_legal = True

                logger.info(
                    "tool_calls_round",
                    round=round_num + 1,
                    tools=tools_this_round,
                )

                for tc in tool_calls:
                    name = tc["name"]
                    yield _sse("status", {
                        "agent": "Tool",
                        "message": f"Executing {name}({tc['arguments'][:80]})…",
                    })

                    result = await _execute_tool(name, tc["arguments"])
                    all_tool_results.append({"call": tc, "result": result})

                    comp_event = _tool_result_to_component(name, result)
                    if comp_event:
                        yield comp_event

                    yield _sse("status", {
                        "agent": "Tool",
                        "message": f"{name} → {len(json.dumps(result))} bytes",
                    })

                # Build context for next round — instruct the LLM to use
                # the slugs from search results for detail/deadline lookups
                context_parts = []
                for tr in all_tool_results:
                    n = tr["call"]["name"]
                    a = tr["call"]["arguments"]
                    d = json.dumps(tr["result"], indent=2)
                    context_parts.append(f"=== TOOL: {n}({a}) ===\n{d}")

                tool_context = "\n\n".join(context_parts)
                already_called = ", ".join(set(all_tools_used))

                round_system = (
                    f"{body.system_prompt or SYSTEM_PROMPT}\n\n"
                    f"TOOL RESULTS FROM PREVIOUS STEPS:\n\n"
                    f"{tool_context}\n\n"
                    f"INSTRUCTIONS FOR THIS STEP:\n"
                    f"- You already called: {already_called}. Do NOT re-call the same tools.\n"
                    f"- If search results contain case_slug values, use get_case_detail "
                    f"or get_case_deadlines with those exact slugs.\n"
                    f"- If you have enough data, respond directly with a grounded answer.\n"
                )

                messages_with_context = [
                    {"role": "system", "content": round_system},
                ]
                messages_with_context.extend(body.messages)

                tool_payload = {
                    "model": SWARM_MODEL,
                    "messages": messages_with_context,
                    "tools": TOOLS,
                    "tool_choice": "auto",
                    "stream": True,
                    "max_tokens": body.max_tokens,
                    "temperature": body.temperature,
                }

            if direct_response:
                # The LLM already streamed a response (with or without
                # tool context from earlier rounds). We're done.
                elapsed = round((time.perf_counter() - start) * 1000)
                yield _sse("done", {
                    "model": f"SWARM ({SWARM_MODEL})",
                    "model_id": SWARM_MODEL,
                    "tokens": total_tokens,
                    "latency_ms": elapsed,
                    "tok_per_sec": round(total_tokens / max(elapsed / 1000, 0.001), 1),
                    "tools_used": all_tools_used,
                    "grounded": bool(all_tool_results),
                })
                return

            # ── Phase 3: Grounded synthesis ───────────────────────────
            # Feed tool results back to the LLM for a grounded response.
            # We use CONTEXT INJECTION (not tool role messages) because
            # deepseek-r1 and some models don't support the "tool" role.
            # This is more robust across all model families.
            if body.model == "auto" and is_legal:
                synthesis_url = HYDRA_URL
                synthesis_model = HYDRA_MODEL
                synthesis_label = "HYDRA"

            yield _sse("status", {
                "agent": synthesis_label,
                "message": f"Synthesizing grounded response with {synthesis_label}…",
            })

            # Build grounding context from all tool results
            context_parts = []
            for tr in all_tool_results:
                name = tr["call"]["name"]
                args = tr["call"]["arguments"]
                data = json.dumps(tr["result"], indent=2)
                context_parts.append(
                    f"=== TOOL: {name}({args}) ===\n{data}"
                )
            grounding_context = "\n\n".join(context_parts)

            grounded_system = (
                f"{body.system_prompt or SYSTEM_PROMPT}\n\n"
                f"GROUNDING DATA (from database queries — these are FACTS, "
                f"do NOT contradict or hallucinate beyond this data):\n\n"
                f"{grounding_context}"
            )

            # Fresh message list: grounded system + original user messages
            synth_messages = [
                {"role": "system", "content": grounded_system},
            ]
            synth_messages.extend(body.messages)

            synth_max_tokens = body.max_tokens
            if synthesis_model == HYDRA_MODEL:
                synth_max_tokens = max(body.max_tokens * 4, 8192)

            synthesis_payload = {
                "model": synthesis_model,
                "messages": synth_messages,
                "stream": True,
                "max_tokens": synth_max_tokens,
                "temperature": body.temperature,
            }

            # Stream the grounded response
            synth_result = _StreamResult()
            async for frame in _stream_llm(request, synthesis_url, synthesis_payload, synth_result):
                yield frame

            total_tokens += synth_result.token_count
            elapsed = round((time.perf_counter() - start) * 1000)
            yield _sse("done", {
                "model": f"{synthesis_label} ({synthesis_model})",
                "model_id": synthesis_model,
                "tokens": total_tokens,
                "latency_ms": elapsed,
                "tok_per_sec": round(total_tokens / max(elapsed / 1000, 0.001), 1),
                "tools_used": all_tools_used,
                "grounded": True,
            })
            logger.info(
                "agentic_stream_complete",
                model=synthesis_model,
                tools=all_tools_used,
                tokens=total_tokens,
                latency_ms=elapsed,
            )

        except asyncio.CancelledError:
            logger.info("stream_cancelled_by_client", tokens=total_tokens)
            raise
        except Exception as exc:
            logger.exception("ooda_loop_error", error=str(exc))
            yield _sse("status", {
                "agent": "Error",
                "message": f"Stream error: {type(exc).__name__}: {exc}",
            })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/council/execute")
async def council_execute(
    request: Request,
    body: CouncilExecuteRequest,
    _user=Depends(require_manager_or_admin),
):
    """
    Stream council DAG execution progress to the frontend.
    """
    node_labels = {
        "architect": "Architect",
        "engineer": "Engineer",
        "executor": "Executor",
        "critic": "Critic",
    }
    node_messages = {
        "architect": "Analyzing request and querying memory vault...",
        "engineer": "Drafting execution payload...",
        "executor": "Running code in hardened sandbox...",
        "critic": "Verifying and polishing final answer...",
    }

    async def generate():
        start = time.perf_counter()
        latest_state: Dict[str, Any] = {
            "user_prompt": body.prompt,
            "timeout_seconds": body.timeout_seconds,
            "retry_count": 0,
            "audit_trail": [],
        }
        executor_attempt = 0
        critic_announced = False

        try:
            # Emit immediately so clients can render timeline state without waiting
            # for the first model-backed graph update.
            yield _sse("status", {
                "event": "status",
                "agent": "Council",
                "message": "Council execution initiated...",
            })

            stream_ok = False
            try:
                async for update in council_orchestrator.astream(latest_state, stream_mode="updates"):
                    if await request.is_disconnected():
                        break
                    if not isinstance(update, dict):
                        continue
                    stream_ok = True

                    for node_name, node_update in update.items():
                        if not isinstance(node_update, dict):
                            continue
                        latest_state.update(node_update)

                        yield _sse("node_start", {
                            "event": "node_start",
                            "node": node_labels.get(node_name, node_name.title()),
                            "message": node_messages.get(node_name, "Processing node..."),
                        })

                        if node_name == "executor":
                            executor_attempt += 1
                            failed = int(latest_state.get("execution_exit_code", -1)) != 0
                            stderr = latest_state.get("execution_stderr", "") or ""
                            err_cls = latest_state.get("execution_error_class", "") or ""
                            yield _sse("execution_result", {
                                "event": "execution_result",
                                "status": "failed" if failed else "success",
                                "retry_count": max(executor_attempt - 1, 0),
                                "stderr": stderr[:1200],
                            })
                            if failed and (err_cls in ("ExecutionTimeout", "SyntaxError") or "SyntaxError" in stderr):
                                yield _sse("status", {
                                    "event": "status",
                                    "agent": "Engineer",
                                    "message": f"Engineer is rewriting code (Attempt {min(executor_attempt, 3)}/3)...",
                                })
                            will_retry = (
                                failed
                                and (err_cls in ("ExecutionTimeout", "SyntaxError") or "SyntaxError" in stderr)
                                and int(latest_state.get("retry_count", 0)) < 3
                            )
                            if not will_retry and not critic_announced:
                                critic_announced = True
                                yield _sse("node_start", {
                                    "event": "node_start",
                                    "node": "Critic",
                                    "message": "Validating execution output and formatting response...",
                                })

                        if node_name == "critic":
                            critic_announced = True

                if not stream_ok:
                    latest_state = await run_council_orchestration(
                        user_prompt=body.prompt,
                        timeout_seconds=body.timeout_seconds,
                    )
            except Exception as stream_exc:
                logger.warning("council_stream_fallback", error=str(stream_exc)[:200])
                latest_state = await run_council_orchestration(
                    user_prompt=body.prompt,
                    timeout_seconds=body.timeout_seconds,
                )

            final_content = (latest_state.get("final_response") or "").strip()
            if not final_content:
                final_content = "Council orchestration completed without a final response."

            if not critic_announced:
                yield _sse("node_start", {
                    "event": "node_start",
                    "node": "Critic",
                    "message": "Validating execution output and formatting response...",
                })

            # Stream critic response progressively for terminal UX.
            chunk_size = 120
            for i in range(0, len(final_content), chunk_size):
                yield _sse("token", {
                    "event": "token",
                    "content": final_content[i:i + chunk_size],
                })

            yield _sse("final_response", {
                "event": "final_response",
                "content": final_content,
                "solved": bool(latest_state.get("solved", False)),
            })

            elapsed = round((time.perf_counter() - start) * 1000)
            yield _sse("done", {
                "event": "done",
                "latency_ms": elapsed,
                "retry_count": int(latest_state.get("retry_count", 0)),
                "audit_trail": latest_state.get("audit_trail", []),
            })
        except Exception as exc:
            logger.exception("council_execute_error", error=str(exc))
            yield _sse("error", {
                "event": "error",
                "message": f"Council execution failed: {type(exc).__name__}: {exc}",
            })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/models")
async def list_models(_user=Depends(require_manager_or_admin)):
    """Return available inference models and routing metadata."""
    return {
        "models": [
            {
                "id": "auto",
                "name": "Auto-Route",
                "description": (
                    "SWARM handles tool calling; auto-upgrades to HYDRA "
                    "for grounded legal synthesis"
                ),
            },
            {
                "id": "swarm",
                "name": f"SWARM ({SWARM_MODEL})",
                "description": "Fast inference with tool calling",
            },
            {
                "id": "hydra",
                "name": f"HYDRA ({HYDRA_MODEL})",
                "description": "Deep reasoning for grounded synthesis",
            },
        ],
    }


@router.get("/tools")
async def list_tools(_user=Depends(require_manager_or_admin)):
    """Return the tool definitions available to the LLM."""
    return {"tools": TOOLS}


@router.get("/market-snapshot/latest")
async def market_snapshot_latest(_user=Depends(require_manager_or_admin)):
    """
    Read-only Gate D analytics contract payload.
    Returns payload hash + top-level sections for shadow dashboard rendering.
    """
    try:
        payload, payload_hash = _snapshot_payload_and_hash()
        resolved_path = Path(payload.get("_resolved_snapshot_path", str(MARKET_SNAPSHOT_PATH)))
        stat = resolved_path.stat()
        return {
            "snapshot_hash": payload_hash,
            "snapshot_path": str(resolved_path),
            "snapshot_mtime": datetime.datetime.fromtimestamp(
                stat.st_mtime,
                tz=datetime.timezone.utc,
            ).isoformat(),
            "generated_at": payload.get("generated_at"),
            "summary": payload.get("summary", {}),
            "source": payload.get("source", {}),
            "adr_history": payload.get("adr_history", {}),
            "occupancy_gaps": payload.get("occupancy_gaps", {}),
            "booking_lead_times": payload.get("booking_lead_times", {}),
            "channel_mix": payload.get("channel_mix", {}),
            "competitor_pricing_deltas": payload.get("competitor_pricing_deltas", {}),
        }
    except FileNotFoundError as exc:
        return {
            "snapshot_hash": None,
            "error": "snapshot_not_found",
            "detail": str(exc),
        }
    except Exception as exc:
        logger.exception("market_snapshot_latest_failed", error=str(exc))
        return {
            "snapshot_hash": None,
            "error": "snapshot_read_failed",
            "detail": str(exc),
        }


@router.post("/market-snapshot/canary-recommendation")
async def market_snapshot_canary_recommendation(
    body: MarketSnapshotCanaryRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_manager_or_admin),
):
    """
    Gate D canary bridge: send compact snapshot contract to Sovereign inference.
    Skips expensive inference if snapshot hash has not changed unless force=true.
    """
    try:
        payload, payload_hash = _snapshot_payload_and_hash()
        if (not body.force) and body.last_payload_hash and body.last_payload_hash == payload_hash:
            return {
                "skipped": True,
                "reason": "unchanged_snapshot_hash",
                "snapshot_hash": payload_hash,
                "model": SOVEREIGN_MODEL,
            }

        compact_contract = {
            "generated_at": payload.get("generated_at"),
            "summary": payload.get("summary", {}),
            "adr_monthly_recent": (payload.get("adr_history", {}).get("monthly", []) or [])[-6:],
            "weakest_months": payload.get("occupancy_gaps", {}).get("weakest_months", []) or [],
            "weekpart": payload.get("occupancy_gaps", {}).get("weekpart", []) or [],
            "lead_time_distribution": payload.get("booking_lead_times", {}).get("distribution", []) or [],
            "channel_mix": (payload.get("channel_mix", {}).get("by_channel", []) or [])[:6],
            "competitor_pricing_deltas": payload.get("competitor_pricing_deltas", {}),
        }
        property_catalog = await _load_property_catalog_async(db)
        if not property_catalog:
            # Fallback to legacy read-only connector if async DB path is unavailable.
            try:
                property_catalog = await asyncio.to_thread(_load_property_catalog)
            except Exception as exc:
                logger.warning("market_snapshot_property_catalog_load_failed", error=str(exc)[:240])
                property_catalog = []
        compact_contract["property_catalog"] = property_catalog

        prompt = body.prompt_override or (
            "You are Sovereign (.106), operating as a deterministic quantitative analyst "
            "and SOTA hospitality marketer for CROG-VRS. "
            "Analyze the MARKET_CONTRACT_JSON and identify underperforming properties "
            "against seasonal baseline signals (occupancy gaps, ADR drift, weekpart weakness). "
            "Return ONLY valid JSON with this exact shape: "
            "{"
            "\"generated_at_utc\": \"ISO8601\", "
            "\"snapshot_hash\": \"string\", "
            "\"underperformers\": ["
            "{"
            "\"property_id\": \"string\", "
            "\"property_name\": \"string\", "
            "\"anomaly_summary\": \"string\", "
            "\"recommended_base_rate\": number, "
            "\"dynamic_rate_adjustment_pct\": number, "
            "\"google_ads_headline\": \"string <= 90 chars\", "
            "\"nextjs_seo_summary\": \"string <= 320 chars\", "
            "\"confidence\": number"
            "}"
            "], "
            "\"portfolio_actions\": [\"string\", \"string\"], "
            "\"method_notes\": [\"string\"]"
            "}. "
            "Rules: (1) Use only supplied contract data, no hallucinations. "
            "(2) dynamic_rate_adjustment_pct must be within [-25, 25]. "
            "(3) recommended_base_rate must be > 0 and represent the final base nightly USD rate. "
            "(4) property_id and property_name MUST come exactly from property_catalog; never invent synthetic IDs. "
            "(5) If evidence is insufficient for a property, omit it. "
            "(6) Keep language executive and operational."
        )

        timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            selected_model, selected_chat_url = await _resolve_sovereign_model(client)
            sovereign_payload = {
                "model": selected_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a deterministic enterprise analyst with strict schema compliance. "
                            "Output must be valid JSON only, with no markdown fences and no prose outside JSON. "
                            "Do not invent properties or metrics not present in the provided contract."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"{prompt}\n\nMARKET_CONTRACT_JSON:\n{json.dumps(compact_contract)}",
                    },
                ],
                "temperature": body.temperature,
                "max_tokens": body.max_tokens,
                "stream": False,
            }
            resp = await client.post(selected_chat_url, json=sovereign_payload)
            if resp.status_code != 200:
                detail = resp.text[:800]
                logger.error(
                    "market_snapshot_canary_upstream_error",
                    status=resp.status_code,
                    detail=detail,
                )
                return {
                    "skipped": False,
                    "error": "sovereign_upstream_error",
                    "status": resp.status_code,
                    "detail": detail,
                    "snapshot_hash": payload_hash,
                    "model": selected_model,
                }

        data = resp.json()
        raw_recommendation = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        try:
            parsed_json = _extract_json_from_model_text(raw_recommendation)
            parsed_json = _normalize_canary_contract(
                parsed_json,
                payload_hash,
                (payload.get("summary") or {}).get("global_adr"),
                property_catalog,
            )
            validated = SovereignCanaryResponseModel.model_validate(parsed_json)
        except (ValueError, json.JSONDecodeError, ValidationError) as parse_exc:
            logger.warning(
                "market_snapshot_canary_parse_failed",
                error=str(parse_exc),
            )
            repaired = await _repair_canary_json(
                chat_url=selected_chat_url,
                model=selected_model,
                snapshot_hash=payload_hash,
                raw_output=raw_recommendation,
            )
            if repaired is not None:
                try:
                    repaired = _normalize_canary_contract(
                        repaired,
                        payload_hash,
                        (payload.get("summary") or {}).get("global_adr"),
                        property_catalog,
                    )
                    validated = SovereignCanaryResponseModel.model_validate(repaired)
                except ValidationError:
                    validated = None
                if validated is not None:
                    logger.info("market_snapshot_canary_repair_success", model=selected_model)
                    return {
                        "skipped": False,
                        "snapshot_hash": payload_hash,
                        "model": selected_model,
                        "sovereign_url": selected_chat_url,
                        "recommendation": json.dumps(validated.model_dump(), indent=2),
                        "recommendation_json": validated.model_dump(),
                        "repair_applied": True,
                    }
            logger.warning("market_snapshot_canary_local_fallback_applied", model=selected_model)
            fallback_contract = SovereignCanaryResponseModel(
                generated_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                snapshot_hash=payload_hash,
                underperformers=[],
                portfolio_actions=[],
                method_notes=[
                    "model_output_unparseable_fallback_applied",
                    f"parse_error={str(parse_exc)[:180]}",
                ],
            )
            return {
                "skipped": False,
                "snapshot_hash": payload_hash,
                "model": selected_model,
                "sovereign_url": selected_chat_url,
                "recommendation": json.dumps(fallback_contract.model_dump(), indent=2),
                "recommendation_json": fallback_contract.model_dump(),
                "fallback_applied": True,
                "recommendation_raw": raw_recommendation[:4000],
            }
        except ValidationError as val_exc:
            logger.warning(
                "market_snapshot_canary_schema_failed",
                error=val_exc.errors(),
            )
            return {
                "skipped": False,
                "error": "invalid_model_schema",
                "detail": val_exc.errors(),
                "snapshot_hash": payload_hash,
                "model": selected_model,
                "recommendation_raw": raw_recommendation[:4000],
            }

        return {
            "skipped": False,
            "snapshot_hash": payload_hash,
            "model": selected_model,
            "sovereign_url": selected_chat_url,
            "recommendation": json.dumps(validated.model_dump(), indent=2),
            "recommendation_json": validated.model_dump(),
        }
    except FileNotFoundError as exc:
        return {
            "skipped": True,
            "error": "snapshot_not_found",
            "detail": str(exc),
        }
    except Exception as exc:
        logger.exception("market_snapshot_canary_failed", error=str(exc))
        return {
            "skipped": True,
            "error": "canary_failed",
            "detail": str(exc),
        }


@router.post("/market-snapshot/shadow-board/apply")
async def apply_market_canary_to_shadow_board(
    body: ShadowBoardApplyRequest,
    user: StaffUser = Depends(get_current_user),
):
    """
    Persist a validated canary recommendation into the Shadow Pricing Board queue.
    This is review-only and does not auto-deploy any pricing actions.
    """
    _require_shadow_board_role(user)
    normalized = _normalize_canary_contract(body.recommendation_json, body.snapshot_hash)
    try:
        validated = SovereignCanaryResponseModel.model_validate(normalized)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_recommendation_json",
                "invalid_params": exc.errors(),
            },
        ) from exc

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entry = {
        "id": str(uuid4()),
        "created_at": now_iso,
        "status": "pending_review",
        "snapshot_hash": body.snapshot_hash,
        "model": body.model,
        "actor": _actor_from_user(user),
        "note": body.note,
        "recommendation_json": validated.model_dump(),
        "recommendation_raw": (body.recommendation_raw or "")[:20000],
    }

    board = _read_shadow_board()
    entries = board.get("entries", [])
    entries.insert(0, entry)
    board["entries"] = entries[:200]
    _write_shadow_board(board)

    return {
        "ok": True,
        "entry_id": entry["id"],
        "status": entry["status"],
        "snapshot_hash": entry["snapshot_hash"],
        "model": entry["model"],
    }


@router.get("/market-snapshot/shadow-board")
async def list_market_shadow_board(
    limit: int = 20,
    user: StaffUser = Depends(get_current_user),
):
    """
    Read-only list of queued Shadow Pricing Board entries.
    """
    _require_shadow_board_role(user)
    safe_limit = min(max(int(limit), 1), 100)
    board = _read_shadow_board()
    entries = board.get("entries", [])
    return {"entries": entries[:safe_limit], "total": len(entries)}


def _update_shadow_board_entry(entry_id: str, status: str, actor: str, note: Optional[str]) -> Dict[str, Any]:
    board = _read_shadow_board()
    entries = board.get("entries", [])
    target: Optional[Dict[str, Any]] = None
    for entry in entries:
        if entry.get("id") == entry_id:
            target = entry
            break
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="shadow_board_entry_not_found",
        )
    if target.get("status") != "pending_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"shadow_board_entry_not_pending:{target.get('status')}",
        )

    target["status"] = status
    target["reviewed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    target["reviewed_by"] = actor
    if note:
        target["review_note"] = note
    _write_shadow_board(board)
    return target


@router.post("/market-snapshot/shadow-board/{entry_id}/approve")
async def approve_market_shadow_board_entry(
    entry_id: str,
    body: ShadowBoardDecisionRequest,
    user: StaffUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Approve a queued Shadow Board recommendation and actuate routing rows.
    """
    _require_shadow_board_role(user)
    board = _read_shadow_board()
    entries = board.get("entries", [])
    target: Optional[Dict[str, Any]] = None
    for entry in entries:
        if entry.get("id") == entry_id:
            target = entry
            break
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="shadow_board_entry_not_found",
        )
    if target.get("status") != "pending_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"shadow_board_entry_not_pending:{target.get('status')}",
        )

    actor = _actor_from_user(user)
    actuation = await _actuate_shadow_board_entry(
        db=db,
        entry=target,
        actor=actor,
        overrides=body.final_channel_adjustments,
    )
    await db.commit()

    target["status"] = "approved"
    target["reviewed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    target["reviewed_by"] = actor
    if body.note:
        target["review_note"] = body.note
    target["actuation"] = {
        "targets": ["property_base_rates", "property_channel_rate_adjustments"],
        "base_rate_count": len(actuation.get("base_rates", [])),
        "channel_adjustment_count": len(actuation.get("channel_adjustments", [])),
        "base_rates": actuation.get("base_rates", []),
        "channel_adjustments": actuation.get("channel_adjustments", []),
        "final_channel_adjustments": actuation.get("final_channel_adjustments", []),
        "skipped": actuation.get("skipped", []),
    }
    _write_shadow_board(board)

    return {
        "ok": True,
        "entry_id": entry_id,
        "status": target.get("status"),
        "actuation": target.get("actuation"),
    }


@router.post("/market-snapshot/shadow-board/{entry_id}/reject")
async def reject_market_shadow_board_entry(
    entry_id: str,
    body: ShadowBoardDecisionRequest,
    user: StaffUser = Depends(get_current_user),
):
    """
    Reject a queued Shadow Board recommendation (review state only).
    """
    _require_shadow_board_role(user)
    review_note = (body.note or "").strip()
    if not review_note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="review_note_required_for_reject",
        )

    updated = _update_shadow_board_entry(
        entry_id=entry_id,
        status="rejected",
        actor=_actor_from_user(user),
        note=review_note,
    )

    return {"ok": True, "entry_id": entry_id, "status": updated.get("status")}
