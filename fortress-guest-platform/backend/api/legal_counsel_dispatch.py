"""
OUTSIDE COUNSEL DISPATCH ENGINE — Dynamic Multi-Source Legal Headhunter
=======================================================================

POST /api/legal/counsel/dispatch/draft
    Accepts case_brief + consensus, uses the God Head to generate a
    Fortune-500 style "Limited Scope Representation Inquiry" email.

POST /api/legal/counsel/dispatch/hunt
    Dynamic multi-source attorney search.  Accepts jurisdiction, specialty,
    and case_brief.  The God Head generates 3 distinct search queries,
    executes them against docket/caselaw sites AND legal journalism sites,
    then evaluates the scraped results to return a ranked attorney list
    with firm, contact info, and reason for recommendation.

POST /api/legal/counsel/dispatch/feedback
    Vectorized episodic memory.  CEO thumbs-up/down on hunt results is
    embedded via nomic-embed-text (768-dim) and upserted into the
    legal_headhunter_memory Qdrant collection for semantic pre-retrieval
    on future hunts.  Raw log also written to legal.headhunter_memory
    for audit purposes.
"""

import json
import os
import re
import uuid as _uuid
import structlog
import httpx
import asyncio

from datetime import datetime, timezone
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from typing import Any, Optional
from urllib.parse import quote_plus

from backend.core.config import settings
from backend.services.ediscovery_agent import LegacySession

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

logger = structlog.get_logger()
router = APIRouter()

ALLOW_CLOUD_LLM = os.getenv("ALLOW_CLOUD_LLM", "false").lower() == "true"
ANTHROPIC_PROXY = os.getenv("ANTHROPIC_PROXY_URL", "http://localhost:5100/v1")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
HYDRA_URL = os.getenv("HYDRA_FALLBACK_URL", "http://192.168.0.100/hydra/v1")
HYDRA_MODEL = os.getenv("HYDRA_MODEL", "deepseek-r1:70b")
SWARM_URL = os.getenv("SWARM_URL", "http://192.168.0.100/v1")
SWARM_MODEL = os.getenv("SWARM_MODEL", "qwen2.5:7b")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

# ── Qdrant Episodic Memory Configuration ─────────────────────────────
QDRANT_URL = getattr(settings, "qdrant_url", "http://localhost:6333").rstrip("/")
QDRANT_API_KEY = getattr(settings, "qdrant_api_key", "") or ""
QDRANT_HEADERS: dict[str, str] = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}
EMBED_URL = getattr(settings, "embed_base_url", "http://192.168.0.100:11434")
EMBED_MODEL = getattr(settings, "embed_model", "nomic-embed-text")
MEMORY_COLLECTION = "legal_headhunter_memory"
MEMORY_VECTOR_DIM = 768

HTTPX_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
SEARCH_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


# ══════════════════════════════════════════════════════════════════════
# QDRANT EPISODIC MEMORY — Collection Init + Embedding + Retrieval
# ══════════════════════════════════════════════════════════════════════


async def ensure_memory_collection() -> bool:
    """Create the legal_headhunter_memory Qdrant collection if missing (idempotent)."""
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                f"{QDRANT_URL}/collections/{MEMORY_COLLECTION}",
                headers=QDRANT_HEADERS,
            )
            if resp.status_code == 200:
                info = resp.json().get("result", {})
                logger.info(
                    "headhunter_memory_collection_exists",
                    collection=MEMORY_COLLECTION,
                    points=info.get("points_count", 0),
                )
                return True
        except httpx.ConnectError:
            logger.warning("qdrant_unreachable_for_memory", url=QDRANT_URL)
            return False

        try:
            create_resp = await client.put(
                f"{QDRANT_URL}/collections/{MEMORY_COLLECTION}",
                json={
                    "vectors": {
                        "size": MEMORY_VECTOR_DIM,
                        "distance": "Cosine",
                    },
                },
                headers=QDRANT_HEADERS,
            )
            create_resp.raise_for_status()
            logger.info(
                "headhunter_memory_collection_created",
                collection=MEMORY_COLLECTION,
                vector_dim=MEMORY_VECTOR_DIM,
                distance="Cosine",
            )

            for field, schema in [
                ("case_slug", "keyword"),
                ("attorney_name", "keyword"),
                ("jurisdiction", "keyword"),
                ("specialty", "keyword"),
                ("sentiment", "keyword"),
            ]:
                await client.put(
                    f"{QDRANT_URL}/collections/{MEMORY_COLLECTION}/index",
                    json={"field_name": field, "field_schema": schema},
                    headers=QDRANT_HEADERS,
                )
            return True
        except Exception as e:
            logger.error("headhunter_memory_collection_create_failed", error=str(e)[:300])
            return False


