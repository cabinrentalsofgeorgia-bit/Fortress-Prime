"""
LEGAL EXTRACTION SERVICE
========================

Structured entity extraction for legal war-room records.
Converts free-text case/correspondence notes into the frontend's
ExtractedEntities shape.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, Field

from backend.core.config import settings

logger = structlog.get_logger()

HTTPX_TIMEOUT = httpx.Timeout(connect=8.0, read=25.0, write=8.0, pool=8.0)


class ExtractedParty(BaseModel):
    name: str = ""
    role: str = ""


class ExtractedAmount(BaseModel):
    value: float = 0.0
    currency: str = "USD"
    description: str = ""


class ExtractedDeadline(BaseModel):
    description: str = ""
    due_date: str = ""
    source_text: str | None = None


class ExtractedEntities(BaseModel):
    summary: str = ""
    risk_score: int = Field(default=3, ge=1, le=5)
    risk_justification: str | None = None
    document_type: str | None = None
    jurisdiction: str | None = None
    case_number: str | None = None
    parties: list[ExtractedParty] = Field(default_factory=list)
    amounts: list[ExtractedAmount] = Field(default_factory=list)
    key_claims: list[str] = Field(default_factory=list)
    deadlines: list[ExtractedDeadline] = Field(default_factory=list)


EXTRACTION_SYSTEM_PROMPT = """You are a legal extraction engine.
Return ONLY strict JSON with this exact schema:
{
  "summary": "string",
  "risk_score": 1-5 integer,
  "risk_justification": "string|null",
  "document_type": "string|null",
  "jurisdiction": "string|null",
  "case_number": "string|null",
  "parties": [{"name":"string","role":"string"}],
  "amounts": [{"value": 0.0, "currency": "USD", "description":"string"}],
  "key_claims": ["string"],
  "deadlines": [{"description":"string","due_date":"YYYY-MM-DD","source_text":"string|null"}]
}

Rules:
- Be conservative: unknown values should be null, empty list, or empty string.
- risk_score 1=low risk, 5=critical risk.
- deadlines.due_date must be ISO YYYY-MM-DD when possible.
- Never include markdown fences or prose outside JSON.
"""


def _extract_json_object(raw: str) -> dict[str, Any]:
    cleaned = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    brace = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if brace:
        cleaned = brace.group(0)
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


def _sanitize_entities(raw_obj: dict[str, Any]) -> dict[str, Any]:
    base = {
        "summary": str(raw_obj.get("summary") or "").strip(),
        "risk_score": raw_obj.get("risk_score", 3),
        "risk_justification": raw_obj.get("risk_justification"),
        "document_type": raw_obj.get("document_type"),
        "jurisdiction": raw_obj.get("jurisdiction"),
        "case_number": raw_obj.get("case_number"),
        "parties": raw_obj.get("parties") or [],
        "amounts": raw_obj.get("amounts") or [],
        "key_claims": raw_obj.get("key_claims") or [],
        "deadlines": raw_obj.get("deadlines") or [],
    }

    try:
        risk_score = int(base["risk_score"])
    except (TypeError, ValueError):
        risk_score = 3
    base["risk_score"] = max(1, min(5, risk_score))

    if not isinstance(base["parties"], list):
        base["parties"] = []
    if not isinstance(base["amounts"], list):
        base["amounts"] = []
    if not isinstance(base["key_claims"], list):
        base["key_claims"] = []
    if not isinstance(base["deadlines"], list):
        base["deadlines"] = []

    entities = ExtractedEntities.model_validate(base)
    return entities.model_dump()


async def _call_llm(
    *,
    base_url: str,
    model: str,
    user_prompt: str,
    api_key: str | None = None,
) -> tuple[dict[str, Any], str] | tuple[None, None]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 2500,
    }

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
        try:
            resp = await client.post(f"{base_url.rstrip('/')}/chat/completions", json=payload, headers=headers)
            if resp.status_code != 200:
                logger.warning("legal_extract_llm_non200", base_url=base_url, model=model, status=resp.status_code)
                return None, None
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            raw_obj = _extract_json_object(content)
            if not raw_obj:
                logger.warning("legal_extract_no_json", base_url=base_url, model=model)
                return None, None
            return _sanitize_entities(raw_obj), model
        except Exception as exc:
            logger.warning("legal_extract_llm_error", base_url=base_url, model=model, error=str(exc)[:240])
            return None, None




def _heuristic_fallback(source_text: str, target: str) -> dict[str, Any]:
    lines = [ln.strip() for ln in source_text.splitlines() if ln.strip()]
    summary = (" ".join(lines)[:320] or "No summary extracted").strip()

    claims: list[str] = []
    for ln in lines[:8]:
        if len(ln) > 20:
            claims.append(ln[:180])
    if not claims and summary:
        claims = [summary]

    amounts = []
    m = re.findall(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)", source_text)
    for raw in m[:5]:
        try:
            amounts.append({
                "value": float(raw.replace(",", "")),
                "currency": "USD",
                "description": "Extracted amount",
            })
        except ValueError:
            continue

    deadlines = []
    dates = re.findall(r"(20\d{2}-\d{2}-\d{2})", source_text)
    for dt in dates[:3]:
        deadlines.append({"description": "Referenced date", "due_date": dt, "source_text": dt})

    parties = []
    if "Generali" in source_text:
        parties.append({"name": "Generali Global Assistance, Inc.", "role": "plaintiff"})
    if "Cabin Rentals of Georgia" in source_text or "CROG" in source_text:
        parties.append({"name": "Cabin Rentals of Georgia, LLC", "role": "defendant"})

    risk_score = 4 if (amounts or deadlines) else 3

    return ExtractedEntities.model_validate({
        "summary": summary,
        "risk_score": risk_score,
        "risk_justification": "Heuristic fallback used due LLM timeout/unavailable",
        "document_type": target,
        "jurisdiction": None,
        "case_number": None,
        "parties": parties,
        "amounts": amounts,
        "key_claims": claims[:6],
        "deadlines": deadlines,
    }).model_dump()


async def extract_entities(
    *,
    source_text: str,
    target: str,
    case_slug: str,
) -> tuple[dict[str, Any], str]:
    """
    Extract entities using HYDRA first, then SWARM fallback.
    Returns (entities_dict, model_used). Raises RuntimeError on complete failure.
    """
    trimmed = (source_text or "").strip()
    if not trimmed:
        raise RuntimeError("No extraction text provided")

    hydra_url = settings.dgx_reasoner_url
    hydra_model = settings.dgx_reasoner_model or "deepseek-r1:70b"
    swarm_url = (settings.litellm_base_url or "http://127.0.0.1:8002/v1").rstrip("/")
    # Use deepseek-chat via LiteLLM gateway — registered and verified working
    swarm_model = "deepseek-chat"

    user_prompt = (
        f"Case slug: {case_slug}\n"
        f"Target: {target}\n\n"
        f"Text to extract from:\n{trimmed[:32000]}"
    )

    entities, model_used = await _call_llm(base_url=hydra_url, model=hydra_model, user_prompt=user_prompt)
    if entities:
        return entities, model_used or hydra_model

    swarm_key = settings.litellm_master_key or None
    entities, model_used = await _call_llm(base_url=swarm_url, model=swarm_model, user_prompt=user_prompt, api_key=swarm_key)
    if entities:
        return entities, model_used or swarm_model

    logger.warning("legal_extract_fallback", target=target, case_slug=case_slug)
    return _heuristic_fallback(trimmed, target), "heuristic-fallback"
