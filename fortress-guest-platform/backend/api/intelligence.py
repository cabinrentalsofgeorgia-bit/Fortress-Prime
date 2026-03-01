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
import json
import os
import time
from typing import Any, Dict, List, Optional

import httpx
import psycopg2
import psycopg2.extras
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.core.config import settings

logger = structlog.get_logger()
router = APIRouter()

# ── Inference Endpoints ──────────────────────────────────────────────
SWARM_URL = "http://192.168.0.100/v1/chat/completions"
HYDRA_URL = "http://192.168.0.100/hydra/v1/chat/completions"
SWARM_MODEL = getattr(settings, "ollama_fast_model", "qwen2.5:7b")
HYDRA_MODEL = getattr(settings, "ollama_deep_model", "deepseek-r1:70b")

# ── Service / DB Endpoints ───────────────────────────────────────────
QDRANT_URL = getattr(settings, "qdrant_url", "http://localhost:6333")
EMBED_URL = getattr(settings, "embed_base_url", "http://192.168.0.100:11434")
EMBED_MODEL = getattr(settings, "embed_model", "nomic-embed-text")

DB_CFG = dict(
    host=os.getenv("FORTRESS_DB_HOST", "localhost"),
    port=int(os.getenv("FORTRESS_DB_PORT", "5432")),
    dbname=os.getenv("FORTRESS_DB_NAME", "fortress_db"),
    user=os.getenv("FORTRESS_DB_USER", "miner_bot"),
    password=os.getenv("FORTRESS_DB_PASS", ""),
)

HTTPX_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=10.0, pool=10.0)

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


_QDRANT_COLLECTIONS = {
    "fortress_knowledge": {
        "content_field": "text",
        "source_field": "source_file",
    },
    "email_embeddings": {
        "content_field": "preview",
        "source_field": "subject",
    },
    "legal_library": {
        "content_field": "text",
        "source_field": "source_file",
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
    """Federated search across fortress_knowledge, email_embeddings, and legal_library."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            embed_resp = await client.post(
                f"{EMBED_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": query},
            )
            embed_resp.raise_for_status()
            embedding = embed_resp.json().get("embedding")
            if not embedding:
                return _model_dump(ToolError(
                    tool_error="Embedding generation failed",
                    details="Embedding endpoint returned no vector",
                ))

            per_collection = 5
            search_tasks = [
                _search_single_collection(client, coll, embedding, per_collection)
                for coll in _QDRANT_COLLECTIONS
            ]
            collection_results = await asyncio.gather(
                *search_tasks, return_exceptions=True,
            )

            merged: List[KnowledgeResult] = []
            searched: List[str] = []
            for coll_name, result in zip(_QDRANT_COLLECTIONS, collection_results):
                searched.append(coll_name)
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


@router.post("/stream")
async def stream_intelligence(request: Request, body: StreamRequest):
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


@router.get("/models")
async def list_models():
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
async def list_tools():
    """Return the tool definitions available to the LLM."""
    return {"tools": TOOLS}