async def _embed_text(text_input: str) -> list[float]:
    """Generate a 768-dim embedding via the local nomic-embed-text model (Ollama-compatible)."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{EMBED_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text_input},
        )
        resp.raise_for_status()
        embedding = resp.json().get("embedding", [])
        if not embedding:
            raise ValueError("Empty embedding returned from model")
        return embedding


async def _upsert_memory_vector(
    point_id: str,
    vector: list[float],
    payload: dict[str, Any],
) -> bool:
    """Upsert a single point into the legal_headhunter_memory collection."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(
            f"{QDRANT_URL}/collections/{MEMORY_COLLECTION}/points",
            json={
                "points": [
                    {
                        "id": point_id,
                        "vector": vector,
                        "payload": payload,
                    }
                ]
            },
            headers=QDRANT_HEADERS,
        )
        resp.raise_for_status()
        return True


async def _retrieve_memory_lessons(
    jurisdiction: str,
    specialty: str,
    top_k: int = 3,
    score_threshold: float = 0.40,
) -> list[dict[str, Any]]:
    """Semantic pre-retrieval: embed [jurisdiction] + [specialty] and search for past CEO feedback."""
    try:
        query_text = f"{jurisdiction} {specialty}"
        query_vector = await _embed_text(query_text)

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{QDRANT_URL}/collections/{MEMORY_COLLECTION}/points/search",
                json={
                    "vector": query_vector,
                    "limit": top_k,
                    "score_threshold": score_threshold,
                    "with_payload": True,
                },
                headers=QDRANT_HEADERS,
            )
            resp.raise_for_status()
            results = resp.json().get("result", [])

        lessons = []
        for hit in results:
            payload = hit.get("payload", {})
            lessons.append({
                "score": round(hit.get("score", 0), 4),
                "feedback_notes": payload.get("feedback_notes", ""),
                "attorney_name": payload.get("attorney_name", ""),
                "sentiment": payload.get("sentiment", ""),
                "jurisdiction": payload.get("jurisdiction", ""),
                "specialty": payload.get("specialty", ""),
                "case_slug": payload.get("case_slug", ""),
            })

        logger.info(
            "headhunter_memory_retrieval",
            query=query_text[:100],
            lessons_found=len(lessons),
            top_score=lessons[0]["score"] if lessons else 0,
        )
        return lessons

    except Exception as e:
        logger.warning("headhunter_memory_retrieval_failed", error=str(e)[:300])
        return []


# ── RFP Draft Prompt ──────────────────────────────────────────────────

RFP_SYSTEM_PROMPT = """You are the Chief Legal Operations Officer for a sophisticated real-estate holding company. You are drafting a professional email to prospective outside counsel requesting a limited-scope representation quote.

Write a polished, Fortune-500 quality email that:

1. Opens with a one-paragraph executive summary of the case (parties, court, case number, amount in controversy, claim types).
2. Summarises the internal legal analysis and defense strategy in 3-5 bullet points. DO NOT reveal attorney-client privileged analysis — present only the strategic posture.
3. States that an Answer and Affirmative Defenses have already been drafted and are ready for attorney review and filing.
4. Specifies the scope of engagement sought: limited-scope representation covering Answer filing, initial discovery, and (if possible) early dispositive motion or settlement conference.
5. Requests a flat-fee quote or capped retainer structure. Ask for the fee proposal broken into: (a) Answer review and filing, (b) discovery phase, (c) dispositive motion / settlement.
6. Requests the attorney's earliest available consultation window.
7. Closes professionally with contact information placeholders.

Format: Professional email with Subject line, greeting, body, and signature block.
Tone: Confident, prepared, and efficient — you are a sophisticated client who has done thorough preparation.
Do NOT include any disclaimers or hedge language. This is a business communication."""

# ── Hunt Prompts ──────────────────────────────────────────────────────

