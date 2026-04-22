"""
FORTRESS PRIME — CROG CONCIERGE ENGINE (Division 1)
====================================================
9-seat adversarial deliberation for guest communications, modeled on Legal Council.

Phase one: triage + drafted reply only — no booking mutations or outbound sends.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

import httpx
from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

_project_root = Path(__file__).resolve().parent.parent.parent.parent
_fgp_root = Path(__file__).resolve().parent.parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(_fgp_root / ".env", override=False)
    load_dotenv(_project_root / ".env", override=False)
except ImportError:
    pass

from backend.core.config import settings as _cfg
from backend.models import Guest, Message, Property, PropertyKnowledge, Reservation, WorkOrder
from backend.services.message_service import MessageService

logger = logging.getLogger("crog_concierge_engine")

# Personas (hospitality roster)
CONCIERGE_PERSONAS_DIR = os.getenv(
    "CONCIERGE_PERSONAS_DIR",
    str(_project_root / "personas" / "concierge"),
)
CONCIERGE_ALLOWED_VECTOR_COLLECTIONS = frozenset({"fgp_knowledge"})

_LITELLM_BASE = getattr(_cfg, "litellm_base_url", "http://127.0.0.1:4000/v1").rstrip("/")
_LITELLM_KEY = getattr(_cfg, "litellm_master_key", "")

ANTHROPIC_PROXY = os.getenv("ANTHROPIC_PROXY_URL", _LITELLM_BASE).rstrip("/")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", _LITELLM_BASE).rstrip("/")
XAI_BASE_URL = os.getenv("XAI_BASE_URL", _LITELLM_BASE).rstrip("/")
HYDRA_URL = os.getenv("HYDRA_FALLBACK_URL", _LITELLM_BASE).rstrip("/")
SWARM_URL = os.getenv("SWARM_URL", _LITELLM_BASE).rstrip("/")
HYDRA_32B_URL = os.getenv("HYDRA_32B_URL", "http://192.168.0.105:11434/v1").rstrip("/")
HYDRA_120B_URL = os.getenv("HYDRA_120B_URL", "http://192.168.0.106:11434/v1").rstrip("/")
VLLM_120B_URL = os.getenv("VLLM_120B_URL", "http://192.168.0.106:8000/v1").rstrip("/")

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")  # matches litellm_config.yaml
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-4")          # litellm_config.yaml registers grok-4; grok-3 not registered
XAI_MODEL_FLAGSHIP = os.getenv("XAI_MODEL_FLAGSHIP", "grok-4")  # grok-4-0709 not in config
VLLM_MODEL_120B = os.getenv("VLLM_MODEL_120B", "openai/gpt-oss-120b")
HYDRA_MODEL_32B = os.getenv("HYDRA_MODEL_32B", "qwen2.5:32b")  # qwen3:32b not loaded; qwen2.5:32b on spark-1+spark-4
HYDRA_MODEL_120B = os.getenv("HYDRA_MODEL_120B", "gpt-oss:120b")
SWARM_MODEL = os.getenv("SWARM_MODEL", "qwen2.5:7b")
HYDRA_MODEL = HYDRA_MODEL_120B

# Deployment A — Nemotron NIM for VRS concierge (spark-4 :8100)
# Falls back to HYDRA_120B_URL/qwen2.5:7b if NIM is unavailable
VRS_NIM_URL = os.getenv("VRS_NIM_URL", "http://192.168.0.106:8100/v1").rstrip("/")
VRS_NIM_MODEL = os.getenv("VRS_NIM_MODEL", "nvidia/nvidia-nemotron-nano-9b-v2")

ALLOW_CLOUD_LLM = os.getenv("ALLOW_CLOUD_LLM", "false").lower() == "true"
FRONTIER_GATEWAY_API_KEY = os.getenv("LITELLM_MASTER_KEY", _LITELLM_KEY)

# Same MoE routing map as Legal Council — roles are hospitality in persona JSON
SEAT_ROUTING: Dict[int, Dict[str, str]] = {
    1: {"provider": "ANTHROPIC", "role": "Guest Experience Lead"},
    2: {"provider": "ANTHROPIC", "role": "Booking & Revenue Integrity"},
    3: {"provider": "GEMINI", "role": "Housekeeping & Turn Standards"},
    4: {"provider": "HYDRA_32B", "role": "Maintenance & Safety"},
    5: {"provider": "XAI", "role": "Guest Advocate (Skeptic)"},
    6: {"provider": "HYDRA_32B", "role": "Policy & Compliance"},
    7: {"provider": "VLLM_120B", "role": "Field Ops Reality"},
    8: {"provider": "GEMINI", "role": "Reputation & Review Risk"},
    9: {"provider": "XAI_FLAGSHIP", "role": "Concierge Director"},
}

SEAT_RETRY_FALLBACKS: Dict[int, List[str]] = {
    1: ["ANTHROPIC", "GEMINI", "HYDRA_32B"],
    2: ["ANTHROPIC", "GEMINI", "HYDRA_32B"],
    7: ["VLLM_120B", "HYDRA_32B", "SWARM"],
    9: ["XAI_FLAGSHIP", "GEMINI", "HYDRA_32B"],
}

_LLM_SEMAPHORE = asyncio.Semaphore(9)
PERSONA_TIMEOUT_SECONDS = int(os.getenv("CONCIERGE_PERSONA_TIMEOUT_SECONDS", "180"))
HTTPX_TIMEOUT = httpx.Timeout(connect=60.0, read=float(PERSONA_TIMEOUT_SECONDS), write=10.0, pool=10.0)
HTTPX_FALLBACK_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)

_OLLAMA_ENDPOINTS = {HYDRA_32B_URL, HYDRA_120B_URL, HYDRA_URL, SWARM_URL}
_OLLAMA_CTX_LIMITS: dict[str, int] = {
    HYDRA_120B_URL: 8192,
    HYDRA_32B_URL: 16384,
}
_OLLAMA_CTX_DEFAULT = 8192
_CLOUD_PROVIDERS = {"ANTHROPIC", "GEMINI", "XAI", "XAI_FLAGSHIP"}

_REASONING_MODELS = {"qwen3:32b", "gpt-oss:120b", "gpt-oss", "deepseek-r1:70b", "openai/gpt-oss-120b"}

_PII_PATTERNS = [
    (re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"), "[PHONE_REDACTED]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[EMAIL_REDACTED]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN_REDACTED]"),
    (re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), "[CARD_REDACTED]"),
]


def _sanitize_for_cloud(text: str) -> str:
    result = text
    for pattern, replacement in _PII_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


class ConciergeSignal(str, Enum):
    STRONG_RESOLUTION = "STRONG_RESOLUTION"
    RESOLVE = "RESOLVE"
    NEUTRAL = "NEUTRAL"
    CAUTION = "CAUTION"
    CRITICAL_RISK = "CRITICAL_RISK"
    ERROR = "ERROR"


SIGNAL_WEIGHTS = {
    ConciergeSignal.STRONG_RESOLUTION: 1.0,
    ConciergeSignal.RESOLVE: 0.5,
    ConciergeSignal.NEUTRAL: 0.0,
    ConciergeSignal.CAUTION: -0.5,
    ConciergeSignal.CRITICAL_RISK: -1.0,
    ConciergeSignal.ERROR: 0.0,
}

VALID_DEPARTMENTS = frozenset({"guest", "housekeeping", "maintenance", "booking"})


@dataclass
class ConciergeOpinion:
    persona_name: str
    seat: int
    slug: str
    event: str
    signal: ConciergeSignal
    conviction: float
    reasoning: str
    operational_arguments: List[str]
    risk_factors: List[str]
    recommended_actions: List[str]
    departments: List[str]
    timestamp: str
    model_used: str = ""
    elapsed_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "persona": self.persona_name,
            "seat": self.seat,
            "slug": self.slug,
            "signal": self.signal.value,
            "conviction": self.conviction,
            "reasoning": self.reasoning,
            "operational_arguments": self.operational_arguments,
            "risk_factors": self.risk_factors,
            "recommended_actions": self.recommended_actions,
            "departments": self.departments,
            "timestamp": self.timestamp,
            "model_used": self.model_used,
            "elapsed_seconds": self.elapsed_seconds,
        }


@dataclass
class ConciergePersona:
    name: str
    slug: str
    seat: int
    archetype: str
    domain: str
    god_head_domain: str
    worldview: str
    bias: List[str]
    focus_areas: List[str]
    trigger_events: List[str]
    godhead_prompt: str
    vector_collection: str
    created_at: str = ""

    @classmethod
    def load(cls, filepath: str) -> ConciergePersona:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        vector_collection = data.get("vector_collection", "fgp_knowledge")
        _validate_concierge_persona_boundary(
            slug=data.get("slug", os.path.basename(filepath)),
            vector_collection=vector_collection,
        )
        return cls(
            name=data["name"],
            slug=data["slug"],
            seat=int(data.get("seat", 0)),
            archetype=data.get("archetype", ""),
            domain=data.get("domain", "hospitality"),
            god_head_domain=data.get("god_head_domain", "hospitality"),
            worldview=data.get("worldview", ""),
            bias=data.get("bias", []),
            focus_areas=data.get("focus_areas", []),
            trigger_events=data.get("trigger_events", []),
            godhead_prompt=data.get("godhead_prompt", ""),
            vector_collection=vector_collection,
            created_at=data.get("created_at", ""),
        )

    @classmethod
    def load_all(cls) -> List[ConciergePersona]:
        directory = CONCIERGE_PERSONAS_DIR
        if not os.path.isdir(directory):
            logger.warning("concierge_personas_missing_dir path=%s", directory)
            return []
        personas: List[ConciergePersona] = []
        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".json"):
                continue
            try:
                personas.append(cls.load(os.path.join(directory, fname)))
            except ConciergePersonaBoundaryError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning("concierge_persona_load_failed file=%s err=%s", fname, e)
        personas.sort(key=lambda p: p.seat)
        return personas


class ConciergePersonaBoundaryError(RuntimeError):
    """Raised when hospitality personas attempt to cross the legal boundary."""


def _validate_concierge_persona_boundary(*, slug: str, vector_collection: str) -> None:
    if vector_collection not in CONCIERGE_ALLOWED_VECTOR_COLLECTIONS:
        raise ConciergePersonaBoundaryError(
            f"Concierge persona '{slug}' attempted to access forbidden vector collection '{vector_collection}'."
        )


def _extract_content(data: dict) -> str:
    msg = data.get("choices", [{}])[0].get("message", {})
    content = msg.get("content", "") or ""
    if content.strip():
        return content
    reasoning = msg.get("reasoning", "") or msg.get("reasoning_content", "") or ""
    if reasoning.strip():
        return reasoning
    return ""


async def _call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = "",
    base_url: str = "",
    api_key: str = "",
    temperature: float = 0.35,
    max_tokens: int = 2048,
) -> Tuple[str, str]:
    if not model:
        model = ANTHROPIC_MODEL
    if not base_url:
        base_url = ANTHROPIC_PROXY

    async with _LLM_SEMAPHORE:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
            try:
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                effective_user = user_prompt
                is_ollama = base_url in _OLLAMA_ENDPOINTS
                is_vllm = base_url == VLLM_120B_URL
                is_local_reasoning = model in _REASONING_MODELS and (is_ollama or is_vllm)
                if is_local_reasoning:
                    effective_user = f"/no_think\n{user_prompt}"

                payload: dict[str, Any] = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": effective_user},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if is_ollama:
                    ctx = _OLLAMA_CTX_LIMITS.get(base_url, _OLLAMA_CTX_DEFAULT)
                    payload["options"] = {"num_ctx": ctx}
                if is_vllm:
                    payload["response_format"] = {"type": "json_object"}
                    payload.pop("max_tokens", None)

                resp = await client.post(
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = _extract_content(data)
                    if content:
                        return content, model
                logger.warning(
                    "concierge_llm_primary_failed model=%s url=%s status=%s",
                    model,
                    base_url,
                    resp.status_code,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("concierge_llm_primary_error %s", e)

            if base_url not in (HYDRA_120B_URL, VLLM_120B_URL):
                try:
                    fb_user = f"/no_think\n{user_prompt}" if HYDRA_MODEL_120B in _REASONING_MODELS else user_prompt
                    fb_payload: dict[str, Any] = {
                        "model": HYDRA_MODEL_120B,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": fb_user},
                        ],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "options": {"num_ctx": _OLLAMA_CTX_LIMITS.get(HYDRA_120B_URL, 8192)},
                    }
                    async with httpx.AsyncClient(timeout=HTTPX_FALLBACK_TIMEOUT) as fb_client:
                        resp = await fb_client.post(
                            f"{HYDRA_120B_URL}/chat/completions",
                            json=fb_payload,
                        )
                        if resp.status_code == 200:
                            content = _extract_content(resp.json())
                            if content:
                                return content, f"HYDRA_120B ({HYDRA_MODEL_120B})"
                except Exception as e:  # noqa: BLE001
                    logger.error("concierge_hydra_fallback_failed %s", e)

            try:
                sw_payload: dict[str, Any] = {
                    "model": SWARM_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "options": {"num_ctx": _OLLAMA_CTX_DEFAULT},
                }
                async with httpx.AsyncClient(timeout=HTTPX_FALLBACK_TIMEOUT) as sw_client:
                    resp = await sw_client.post(
                        f"{SWARM_URL}/chat/completions",
                        json=sw_payload,
                    )
                    if resp.status_code == 200:
                        content = _extract_content(resp.json())
                        if content:
                            return content, f"SWARM ({SWARM_MODEL})"
            except Exception as e:  # noqa: BLE001
                logger.error("concierge_swarm_fallback_failed %s", e)

    return "", "none"


def _extract_json_block(raw: str) -> dict:
    cleaned = raw.strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in response")
    cleaned = cleaned[start : end + 1]
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return json.loads(cleaned)


def _sanitize_str(val: str, max_len: int = 5000) -> str:
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", val)
    return s[:max_len] if len(s) > max_len else s


def _sanitize_str_list(items: Any, max_items: int = 20) -> List[str]:
    if not isinstance(items, list):
        return []
    return [_sanitize_str(str(x), 1000) for x in items[:max_items] if x]


def _parse_departments(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for x in raw[:12]:
        d = str(x).strip().lower()
        if d in VALID_DEPARTMENTS:
            out.append(d)
    return list(dict.fromkeys(out))


def _coerce_signal(raw: str | None) -> ConciergeSignal:
    token = str(raw or "").strip().upper().replace(" ", "_").replace("-", "_")
    alias_map = {
        "STRONG_RESOLVE": ConciergeSignal.STRONG_RESOLUTION,
        "STRONG_COMPENSATE": ConciergeSignal.STRONG_RESOLUTION,
        "COMPENSATE": ConciergeSignal.STRONG_RESOLUTION,
        "DENY": ConciergeSignal.CAUTION,
        "CRITICAL": ConciergeSignal.CRITICAL_RISK,
        "RISK": ConciergeSignal.CRITICAL_RISK,
    }
    if token in ConciergeSignal.__members__:
        return ConciergeSignal[token]
    return alias_map.get(token, ConciergeSignal.NEUTRAL)


def _extract_labeled_value(raw_text: str, labels: list[str]) -> str | None:
    joined = "|".join(labels)
    pattern = re.compile(
        rf"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?(?:{joined})(?:\*\*)?\s*[:=-]\s*(.+?)\s*$"
    )
    match = pattern.search(raw_text)
    if not match:
        return None
    return match.group(1).strip()


def _extract_labeled_block(raw_text: str, labels: list[str]) -> list[str]:
    joined = "|".join(labels)
    heading_pattern = re.compile(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?([a-z _-]+?)(?:\*\*)?\s*[:=-]\s*(.*)$")
    target_pattern = re.compile(
        rf"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?(?:{joined})(?:\*\*)?\s*[:=-]\s*(.*)$"
    )
    lines = raw_text.splitlines()
    collecting = False
    collected: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not collecting:
            target = target_pattern.match(line)
            if not target:
                continue
            collecting = True
            if target.group(1).strip():
                collected.append(target.group(1).strip())
            continue

        if (":" in stripped or "=" in stripped) and heading_pattern.match(line):
            break
        if not stripped:
            if collected:
                break
            continue
        bullet = re.sub(r"^\s*[-*•]\s*", "", stripped).strip()
        if bullet:
            collected.append(bullet)

    return [item for item in collected if item]


def _extract_conviction_from_text(raw_text: str) -> float | None:
    value = _extract_labeled_value(raw_text, ["conviction", "confidence"])
    if not value:
        return None
    number_match = re.search(r"(\d+(?:\.\d+)?)", value)
    if not number_match:
        return None
    number = float(number_match.group(1))
    if "%" in value or number > 1.0:
        number = number / 100.0
    return min(max(number, 0.0), 1.0)


def _parse_loose_opinion(
    persona: ConciergePersona,
    event: str,
    raw_text: str,
    model_used: str,
    elapsed: float,
) -> ConciergeOpinion | None:
    cleaned = _sanitize_str(raw_text.strip())
    if not cleaned:
        return ConciergeOpinion(
            persona_name=persona.name,
            seat=persona.seat,
            slug=persona.slug,
            event=event,
            signal=ConciergeSignal.NEUTRAL,
            conviction=0.5,
            reasoning="Seat returned a blank response.",
            operational_arguments=[],
            risk_factors=["Seat response was empty — manual review suggested"],
            recommended_actions=["Retry guest triage or check LLM endpoint health"],
            departments=[],
            timestamp=datetime.now().isoformat(),
            model_used=model_used,
            elapsed_seconds=round(elapsed, 1),
        )
    cleaned = cleaned.replace("**", "")

    signal = _coerce_signal(_extract_labeled_value(cleaned, ["signal", "stance", "verdict"]))
    conviction = _extract_conviction_from_text(cleaned) or 0.5
    reasoning = _extract_labeled_value(cleaned, ["reasoning", "analysis", "rationale"])
    operational_arguments = _extract_labeled_block(cleaned, ["operational arguments?", "arguments?"])
    risk_factors = _extract_labeled_block(cleaned, ["risk factors?", "risks?"])
    recommended_actions = _extract_labeled_block(cleaned, ["recommended actions?", "actions?", "next steps?"])
    department_values = _extract_labeled_block(cleaned, ["departments?", "implicated departments?"])
    if department_values:
        expanded_departments: list[str] = []
        for item in department_values:
            expanded_departments.extend(part.strip() for part in re.split(r"[,/]", item) if part.strip())
        departments = _parse_departments(expanded_departments)
    else:
        departments = _parse_departments(
            re.split(r"[,/]", _extract_labeled_value(cleaned, ["departments?", "implicated departments?"]) or "")
        )

    if not any([reasoning, operational_arguments, risk_factors, recommended_actions, departments]) and signal == ConciergeSignal.NEUTRAL:
        return None

    if not reasoning:
        reasoning = cleaned[:800]

    return ConciergeOpinion(
        persona_name=persona.name,
        seat=persona.seat,
        slug=persona.slug,
        event=event,
        signal=signal,
        conviction=conviction,
        reasoning=_sanitize_str(reasoning),
        operational_arguments=_sanitize_str_list(operational_arguments),
        risk_factors=_sanitize_str_list(risk_factors),
        recommended_actions=_sanitize_str_list(recommended_actions),
        departments=departments,
        timestamp=datetime.now().isoformat(),
        model_used=model_used,
        elapsed_seconds=round(elapsed, 1),
    )


def _provider_attempt_sequence(primary_provider: str, seat: int) -> List[str]:
    providers = list(SEAT_RETRY_FALLBACKS.get(seat, [primary_provider, "HYDRA_32B", "SWARM"]))
    if primary_provider not in providers:
        providers.insert(0, primary_provider)
    return list(dict.fromkeys(providers))


def _parse_opinion(
    persona: ConciergePersona,
    event: str,
    raw_text: str,
    model_used: str,
    elapsed: float,
) -> ConciergeOpinion:
    try:
        data = _extract_json_block(raw_text)
        signal = _coerce_signal(str(data.get("signal", "NEUTRAL")))
        return ConciergeOpinion(
            persona_name=persona.name,
            seat=persona.seat,
            slug=persona.slug,
            event=event,
            signal=signal,
            conviction=min(max(float(data.get("conviction", 0.5)), 0.0), 1.0),
            reasoning=_sanitize_str(str(data.get("reasoning", "No reasoning provided"))),
            operational_arguments=_sanitize_str_list(data.get("operational_arguments", [])),
            risk_factors=_sanitize_str_list(data.get("risk_factors", [])),
            recommended_actions=_sanitize_str_list(data.get("recommended_actions", [])),
            departments=_parse_departments(data.get("departments", [])),
            timestamp=datetime.now().isoformat(),
            model_used=model_used,
            elapsed_seconds=round(elapsed, 1),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("concierge_opinion_parse_failed persona=%s err=%s", persona.name, e)
        loose = _parse_loose_opinion(persona, event, raw_text, model_used, elapsed)
        if loose is not None:
            return loose
        safe_excerpt = _sanitize_str(raw_text[:200])
        return ConciergeOpinion(
            persona_name=persona.name,
            seat=persona.seat,
            slug=persona.slug,
            event=event,
            signal=ConciergeSignal.NEUTRAL,
            conviction=0.5,
            reasoning=f"Non-standard response. Excerpt: {safe_excerpt}",
            operational_arguments=[],
            risk_factors=["LLM response required manual extraction"],
            recommended_actions=["Retry triage or review raw seat output"],
            departments=[],
            timestamp=datetime.now().isoformat(),
            model_used=model_used,
            elapsed_seconds=round(elapsed, 1),
        )


def _make_error_opinion(persona: ConciergePersona, error_msg: str, elapsed: float) -> ConciergeOpinion:
    return ConciergeOpinion(
        persona_name=persona.name,
        seat=persona.seat,
        slug=persona.slug,
        event="error",
        signal=ConciergeSignal.ERROR,
        conviction=0.0,
        reasoning=f"Seat failed: {error_msg}",
        operational_arguments=[],
        risk_factors=["Seat analysis unavailable — manual review suggested"],
        recommended_actions=["Retry guest triage or check LLM endpoint health"],
        departments=[],
        timestamp=datetime.now().isoformat(),
        model_used="none",
        elapsed_seconds=round(elapsed, 1),
    )


async def analyze_with_concierge_persona(
    persona: ConciergePersona,
    case_brief: str,
    context: str = "",
) -> ConciergeOpinion:
    system_prompt = f"""{persona.godhead_prompt}

