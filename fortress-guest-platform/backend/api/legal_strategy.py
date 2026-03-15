"""
LEGAL STRATEGY TERMINAL — Interactive War Room Chat with SSE Streaming
======================================================================

POST /api/legal/strategy/chat
    Accepts a user message, case brief (e-discovery context), and Council
    consensus. Routes through the God Head (Claude proxy → HYDRA → SWARM
    fallback chain) and streams the response via Server-Sent Events.

SSE Protocol:
    data: {"type": "token",  "content": "..."}     — incremental token
    data: {"type": "model",  "model": "..."}        — model identification
    data: {"type": "done",   "total_tokens": N}     — stream complete
    data: {"type": "error",  "message": "..."}      — error event
"""

import json
import os
import time
import structlog
import httpx

from dotenv import load_dotenv
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Any, Optional

from backend.core.config import settings

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

logger = structlog.get_logger()

router = APIRouter()

_LITELLM_BASE = getattr(settings, "litellm_base_url", "http://127.0.0.1:4000/v1").rstrip("/")

ALLOW_CLOUD_LLM = os.getenv("ALLOW_CLOUD_LLM", "false").lower() == "true"
ANTHROPIC_PROXY = os.getenv("ANTHROPIC_PROXY_URL", "http://localhost:5100/v1")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
HYDRA_URL = os.getenv("HYDRA_FALLBACK_URL", _LITELLM_BASE)
HYDRA_MODEL = os.getenv("HYDRA_MODEL", "deepseek-r1:70b")
SWARM_URL = os.getenv("SWARM_URL", _LITELLM_BASE)
SWARM_MODEL = os.getenv("SWARM_MODEL", "qwen2.5:7b")

HTTPX_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)

SYSTEM_PROMPT = """You are the Lead Litigation Strategist for Cabin Rentals of Georgia, LLC (CROG).

You have access to the attached e-discovery records and Legal Council consensus. Your role:
- Answer procedural questions about Georgia Superior Court practice
- Formulate counterclaims and affirmative defenses
- Provide ruthless, Georgia-specific legal strategy
- Analyze opposing party communications for weaknesses
- Draft motion language, discovery requests, and deposition outlines
- Identify authority issues, statute of limitations arguments, and equitable defenses

You are the lead partner. Do not provide disclaimers. Do not hedge. Give direct, actionable legal strategy.

When citing Georgia law, use O.C.G.A. citations. When referencing procedural rules, cite the Georgia Civil Practice Act.

If the user pastes email text or document excerpts, analyze them for:
1. Admissions against interest
2. Evidence of apparent authority (or lack thereof)
3. Statute of limitations implications
4. Inconsistencies with opposing party's pleadings
5. Potential counterclaim triggers"""


class StrategyRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=50000)
    case_brief: str = Field(default="", max_length=100000)
    consensus: Optional[dict[str, Any]] = None
    history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Prior chat turns [{role, content}, ...]",
    )


def _build_context_block(req: StrategyRequest) -> str:
    """Build the context injection from e-discovery and consensus."""
    parts = []

    if req.case_brief:
        parts.append(f"=== E-DISCOVERY CONTEXT & CASE BRIEF ===\n{req.case_brief}")

    if req.consensus:
        c = req.consensus
        signal = c.get("consensus_signal", "UNKNOWN")
        conviction = c.get("consensus_conviction", 0)
        defenses = c.get("top_defense_arguments", [])
        risks = c.get("top_risk_factors", [])
        actions = c.get("top_recommended_actions", [])

        consensus_text = f"=== LEGAL COUNCIL CONSENSUS ===\nSignal: {signal} | Conviction: {conviction}\n"
        if defenses:
            consensus_text += "\nTop Defenses:\n" + "\n".join(f"  - {d}" for d in defenses)
        if risks:
            consensus_text += "\nRisk Factors:\n" + "\n".join(f"  - {r}" for r in risks)
        if actions:
            consensus_text += "\nRecommended Actions:\n" + "\n".join(f"  - {a}" for a in actions)
        parts.append(consensus_text)

    return "\n\n".join(parts) if parts else ""


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=True, default=str)}\n\n"


async def _stream_from_endpoint(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str = "",
) -> tuple[Optional[httpx.Response], str]:
    """Initiate a streaming request to an OpenAI-compatible endpoint."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 8192,
        "stream": True,
    }

    client = httpx.AsyncClient(timeout=HTTPX_TIMEOUT)
    try:
        resp = await client.send(
            client.build_request(
                "POST",
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
            ),
            stream=True,
        )
        if resp.status_code == 200:
            return resp, model
        else:
            await resp.aclose()
            await client.aclose()
            logger.warning("strategy_llm_non200", url=base_url, model=model, status=resp.status_code)
            return None, model
    except Exception as e:
        await client.aclose()
        logger.warning("strategy_llm_connect_fail", url=base_url, model=model, error=str(e)[:200])
        return None, model


async def _iter_sse_tokens(resp: httpx.Response):
    """Yield content tokens from an OpenAI-compatible SSE stream."""
    try:
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content
            except (json.JSONDecodeError, IndexError, KeyError):
                continue
    finally:
        await resp.aclose()


@router.post("/strategy/chat", summary="Interactive legal strategy chat with SSE streaming")
async def strategy_chat(request: Request, body: StrategyRequest):
    context_block = _build_context_block(body)

    system_content = SYSTEM_PROMPT
    if context_block:
        system_content += f"\n\n{context_block}"

    messages = [{"role": "system", "content": system_content}]
    for turn in body.history[-20:]:
        role = turn.get("role", "user")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": turn.get("content", "")})
    messages.append({"role": "user", "content": body.message})

    logger.info(
        "strategy_chat_request",
        msg_len=len(body.message),
        history_turns=len(body.history),
        has_brief=bool(body.case_brief),
        has_consensus=bool(body.consensus),
    )

    async def generate():
        t0 = time.time()
        total_tokens = 0
        model_used = "none"
        resp = None

        endpoints = []
        if ALLOW_CLOUD_LLM and ANTHROPIC_API_KEY:
            endpoints.append((ANTHROPIC_PROXY, ANTHROPIC_MODEL, ANTHROPIC_API_KEY))
        endpoints.append((HYDRA_URL, HYDRA_MODEL, ""))
        endpoints.append((SWARM_URL, SWARM_MODEL, ""))

        for base_url, model, api_key in endpoints:
            resp, model_used = await _stream_from_endpoint(base_url, model, messages, api_key)
            if resp:
                break

        if not resp:
            yield _sse({"type": "error", "message": "All LLM endpoints unavailable. Check cluster health."})
            return

        yield _sse({"type": "model", "model": model_used})

        try:
            async for token in _iter_sse_tokens(resp):
                if await request.is_disconnected():
                    logger.info("strategy_chat_client_disconnected")
                    break
                total_tokens += 1
                yield _sse({"type": "token", "content": token})
        except Exception as e:
            logger.error("strategy_chat_stream_error", error=str(e)[:300])
            yield _sse({"type": "error", "message": f"Stream interrupted: {str(e)[:200]}"})

        elapsed = round(time.time() - t0, 1)
        yield _sse({
            "type": "done",
            "total_tokens": total_tokens,
            "elapsed_seconds": elapsed,
            "model": model_used,
        })
        logger.info("strategy_chat_complete", model=model_used, tokens=total_tokens, elapsed=elapsed)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