HUNT_QUERY_GEN_PROMPT = """You are a legal research strategist. Given a case brief, jurisdiction, and required specialty, generate exactly 3 distinct Google search queries designed to find attorneys who have won or settled similar cases.

STRICT RULES (violating any rule invalidates the output):
1. Use a MAXIMUM of 4 to 6 core keywords per query. Shorter queries return more results.
2. NEVER include local trial courts, counties, or judicial circuits (e.g., do NOT use "Fannin County", "Appalachian Circuit", "Blue Ridge"). ONLY use the STATE name (e.g., "Georgia").
3. Focus queries heavily on specific statutes (e.g., "O.C.G.A. § 10-6-1") and core legal defenses (e.g., "apparent authority", "account stated").
4. Each query must be phrased differently to cast a wide net across appellate dockets and legal journalism.
5. Prefer quoting 2-3 word legal phrases to improve search precision (e.g., "apparent authority").

GOOD query example: Georgia "O.C.G.A. 10-6-1" "apparent authority" defense attorney
BAD query example: Fannin county breach of contract lack of privity settlement Appalachian circuit superior court

Output ONLY a JSON array of 3 strings. No markdown, no explanation, just the array.

Example output:
["query one", "query two", "query three"]"""

HUNT_EVAL_PROMPT = """You are a senior legal talent scout AND case law researcher for a Fortune-500 holding company. You have been given raw search results from court docket databases and legal journalism outlets.

You have TWO tasks:

═══ TASK 1: ATTORNEY EXTRACTION ═══
Extract and evaluate attorneys who appear to have relevant expertise based on the search results.
For each qualified attorney found, provide:
- attorney_name: Full name
- firm: Law firm name (or "Solo Practitioner")
- email: Best available contact email (or "Not found — check firm website")
- phone: Phone if available (or "Not found")
- jurisdiction_match: true/false — do they practice in the target jurisdiction?
- specialty_match: true/false — does their track record match the required specialty?
- reason: 2-3 sentence explanation of WHY this attorney is recommended, citing the specific case or article found.

═══ TASK 2: PRECEDENT EXTRACTION (80% THRESHOLD) ═══
Analyze the scraped dockets and case law against our case brief. If you find a court case that supports our defense, score its relevance from 0-100.
ONLY return cases with a relevance_score of 80 or higher. This is a strict threshold — do NOT include anything below 80.
For each qualifying precedent, provide:
- citation: The formal legal citation (e.g., "Smith v. Jones, 305 Ga. 123 (2019)")
- url: The source URL where this case was found
- relevance_score: Integer 80-100 representing how directly applicable this precedent is to our defense
- justification: A 2-sentence explanation of why this case serves as strong precedent for our defense position, including what legal principle it establishes.

═══ OUTPUT FORMAT ═══
Output ONLY a single JSON object with two keys:
{{"attorneys": [...], "precedents": [...]}}

If no attorneys are found, set "attorneys" to [].
If no precedents score 80 or above, set "precedents" to [].
No markdown fences, no explanation outside the JSON.

Target Jurisdiction: {jurisdiction}
Required Specialty: {specialty}"""

# ── Models ────────────────────────────────────────────────────────────


class DispatchDraftRequest(BaseModel):
    case_brief: str = Field(..., min_length=10, max_length=100000)
    consensus: Optional[dict[str, Any]] = None


class DispatchDraftResponse(BaseModel):
    subject: str
    body: str
    model_used: str


class HuntRequest(BaseModel):
    case_brief: str = Field(..., min_length=10, max_length=100000)
    jurisdiction: str = Field(..., min_length=2, max_length=200)
    specialty: str = Field(..., min_length=2, max_length=500)


class AttorneyResult(BaseModel):
    attorney_name: str = ""
    firm: str = ""
    email: str = ""
    phone: str = ""
    jurisdiction_match: bool = False
    specialty_match: bool = False
    reason: str = ""


class PrecedentResult(BaseModel):
    citation: str = ""
    url: str = ""
    relevance_score: int = 0
    justification: str = ""


class HuntResponse(BaseModel):
    attorneys: list[AttorneyResult]
    precedents: list[PrecedentResult]
    search_queries: list[str]
    sources_searched: int
    model_used: str


# ── Shared LLM caller ────────────────────────────────────────────────