YOUR WORLDVIEW:
{persona.worldview}

YOUR BIASES & FOCUS:
{chr(10).join(f"- {b}" for b in persona.bias)}
{chr(10).join(f"- {f}" for f in persona.focus_areas)}

CRITICAL DIRECTIVE:
You MUST output your ENTIRE response as a single, valid JSON object.
- DO NOT wrap the JSON in markdown.
- DO NOT include conversational filler.

REQUIRED JSON SCHEMA:
{{
  "signal": "STRONG_RESOLUTION" | "RESOLVE" | "NEUTRAL" | "CAUTION" | "CRITICAL_RISK",
  "conviction": <float 0.0-1.0>,
  "reasoning": "<analysis>",
  "operational_arguments": ["<arg1>", "<arg2>"],
  "risk_factors": ["<risk1>"],
  "recommended_actions": ["<action1>"],
  "departments": ["guest"|"housekeeping"|"maintenance"|"booking"]
}}
Include only departments materially implicated; use [] if none.
"""

    user_prompt = f"""GUEST TRIAGE CASE BRIEF:
{case_brief}
{f"ADDITIONAL CONTEXT:{chr(10)}{context}" if context else ""}

Return the raw JSON object only.
"""

    t0 = time.time()
    routing = SEAT_ROUTING.get(persona.seat, {})
    provider = routing.get("provider", "HYDRA_120B") if ALLOW_CLOUD_LLM else "HYDRA_120B"
    provider_sequence = _provider_attempt_sequence(provider, persona.seat)

    if provider in _CLOUD_PROVIDERS:
        base_system = _sanitize_for_cloud(system_prompt)
        base_user = _sanitize_for_cloud(user_prompt)
    else:
        base_system = system_prompt
        base_user = user_prompt

    async def _invoke_once(current_system: str, current_user: str, selected_provider: str) -> Tuple[str, str]:
        if selected_provider == "ANTHROPIC" and FRONTIER_GATEWAY_API_KEY:
            return await _call_llm(
                current_system,
                current_user,
                model=ANTHROPIC_MODEL,
                base_url=ANTHROPIC_PROXY,
                api_key=FRONTIER_GATEWAY_API_KEY,
            )
        if selected_provider == "GEMINI" and FRONTIER_GATEWAY_API_KEY:
            return await _call_llm(
                current_system,
                current_user,
                model=GEMINI_MODEL,
                base_url=GEMINI_BASE_URL,
                api_key=FRONTIER_GATEWAY_API_KEY,
            )
        if selected_provider == "XAI" and FRONTIER_GATEWAY_API_KEY:
            return await _call_llm(
                current_system,
                current_user,
                model=XAI_MODEL,
                base_url=XAI_BASE_URL,
                api_key=FRONTIER_GATEWAY_API_KEY,
            )
        if selected_provider == "XAI_FLAGSHIP" and FRONTIER_GATEWAY_API_KEY:
            return await _call_llm(
                current_system,
                current_user,
                model=XAI_MODEL_FLAGSHIP,
                base_url=XAI_BASE_URL,
                api_key=FRONTIER_GATEWAY_API_KEY,
            )
        if selected_provider == "VLLM_120B":
            return await _call_llm(
                current_system,
                current_user,
                model=VLLM_MODEL_120B,
                base_url=VLLM_120B_URL,
            )
        if selected_provider == "HYDRA_32B":
            return await _call_llm(
                current_system,
                current_user,
                model=HYDRA_MODEL_32B,
                base_url=HYDRA_32B_URL,
            )
        if selected_provider == "HYDRA_120B":
            return await _call_llm(
                current_system,
                current_user,
                model=HYDRA_MODEL_120B,
                base_url=HYDRA_120B_URL,
            )
        return await _call_llm(
            current_system,
            current_user,
            model=HYDRA_MODEL_120B,
            base_url=HYDRA_120B_URL,
        )

    repair_hint = "REPAIR_HINT: Return ONLY valid JSON matching the schema. No markdown or prose."
    empty_hint = (
        "EMPTY_RESPONSE_HINT: Your previous response was blank or whitespace. "
        "Return a fully populated JSON object now. Do not omit any required field."
    )
    text = ""
    model = "none"
    for attempt in range(1, 4):
        selected_provider = provider_sequence[min(attempt - 1, len(provider_sequence) - 1)]
        if attempt == 1:
            current_user = base_user
        else:
            retry_hint = empty_hint if not (text or "").strip() else repair_hint
            retry_excerpt_label = "EMPTY_RESPONSE" if not (text or "").strip() else "INVALID_EXCERPT"
            current_user = (
                f"{base_user}\n\n{retry_hint}\n\n{retry_excerpt_label}:\n{text[:400]}"
            )
        text, model = await _invoke_once(base_system, current_user, selected_provider)
        try:
            if not (text or "").strip():
                raise ValueError("Blank response")
            _extract_json_block(text)
            break
        except Exception as exc:  # noqa: BLE001
            if (text or "").strip():
                loose = _parse_loose_opinion(
                    persona,
                    case_brief[:200],
                    text,
                    model,
                    time.time() - t0,
                )
                if loose is not None:
                    break
            logger.warning(
                "concierge_seat_retry seat=%s attempt=%s provider=%s err=%s",
                persona.seat,
                attempt,
                selected_provider,
                str(exc)[:120],
            )
    elapsed = time.time() - t0
    return _parse_opinion(persona, case_brief[:200], text, model, elapsed)


def _dedupe_top(items: List[str], limit: int) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        normalized = item.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(item.strip())
        if len(result) >= limit:
            break
    return result


def compute_concierge_consensus(opinions: List[ConciergeOpinion]) -> Dict[str, Any]:
    if not opinions:
        return {"error": "No opinions to aggregate"}

    valid = [o for o in opinions if o.signal != ConciergeSignal.ERROR]
    error_count = len(opinions) - len(valid)

    signal_counts = {s: 0 for s in ConciergeSignal}
    total_conviction = 0.0
    weighted_score = 0.0

    for op in opinions:
        signal_counts[op.signal] += 1

    for op in valid:
        total_conviction += op.conviction
        weighted_score += SIGNAL_WEIGHTS.get(op.signal, 0) * op.conviction

    n = len(valid) if valid else 1
    avg_conviction = total_conviction / n
    net_score = weighted_score / n

    devils = [op for op in valid if op.seat == 5]
    if devils:
        da = devils[0]
        da_inverted = -SIGNAL_WEIGHTS.get(da.signal, 0) * da.conviction
        net_score_adjusted = (
            weighted_score - SIGNAL_WEIGHTS.get(da.signal, 0) * da.conviction + da_inverted
        ) / n
    else:
        net_score_adjusted = net_score

    if net_score_adjusted >= 0.4:
        consensus = ConciergeSignal.STRONG_RESOLUTION
    elif net_score_adjusted >= 0.15:
        consensus = ConciergeSignal.RESOLVE
    elif net_score_adjusted > -0.15:
        consensus = ConciergeSignal.NEUTRAL
    elif net_score_adjusted > -0.4:
        consensus = ConciergeSignal.CAUTION
    else:
        consensus = ConciergeSignal.CRITICAL_RISK

    strong_resolve = signal_counts[ConciergeSignal.STRONG_RESOLUTION] + signal_counts[ConciergeSignal.RESOLVE]
    weak_side = signal_counts[ConciergeSignal.CAUTION] + signal_counts[ConciergeSignal.CRITICAL_RISK]
    majority = max(signal_counts, key=signal_counts.get)
    agreement_rate = signal_counts[majority] / len(opinions)

    all_ops: List[str] = []
    all_risks: List[str] = []
    all_actions: List[str] = []
    dept_counts: Dict[str, int] = {}
    for op in opinions:
        all_ops.extend(op.operational_arguments)
        all_risks.extend(op.risk_factors)
        all_actions.extend(op.recommended_actions)
        for d in op.departments:
            dept_counts[d] = dept_counts.get(d, 0) + 1

    departments_ranked = sorted(dept_counts.keys(), key=lambda d: dept_counts[d], reverse=True)

    return {
        "consensus_signal": consensus.value,
        "consensus_conviction": round(avg_conviction, 4),
        "net_score": round(net_score, 4),
        "net_score_adjusted": round(net_score_adjusted, 4),
        "strong_or_resolve_seats": strong_resolve,
        "caution_or_critical_seats": weak_side,
        "neutral_count": signal_counts[ConciergeSignal.NEUTRAL],
        "error_count": error_count,
        "total_voters": len(opinions),
        "agreement_rate": round(agreement_rate, 4),
        "signal_breakdown": {s.value: c for s, c in signal_counts.items()},
        "top_operational_arguments": _dedupe_top(all_ops, 10),
        "top_defense_arguments": _dedupe_top(all_ops, 10),
        "top_risk_factors": _dedupe_top(all_risks, 10),
        "top_recommended_actions": _dedupe_top(all_actions, 10),
        "departments_implicated": departments_ranked,
        "department_scores": dept_counts,
    }


def _infer_categories(body: str) -> List[str]:
    text = (body or "").lower()
    categories: List[str] = []
    if any(k in text for k in ("wifi", "wi-fi", "internet", "password")):
        categories.append("wifi")
    if any(k in text for k in ("hot tub", "hottub", "spa", "jacuzzi")):
        categories.append("hot_tub")
    if any(k in text for k in ("heat", "thermostat", "hvac", "a/c", "ac")):
        categories.append("hvac")
    if any(k in text for k in ("check in", "check-in", "arrival", "door code", "gate code")):
        categories.append("check_in")
    if any(k in text for k in ("check out", "check-out", "checkout", "departure")):
        categories.append("check_out")
    return categories


async def fetch_property_knowledge_snippets(
    db: AsyncSession,
    property_id: Optional[UUID],
    body: str,
) -> List[Dict[str, Any]]:
    categories = _infer_categories(body)
    records: Sequence[PropertyKnowledge] = []
    if property_id:
        if categories:
            stmt = (
                select(PropertyKnowledge)
                .where(
                    PropertyKnowledge.property_id == property_id,
                    PropertyKnowledge.category.in_(categories),
                )
                .order_by(PropertyKnowledge.updated_at.desc())
                .limit(5)
            )
            records = (await db.execute(stmt)).scalars().all()
        if not records:
            tokens = re.findall(r"[a-zA-Z]{4,}", (body or "").lower())[:6]
            if tokens:
                token_filters = [PropertyKnowledge.content.ilike(f"%{token}%") for token in tokens]
                stmt = (
                    select(PropertyKnowledge)
                    .where(
                        PropertyKnowledge.property_id == property_id,
                        or_(*token_filters),
                    )
                    .order_by(PropertyKnowledge.updated_at.desc())
                    .limit(5)
                )
                records = (await db.execute(stmt)).scalars().all()
    elif categories:
        stmt = (
            select(PropertyKnowledge)
            .where(PropertyKnowledge.category.in_(categories))
            .order_by(PropertyKnowledge.updated_at.desc())
            .limit(5)
        )
        records = (await db.execute(stmt)).scalars().all()

    return [
        {
            "knowledge_id": str(item.id),
            "property_id": str(item.property_id),
            "category": item.category,
            "content": (item.content or "")[:1200],
        }
        for item in records
    ]


async def _find_active_reservation_for_guest(db: AsyncSession, guest_id: UUID) -> Optional[Reservation]:
    today = datetime.utcnow().date()
    result = await db.execute(
        select(Reservation)
        .where(
            and_(
                Reservation.guest_id == guest_id,
                Reservation.check_out_date >= today,
                Reservation.status.in_(["confirmed", "checked_in"]),
            )
        )
        .order_by(Reservation.check_in_date.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _normalize_phone(phone: str) -> str:
    import re as _re

    clean = _re.sub(r"[^\d+]", "", phone or "")
    if clean and not clean.startswith("+"):
        if len(clean) == 10:
            clean = "+1" + clean
        elif len(clean) == 11 and clean.startswith("1"):
            clean = "+" + clean
    return clean[:40]


def _csv_allowlist(raw: str) -> set[str]:
    return {item.strip().lower() for item in (raw or "").split(",") if item.strip()}


def _guest_public_dict(g: Guest) -> Dict[str, Any]:
    return {
        "id": str(g.id),
        "full_name": g.full_name,
        "phone": g.phone_number,
        "email": g.email,
        "loyalty_tier": g.loyalty_tier,
        "is_vip": bool(g.is_vip),
        "risk_score": g.risk_score,
        "value_score": g.value_score,
        "requires_supervision": bool(g.requires_supervision),
        "is_blacklisted": bool(g.is_blacklisted),
        "is_do_not_contact": bool(g.is_do_not_contact),
        "verification_status": g.verification_status,
    }


def _reservation_public_dict(r: Reservation) -> Dict[str, Any]:
    return {
        "id": str(r.id),
        "confirmation_code": r.confirmation_code,
        "status": r.status,
        "check_in_date": r.check_in_date.isoformat() if r.check_in_date else None,
        "check_out_date": r.check_out_date.isoformat() if r.check_out_date else None,
        "booking_source": r.booking_source,
        "special_requests": (r.special_requests or "")[:2000],
        "num_guests": r.num_guests,
        "balance_due": str(r.balance_due) if r.balance_due is not None else None,
        "property_id": str(r.property_id),
    }


def _property_public_dict(p: Property, include_sensitive: bool = False) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": str(p.id),
        "name": p.name,
        "slug": p.slug,
        "address": (p.address or "")[:500],
        "max_guests": p.max_guests,
        "access_code_type": p.access_code_type,
        "access_code_location": (p.access_code_location or "")[:800],
        "parking_instructions": (p.parking_instructions or "")[:800],
    }
    if include_sensitive:
        data["wifi_ssid"] = p.wifi_ssid
        data["wifi_password"] = p.wifi_password
    return data


def _message_public_dict(m: Message) -> Dict[str, Any]:
    return {
        "id": str(m.id),
        "direction": m.direction,
        "body": (m.body or "")[:4000],
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "intent": m.intent,
        "sentiment": m.sentiment,
        "category": m.category,
        "requires_human_review": bool(m.requires_human_review),
        "reservation_id": str(m.reservation_id) if m.reservation_id else None,
    }


def _work_order_public_dict(wo: WorkOrder) -> Dict[str, Any]:
    return {
        "id": str(wo.id),
        "ticket_number": wo.ticket_number,
        "title": (wo.title or "")[:255],
        "description": (wo.description or "")[:2000],
        "category": wo.category,
        "priority": wo.priority,
        "status": wo.status,
        "assigned_to": wo.assigned_to,
        "created_by": wo.created_by,
        "created_at": wo.created_at.isoformat() if wo.created_at else None,
        "resolved_at": wo.resolved_at.isoformat() if wo.resolved_at else None,
        "resolution_notes": (wo.resolution_notes or "")[:2000],
        "reported_via_message_id": str(wo.reported_via_message_id) if wo.reported_via_message_id else None,
    }


async def fetch_recent_work_orders(
    db: AsyncSession,
    *,
    property_id: Optional[UUID],
    guest_id: Optional[UUID] = None,
    reservation_id: Optional[UUID] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    if property_id is None:
        return []

    filters = [WorkOrder.property_id == property_id]
    if guest_id is not None or reservation_id is not None:
        scoped = []
        if guest_id is not None:
            scoped.append(WorkOrder.guest_id == guest_id)
        if reservation_id is not None:
            scoped.append(WorkOrder.reservation_id == reservation_id)
        if scoped:
            filters.append(or_(*scoped))

    stmt = (
        select(WorkOrder)
        .where(and_(*filters))
        .order_by(WorkOrder.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [_work_order_public_dict(wo) for wo in result.scalars().all()]


def _build_case_brief(
    *,
    focal_message: str,
    guest: Guest,
    reservation: Optional[Reservation],
    prop: Optional[Property],
    knowledge_snippets: List[Dict[str, Any]],
    thread_summaries: List[Dict[str, Any]],
    work_order_summaries: List[Dict[str, Any]],
    ambiguity_note: Optional[str],
) -> str:
    lines = [
        "=== GUEST TRIAGE — OPERATIONAL CASE BRIEF ===",
        "",
        f"FOCAL_MESSAGE: {focal_message[:8000]}",
        "",
        "GUEST_PROFILE:",
        json.dumps(_guest_public_dict(guest), default=str, indent=2),
    ]
    if ambiguity_note:
        lines.extend(["", f"AMBIGUITY: {ambiguity_note}"])
    if reservation:
        lines.extend(["", "RESERVATION:", json.dumps(_reservation_public_dict(reservation), default=str, indent=2)])
    else:
        lines.append("\nRESERVATION: none linked or not found for window.")
    if prop:
        lines.extend(
            [
                "",
                "PROPERTY (operational summary; verify before quoting access credentials):",
                json.dumps(_property_public_dict(prop, include_sensitive=False), default=str, indent=2),
            ]
        )
    if knowledge_snippets:
        lines.extend(
            [
                "",
                "PROPERTY_KNOWLEDGE_SNIPPETS:",
                json.dumps(knowledge_snippets, default=str, indent=2),
            ]
        )
    if work_order_summaries:
        lines.extend(["", "RECENT_WORK_ORDERS:", json.dumps(work_order_summaries, default=str, indent=2)])
    if thread_summaries:
        lines.extend(["", "RECENT_THREAD:", json.dumps(thread_summaries, default=str, indent=2)])
    return "\n".join(lines)


def _heuristic_escalation(
    focal: str,
    consensus_signal: str,
    requires_human_review_hint: bool,
) -> Tuple[str, str]:
    text = (focal or "").lower()
    if consensus_signal == "CRITICAL_RISK":
        return "critical", "Consensus indicates critical guest-experience or safety risk."
    if requires_human_review_hint or consensus_signal == "CAUTION":
        return "high", "Elevated scrutiny: policy, complaint, or maintenance may require human coordination."
    if any(w in text for w in ("911", "emergency", "fire", "flood", "gas", "not breathing")):
        return "critical", "Possible emergency language detected — verify immediately."
    if consensus_signal in ("STRONG_RESOLUTION", "RESOLVE"):
        return "standard", "Operational path likely in-bounds for first-line resolution."
    return "standard", "Monitor thread; use council recommendations."


def _primary_issue_label(consensus: Dict[str, Any], focal: str) -> str:
    tops = consensus.get("top_operational_arguments") or []
    if tops:
        return tops[0][:200]
    return (focal or "")[:120] or "general_guest_inquiry"


async def _compose_draft_reply(
    *,
    case_brief: str,
    consensus: Dict[str, Any],
    focal_message: str,
) -> str:
    summary = json.dumps(
        {
            "consensus_signal": consensus.get("consensus_signal"),
            "top_recommended_actions": consensus.get("top_recommended_actions", [])[:8],
            "top_risk_factors": consensus.get("top_risk_factors", [])[:5],
            "departments_implicated": consensus.get("departments_implicated", []),
        },
        ensure_ascii=False,
    )
    system = (
        "You draft SMS replies for Cabin Rentals of Georgia. "
        "Warm, professional Southern hospitality; concise; no placeholders. "
        "Do not invent specific codes, refunds, or promises unless in the case brief. "
        "If facts are missing, acknowledge and promise verified follow-up. "
        "Output plain text only — the exact message to send, no quotes or JSON."
    )
    user = f"""Guest's latest message:
{focal_message[:4000]}