def _build_rfp_context(req: DispatchDraftRequest) -> str:
    parts = [f"=== CASE BRIEF ===\n{req.case_brief}"]

    if req.consensus:
        c = req.consensus
        signal = c.get("consensus_signal", "UNKNOWN")
        conviction = c.get("consensus_conviction", 0)
        defenses = c.get("top_defense_arguments", [])
        risks = c.get("top_risk_factors", [])

        ctx = f"=== INTERNAL ANALYSIS (summarise, do not quote) ===\nSignal: {signal} | Conviction: {conviction}\n"
        if defenses:
            ctx += "\nKey Defenses:\n" + "\n".join(f"  - {d}" for d in defenses)
        if risks:
            ctx += "\nRisk Factors:\n" + "\n".join(f"  - {r}" for r in risks)
        parts.append(ctx)

    return "\n\n".join(parts)


async def _call_llm_sync(
    system: str, user: str, *, temperature: float = 0.3, max_tokens: int = 4096
) -> tuple[str, str]:
    """Non-streaming LLM call with God Head fallback chain."""
    endpoints: list[tuple[str, str, str]] = []
    if ALLOW_CLOUD_LLM and ANTHROPIC_API_KEY:
        endpoints.append((ANTHROPIC_PROXY, ANTHROPIC_MODEL, ANTHROPIC_API_KEY))
    endpoints.append((HYDRA_URL, HYDRA_MODEL, ""))
    endpoints.append((SWARM_URL, SWARM_MODEL, ""))

    async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
        for base_url, model, api_key in endpoints:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            try:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                    if content:
                        return content, model
                logger.warning(
                    "counsel_dispatch_llm_non200",
                    url=base_url, model=model, status=resp.status_code,
                )
            except Exception as e:
                logger.warning(
                    "counsel_dispatch_llm_fail",
                    url=base_url, model=model, error=str(e)[:200],
                )

    return "", "none"


def _parse_email(raw: str) -> tuple[str, str]:
    """Extract Subject and Body from the LLM output."""
    subject = ""
    body = raw.strip()

    for line in raw.strip().splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("subject:"):
            subject = stripped[len("subject:"):].strip().strip("*").strip()
            body = raw[raw.index(line) + len(line):].strip()
            break

    if not subject:
        subject = "Limited Scope Representation Inquiry — Cabin Rentals of Georgia, LLC"

    return subject, body


# ── Web search helpers ────────────────────────────────────────────────

DOCKET_SITE_FILTER = "(site:justia.com OR site:caselaw.findlaw.com)"
JOURNALISM_SITE_FILTER = "(site:law.com OR site:law360.com OR site:reuters.com/legal)"


async def _serper_search(query: str, client: httpx.AsyncClient) -> list[dict[str, str]]:
    """Call Serper.dev Google Search API and return simplified results."""
    if not SERPER_API_KEY:
        return []
    try:
        resp = await client.post(
            "https://google.serper.dev/search",
            json={"q": query, "num": 10},
            headers={
                "X-API-KEY": SERPER_API_KEY,
                "Content-Type": "application/json",
            },
        )
        if resp.status_code != 200:
            logger.warning("serper_search_non200", status=resp.status_code, query=query[:80])
            return []
        data = resp.json()
        results = []
        for item in data.get("organic", []):
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "link": item.get("link", ""),
            })
        return results
    except Exception as e:
        logger.warning("serper_search_fail", error=str(e)[:200], query=query[:80])
        return []


async def _fallback_scrape(query: str, client: httpx.AsyncClient) -> list[dict[str, str]]:
    """DuckDuckGo HTML scrape as a zero-cost fallback when no Serper key."""
    try:
        encoded = quote_plus(query)
        resp = await client.get(
            f"https://html.duckduckgo.com/html/?q={encoded}",
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) FortressLegalBot/1.0"},
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return []

        text = resp.text
        results: list[dict[str, str]] = []
        snippets = re.findall(
            r'<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            text,
            re.DOTALL,
        )
        for link, title, snippet in snippets[:10]:
            clean_title = re.sub(r"<[^>]+>", "", title).strip()
            clean_snippet = re.sub(r"<[^>]+>", "", snippet).strip()
            results.append({"title": clean_title, "snippet": clean_snippet, "link": link})
        return results
    except Exception as e:
        logger.warning("duckduckgo_fallback_fail", error=str(e)[:200])
        return []


async def _search(query: str, client: httpx.AsyncClient) -> list[dict[str, str]]:
    """Route to Serper if key available, else fall back to DDG scrape."""
    if SERPER_API_KEY:
        return await _serper_search(query, client)
    return await _fallback_scrape(query, client)


def _extract_json_array(raw: str) -> list:
    """Robustly extract a JSON array from LLM output that may include markdown fences."""
    cleaned = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    bracket_match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if bracket_match:
        cleaned = bracket_match.group(0)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return []


def _extract_json_object(raw: str) -> dict:
    """Robustly extract a JSON object from LLM output that may include markdown fences."""
    cleaned = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if brace_match:
        cleaned = brace_match.group(0)
    try:
        result = json.loads(cleaned)
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        return {}


def _infer_case_slug(case_brief: str) -> str:
    """Extract a known case_slug from the brief text, defaulting to the active case."""
    slug_map = {
        "SUV2026000013": "fish-trap-suv2026000013",
        "fish-trap": "fish-trap-suv2026000013",
        "23-11161": "prime-trust-23-11161",
        "prime trust": "prime-trust-23-11161",
    }
    brief_upper = case_brief.upper()
    for keyword, slug in slug_map.items():
        if keyword.upper() in brief_upper:
            return slug
    return "fish-trap-suv2026000013"


# ── Endpoints ─────────────────────────────────────────────────────────


@router.post(
    "/counsel/dispatch/draft",
    response_model=DispatchDraftResponse,
    summary="Generate an outside-counsel RFP email draft",
)
async def generate_dispatch_draft(req: DispatchDraftRequest):
    context = _build_rfp_context(req)
    user_prompt = (
        f"Using the case information below, draft the outside counsel inquiry email.\n\n{context}"
    )

    logger.info(
        "counsel_dispatch_draft_request",
        brief_len=len(req.case_brief),
        has_consensus=bool(req.consensus),
    )

    raw_text, model_used = await _call_llm_sync(RFP_SYSTEM_PROMPT, user_prompt)

    if not raw_text:
        raise HTTPException(
            status_code=502,
            detail={
                "type": "https://fortress/errors/llm-unavailable",
                "title": "LLM Unavailable",
                "status": 502,
                "detail": "All LLM endpoints failed to generate the RFP draft.",
            },
        )

    subject, body = _parse_email(raw_text)

    logger.info(
        "counsel_dispatch_draft_complete",
        model=model_used,
        subject_len=len(subject),
        body_len=len(body),
    )

    return DispatchDraftResponse(subject=subject, body=body, model_used=model_used)