Council summary (for your judgment only):
{summary}

Full operational brief (reference):
{case_brief[:12000]}

Write one draft SMS reply."""
    # qwen2.5:7b at HYDRA_120B_URL (spark-4 :11434/v1) — confirmed working.
    # HYDRA_MODEL_120B (gpt-oss:120b) is not loaded on any node.
    text, _model = await _call_llm(
        system,
        user,
        model="qwen2.5:7b",
        base_url=HYDRA_120B_URL,
        temperature=0.55,
        max_tokens=512,
    )
    draft = (text or "").strip()
    if not draft:
        draft = (
            "Thanks for reaching out — we're on it and will follow up shortly with verified details. "
            "If anything feels urgent (safety, lockout, or no heat), reply URGENT and we'll prioritize."
        )
    return draft[:1600]


async def run_guest_triage(
    db: AsyncSession,
    *,
    guest_id: Optional[UUID] = None,
    reservation_id: Optional[UUID] = None,
    message_id: Optional[UUID] = None,
    guest_phone: Optional[str] = None,
    inbound_message: Optional[str] = None,
    trigger_type: str = "PAPERCLIP_TOOL_GUEST_TRIAGE",
    include_wifi_in_property_block: bool = False,
) -> Dict[str, Any]:
    """
    Load guest / reservation / property / messages; run 9-seat concierge matrix; return triage + draft.

    Does not write to DB or send SMS.
    """
    _ = trigger_type  # reserved for future vault / audit hooks
    ambiguity_note: Optional[str] = None
    focal_message = (inbound_message or "").strip()
    anchor_message: Optional[Message] = None
    guest: Optional[Guest] = None
    reservation: Optional[Reservation] = None
    prop: Optional[Property] = None

    if message_id:
        anchor_message = await db.get(Message, message_id)
        if not anchor_message:
            raise ValueError(f"message_id not found: {message_id}")
        focal_message = focal_message or (anchor_message.body or "").strip()
        if anchor_message.guest_id:
            guest = await db.get(Guest, anchor_message.guest_id)
        if anchor_message.reservation_id:
            reservation = await db.get(Reservation, anchor_message.reservation_id)

    if guest_id and guest is None:
        guest = await db.get(Guest, guest_id)
        if not guest:
            raise ValueError(f"guest_id not found: {guest_id}")

    if guest_phone and guest is None:
        normalized = _normalize_phone(guest_phone)
        if not normalized:
            raise ValueError("guest_phone is empty after normalization")
        res = await db.execute(select(Guest).where(Guest.phone_number == normalized))
        guest = res.scalar_one_or_none()
        if not guest:
            raise ValueError(f"No guest found for phone: {normalized}")

    if reservation_id:
        reservation = await db.get(Reservation, reservation_id)
        if not reservation:
            raise ValueError(f"reservation_id not found: {reservation_id}")
        if guest is None:
            guest = await db.get(Guest, reservation.guest_id)
        if guest is None:
            raise ValueError("Reservation has no resolvable guest")

    if guest is None:
        raise ValueError(
            "Provide at least one of: message_id, guest_id, guest_phone, or reservation_id "
            "(with implied guest)."
        )

    if not focal_message:
        raise ValueError("inbound_message is required when no message_id is provided, or message body is empty.")

    if reservation is None:
        reservation = await _find_active_reservation_for_guest(db, guest.id)
        if reservation is None:
            ambiguity_note = (
                "No active/upcoming reservation matched (confirmed/checked_in, checkout>=today). "
                "Guest may be between stays or message not linked."
            )

    if reservation:
        alt = await db.execute(
            select(Reservation.id).where(
                and_(
                    Reservation.guest_id == guest.id,
                    Reservation.check_out_date >= date.today(),
                    Reservation.status.in_(["confirmed", "checked_in"]),
                )
            )
        )
        alt_ids = [row[0] for row in alt.all()]
        if len(alt_ids) > 1:
            ambiguity_note = (ambiguity_note + " " if ambiguity_note else "") + (
                f"Multiple active/upcoming reservations for guest ({len(alt_ids)}); "
                "using earliest check-in match — verify correct stay."
            )

    if reservation:
        prop = await db.get(Property, reservation.property_id)

    knowledge = await fetch_property_knowledge_snippets(
        db,
        reservation.property_id if reservation else None,
        focal_message,
    )
    work_orders = await fetch_recent_work_orders(
        db,
        property_id=reservation.property_id if reservation else None,
        guest_id=guest.id,
        reservation_id=reservation.id if reservation else None,
        limit=5,
    )

    msg_query = (
        select(Message)
        .where(Message.guest_id == guest.id)
        .order_by(Message.created_at.desc())
        .limit(30)
    )
    msg_result = await db.execute(msg_query)
    recent = list(reversed(msg_result.scalars().all()))
    thread_summaries = [_message_public_dict(m) for m in recent[-20:]]

    requires_hint = any(
        m.get("requires_human_review") for m in thread_summaries if m.get("direction") == "inbound"
    )
    case_brief = _build_case_brief(
        focal_message=focal_message,
        guest=guest,
        reservation=reservation,
        prop=prop,
        knowledge_snippets=knowledge,
        thread_summaries=thread_summaries,
        work_order_summaries=work_orders,
        ambiguity_note=ambiguity_note,
    )

    frozen_context = ""
    if knowledge:
        frozen_context = "--- PROPERTY KNOWLEDGE ---\n" + "\n".join(
            f"[{s.get('category')}] {s.get('content', '')[:600]}" for s in knowledge[:5]
        )

    personas = ConciergePersona.load_all()
    if not personas:
        raise RuntimeError(
            f"No concierge personas found in {CONCIERGE_PERSONAS_DIR}. "
            "Install personas/concierge/*.json."
        )

    session_id = f"paperclip-concierge-{uuid.uuid4()}"
    opinions: List[ConciergeOpinion] = []

    async def _one(p: ConciergePersona) -> None:
        try:
            op = await asyncio.wait_for(
                analyze_with_concierge_persona(p, case_brief, frozen_context),
                timeout=float(PERSONA_TIMEOUT_SECONDS),
            )
        except asyncio.TimeoutError:
            op = _make_error_opinion(p, f"timeout after {PERSONA_TIMEOUT_SECONDS}s", float(PERSONA_TIMEOUT_SECONDS))
        except Exception as exc:  # noqa: BLE001
            op = _make_error_opinion(p, f"{type(exc).__name__}: {str(exc)[:200]}", 0.0)
        opinions.append(op)

    await asyncio.gather(*[_one(p) for p in personas])
    opinions.sort(key=lambda o: o.seat)

    consensus = compute_concierge_consensus(opinions)
    if consensus.get("error"):
        raise RuntimeError(str(consensus.get("error")))

    escalation_level, escalation_rationale = _heuristic_escalation(
        focal_message,
        str(consensus.get("consensus_signal", "NEUTRAL")),
        bool(requires_hint),
    )

    draft_reply = await _compose_draft_reply(
        case_brief=case_brief,
        consensus=consensus,
        focal_message=focal_message,
    )

    prop_out = _property_public_dict(prop, include_sensitive=include_wifi_in_property_block) if prop else None

    return {
        "workflow": "guest_comm_triage",
        "session_id": session_id,
        "trigger_type": trigger_type,
        "guest": _guest_public_dict(guest),
        "reservation": _reservation_public_dict(reservation) if reservation else None,
        "property": prop_out,
        "conversation": {
            "focal_text": focal_message[:8000],
            "recent_messages": thread_summaries,
            "knowledge_snippets": knowledge,
            "recent_work_orders": work_orders,
        },
        "triage": {
            "primary_issue": _primary_issue_label(consensus, focal_message),
            "escalation_level": escalation_level,
            "escalation_rationale": escalation_rationale,
            "consensus_signal": consensus.get("consensus_signal"),
            "consensus_conviction": consensus.get("consensus_conviction"),
            "departments_implicated": consensus.get("departments_implicated", []),
            "department_scores": consensus.get("department_scores", {}),
            "ambiguity_note": ambiguity_note,
        },
        "council": {
            "session_id": session_id,
            "consensus_signal": consensus.get("consensus_signal"),
            "consensus_conviction": consensus.get("consensus_conviction"),
            "opinions": [o.to_dict() for o in opinions],
            "net_score": consensus.get("net_score"),
            "net_score_adjusted": consensus.get("net_score_adjusted"),
            "signal_breakdown": consensus.get("signal_breakdown"),
            "top_operational_arguments": consensus.get("top_operational_arguments"),
            "top_risk_factors": consensus.get("top_risk_factors"),
            "top_recommended_actions": consensus.get("top_recommended_actions"),
        },
        "draft_reply": {
            "text": draft_reply,
            "is_draft": True,
            "channel": "sms",
        },
        "recommended_actions": consensus.get("top_recommended_actions", []),
    }


def _summarize_field_reality(
    focal_message: str,
    work_orders: List[Dict[str, Any]],
) -> Dict[str, Any]:
    text_lower = (focal_message or "").lower()
    matched = []
    for wo in work_orders:
        haystack = " ".join(
            [
                str(wo.get("title") or ""),
                str(wo.get("description") or ""),
                str(wo.get("category") or ""),
                str(wo.get("resolution_notes") or ""),
            ]
        ).lower()
        if any(
            keyword in haystack
            for keyword in [
                "wifi" if "wifi" in text_lower or "internet" in text_lower else "",
                "hot tub" if "hot tub" in text_lower or "spa" in text_lower else "",
                "hvac" if "heat" in text_lower or "ac" in text_lower or "hvac" in text_lower else "",
                "clean" if "dirty" in text_lower or "clean" in text_lower else "",
                "refund" if "refund" in text_lower else "",
                "broken" if "broken" in text_lower or "not working" in text_lower else "",
            ]
            if keyword
        ):
            matched.append(wo)

    active = [wo for wo in work_orders if wo.get("status") in {"open", "in_progress", "waiting_parts"}]
    completed_recent = [wo for wo in work_orders if wo.get("status") == "completed"]
    return {
        "matched_work_orders": matched[:5],
        "active_work_orders": active[:5],
        "completed_recent_work_orders": completed_recent[:5],
        "has_prior_field_activity": bool(work_orders),
        "has_active_issue": bool(active),
        "has_recent_matching_issue": bool(matched),
    }


def _conflict_outcome(
    focal_message: str,
    consensus: Dict[str, Any],
    field_reality: Dict[str, Any],
) -> Dict[str, Any]:
    text_lower = (focal_message or "").lower()
    asks_refund = "refund" in text_lower
    matching = field_reality.get("matched_work_orders", [])
    has_active_issue = bool(field_reality.get("has_active_issue"))
    has_recent_matching_issue = bool(field_reality.get("has_recent_matching_issue"))
    signal = str(consensus.get("consensus_signal") or "NEUTRAL")

    if has_active_issue or (has_recent_matching_issue and signal in {"CAUTION", "CRITICAL_RISK"}):
        legitimacy = "likely_legitimate_failure"
        scheduling = "schedule_or_confirm_corrective_visit"
        refund_risk = "do_not_auto_refund_without_policy_check"
    elif asks_refund and not matching and signal in {"STRONG_RESOLUTION", "RESOLVE", "NEUTRAL"}:
        legitimacy = "possible_exaggeration_or_unverified_claim"
        scheduling = "request_verification_before_dispatch"
        refund_risk = "refund_not_supported_by_field_reality"
    else:
        legitimacy = "needs_operator_verification"
        scheduling = "manual_review_and_triage"
        refund_risk = "hold_refund_pending_evidence"

    return {
        "complaint_legitimacy": legitimacy,
        "corrective_scheduling": scheduling,
        "refund_position": refund_risk,
    }


async def _persist_operational_deliberation_log(
    db: AsyncSession,
    *,
    verdict_type: str,
    session_id: str,
    guest_id: Optional[UUID],
    reservation_id: Optional[UUID],
    property_id: Optional[UUID],
    message_id: Optional[UUID],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        row_id = str(uuid.uuid4())
        await db.execute(
            text(
                """
                INSERT INTO core.deliberation_logs (
                    id,
                    verdict_type,
                    session_id,
                    guest_id,
                    reservation_id,
                    property_id,
                    message_id,
                    payload_json,
                    created_at
                )
                VALUES (
                    :id,
                    :verdict_type,
                    :session_id,
                    :guest_id,
                    :reservation_id,
                    :property_id,
                    :message_id,
                    CAST(:payload_json AS jsonb),
                    NOW()
                )
                """
            ),
            {
                "id": row_id,
                "verdict_type": verdict_type,
                "session_id": session_id,
                "guest_id": str(guest_id) if guest_id else None,
                "reservation_id": str(reservation_id) if reservation_id else None,
                "property_id": str(property_id) if property_id else None,
                "message_id": str(message_id) if message_id else None,
                "payload_json": json.dumps(payload, default=str, ensure_ascii=False),
            },
        )
        await db.commit()
        return {"status": "persisted", "table": "core.deliberation_logs", "id": row_id}
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.warning(
            "operational_deliberation_log_failed",
            extra={"session_id": session_id, "error": str(exc)[:200]},
        )
        return {
            "status": "skipped",
            "table": "core.deliberation_logs",
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }


async def run_guest_resolve_conflict(
    db: AsyncSession,
    *,
    guest_id: Optional[UUID] = None,
    reservation_id: Optional[UUID] = None,
    message_id: Optional[UUID] = None,
    guest_phone: Optional[str] = None,
    inbound_message: Optional[str] = None,
    trigger_type: str = "PAPERCLIP_TOOL_GUEST_RESOLVE_CONFLICT",
    include_wifi_in_property_block: bool = False,
) -> Dict[str, Any]:
    triage = await run_guest_triage(
        db,
        guest_id=guest_id,
        reservation_id=reservation_id,
        message_id=message_id,
        guest_phone=guest_phone,
        inbound_message=inbound_message,
        trigger_type=trigger_type,
        include_wifi_in_property_block=include_wifi_in_property_block,
    )

    work_orders = (triage.get("conversation") or {}).get("recent_work_orders", [])
    focal_text = (triage.get("conversation") or {}).get("focal_text", "")
    field_reality = _summarize_field_reality(focal_text, work_orders)
    consensus = triage.get("council") or {}
    outcome = _conflict_outcome(focal_text, consensus, field_reality)

    result = {
        **triage,
        "workflow": "guest_conflict_resolution",
        "field_reality": field_reality,
        "conflict_resolution": {
            **outcome,
            "departments_implicated": (triage.get("triage") or {}).get("departments_implicated", []),
            "consensus_signal": consensus.get("consensus_signal"),
            "consensus_conviction": consensus.get("consensus_conviction"),
        },
    }

    audit = await _persist_operational_deliberation_log(
        db,
        verdict_type="guest_resolve_conflict",
        session_id=str(result.get("session_id")),
        guest_id=UUID(str(triage["guest"]["id"])) if triage.get("guest", {}).get("id") else None,
        reservation_id=UUID(str(triage["reservation"]["id"])) if triage.get("reservation") and triage["reservation"].get("id") else None,
        property_id=UUID(str(triage["property"]["id"])) if triage.get("property") and triage["property"].get("id") else None,
        message_id=message_id,
        payload={
            "triage": result.get("triage"),
            "conflict_resolution": result.get("conflict_resolution"),
            "field_reality": result.get("field_reality"),
        },
    )
    result["audit_log"] = audit
    return result


async def run_guest_send_sms(
    db: AsyncSession,
    *,
    guest_id: Optional[UUID] = None,
    reservation_id: Optional[UUID] = None,
    guest_phone: Optional[str] = None,
    body: str,
    consensus_conviction: float,
    minimum_conviction: float = 0.8,
    session_id: Optional[str] = None,
    source_workflow: Optional[str] = None,
    trigger_type: str = "PAPERCLIP_TOOL_GUEST_SEND_SMS",
) -> Dict[str, Any]:
    if consensus_conviction < minimum_conviction:
        raise ValueError(
            f"Consensus conviction {consensus_conviction:.4f} is below send threshold {minimum_conviction:.4f}.",
        )
    if not (body or "").strip():
        raise ValueError("SMS body is required.")
    if len(body) > int(_cfg.max_message_length):
        raise ValueError(
            f"SMS body exceeds max_message_length ({len(body)} > {_cfg.max_message_length}).",
        )

    guest: Optional[Guest] = None
    reservation: Optional[Reservation] = None
    prop: Optional[Property] = None

    if guest_id is not None:
        guest = await db.get(Guest, guest_id)
        if guest is None:
            raise ValueError(f"guest_id not found: {guest_id}")

    if reservation_id is not None:
        reservation = await db.get(Reservation, reservation_id)
        if reservation is None:
            raise ValueError(f"reservation_id not found: {reservation_id}")
        if guest is None:
            guest = await db.get(Guest, reservation.guest_id)

    if guest_phone and guest is None:
        normalized = _normalize_phone(guest_phone)
        if not normalized:
            raise ValueError("guest_phone is empty after normalization")
        result = await db.execute(select(Guest).where(Guest.phone_number == normalized))
        guest = result.scalar_one_or_none()
        if guest is None:
            raise ValueError(f"No guest found for phone: {normalized}")

    if guest is None:
        raise ValueError("Provide at least one of guest_id, reservation_id, or guest_phone.")

    if reservation is None:
        reservation = await _find_active_reservation_for_guest(db, guest.id)

    if reservation is not None:
        prop = await db.get(Property, reservation.property_id)

    target_phone = _normalize_phone(guest_phone or guest.phone_number or "")
    if not target_phone:
        raise ValueError("Target guest has no routable phone number.")

    if guest.is_do_not_contact:
        raise ValueError("Guest is marked do_not_contact; autonomous SMS blocked.")
    if guest.is_blacklisted:
        raise ValueError("Guest is blacklisted; autonomous SMS blocked.")

    if not _cfg.enable_auto_replies:
        raise RuntimeError("enable_auto_replies is disabled.")
    if not _cfg.concierge_recovery_sms_enabled:
        raise RuntimeError("concierge_recovery_sms_enabled is disabled.")
    if not _cfg.concierge_strike_enabled:
        raise RuntimeError("concierge_strike_enabled is disabled.")
    if _cfg.concierge_strike_require_agentic_system_active and not _cfg.agentic_system_active:
        raise RuntimeError("AGENTIC_SYSTEM_ACTIVE is disabled; live Concierge send blocked.")

    allowed_guest_ids = _csv_allowlist(_cfg.concierge_strike_allowed_guest_ids)
    if allowed_guest_ids and str(guest.id).lower() not in allowed_guest_ids:
        raise RuntimeError("Guest is outside Concierge strike guest allowlist.")

    allowed_property_slugs = _csv_allowlist(_cfg.concierge_strike_allowed_property_slugs)
    if allowed_property_slugs:
        property_slug = (prop.slug if prop else "").strip().lower()
        if not property_slug or property_slug not in allowed_property_slugs:
            raise RuntimeError("Property is outside Concierge strike property allowlist.")

    allowed_loyalty_tiers = _csv_allowlist(_cfg.concierge_strike_allowed_loyalty_tiers)
    if allowed_loyalty_tiers:
        loyalty_tier = (guest.loyalty_tier or "").strip().lower()
        if loyalty_tier not in allowed_loyalty_tiers:
            raise RuntimeError("Guest is outside Concierge strike loyalty allowlist.")

    service = MessageService(db)
    message = await service.send_sms(
        to_phone=target_phone,
        body=body.strip(),
        guest_id=guest.id,
        reservation_id=reservation.id if reservation else None,
        is_auto_response=True,
        ai_confidence=consensus_conviction,
    )

    audit = await _persist_operational_deliberation_log(
        db,
        verdict_type="guest_send_sms",
        session_id=session_id or f"paperclip-concierge-send-{uuid.uuid4()}",
        guest_id=guest.id,
        reservation_id=reservation.id if reservation else None,
        property_id=prop.id if prop else None,
        message_id=message.id,
        payload={
            "trigger_type": trigger_type,
            "source_workflow": source_workflow,
            "consensus_conviction": consensus_conviction,
            "minimum_conviction": minimum_conviction,
            "target_phone": target_phone,
            "body": body.strip(),
            "twilio_external_id": message.external_id,
        },
    )

    return {
        "workflow": "guest_send_sms",
        "dispatched": True,
        "guest": _guest_public_dict(guest),
        "reservation": _reservation_public_dict(reservation) if reservation else None,
        "property": _property_public_dict(prop, include_sensitive=False) if prop else None,
        "delivery": {
            "message_id": str(message.id),
            "external_id": message.external_id,
            "status": message.status,
            "phone_to": message.phone_to,
            "segments": message.num_segments,
            "cost_amount": float(message.cost_amount) if message.cost_amount is not None else None,
            "sent_at": message.sent_at.isoformat() if message.sent_at else None,
            "ai_confidence": float(message.ai_confidence) if message.ai_confidence is not None else None,
        },
        "audit_log": audit,
    }