@router.post(
    "/counsel/dispatch/hunt",
    response_model=HuntResponse,
    summary="Dynamic multi-source attorney headhunter search",
)
async def hunt_outside_counsel(req: HuntRequest):
    """
    Phase 1: God Head generates 3 search queries from the case context.
    Phase 2: Execute each query against docket/caselaw AND legal journalism sites.
    Phase 3: God Head evaluates scraped results and returns ranked attorney list.
    """
    logger.info(
        "counsel_hunt_start",
        jurisdiction=req.jurisdiction,
        specialty=req.specialty,
        brief_len=len(req.case_brief),
    )

    # ── Phase 0: Semantic Pre-Retrieval (Episodic Memory) ─────────────
    memory_lessons = await _retrieve_memory_lessons(
        req.jurisdiction, req.specialty, top_k=3, score_threshold=0.40
    )

    memory_context = ""
    if memory_lessons:
        lines = ["═══ CEO PREFERENCE MEMORY (from past feedback) ═══"]
        for i, lesson in enumerate(memory_lessons, 1):
            sentiment_label = "APPROVED" if lesson["sentiment"] == "thumbs_up" else "REJECTED"
            lines.append(
                f"{i}. [{sentiment_label}] Attorney: {lesson['attorney_name']} | "
                f"Feedback: {lesson['feedback_notes']} "
                f"(jurisdiction: {lesson['jurisdiction']}, specialty: {lesson['specialty']}, "
                f"similarity: {lesson['score']})"
            )
        lines.append(
            "Use these lessons to EXCLUDE rejected patterns and PREFER approved patterns."
        )
        memory_context = "\n".join(lines)
        logger.info(
            "counsel_hunt_memory_injected",
            lesson_count=len(memory_lessons),
            top_score=memory_lessons[0]["score"],
        )

    # ── Phase 1: Generate search queries ──────────────────────────────
    query_user_parts = [
        f"Jurisdiction: {req.jurisdiction}",
        f"Required Specialty: {req.specialty}",
    ]
    if memory_context:
        query_user_parts.append(f"\n{memory_context}")
    query_user_parts.append(f"\nCase Brief (abbreviated):\n{req.case_brief[:3000]}")
    query_user = "\n".join(query_user_parts)

    raw_queries, qgen_model = await _call_llm_sync(
        HUNT_QUERY_GEN_PROMPT, query_user, temperature=0.4, max_tokens=1024
    )

    search_queries: list[str] = []
    if raw_queries:
        parsed = _extract_json_array(raw_queries)
        if isinstance(parsed, list):
            search_queries = [str(q) for q in parsed if isinstance(q, str)][:3]

    if not search_queries:
        search_queries = [
            f"{req.specialty} attorney {req.jurisdiction} verdict settlement",
            f'"{req.specialty}" lawyer {req.jurisdiction} case won',
            f"{req.jurisdiction} {req.specialty} litigation counsel",
        ]

    logger.info("counsel_hunt_queries_generated", queries=search_queries, model=qgen_model)

    # ── Phase 2: Execute multi-source searches ────────────────────────
    all_results: list[dict[str, str]] = []
    source_count = 0

    async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
        tasks = []
        for base_query in search_queries:
            tasks.append(_search(f"{base_query} {DOCKET_SITE_FILTER}", client))
            tasks.append(_search(f"{base_query} {JOURNALISM_SITE_FILTER}", client))

        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in batch_results:
            if isinstance(result, list):
                source_count += 1
                all_results.extend(result)

    logger.info("counsel_hunt_search_complete", total_results=len(all_results), sources=source_count)

    # ── Phase 3: Evaluate results with God Head (dual extraction) ────
    if not all_results:
        return HuntResponse(
            attorneys=[],
            precedents=[],
            search_queries=search_queries,
            sources_searched=source_count,
            model_used=qgen_model,
        )

    results_text = "\n\n".join(
        f"[{i+1}] {r.get('title', '')}\n{r.get('snippet', '')}\nURL: {r.get('link', '')}"
        for i, r in enumerate(all_results[:40])
    )

    eval_system = HUNT_EVAL_PROMPT.format(
        jurisdiction=req.jurisdiction,
        specialty=req.specialty,
    )
    eval_user_parts = [
        f"=== CASE BRIEF (abbreviated) ===\n{req.case_brief[:2000]}",
    ]
    if memory_context:
        eval_user_parts.append(f"\n{memory_context}")
    eval_user_parts.append(
        f"\n=== SEARCH RESULTS ({len(all_results)} total, showing top {min(40, len(all_results))}) ===\n{results_text}"
    )
    eval_user = "\n\n".join(eval_user_parts)

    raw_eval, eval_model = await _call_llm_sync(
        eval_system, eval_user, temperature=0.2, max_tokens=8192
    )

    attorneys: list[AttorneyResult] = []
    precedents: list[PrecedentResult] = []

    if raw_eval:
        parsed_obj = _extract_json_object(raw_eval)

        raw_attorneys = parsed_obj.get("attorneys", [])
        if not isinstance(raw_attorneys, list):
            raw_attorneys = _extract_json_array(raw_eval)

        for item in raw_attorneys:
            if isinstance(item, dict):
                try:
                    attorneys.append(AttorneyResult(
                        attorney_name=str(item.get("attorney_name", "")),
                        firm=str(item.get("firm", "")),
                        email=str(item.get("email", "")),
                        phone=str(item.get("phone", "")),
                        jurisdiction_match=bool(item.get("jurisdiction_match", False)),
                        specialty_match=bool(item.get("specialty_match", False)),
                        reason=str(item.get("reason", "")),
                    ))
                except Exception:
                    continue

        raw_precedents = parsed_obj.get("precedents", [])
        if isinstance(raw_precedents, list):
            for item in raw_precedents:
                if not isinstance(item, dict):
                    continue
                score = int(item.get("relevance_score", 0))
                if score < 80:
                    continue
                try:
                    precedents.append(PrecedentResult(
                        citation=str(item.get("citation", "")),
                        url=str(item.get("url", "")),
                        relevance_score=score,
                        justification=str(item.get("justification", "")),
                    ))
                except Exception:
                    continue

    # ── Phase 4: Persist precedents to legal.case_precedents ──────────
    case_slug = _infer_case_slug(req.case_brief)
    if precedents and case_slug:
        try:
            async with LegacySession() as session:
                for p in precedents:
                    await session.execute(
                        text("""
                            INSERT INTO legal.case_precedents
                                (case_slug, citation, url, relevance_score, justification)
                            VALUES (:slug, :citation, :url, :score, :justification)
                            ON CONFLICT DO NOTHING
                        """),
                        {
                            "slug": case_slug,
                            "citation": p.citation,
                            "url": p.url,
                            "score": p.relevance_score,
                            "justification": p.justification,
                        },
                    )
                await session.commit()
            logger.info(
                "counsel_hunt_precedents_saved",
                case_slug=case_slug,
                count=len(precedents),
            )
        except Exception as e:
            logger.warning(
                "counsel_hunt_precedents_save_failed",
                error=str(e)[:300],
                case_slug=case_slug,
            )

    logger.info(
        "counsel_hunt_complete",
        attorneys_found=len(attorneys),
        precedents_found=len(precedents),
        model=eval_model,
        sources=source_count,
    )

    return HuntResponse(
        attorneys=attorneys,
        precedents=precedents,
        search_queries=search_queries,
        sources_searched=source_count,
        model_used=eval_model,
    )


@router.get(
    "/counsel/dispatch/precedents/{case_slug}",
    summary="Get all saved precedents for a case (80+ relevance)",
)
async def get_case_precedents(case_slug: str):
    """Return all AI-discovered precedents for the given case, ordered by relevance."""
    try:
        async with LegacySession() as session:
            result = await session.execute(
                text("""
                    SELECT id, case_slug, citation, url, relevance_score, justification,
                           extracted_at
                    FROM legal.case_precedents
                    WHERE case_slug = :slug
                    ORDER BY relevance_score DESC, extracted_at DESC
                """),
                {"slug": case_slug},
            )
            rows = result.fetchall()
            precedents = []
            for row in rows:
                d = dict(row._mapping)
                if hasattr(d.get("extracted_at"), "isoformat"):
                    d["extracted_at"] = d["extracted_at"].isoformat()
                precedents.append(d)

            return {"case_slug": case_slug, "precedents": precedents, "count": len(precedents)}
    except Exception as e:
        logger.error("get_precedents_failed", case_slug=case_slug, error=str(e)[:300])
        raise HTTPException(
            status_code=500,
            detail={
                "type": "https://fortress/errors/database",
                "title": "Precedents Query Failed",
                "status": 500,
                "detail": "Failed to retrieve case precedents",
            },
        )


# ══════════════════════════════════════════════════════════════════════
# EPISODIC MEMORY — Feedback Loop (Qdrant + PostgreSQL Audit)
# ══════════════════════════════════════════════════════════════════════


class FeedbackRequest(BaseModel):
    case_slug: str = Field(..., min_length=1, max_length=200)
    item_type: str = Field(..., description="'attorney' or 'precedent'")
    item_name: str = Field(..., min_length=1, max_length=500, description="Attorney name or citation")
    sentiment: str = Field(..., pattern=r"^(thumbs_up|thumbs_down)$")
    jurisdiction: str = Field("", max_length=200)
    specialty: str = Field("", max_length=500)
    feedback_notes: str = Field("", max_length=5000)


class FeedbackResponse(BaseModel):
    status: str
    memory_id: str
    vectorized: bool
    pg_logged: bool


@router.post(
    "/counsel/dispatch/feedback",
    response_model=FeedbackResponse,
    summary="Submit episodic memory feedback (vectorized Qdrant + PG audit)",
)
async def submit_hunt_feedback(req: FeedbackRequest):
    """
    When the CEO submits a thumbs-up/down on a hunt result:
    1. Embed the combined [Jurisdiction] [Specialty] - [Feedback Notes] string
    2. Upsert into the legal_headhunter_memory Qdrant collection
    3. Write raw audit log to legal.headhunter_memory PostgreSQL table
    """
    memory_id = str(_uuid.uuid4())
    vectorized = False
    pg_logged = False

    embed_text = f"{req.jurisdiction} {req.specialty} - {req.feedback_notes}".strip()
    if not embed_text or embed_text == "-":
        embed_text = f"{req.jurisdiction} {req.specialty} {req.item_name}"

    logger.info(
        "headhunter_feedback_received",
        case_slug=req.case_slug,
        item_type=req.item_type,
        item_name=req.item_name[:80],
        sentiment=req.sentiment,
        embed_text_len=len(embed_text),
    )

    # ── Step 1: Vectorize and upsert to Qdrant ──────────────────────
    try:
        await ensure_memory_collection()
        vector = await _embed_text(embed_text)

        payload = {
            "case_slug": req.case_slug,
            "item_type": req.item_type,
            "attorney_name": req.item_name,
            "sentiment": req.sentiment,
            "jurisdiction": req.jurisdiction,
            "specialty": req.specialty,
            "feedback_notes": req.feedback_notes,
            "embed_text": embed_text,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        await _upsert_memory_vector(memory_id, vector, payload)
        vectorized = True
        logger.info(
            "headhunter_feedback_vectorized",
            memory_id=memory_id,
            collection=MEMORY_COLLECTION,
            vector_dim=len(vector),
        )
    except Exception as e:
        logger.error(
            "headhunter_feedback_vectorize_failed",
            memory_id=memory_id,
            error=str(e)[:300],
        )

    # ── Step 2: Audit log to PostgreSQL ──────────────────────────────
    try:
        async with LegacySession() as session:
            await session.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS legal.headhunter_memory (
                        id UUID PRIMARY KEY,
                        case_slug TEXT NOT NULL,
                        item_type TEXT NOT NULL,
                        item_name TEXT NOT NULL,
                        sentiment TEXT NOT NULL,
                        jurisdiction TEXT,
                        specialty TEXT,
                        feedback_notes TEXT,
                        embed_text TEXT,
                        vectorized BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """),
            )
            await session.execute(
                text("""
                    INSERT INTO legal.headhunter_memory
                        (id, case_slug, item_type, item_name, sentiment,
                         jurisdiction, specialty, feedback_notes, embed_text, vectorized)
                    VALUES (:id, :case_slug, :item_type, :item_name, :sentiment,
                            :jurisdiction, :specialty, :feedback_notes, :embed_text, :vectorized)
                """),
                {
                    "id": memory_id,
                    "case_slug": req.case_slug,
                    "item_type": req.item_type,
                    "item_name": req.item_name,
                    "sentiment": req.sentiment,
                    "jurisdiction": req.jurisdiction,
                    "specialty": req.specialty,
                    "feedback_notes": req.feedback_notes,
                    "embed_text": embed_text,
                    "vectorized": vectorized,
                },
            )
            await session.commit()
            pg_logged = True
            logger.info("headhunter_feedback_pg_logged", memory_id=memory_id)
    except Exception as e:
        logger.error(
            "headhunter_feedback_pg_failed",
            memory_id=memory_id,
            error=str(e)[:300],
        )

    if not vectorized and not pg_logged:
        raise HTTPException(
            status_code=502,
            detail={
                "type": "https://fortress/errors/memory-write-failed",
                "title": "Episodic Memory Write Failed",
                "status": 502,
                "detail": "Both Qdrant and PostgreSQL writes failed for feedback",
            },
        )

    return FeedbackResponse(
        status="ok",
        memory_id=memory_id,
        vectorized=vectorized,
        pg_logged=pg_logged,
    )


@router.get(
    "/counsel/dispatch/memory/{case_slug}",
    summary="Retrieve episodic memory entries for a case",
)
async def get_memory_entries(case_slug: str):
    """Return all feedback memory entries for audit/review."""
    try:
        async with LegacySession() as session:
            result = await session.execute(
                text("""
                    SELECT id, case_slug, item_type, item_name, sentiment,
                           jurisdiction, specialty, feedback_notes, vectorized, created_at
                    FROM legal.headhunter_memory
                    WHERE case_slug = :slug
                    ORDER BY created_at DESC
                """),
                {"slug": case_slug},
            )
            rows = result.fetchall()
            entries = []
            for row in rows:
                d = dict(row._mapping)
                d["id"] = str(d["id"])
                if hasattr(d.get("created_at"), "isoformat"):
                    d["created_at"] = d["created_at"].isoformat()
                entries.append(d)

            return {"case_slug": case_slug, "entries": entries, "count": len(entries)}
    except Exception as e:
        logger.error("get_memory_failed", case_slug=case_slug, error=str(e)[:300])
        raise HTTPException(
            status_code=500,
            detail={
                "type": "https://fortress/errors/database",
                "title": "Memory Query Failed",
                "status": 500,
                "detail": "Failed to retrieve episodic memory entries",
            },
        )
