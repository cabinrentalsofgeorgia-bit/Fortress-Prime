"""
FORTRESS PRIME — LEGAL COUNCIL OF 9
====================================
Multi-persona legal deliberation engine for the Generali/Fannin County defense.

Ported from tools/intelligence_engine.py + src/persona_template.py
and adapted for legal domain analysis with 9 specialized legal personas.

Architecture:
    FastAPI route (api/legal_council.py) → LegalCouncil engine (this file)
      → God-Head Router (Anthropic Opus / Gemini Pro for legal domain)
      → Semaphore-throttled parallel fan-out across 4 DGX Spark nodes
      → SSE streaming via asyncio.Queue for real-time leaderboard

Each persona analyzes the case through their unique lens and produces:
    - Signal: STRONG_DEFENSE, DEFENSE, NEUTRAL, WEAK, VULNERABLE
    - Conviction: 0.0 to 1.0
    - Reasoning, defense arguments, risk factors, recommended actions

Concurrency:
    asyncio.Semaphore(3) limits parallel LLM calls to 3 at a time.
    Per-persona timeout of 120s prevents any single seat from hanging.
    Every persona MUST emit a completion event — failures yield ERROR state.
"""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.core.database import AsyncSessionLocal
from backend.services.deliberation_vault import (
    load_active_roster,
    vault_deliberation,
)

# ═══════════════════════════════════════════════════════════════════════
# Load environment from root .env (not handled by pydantic-settings for
# os.getenv calls). This ensures ALLOW_CLOUD_LLM, ANTHROPIC_API_KEY,
# and other LLM routing vars are available.
# ═══════════════════════════════════════════════════════════════════════

try:
    from dotenv import load_dotenv

    _project_root = Path(__file__).resolve().parent.parent.parent.parent
    _fgp_root = Path(__file__).resolve().parent.parent.parent

    # FGP .env first (more specific), then root .env (override=False keeps first-wins)
    load_dotenv(_fgp_root / ".env", override=False)
    load_dotenv(_project_root / ".env", override=False)
except ImportError:
    pass

logger = logging.getLogger("legal_council")

# ═══════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════

PERSONAS_DIR = os.getenv(
    "LEGAL_PERSONAS_DIR",
    "/home/admin/Fortress-Prime/personas/legal",
)
# Phase A PR #2 (2026-04-30): caselaw + library cut over to 2048-dim legal-embed
# _v2 collections; ediscovery stays on legacy 768-dim nomic-embed-text per Option B.
# Legacy `legal_library` and `legal_caselaw` removed from the allowlist so the
# council strictly uses the cut-over targets.
LEGAL_ALLOWED_VECTOR_COLLECTIONS = frozenset(
    {"legal_library_v2", "legal_ediscovery", "legal_caselaw_v2"}
)

# Precedent retrieval knobs — legal_caselaw_v2 holds the controlling-authority corpus
# (CourtListener opinions). Defaults picked to fit comfortably inside frontier-model
# context budgets after case brief + evidence chunks.
CASELAW_COLLECTION = "legal_caselaw_v2"
CASELAW_TOP_K = int(os.getenv("LEGAL_COUNCIL_CASELAW_TOP_K", "10"))
CONTEXT_BUDGET_TOKENS = int(os.getenv("LEGAL_COUNCIL_CONTEXT_BUDGET_TOKENS", "12000"))
# Approximate char-per-token ratio used for budget enforcement on pre-prompt
# retrieved context only (not the full seat prompt).
_CHARS_PER_TOKEN = 4

CASELAW_CONTEXT_HEADER = "--- CONTROLLING AUTHORITY (LEGAL CASE LAW) ---"
EVIDENCE_CONTEXT_HEADER = "--- CASE EVIDENCE (E-DISCOVERY) ---"

CITATION_INSTRUCTION = (
    "CITATION DISCIPLINE:\n"
    "When citing case law, cite only from the [CASE LAW: ...] blocks provided in "
    "context. Do not invent citations. If no case law block is provided for a "
    "proposition, state the proposition without a citation and note uncertainty."
)

from backend.core.config import settings as _cfg

_LITELLM_BASE = getattr(_cfg, "litellm_base_url", "http://127.0.0.1:8002/v1").rstrip("/")
# NIM inference endpoint (k8s ClusterIP, spark-2 internal) — used for served_by_endpoint tagging
_NIM_ENDPOINT = os.getenv("LEGAL_NIM_ENDPOINT", _cfg.nim_sovereign_url)
_raw_litellm_key = getattr(_cfg, "litellm_master_key", None) or os.getenv("LITELLM_MASTER_KEY")
if not _raw_litellm_key:
    raise RuntimeError(
        "LITELLM_MASTER_KEY is not configured — set litellm_master_key in settings "
        "or export LITELLM_MASTER_KEY env var before starting the service"
    )
_LITELLM_KEY = _raw_litellm_key

# ── Frontier model endpoints (all route through local LiteLLM gateway) ──────
ANTHROPIC_PROXY   = os.getenv("ANTHROPIC_PROXY_URL",  _LITELLM_BASE).rstrip("/")
OPENAI_BASE_URL   = os.getenv("OPENAI_BASE_URL",       _LITELLM_BASE).rstrip("/")
XAI_BASE_URL      = os.getenv("XAI_BASE_URL",          _LITELLM_BASE).rstrip("/")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL",     _LITELLM_BASE).rstrip("/")
GEMINI_BASE_URL   = os.getenv("GEMINI_BASE_URL",       _LITELLM_BASE).rstrip("/")

# ── Local sovereign endpoints (Ollama on DGX Sparks) ────────────────────────
# spark-node-2 local Ollama — use 127.0.0.1 to avoid network interface latency
_LOCAL_OLLAMA = "http://127.0.0.1:11434/v1"
SPARK2_URL      = os.getenv("SPARK2_URL",      _LOCAL_OLLAMA).rstrip("/")
SPARK_LOCAL_URL = os.getenv("SPARK_LOCAL_URL", _LOCAL_OLLAMA).rstrip("/")
# Legacy Hydra URLs (all fall back to local Ollama on spark-node-2)
HYDRA_URL       = os.getenv("HYDRA_FALLBACK_URL", _LOCAL_OLLAMA).rstrip("/")
SWARM_URL       = os.getenv("SWARM_URL",          _LOCAL_OLLAMA).rstrip("/")
HYDRA_32B_URL   = os.getenv("HYDRA_32B_URL",      _LOCAL_OLLAMA).rstrip("/")
HYDRA_120B_URL  = os.getenv("HYDRA_120B_URL",     _LOCAL_OLLAMA).rstrip("/")
VLLM_120B_URL   = os.getenv("VLLM_120B_URL",      _LOCAL_OLLAMA).rstrip("/")

# ── Model name constants ─────────────────────────────────────────────────────
# ── Council consumer cutover (ADR-003 Phase 1 / ADR-007 Wave 2, 2026-05-01) ─
# Defaults are the sovereign legal-* aliases established by PR #285's LiteLLM
# config and rerouted by Wave 2 (PR #337 / #338 / #339): every "frontier"
# provider routes through the spark-2 LiteLLM gateway → Nemotron-3-Super-120B-
# A12B-NVFP4 TP=2 frontier on spark-3 + spark-4 per ADR-007. The env-var
# override path is preserved as the rollback contract: set
# ANTHROPIC_MODEL=claude-sonnet-4-6 (etc.) to revert any seat to the cloud
# provider.
# Mapping: reasoning seats → legal-reasoning; counselor (Gemini-style) → legal-summarization.
# BRAIN-49B (Llama-3.3-Nemotron-Super-49B-v1.5-FP8 NIM on spark-5:8100) was
# retired 2026-04-30; image + unit preserved per
# docs/operational/runbooks/brain-49b-retirement.md.
ANTHROPIC_MODEL        = os.getenv("ANTHROPIC_MODEL",        "legal-reasoning")
ANTHROPIC_OPUS_MODEL   = os.getenv("ANTHROPIC_OPUS_MODEL",   "legal-reasoning")
OPENAI_MODEL           = os.getenv("OPENAI_MODEL",           "legal-reasoning")
XAI_MODEL              = os.getenv("XAI_MODEL",              "legal-reasoning")
XAI_MODEL_FLAGSHIP     = os.getenv("XAI_MODEL_FLAGSHIP",     "legal-reasoning")
DEEPSEEK_MODEL         = os.getenv("DEEPSEEK_MODEL",         "legal-reasoning")
DEEPSEEK_REASONER_MODEL= os.getenv("DEEPSEEK_REASONER_MODEL","legal-reasoning")
GEMINI_MODEL           = os.getenv("GEMINI_MODEL",           "legal-summarization")
SPARK2_MODEL       = os.getenv("SPARK2_MODEL",     "qwen2.5:7b")
SPARK_LOCAL_MODEL  = os.getenv("SPARK_LOCAL_MODEL","qwen2.5:7b")
SWARM_MODEL        = os.getenv("SWARM_MODEL",      "qwen2.5:7b")
# Legacy Hydra model names (fall through to qwen2.5:7b via Spark2)
VLLM_MODEL_120B  = os.getenv("VLLM_MODEL_120B",   "qwen2.5:7b")
HYDRA_MODEL_32B  = os.getenv("HYDRA_MODEL_32B",   "qwen2.5:7b")
HYDRA_MODEL_120B = os.getenv("HYDRA_MODEL_120B",  "qwen2.5:7b")
HYDRA_MODEL      = HYDRA_MODEL_120B

ALLOW_CLOUD_LLM = os.getenv("ALLOW_CLOUD_LLM", "false").lower() == "true"
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_AI_API_KEY", ""))
XAI_API_KEY     = os.getenv("XAI_API_KEY", "")
FRONTIER_GATEWAY_API_KEY = os.getenv("LITELLM_MASTER_KEY", _LITELLM_KEY)

# ── All 9 seats use distinct frontier models via LiteLLM gateway ─────────────
# Seat 9 = Chief Justice → Claude Opus (most capable, reserved for synthesis)
# Seats 5-8 = distributed across claude-sonnet, gpt-4o, grok-4, deepseek-reasoner
# Seats 1-4 = original frontier assignments
SEAT_ROUTING = {
    1: {"provider": "ANTHROPIC",          "role": "The Senior Litigator"},   # Claude Sonnet
    2: {"provider": "OPENAI",             "role": "The Contract Auditor"},   # GPT-4o
    3: {"provider": "XAI",               "role": "The Statutory Scholar"},  # Grok-4
    4: {"provider": "DEEPSEEK_REASONER",  "role": "The E-Discovery Forensic"},# DeepSeek-Reasoner
    5: {"provider": "ANTHROPIC",          "role": "The Devil's Advocate"},   # Claude Sonnet
    6: {"provider": "OPENAI",             "role": "The Compliance Officer"}, # GPT-4o
    7: {"provider": "XAI",               "role": "The Local Counsel"},      # Grok-4
    8: {"provider": "DEEPSEEK_REASONER",  "role": "The Risk Assessor"},     # DeepSeek-Reasoner
    9: {"provider": "ANTHROPIC_OPUS",     "role": "The Chief Justice"},     # Claude Opus
}

_LLM_SEMAPHORE = asyncio.Semaphore(3)   # max 3 concurrent LiteLLM calls

# DeepSeek-Reasoner needs 2000+ tokens for chain-of-thought before outputting JSON;
# other frontier models complete in 10-60s with 1200 tokens
PERSONA_TIMEOUT_SECONDS = 180

HTTPX_TIMEOUT = httpx.Timeout(connect=15.0, read=180.0, write=10.0, pool=10.0)
HTTPX_FALLBACK_TIMEOUT = httpx.Timeout(connect=10.0, read=150.0, write=10.0, pool=10.0)

_OLLAMA_ENDPOINTS = {HYDRA_32B_URL, HYDRA_120B_URL, HYDRA_URL, SWARM_URL,
                     SPARK2_URL, SPARK_LOCAL_URL}
_OLLAMA_CTX_LIMITS: dict[str, int] = {
    SPARK2_URL: 8192,
    SPARK_LOCAL_URL: 8192,
}
_OLLAMA_CTX_DEFAULT = 8192

_CLOUD_PROVIDERS = {"ANTHROPIC", "ANTHROPIC_OPUS", "OPENAI", "XAI", "XAI_FLAGSHIP",
                    "DEEPSEEK", "DEEPSEEK_REASONER", "GEMINI"}

# Map SEAT_ROUTING provider strings → logical provider names used by the
# COUNCIL_FRONTIER_PROVIDERS_ENABLED env var. Any SEAT_ROUTING provider not in
# this map is treated as a local/sovereign backend (HYDRA, SPARK, SWARM, VLLM)
# and is always allowed — gating only applies to frontier (cloud) providers.
_FRONTIER_PROVIDER_NORMALIZATION = {
    "ANTHROPIC":         "anthropic",
    "ANTHROPIC_OPUS":    "anthropic",
    "OPENAI":            "openai",
    "XAI":               "xai",
    "XAI_FLAGSHIP":      "xai",
    "DEEPSEEK":          "deepseek",
    "DEEPSEEK_REASONER": "deepseek",
    "GEMINI":            "gemini",
}


def _get_enabled_frontier_providers() -> frozenset[str]:
    """Read the COUNCIL_FRONTIER_PROVIDERS_ENABLED allowlist.

    Comma-separated logical provider names. Default is ``"anthropic"`` —
    a degraded-mode floor that matches the current operational state on
    spark-node-2 where only Anthropic upstream auth is known to work
    (see docs/runbooks/litellm-key-rotation.md). Special token ``"all"``
    re-enables every frontier provider (legacy 9-seat behavior).
    """
    raw = os.getenv("COUNCIL_FRONTIER_PROVIDERS_ENABLED", "anthropic")
    parts = {p.strip().lower() for p in raw.split(",") if p.strip()}
    if "google" in parts:
        parts = (parts - {"google"}) | {"gemini"}
    return frozenset(parts)


def _seat_frontier_provider_enabled(seat: int, enabled: frozenset[str]) -> bool:
    """True iff the seat's frontier provider is allowlisted, or if the seat
    routes to a sovereign/local backend (always allowed — gating is for
    frontier-auth contamination only)."""
    if "all" in enabled:
        return True
    seat_provider = SEAT_ROUTING.get(seat, {}).get("provider", "")
    norm = _FRONTIER_PROVIDER_NORMALIZATION.get(seat_provider.upper())
    if norm is None:
        return True
    return norm in enabled


logger.info(
    "legal_council_config  allow_cloud=%s  anthropic=%s  xai=%s  hydra_32b=%s  hydra_120b=%s  vllm_120b=%s",
    ALLOW_CLOUD_LLM, ANTHROPIC_PROXY, XAI_BASE_URL, HYDRA_32B_URL, HYDRA_120B_URL, VLLM_120B_URL,
)

_PII_PATTERNS = [
    (re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"), "[PHONE_REDACTED]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[EMAIL_REDACTED]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN_REDACTED]"),
    (re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), "[CARD_REDACTED]"),
    (re.compile(r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"), "[IP_REDACTED]"),
    (re.compile(r"(?i)\b(?:password|passwd|secret_key|api_key|token)\s*[:=]\s*\S+"), "[CREDENTIAL_REDACTED]"),
]


_capture_log = logging.getLogger("legal_council.capture")


async def _capture_council_training(
    *,
    seat: int,
    persona_name: str,
    model_used: str,
    user_prompt: str,
    response: str,
    # Phase 3 retag — v5 tagging schema (all optional, None = pre-retag)
    served_by_endpoint:  str | None = None,
    served_vector_store: str | None = None,
    escalated_from:      str | None = None,
    sovereign_attempt:   str | None = None,
    teacher_endpoint:    str | None = None,
    teacher_model:       str | None = None,
    task_type:           str | None = None,
    judge_decision:      str | None = None,
    judge_reasoning:     str | None = None,
) -> None:
    """
    Fire-and-forget: write a frontier persona opinion to llm_training_captures
    so the nightly distillation job can use frontier outputs to train local models.
    """
    try:
        import uuid as _uuid
        from sqlalchemy import text as _text
        from backend.core.database import AsyncSessionLocal
        from backend.services.privilege_filter import classify_for_capture, CaptureRoute

        _source_module = f"legal_council_of_9/seat_{seat}/{persona_name}"
        decision = classify_for_capture(
            prompt=user_prompt,
            response=response,
            source_persona=persona_name,
            source_module="legal_council",
        )

        if decision.route == CaptureRoute.BLOCK:
            _capture_log.info("council_capture_blocked reason=%s persona=%s seat=%s",
                              decision.reason, persona_name, seat)
            return

        _capture_id = str(_uuid.uuid4())

        async def _insert() -> None:
            async with AsyncSessionLocal() as session:
                _tag = {
                    "endpoint":    served_by_endpoint[:256]  if served_by_endpoint  else None,
                    "store":       served_vector_store[:64]  if served_vector_store else None,
                    "esc_from":    escalated_from[:256]      if escalated_from       else None,
                    "sov_attempt": sovereign_attempt,
                    "t_endpoint":  teacher_endpoint[:256]    if teacher_endpoint    else None,
                    "t_model":     teacher_model[:128]       if teacher_model       else None,
                    "task":        task_type[:64]            if task_type           else None,
                    "judge_dec":   judge_decision[:16]       if judge_decision      else None,
                    "judge_rsn":   judge_reasoning,
                }
                if decision.route == CaptureRoute.ALLOW:
                    await session.execute(_text("""
                        INSERT INTO llm_training_captures
                            (source_module, model_used, user_prompt, assistant_resp, status,
                             served_by_endpoint, served_vector_store,
                             escalated_from, sovereign_attempt,
                             teacher_endpoint, teacher_model,
                             task_type, judge_decision, judge_reasoning)
                        VALUES
                            (:module, :model, :prompt, :response, 'pending',
                             :endpoint, :store,
                             :esc_from, :sov_attempt,
                             :t_endpoint, :t_model,
                             :task, :judge_dec, :judge_rsn)
                        ON CONFLICT DO NOTHING
                    """), {"module": _source_module[:120], "model": model_used[:120],
                           "prompt": user_prompt[:32_000], "response": response[:32_000],
                           **_tag})
                else:  # RESTRICTED
                    await session.execute(_text("""
                        INSERT INTO restricted_captures
                            (source_module, source_persona, prompt, response,
                             restriction_reason, matched_patterns,
                             served_by_endpoint, served_vector_store,
                             escalated_from, sovereign_attempt,
                             teacher_endpoint, teacher_model,
                             task_type, judge_decision, judge_reasoning)
                        VALUES
                            (:module, :persona, :prompt, :response,
                             :reason, :patterns,
                             :endpoint, :store,
                             :esc_from, :sov_attempt,
                             :t_endpoint, :t_model,
                             :task, :judge_dec, :judge_rsn)
                    """), {"module": _source_module[:120], "persona": persona_name[:128],
                           "prompt": user_prompt[:32_000], "response": response[:32_000],
                           "reason": decision.reason[:256],
                           "patterns": list(decision.matched_patterns),
                           **_tag})
                await session.commit()

                # Phase 4e.1: queue for Godhead labeling (fire-and-forget thread)
                try:
                    from backend.services.labeling_pipeline import queue_capture_for_labeling
                    capture_tbl = (
                        "llm_training_captures"
                        if decision.route == CaptureRoute.ALLOW
                        else "restricted_captures"
                    )
                    queue_capture_for_labeling(
                        capture_id=_capture_id,
                        capture_table=capture_tbl,
                        task_type=(task_type or "legal_reasoning"),
                        user_prompt=user_prompt,
                        sovereign_response=response,
                    )
                except Exception:
                    pass  # never block capture on labeling failure

        asyncio.create_task(_insert())
    except Exception as exc:
        _capture_log.warning("council_training_capture_failed  error=%s", str(exc)[:200])


def _sanitize_for_cloud(text: str) -> str:
    """Strip PII, internal IPs, and credentials before sending to cloud LLMs."""
    result = text
    for pattern, replacement in _PII_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


# ═══════════════════════════════════════════════════════════════════════
# Legal Signal Enum
# ═══════════════════════════════════════════════════════════════════════

class LegalSignal(Enum):
    STRONG_DEFENSE = "STRONG_DEFENSE"
    DEFENSE = "DEFENSE"
    NEUTRAL = "NEUTRAL"
    WEAK = "WEAK"
    VULNERABLE = "VULNERABLE"
    ERROR = "ERROR"


SIGNAL_WEIGHTS = {
    LegalSignal.STRONG_DEFENSE: 1.0,
    LegalSignal.DEFENSE: 0.5,
    LegalSignal.NEUTRAL: 0.0,
    LegalSignal.WEAK: -0.5,
    LegalSignal.VULNERABLE: -1.0,
    LegalSignal.ERROR: 0.0,
}


# ═══════════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class LegalOpinion:
    """Structured opinion from a legal persona."""
    persona_name: str
    seat: int
    slug: str
    event: str
    signal: LegalSignal
    conviction: float
    reasoning: str
    defense_arguments: List[str]
    risk_factors: List[str]
    recommended_actions: List[str]
    timestamp: str
    model_used: str = ""
    elapsed_seconds: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "persona": self.persona_name,
            "seat": self.seat,
            "slug": self.slug,
            "signal": self.signal.value,
            "conviction": self.conviction,
            "reasoning": self.reasoning,
            "defense_arguments": self.defense_arguments,
            "risk_factors": self.risk_factors,
            "recommended_actions": self.recommended_actions,
            "timestamp": self.timestamp,
            "model_used": self.model_used,
            "elapsed_seconds": self.elapsed_seconds,
        }


@dataclass
class LegalPersona:
    """Legal persona loaded from JSON config."""
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
    def load(cls, filepath: str) -> "LegalPersona":
        with open(filepath, "r") as f:
            data = json.load(f)
        vector_collection = data.get("vector_collection", "legal_library_v2")
        _validate_legal_persona_boundary(
            slug=data.get("slug", os.path.basename(filepath)),
            vector_collection=vector_collection,
        )
        return cls(
            name=data["name"],
            slug=data["slug"],
            seat=data.get("seat", 0),
            archetype=data.get("archetype", ""),
            domain=data.get("domain", "legal"),
            god_head_domain=data.get("god_head_domain", "legal"),
            worldview=data.get("worldview", ""),
            bias=data.get("bias", []),
            focus_areas=data.get("focus_areas", []),
            trigger_events=data.get("trigger_events", []),
            godhead_prompt=data.get("godhead_prompt", ""),
            vector_collection=vector_collection,
            created_at=data.get("created_at", ""),
        )

    @classmethod
    def load_all(cls) -> List["LegalPersona"]:
        if not os.path.isdir(PERSONAS_DIR):
            return []
        personas = []
        for fname in sorted(os.listdir(PERSONAS_DIR)):
            if not fname.endswith(".json"):
                continue
            try:
                p = cls.load(os.path.join(PERSONAS_DIR, fname))
                personas.append(p)
            except LegalPersonaBoundaryError:
                raise
            except Exception as e:
                logger.warning("Failed to load persona %s: %s", fname, e)
        personas.sort(key=lambda p: p.seat)
        return personas


class LegalPersonaBoundaryError(RuntimeError):
    """Raised when legal personas attempt to cross into hospitality retrieval."""


def _validate_legal_persona_boundary(*, slug: str, vector_collection: str) -> None:
    if vector_collection not in LEGAL_ALLOWED_VECTOR_COLLECTIONS:
        raise LegalPersonaBoundaryError(
            f"Legal persona '{slug}' attempted to access forbidden vector collection '{vector_collection}'."
        )


# ═══════════════════════════════════════════════════════════════════════
# LLM Inference (Anthropic via Claude Proxy, with HYDRA fallback)
# ═══════════════════════════════════════════════════════════════════════

_REASONING_MODELS = {"qwen3:32b", "gpt-oss:120b", "gpt-oss", "deepseek-r1:70b", "openai/gpt-oss-120b"}


def _extract_content(data: dict) -> str:
    """Extract text from LLM response, preferring content but falling back to reasoning."""
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
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> tuple[str, str]:
    """
    Call an OpenAI-compatible LLM endpoint. Returns (response_text, model_used).
    Falls back through: Primary → HYDRA_120B (Sovereign) → SWARM → empty.
    Injects num_ctx caps for Ollama endpoints to prevent VRAM overrun.
    For Ollama reasoning models, disables internal chain-of-thought via /no_think
    prefix so all tokens go to structured output.
    """
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
                is_vllm = (base_url == VLLM_120B_URL)
                is_local_reasoning = model in _REASONING_MODELS and (is_ollama or is_vllm)
                if is_local_reasoning:
                    effective_user = f"/no_think\n{user_prompt}"

                # Stream by default for sovereign legal-* aliases — matches the
                # BrainClient discipline (PR #280 / Phase A5 §7.2). The Wave 2
                # frontier (Nemotron-3-Super-120B-A12B-NVFP4 TP=2 on spark-3 +
                # spark-4 per ADR-007) carries a longer reasoning prefix on
                # hard prompts than the retired BRAIN-49B (~3.7 tok/s on
                # spark-5 single-node); non-streaming would blow past
                # LiteLLM's request_timeout. Local Ollama / vLLM fallbacks stay
                # non-streaming because the existing fallback path already
                # caps max_tokens for them and doesn't need TTFT discipline.
                use_streaming = (
                    base_url == _LITELLM_BASE
                    and model.startswith("legal-")
                )

                payload: dict[str, Any] = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": effective_user},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if use_streaming:
                    payload["stream"] = True

                if is_ollama:
                    ctx = _OLLAMA_CTX_LIMITS.get(base_url, _OLLAMA_CTX_DEFAULT)
                    payload["options"] = {"num_ctx": ctx}

                if is_vllm:
                    payload["response_format"] = {"type": "json_object"}
                    payload.pop("max_tokens", None)

                if use_streaming:
                    chunks: list[str] = []
                    finish_reason: str | None = None
                    async with client.stream(
                        "POST",
                        f"{base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    ) as resp:
                        if resp.status_code == 200:
                            async for raw_line in resp.aiter_lines():
                                if not raw_line:
                                    continue
                                line = raw_line.strip()
                                if not line.startswith("data:"):
                                    continue
                                data_part = line[5:].strip()
                                if data_part == "[DONE]":
                                    break
                                try:
                                    event = json.loads(data_part)
                                except json.JSONDecodeError:
                                    continue
                                choices = event.get("choices") or []
                                if not choices:
                                    continue
                                delta = choices[0].get("delta") or {}
                                piece = delta.get("content")
                                if piece:
                                    chunks.append(piece)
                                fr = choices[0].get("finish_reason")
                                if fr:
                                    finish_reason = fr
                            if chunks:
                                content = "".join(chunks)
                                return content, model
                            logger.warning(
                                "Primary LLM %s @ %s streamed empty content (finish=%s), falling back",
                                model, base_url, finish_reason,
                            )
                        else:
                            logger.warning(
                                "Primary LLM %s @ %s returned %d on stream open, falling back",
                                model, base_url, resp.status_code,
                            )
                else:
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
                        "Primary LLM %s @ %s returned %d, falling back",
                        model, base_url, resp.status_code,
                    )
            except Exception as e:
                logger.warning("Primary LLM %s failed: %s, falling back", model, e)

            # Fallback: HYDRA_120B (Sovereign Ollama) -- SKIP when primary was
            # also on Sovereign (vLLM or Ollama) to prevent OOM from dual-loading.
            if base_url not in (HYDRA_120B_URL, VLLM_120B_URL):
                try:
                    fb_user = f"/no_think\n{user_prompt}" if HYDRA_MODEL_120B in _REASONING_MODELS else user_prompt
                    # Use reduced max_tokens for local fallback to avoid slow generation
                    local_max_tokens = min(max_tokens, 768)
                    fb_payload: dict[str, Any] = {
                        "model": HYDRA_MODEL_120B,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": fb_user},
                        ],
                        "temperature": temperature,
                        "max_tokens": local_max_tokens,
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
                except Exception as e:
                    logger.error("HYDRA_120B fallback failed: %s", e)

            # Last resort: SWARM (Captain qwen2.5:7b)
            try:
                sw_payload: dict[str, Any] = {
                    "model": SWARM_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": min(max_tokens, 768),   # cap for speed
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
            except Exception as e:
                logger.error("SWARM fallback also failed: %s", e)

    return "", "none"


def _extract_json_block(raw: str) -> dict:
    """Robust JSON extraction that aggressively strips preamble and markdown."""
    cleaned = raw.strip()

    # Fast path: vLLM guided decoding or perfect output.
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass

    # Strip markdown fences if the model wrapped the payload.
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)

    # Aggressively strip any conversational preamble or trailing garbage.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in response")

    cleaned = cleaned[start : end + 1]
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return json.loads(cleaned)


def _sanitize_str(val: str, max_len: int = 5000) -> str:
    """Remove control characters and clamp length for safe SSE serialization."""
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", val)
    return s[:max_len] if len(s) > max_len else s


def _sanitize_str_list(items, max_items: int = 20) -> list[str]:
    if not isinstance(items, list):
        return []
    return [_sanitize_str(str(x), 1000) for x in items[:max_items] if x]


def _parse_opinion(
    persona: LegalPersona,
    event: str,
    raw_text: str,
    model_used: str,
    elapsed: float,
) -> LegalOpinion:
    """Parse LLM JSON response into a LegalOpinion."""
    try:
        data = _extract_json_block(raw_text)

        signal_str = data.get("signal", "NEUTRAL").upper().replace(" ", "_")
        if signal_str in LegalSignal.__members__:
            signal = LegalSignal[signal_str]
        else:
            signal = LegalSignal.NEUTRAL

        return LegalOpinion(
            persona_name=persona.name,
            seat=persona.seat,
            slug=persona.slug,
            event=event,
            signal=signal,
            conviction=min(max(float(data.get("conviction", 0.5)), 0.0), 1.0),
            reasoning=_sanitize_str(str(data.get("reasoning", "No reasoning provided"))),
            defense_arguments=_sanitize_str_list(data.get("defense_arguments", [])),
            risk_factors=_sanitize_str_list(data.get("risk_factors", [])),
            recommended_actions=_sanitize_str_list(data.get("recommended_actions", [])),
            timestamp=datetime.now().isoformat(),
            model_used=model_used,
            elapsed_seconds=round(elapsed, 1),
        )
    except Exception as e:
        logger.warning("Failed to parse opinion for %s: %s — raw[0:300]=%s", persona.name, e, raw_text[:300])
        safe_excerpt = _sanitize_str(raw_text[:200])
        return LegalOpinion(
            persona_name=persona.name,
            seat=persona.seat,
            slug=persona.slug,
            event=event,
            signal=LegalSignal.NEUTRAL,
            conviction=0.5,
            reasoning=f"Analysis completed but response format was non-standard. Excerpt: {safe_excerpt}",
            defense_arguments=[],
            risk_factors=["LLM response required manual extraction"],
            recommended_actions=["Review raw analysis or retry deliberation"],
            timestamp=datetime.now().isoformat(),
            model_used=model_used,
            elapsed_seconds=round(elapsed, 1),
        )


def _make_error_opinion(persona: LegalPersona, error_msg: str, elapsed: float) -> LegalOpinion:
    """Create an ERROR-state opinion when a persona fails entirely."""
    return LegalOpinion(
        persona_name=persona.name,
        seat=persona.seat,
        slug=persona.slug,
        event="error",
        signal=LegalSignal.ERROR,
        conviction=0.0,
        reasoning=f"Persona failed: {error_msg}",
        defense_arguments=[],
        risk_factors=["Persona analysis unavailable — manual review required"],
        recommended_actions=["Retry deliberation or check LLM endpoint health"],
        timestamp=datetime.now().isoformat(),
        model_used="none",
        elapsed_seconds=round(elapsed, 1),
    )


# ═══════════════════════════════════════════════════════════════════════
# Persona Analysis
# ═══════════════════════════════════════════════════════════════════════

async def analyze_with_persona(
    persona: LegalPersona,
    case_brief: str,
    context: str = "",
) -> LegalOpinion:
    """Run a single persona's analysis against the case brief."""
    system_prompt = f"""{persona.godhead_prompt}

YOUR WORLDVIEW:
{persona.worldview}

YOUR BIASES & FOCUS:
{chr(10).join(f'- {b}' for b in persona.bias)}
{chr(10).join(f'- {f}' for f in persona.focus_areas)}

{CITATION_INSTRUCTION}

CRITICAL DIRECTIVE:
You are an automated analytical engine operating on bare-metal hardware. You MUST output your ENTIRE response as a single, valid JSON object.
- DO NOT wrap the JSON in markdown formatting (no ```json).
- DO NOT include conversational filler, greetings, or explanations.
- If you output anything other than raw, parsable JSON, the sovereign matrix will fail.

REQUIRED JSON SCHEMA:
{{
  "signal": "STRONG_DEFENSE" | "DEFENSE" | "NEUTRAL" | "WEAK" | "VULNERABLE",
  "conviction": <float between 0.0 and 1.0>,
  "reasoning": "<your detailed analysis>",
  "defense_arguments": ["<arg1>", "<arg2>"],
  "risk_factors": ["<risk1>", "<risk2>"],
  "recommended_actions": ["<action1>", "<action2>"]
}}
"""

    user_prompt = f"""CASE BRIEF FOR ANALYSIS:
{case_brief}
{f"ADDITIONAL CONTEXT:{chr(10)}{context}" if context else ""}

Execute analysis and return the raw JSON object.
"""

    t0 = time.time()

    # MoE routing: each seat dispatches to its designated provider
    routing = SEAT_ROUTING.get(persona.seat, {})
    provider = routing.get("provider", "HYDRA_120B") if ALLOW_CLOUD_LLM else "HYDRA_120B"

    # PII sanitization gate for cloud-bound prompts
    if provider in _CLOUD_PROVIDERS:
        base_system = _sanitize_for_cloud(system_prompt)
        base_user = _sanitize_for_cloud(user_prompt)
    else:
        base_system = system_prompt
        base_user = user_prompt

    async def _invoke_once(current_system: str, current_user: str) -> tuple[str, str]:
        if provider == "ANTHROPIC" and FRONTIER_GATEWAY_API_KEY:
            return await _call_llm(
                current_system,
                current_user,
                model=ANTHROPIC_MODEL,
                base_url=ANTHROPIC_PROXY,
                api_key=FRONTIER_GATEWAY_API_KEY,
            )
        if provider == "GEMINI" and FRONTIER_GATEWAY_API_KEY:
            return await _call_llm(
                current_system,
                current_user,
                model=GEMINI_MODEL,
                base_url=GEMINI_BASE_URL,
                api_key=FRONTIER_GATEWAY_API_KEY,
            )
        if provider == "XAI" and FRONTIER_GATEWAY_API_KEY:
            return await _call_llm(
                current_system,
                current_user,
                model=XAI_MODEL,
                base_url=XAI_BASE_URL,
                api_key=FRONTIER_GATEWAY_API_KEY,
            )
        if provider == "XAI_FLAGSHIP" and FRONTIER_GATEWAY_API_KEY:
            return await _call_llm(
                current_system,
                current_user,
                model=XAI_MODEL_FLAGSHIP,
                base_url=XAI_BASE_URL,
                api_key=FRONTIER_GATEWAY_API_KEY,
            )
        if provider == "OPENAI" and FRONTIER_GATEWAY_API_KEY:
            return await _call_llm(
                current_system,
                current_user,
                model=OPENAI_MODEL,
                base_url=OPENAI_BASE_URL,
                api_key=FRONTIER_GATEWAY_API_KEY,
            )
        if provider == "DEEPSEEK" and FRONTIER_GATEWAY_API_KEY:
            return await _call_llm(
                current_system,
                current_user,
                model=DEEPSEEK_MODEL,
                base_url=DEEPSEEK_BASE_URL,
                api_key=FRONTIER_GATEWAY_API_KEY,
            )
        if provider == "DEEPSEEK_REASONER" and FRONTIER_GATEWAY_API_KEY:
            # DeepSeek-Reasoner uses chain-of-thought tokens before outputting JSON.
            # Needs max_tokens≥2000 to complete the reasoning + structured answer.
            return await _call_llm(
                current_system,
                current_user,
                model=DEEPSEEK_REASONER_MODEL,
                base_url=DEEPSEEK_BASE_URL,
                api_key=FRONTIER_GATEWAY_API_KEY,
                max_tokens=2500,
            )
        if provider == "ANTHROPIC_OPUS" and FRONTIER_GATEWAY_API_KEY:
            return await _call_llm(
                current_system,
                current_user,
                model=ANTHROPIC_OPUS_MODEL,
                base_url=ANTHROPIC_PROXY,
                api_key=FRONTIER_GATEWAY_API_KEY,
            )
        if provider == "SPARK2":
            return await _call_llm(
                current_system,
                current_user,
                model=SPARK2_MODEL,
                base_url=SPARK2_URL,
            )
        if provider == "SPARK_LOCAL":
            return await _call_llm(
                current_system,
                current_user,
                model=SPARK_LOCAL_MODEL,
                base_url=SPARK_LOCAL_URL,
            )
        if provider == "VLLM_120B":
            return await _call_llm(
                current_system,
                current_user,
                model=VLLM_MODEL_120B,
                base_url=VLLM_120B_URL,
            )
        if provider == "HYDRA_32B":
            return await _call_llm(
                current_system,
                current_user,
                model=HYDRA_MODEL_32B,
                base_url=HYDRA_32B_URL,
            )
        if provider == "HYDRA_120B":
            return await _call_llm(
                current_system,
                current_user,
                model=HYDRA_MODEL_120B,
                base_url=HYDRA_120B_URL,
            )
        if provider == "SWARM":
            return await _call_llm(
                current_system,
                current_user,
                model=SWARM_MODEL,
                base_url=SWARM_URL,
            )
        # Ultimate fallback → Spark2 local (always reachable)
        return await _call_llm(
            current_system,
            current_user,
            model=SPARK2_MODEL,
            base_url=SPARK2_URL,
        )

    repair_hint = (
        "REPAIR_HINT:\n"
        "Your previous response was rejected because it was not a single valid JSON object.\n"
        "Return ONLY raw JSON matching the required schema.\n"
        "Do not include prose, markdown fences, commentary, or any text before or after the JSON object."
    )

    text = ""
    model = "none"
    for attempt in range(1, 4):
        current_user = base_user if attempt == 1 else (
            f"{base_user}\n\n{repair_hint}\n\nINVALID_RESPONSE_EXCERPT:\n{text[:400]}"
        )
        text, model = await _invoke_once(base_system, current_user)
        try:
            _extract_json_block(text)
            # Training capture: write frontier opinion for local model distillation
            if text and provider in _CLOUD_PROVIDERS:
                # Classify task type by seat/persona context (Phase 4e.2)
                try:
                    from backend.services.task_classifier import classify_task_type as _cls
                    _council_task = _cls(
                        source_module=f"legal_council_of_9/seat_{persona.seat}/{persona.name}",
                        prompt=base_user[:600],
                    )
                except Exception:
                    _council_task = "legal_reasoning"

                asyncio.ensure_future(_capture_council_training(
                    seat=persona.seat,
                    persona_name=persona.name,
                    model_used=f"council/{provider.lower()}/{model}",
                    user_prompt=base_user[:16000],
                    response=text[:16000],
                    served_by_endpoint=_NIM_ENDPOINT,   # NIM ClusterIP (audit: 10.43.38.88:8000)
                    served_vector_store=None,             # RAG integration Phase 5a
                    task_type=_council_task,
                ))
            break
        except Exception as exc:
            logger.warning(
                "legal_council_retry_triggered",
                extra={
                    "seat": persona.seat,
                    "persona": persona.name,
                    "attempt": attempt,
                    "provider": provider,
                    "model": model,
                    "error": str(exc)[:200],
                    "raw_excerpt": _sanitize_str(text[:300]),
                },
            )
            if attempt == 3:
                logger.warning(
                    "legal_council_retry_exhausted",
                    extra={
                        "seat": persona.seat,
                        "persona": persona.name,
                        "provider": provider,
                        "model": model,
                    },
                )
                break

    elapsed = time.time() - t0
    logger.info(
        "Seat %d (%s) completed via %s [%s] in %.1fs",
        persona.seat, persona.name, provider, model, elapsed,
    )
    return _parse_opinion(persona, case_brief[:200], text, model, elapsed)


# ═══════════════════════════════════════════════════════════════════════
# Consensus Algorithm
# ═══════════════════════════════════════════════════════════════════════

def compute_consensus(opinions: List[LegalOpinion]) -> Dict[str, Any]:
    """Conviction-weighted consensus across all 9 legal personas."""
    if not opinions:
        return {"error": "No opinions to aggregate"}

    # Filter out ERROR opinions for scoring but include them in counts
    valid = [o for o in opinions if o.signal != LegalSignal.ERROR]
    error_count = len(opinions) - len(valid)

    signal_counts = {s: 0 for s in LegalSignal}
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

    # Devil's Advocate (seat 5) signal is inverted for consensus
    devils_advocate = [op for op in valid if op.seat == 5]
    if devils_advocate:
        da = devils_advocate[0]
        da_inverted_weight = -SIGNAL_WEIGHTS.get(da.signal, 0) * da.conviction
        net_score_adjusted = (weighted_score - SIGNAL_WEIGHTS.get(da.signal, 0) * da.conviction + da_inverted_weight) / n
    else:
        net_score_adjusted = net_score

    if net_score_adjusted >= 0.4:
        consensus = LegalSignal.STRONG_DEFENSE
    elif net_score_adjusted >= 0.15:
        consensus = LegalSignal.DEFENSE
    elif net_score_adjusted > -0.15:
        consensus = LegalSignal.NEUTRAL
    elif net_score_adjusted > -0.4:
        consensus = LegalSignal.WEAK
    else:
        consensus = LegalSignal.VULNERABLE

    defense_count = signal_counts[LegalSignal.STRONG_DEFENSE] + signal_counts[LegalSignal.DEFENSE]
    weak_count = signal_counts[LegalSignal.WEAK] + signal_counts[LegalSignal.VULNERABLE]
    majority = max(signal_counts, key=signal_counts.get)
    agreement_rate = signal_counts[majority] / len(opinions)

    all_defenses = []
    all_risks = []
    all_actions = []
    for op in opinions:
        all_defenses.extend(op.defense_arguments)
        all_risks.extend(op.risk_factors)
        all_actions.extend(op.recommended_actions)

    return {
        "consensus_signal": consensus.value,
        "consensus_conviction": round(avg_conviction, 4),
        "net_score": round(net_score, 4),
        "net_score_adjusted": round(net_score_adjusted, 4),
        "defense_count": defense_count,
        "weak_count": weak_count,
        "neutral_count": signal_counts[LegalSignal.NEUTRAL],
        "error_count": error_count,
        "total_voters": len(opinions),
        "agreement_rate": round(agreement_rate, 4),
        "signal_breakdown": {s.value: c for s, c in signal_counts.items()},
        "top_defense_arguments": _dedupe_top(all_defenses, 10),
        "top_risk_factors": _dedupe_top(all_risks, 10),
        "top_recommended_actions": _dedupe_top(all_actions, 10),
    }


def _dedupe_top(items: List[str], limit: int) -> List[str]:
    seen = set()
    result = []
    for item in items:
        normalized = item.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(item.strip())
        if len(result) >= limit:
            break
    return result


# ═══════════════════════════════════════════════════════════════════════
# Context Freezer (Pillar 2 — Qdrant Evidence Locking)
# ═══════════════════════════════════════════════════════════════════════

# legal_ediscovery holds 859+ vectorised chunks for active cases (indexed by process_vault_upload)
# legal_library has only 3 points (stale/legacy) — use legal_ediscovery for context freezing
LEGAL_COLLECTION = "legal_ediscovery"

# PR G — Council pulls from this collection in addition to LEGAL_COLLECTION when
# COUNCIL_INCLUDE_PRIVILEGED_RETRIEVAL is enabled. Privileged chunks are kept
# physically separate so the storage layer enforces the privileged track, not
# just a payload tag.
PRIVILEGED_COLLECTION = "legal_privileged_communications"

# Warning block appended to deliberation output whenever any privileged chunk
# was retrieved. Wording is exact per PR G spec; if you change it here, also
# update apps/command-center deliberation-panel rendering and the runbook.
FOR_YOUR_EYES_ONLY_WARNING = (
    "⚠️ FOR YOUR EYES ONLY ⚠️\n"
    "This deliberation included attorney-client privileged communications. "
    "Do not use this output in court filings, share with opposing parties, "
    "or quote externally without explicit privilege review. Treat as "
    "internal work product subject to attorney-client privilege."
)


def _council_retrieval_flags() -> tuple[bool, bool]:
    """Read COUNCIL_INCLUDE_PRIVILEGED_RETRIEVAL and COUNCIL_INCLUDE_RELATED_MATTERS
    at *deliberation time* (not at startup). Both default to true. Either env var
    can be flipped to "false" / "0" / "no" to disable mid-flight without a
    restart — emergency containment if a privilege issue surfaces."""
    def _truthy(name: str, default: bool = True) -> bool:
        v = os.environ.get(name, "true" if default else "false").strip().lower()
        return v not in ("false", "0", "no", "off", "")
    return _truthy("COUNCIL_INCLUDE_PRIVILEGED_RETRIEVAL"), _truthy("COUNCIL_INCLUDE_RELATED_MATTERS")


async def _embed_text(text: str) -> Optional[List[float]]:
    """Embed via Ollama OpenAI-compatible /v1/embeddings (backend.core.vector_db).

    Used for legacy 768-dim collections that still ride nomic-embed-text:
    `legal_ediscovery`, `legal_privileged_communications`. Caselaw + library
    queries go through `_embed_legal_query` instead (see Phase A PR #2).
    """
    from backend.core.vector_db import embed_text as _embed_vec

    try:
        vec = await _embed_vec(text[:8000])
        if len(vec) == _cfg.embed_dim:
            return vec
        logger.warning("embed_dim_unexpected  got=%d", len(vec))
    except Exception as e:
        logger.warning("embed_failed  error=%s", str(e)[:200])
    return None


async def _embed_legal_query(text: str) -> Optional[List[float]]:
    """Embed a query for the sovereign legal-embed _v2 collections (caselaw + library).

    Sends `input_type=query` and `encoding_format=float` per the NIM caller
    contract verified in PR #300 §9.5; both are mandatory and the gateway
    will reject HTTP 400 if either is missing/None.

    Returns None on transport / dim-mismatch / auth failure so callers can
    degrade to "no RAG context" rather than crash — matching the failure
    semantics of `_embed_text` above.
    """
    from backend.core.vector_db import LEGAL_EMBED_DIM, embed_legal_query

    try:
        vec = await embed_legal_query(text[:8000])
        if len(vec) == LEGAL_EMBED_DIM:
            return vec
        logger.warning("legal_embed_dim_unexpected  got=%d", len(vec))
    except Exception as e:
        logger.warning("legal_embed_failed  error=%s", str(e)[:200])
    return None


async def freeze_context(
    case_brief: str,
    top_k: int = 20,
    case_slug: Optional[str] = None,
) -> Tuple[List[str], List[str]]:
    """
    Pillar 2: Context Freezing.

    Embeds the case brief, queries the legal_library Qdrant collection,
    and returns the exact (vector_ids, context_chunks) that will be
    injected into every persona's prompt and permanently sealed in the vault.

    On any failure, returns empty lists — deliberation proceeds without
    RAG context rather than crashing.
    """
    logger.info("freeze_context_start  collection=%s  top_k=%d", LEGAL_COLLECTION, top_k)

    query_vec = await _embed_text(case_brief)
    if query_vec is None:
        logger.warning("freeze_context_no_embedding — proceeding without RAG context")
        return [], []

    headers = {"api-key": _cfg.qdrant_api_key} if _cfg.qdrant_api_key else {}
    body: Dict[str, Any] = {
        "vector": query_vec,
        "limit": top_k,
        "with_payload": True,
        "with_vector": False,
    }
    # Filter to the specific case when querying legal_ediscovery
    if case_slug and LEGAL_COLLECTION == "legal_ediscovery":
        body["filter"] = {"must": [{"key": "case_slug", "match": {"value": case_slug}}]}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_cfg.qdrant_url.rstrip('/')}/collections/{LEGAL_COLLECTION}/points/search",
                json=body,
                headers=headers,
            )
            resp.raise_for_status()
            results = resp.json().get("result", [])
    except Exception as e:
        logger.warning("freeze_context_qdrant_failed  error=%s", str(e)[:200])
        return [], []

    vector_ids: List[str] = []
    context_chunks: List[str] = []

    for pt in results:
        point_id = str(pt.get("id", ""))
        payload = pt.get("payload", {})
        text = payload.get("text", "")
        if point_id and text:
            vector_ids.append(point_id)
            source = payload.get("file_name", payload.get("source_file", payload.get("filename", "unknown")))
            context_chunks.append(f"[{source}] {text}")

    logger.info(
        "freeze_context_complete  vectors=%d  chunks=%d  top_score=%.3f",
        len(vector_ids), len(context_chunks),
        results[0].get("score", 0.0) if results else 0.0,
    )
    return vector_ids, context_chunks


async def freeze_privileged_context(
    case_brief: str,
    top_k: int = 10,
    case_slug: Optional[str] = None,
) -> Tuple[List[str], List[str]]:
    """PR G — Pillar 2 sibling: retrieve from legal_privileged_communications.

    Mirrors freeze_context() but targets the privileged collection. Privileged
    chunks are returned with a [PRIVILEGED] header marker so personas (and
    later vault audits) can tell them apart from work-product chunks at a
    glance.

    Returns ([], []) on any failure — same fail-safe behavior as freeze_context.
    """
    logger.info(
        "freeze_privileged_context_start  collection=%s  top_k=%d  case_slug=%s",
        PRIVILEGED_COLLECTION, top_k, case_slug,
    )

    query_vec = await _embed_text(case_brief)
    if query_vec is None:
        return [], []

    headers = {"api-key": _cfg.qdrant_api_key} if _cfg.qdrant_api_key else {}
    body: Dict[str, Any] = {
        "vector": query_vec,
        "limit": top_k,
        "with_payload": True,
        "with_vector": False,
    }
    if case_slug:
        body["filter"] = {"must": [{"key": "case_slug", "match": {"value": case_slug}}]}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_cfg.qdrant_url.rstrip('/')}/collections/{PRIVILEGED_COLLECTION}/points/search",
                json=body,
                headers=headers,
            )
            resp.raise_for_status()
            results = resp.json().get("result", [])
    except Exception as e:
        logger.warning("freeze_privileged_context_qdrant_failed  error=%s", str(e)[:200])
        return [], []

    vector_ids: List[str] = []
    context_chunks: List[str] = []
    for pt in results:
        point_id = str(pt.get("id", ""))
        payload = pt.get("payload", {})
        text = payload.get("text", "")
        if not (point_id and text):
            continue
        vector_ids.append(point_id)
        source = payload.get("file_name", payload.get("source_file", "unknown"))
        domain = payload.get("privileged_counsel_domain") or "unknown-counsel"
        role = payload.get("role") or "unknown-role"
        # Mark every chunk visibly so personas + vault audits can see at a
        # glance that this chunk came from the privileged collection.
        context_chunks.append(
            f"[PRIVILEGED · {domain} · {role}] [{source}] {text}"
        )

    logger.info(
        "freeze_privileged_context_complete  vectors=%d  chunks=%d  case_slug=%s",
        len(vector_ids), len(context_chunks), case_slug,
    )
    return vector_ids, context_chunks


async def _resolve_related_matters_slugs(case_slug: str) -> List[str]:
    """Look up the case's related_matters JSONB array from legal.cases.
    Returns the list of related case_slug strings (excluding the case itself).
    Empty list on any failure or when the column is absent / empty."""
    if not case_slug:
        return []
    try:
        from backend.services.ediscovery_agent import LegacySession
        from sqlalchemy import text as sa_text
        async with LegacySession() as db:
            r = await db.execute(
                sa_text(
                    "SELECT related_matters FROM legal.cases WHERE case_slug = :s"
                ),
                {"s": case_slug},
            )
            row = r.fetchone()
        if not row or not row[0]:
            return []
        raw = row[0]
        # asyncpg returns JSONB as already-deserialized list/dict
        if isinstance(raw, list):
            related = raw
        elif isinstance(raw, str):
            try:
                related = json.loads(raw)
            except (ValueError, TypeError):
                return []
        else:
            return []
        return [s for s in related if isinstance(s, str) and s and s != case_slug]
    except Exception as exc:
        logger.warning("resolve_related_matters_failed  case=%s  err=%s",
                       case_slug, str(exc)[:200])
        return []


def _format_caselaw_citation(payload: Dict[str, Any]) -> str:
    """Render a [CASE LAW: ...] header line from a legal_caselaw point payload."""
    case_name = payload.get("case_name") or "<unknown case>"
    court = payload.get("court") or "<unknown court>"
    date_filed = payload.get("date_filed") or ""
    citation_raw = payload.get("citation")
    if isinstance(citation_raw, list):
        citation = "; ".join(str(c) for c in citation_raw if c) or "no reporter citation"
    else:
        citation = str(citation_raw) if citation_raw else "no reporter citation"
    return f"[CASE LAW: {case_name}, {court} ({date_filed}) — {citation}]"


async def freeze_caselaw_context(
    case_brief: str,
    top_k: int = CASELAW_TOP_K,
) -> Tuple[List[str], List[str]]:
    """
    Retrieve top-K controlling-authority chunks from legal_caselaw for the
    deliberation query. Returns (caselaw_point_refs, context_chunks) where
    each ref is a string of the form "caselaw:{opinion_id}:{chunk_index}"
    so vault consumers can reconstruct which opinions were used without
    touching the vault schema.

    Graceful failure mode: on embed or Qdrant error, returns ([], []) and
    the council proceeds without precedent context rather than crashing.
    """
    logger.info("freeze_caselaw_context_start  collection=%s  top_k=%d", CASELAW_COLLECTION, top_k)

    query_vec = await _embed_legal_query(case_brief)
    if query_vec is None:
        logger.warning("freeze_caselaw_context_no_embedding — proceeding without precedent")
        return [], []

    headers = {"api-key": _cfg.qdrant_api_key} if _cfg.qdrant_api_key else {}
    body: Dict[str, Any] = {
        "vector": query_vec,
        "limit": top_k,
        "with_payload": True,
        "with_vector": False,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_cfg.qdrant_url.rstrip('/')}/collections/{CASELAW_COLLECTION}/points/search",
                json=body,
                headers=headers,
            )
            resp.raise_for_status()
            results = resp.json().get("result", [])
    except Exception as e:
        logger.warning("freeze_caselaw_context_qdrant_failed  error=%s", str(e)[:200])
        return [], []

    refs: List[str] = []
    chunks: List[str] = []
    for pt in results:
        payload = pt.get("payload", {})
        text = payload.get("text_chunk") or payload.get("text") or ""
        opinion_id = payload.get("opinion_id")
        chunk_index = payload.get("chunk_index", 0)
        if not text or opinion_id is None:
            continue
        refs.append(f"caselaw:{opinion_id}:{chunk_index}")
        header = _format_caselaw_citation(payload)
        chunks.append(f"{header}\n{text}")

    logger.info(
        "freeze_caselaw_context_complete  refs=%d  chunks=%d  top_score=%.3f",
        len(refs), len(chunks),
        results[0].get("score", 0.0) if results else 0.0,
    )
    return refs, chunks


def _enforce_context_budget(
    caselaw_chunks: List[str],
    evidence_chunks: List[str],
    budget_tokens: int = CONTEXT_BUDGET_TOKENS,
) -> Tuple[List[str], List[str]]:
    """
    Trim retrieved context so the joined string stays within the char-equivalent
    of budget_tokens. Caselaw (controlling authority) is preserved first; when
    the budget is exceeded, evidence chunks are dropped from the tail until
    the total fits. If caselaw alone already exceeds the budget, caselaw is
    also trimmed from the tail, keeping at least the top-ranked chunk.
    """
    budget_chars = max(1, budget_tokens) * _CHARS_PER_TOKEN

    total = sum(len(c) for c in caselaw_chunks) + sum(len(c) for c in evidence_chunks)
    if total <= budget_chars:
        return caselaw_chunks, evidence_chunks

    evidence_kept: List[str] = []
    running = sum(len(c) for c in caselaw_chunks)
    for chunk in evidence_chunks:
        if running + len(chunk) > budget_chars:
            break
        evidence_kept.append(chunk)
        running += len(chunk)

    if running <= budget_chars:
        return caselaw_chunks, evidence_kept

    caselaw_kept: List[str] = []
    running = 0
    for chunk in caselaw_chunks:
        if caselaw_kept and running + len(chunk) > budget_chars:
            break
        caselaw_kept.append(chunk)
        running += len(chunk)
    return caselaw_kept, []


def assemble_frozen_context(
    caselaw_chunks: List[str],
    evidence_chunks: List[str],
    operator_context: str = "",
) -> str:
    """
    Build the final frozen context string passed to every seat. Order is
    caselaw → evidence → operator_context; sections with no content are
    skipped so empty headers never leak into seat prompts.
    """
    parts: List[str] = []
    if caselaw_chunks:
        parts.append(CASELAW_CONTEXT_HEADER)
        parts.append("\n\n".join(caselaw_chunks))
    if evidence_chunks:
        parts.append(EVIDENCE_CONTEXT_HEADER)
        parts.append("\n\n".join(evidence_chunks))
    if operator_context:
        parts.append("--- OPERATOR CONTEXT ---")
        parts.append(operator_context)
    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════
# Roster Snapshot Builder (Pillar 4 — Hardware & Model Provenance)
# ═══════════════════════════════════════════════════════════════════════

def _build_roster_snapshot() -> Dict[str, Any]:
    """
    Build a frozen snapshot of the MoE roster with exact model versions.

    Merges the NAS roster file with the live SEAT_ROUTING config and
    resolved model version strings so the vault knows exactly which
    models were dispatched.
    """
    nas_roster = load_active_roster()

    model_map = {
        "ANTHROPIC":         ANTHROPIC_MODEL,
        "ANTHROPIC_OPUS":    ANTHROPIC_OPUS_MODEL,
        "OPENAI":            OPENAI_MODEL,
        "XAI":               XAI_MODEL,
        "XAI_FLAGSHIP":      XAI_MODEL_FLAGSHIP,
        "DEEPSEEK":          DEEPSEEK_MODEL,
        "DEEPSEEK_REASONER": DEEPSEEK_REASONER_MODEL,
        "GEMINI":            GEMINI_MODEL,
        "HYDRA":             HYDRA_MODEL,
        "HYDRA_32B":         HYDRA_MODEL_32B,
        "HYDRA_120B":        HYDRA_MODEL_120B,
        "VLLM_120B":         VLLM_MODEL_120B,
        "SWARM":             SWARM_MODEL,
    }

    seats = []
    for seat_num, routing in SEAT_ROUTING.items():
        provider = routing["provider"] if ALLOW_CLOUD_LLM else "HYDRA_120B"
        model_id = model_map.get(provider, HYDRA_MODEL_120B)
        seats.append({
            "seat": seat_num,
            "role": routing["role"],
            "provider": provider,
            "model_id": model_id,
            "cloud_allowed": ALLOW_CLOUD_LLM,
        })

    return {
        "roster_version": nas_roster.get("roster_version", "unknown"),
        "snapshot_time": datetime.now().isoformat(),
        "total_seats": len(seats),
        "seats": seats,
    }


# ═══════════════════════════════════════════════════════════════════════
# Council Session (SSE Streaming)
# ═══════════════════════════════════════════════════════════════════════

_active_sessions: Dict[str, Dict] = {}


def get_session(session_id: str) -> Optional[Dict]:
    return _active_sessions.get(session_id)


async def build_case_deliberation_payload(case_slug: str) -> dict[str, Any]:
    from backend.services.legal_case_graph import get_case_graph_snapshot
    from backend.services.legal_chronology import get_chronology

    async with AsyncSessionLocal() as db:
        snapshot = await get_case_graph_snapshot(db, case_slug=case_slug)
        timeline = await get_chronology(db, case_slug)

    nodes = snapshot.get("nodes", [])
    edges = snapshot.get("edges", [])
    node_lines: list[str] = []
    label_by_id: dict[str, str] = {}
    for node in nodes:
        label = node.label if hasattr(node, "label") else node.get("label", "?")
        entity_type = node.entity_type if hasattr(node, "entity_type") else node.get("entity_type", "?")
        node_id = str(node.id if hasattr(node, "id") else node.get("id", "?"))
        label_by_id[node_id] = label
        node_lines.append(f"[{entity_type}] {label}")

    edge_lines: list[str] = []
    for edge in edges:
        source_id = str(edge.source_node_id if hasattr(edge, "source_node_id") else edge.get("source_node_id", "?"))
        target_id = str(edge.target_node_id if hasattr(edge, "target_node_id") else edge.get("target_node_id", "?"))
        relationship = edge.relationship_type if hasattr(edge, "relationship_type") else edge.get("relationship_type", "?")
        edge_lines.append(f"{label_by_id.get(source_id, source_id)} --({relationship})--> {label_by_id.get(target_id, target_id)}")

    chronology_lines = [
        f"{event.get('event_date', '?')}: {event.get('event_description', '')}"
        for event in timeline
    ]
    case_brief = (
        f"Case: {case_slug}\n\n"
        f"ENTITIES:\n" + "\n".join(node_lines) + "\n\n"
        f"RELATIONSHIPS:\n" + "\n".join(edge_lines) + "\n\n"
        f"CHRONOLOGY:\n" + "\n".join(chronology_lines)
    )
    return {
        "case_brief": case_brief,
        "context": f"Graph: {len(nodes)} entities, {len(edges)} edges. Timeline: {len(timeline)} events.",
        "case_slug": case_slug,
        "trigger_type": "GLASS_DELIBERATE",
    }


async def run_council_deliberation(
    session_id: str,
    case_brief: str,
    context: str = "",
    progress_callback=None,
    case_slug: str = "",
    case_number: str = "",
    trigger_type: str = "MANUAL_RUN",
):
    """
    Run all 9 legal personas with semaphore-throttled concurrency.
    Updates _active_sessions with progress and streams via callback.

    Verifiable Intelligence Engine integration:
        1. Freezes Qdrant context (vector UUIDs + text chunks)
        2. Captures MoE roster snapshot with exact model versions
        3. After consensus, vaults the entire event with SHA-256 signature
        4. Emits context_frozen and vaulted SSE events

    CRITICAL: Every persona MUST emit a persona_complete event, even on
    failure. A missing event deadlocks the SSE stream.
    """
    deliberation_start = time.time()

    personas = LegalPersona.load_all()
    if not personas:
        _active_sessions[session_id] = {
            "status": "error",
            "error": "No legal personas found",
        }
        if progress_callback:
            await progress_callback({
                "type": "error",
                "message": "No legal personas found in " + PERSONAS_DIR,
            })
        return

    # ── Frontier-provider gating (degraded-mode safeguard) ───────────────
    # Skip seats whose frontier provider is not allowlisted. This prevents
    # silent fallback to local Ollama poisoning llm_training_captures with
    # HYDRA outputs disguised as frontier consensus when an upstream
    # provider's auth is broken at the gateway.
    enabled_providers = _get_enabled_frontier_providers()
    active_personas: List[LegalPersona] = []
    skipped_personas: List[LegalPersona] = []
    for _p in personas:
        (active_personas if _seat_frontier_provider_enabled(_p.seat, enabled_providers)
         else skipped_personas).append(_p)
    if skipped_personas:
        logger.warning(
            "council_seats_skipped_disabled_provider",
            extra={
                "skipped_count": len(skipped_personas),
                "active_count": len(active_personas),
                "enabled_providers": sorted(enabled_providers),
                "skipped_seats": [
                    {
                        "seat":     _p.seat,
                        "persona":  _p.name,
                        "provider": SEAT_ROUTING.get(_p.seat, {}).get("provider"),
                    }
                    for _p in skipped_personas
                ],
            },
        )
        if progress_callback:
            await progress_callback({
                "type": "seats_skipped",
                "skipped_count": len(skipped_personas),
                "active_count": len(active_personas),
                "enabled_providers": sorted(enabled_providers),
            })
    if not active_personas:
        _active_sessions[session_id] = {
            "status": "error",
            "error": "All Council seats disabled by COUNCIL_FRONTIER_PROVIDERS_ENABLED",
        }
        if progress_callback:
            await progress_callback({
                "type": "error",
                "message": "All Council seats disabled by COUNCIL_FRONTIER_PROVIDERS_ENABLED — "
                           f"enabled={sorted(enabled_providers)}, no seat routes match",
            })
        return
    personas = active_personas

    # ── Pillar 2: Context Freezing — evidence + controlling authority ──
    evidence_vector_ids, evidence_chunks_raw = await freeze_context(
        case_brief, top_k=20, case_slug=case_slug or None,
    )
    caselaw_refs, caselaw_chunks_raw = await freeze_caselaw_context(
        case_brief, top_k=CASELAW_TOP_K,
    )

    # Enforce retrieved-context token budget (caselaw-first preservation).
    caselaw_chunks, evidence_chunks = _enforce_context_budget(
        caselaw_chunks_raw, evidence_chunks_raw, CONTEXT_BUDGET_TOKENS,
    )

    # ── PR G: privileged retrieval + related_matters expansion ────────
    # Both flags are read NOW (not at module load) so an operator can flip
    # them off mid-flight via env var without a backend restart — emergency
    # containment if a privilege issue surfaces.
    include_privileged, include_related_matters = _council_retrieval_flags()

    # Expand the case_slug list with related_matters if enabled.
    case_slugs_for_retrieval: List[str] = [case_slug] if case_slug else []
    related_slugs: List[str] = []
    if include_related_matters and case_slug:
        related_slugs = await _resolve_related_matters_slugs(case_slug)
        case_slugs_for_retrieval.extend(related_slugs)

    privileged_vector_ids: List[str] = []
    privileged_chunks: List[str] = []
    if include_privileged:
        for slug_for_priv in case_slugs_for_retrieval:
            v_ids, chunks = await freeze_privileged_context(
                case_brief, top_k=10, case_slug=slug_for_priv,
            )
            privileged_vector_ids.extend(v_ids)
            privileged_chunks.extend(chunks)

    contains_privileged: bool = len(privileged_chunks) > 0

    # Wrap progress_callback so EVERY downstream event automatically carries
    # the contains_privileged flag (per PR G spec — UI needs to render the
    # FOR YOUR EYES ONLY warning the moment a privileged chunk is retrieved,
    # not just at end-of-deliberation). Existing callback dicts are left
    # alone; the wrapper only sets the key when not already present.
    _orig_progress_callback = progress_callback
    if _orig_progress_callback is not None:
        async def _privilege_aware_callback(event: Dict[str, Any]) -> None:
            event.setdefault("contains_privileged", contains_privileged)
            await _orig_progress_callback(event)
        progress_callback = _privilege_aware_callback

    frozen_context = assemble_frozen_context(caselaw_chunks, evidence_chunks, context)
    if privileged_chunks:
        # Append privileged chunks to the frozen context so personas have
        # them in their working set for this deliberation. They are visibly
        # marked with [PRIVILEGED · domain · role] tags by
        # freeze_privileged_context.
        priv_block = "\n\n".join(privileged_chunks)
        frozen_context = (
            f"{frozen_context}\n\n=== PRIVILEGED COMMUNICATIONS ===\n{priv_block}"
        )

    # Vault receives both sets of identifiers so audits can verify citation
    # grounding. Caselaw refs are prefixed "caselaw:{opinion_id}:{chunk_index}".
    # Privileged vector ids are recorded too — vault is internal to Fortress
    # and is allowed to know which privileged points fed a deliberation.
    vector_ids = list(evidence_vector_ids) + list(caselaw_refs) + list(privileged_vector_ids)
    context_chunks = list(caselaw_chunks) + list(evidence_chunks) + list(privileged_chunks)

    if progress_callback:
        await progress_callback({
            "type": "context_frozen",
            "vector_count": len(evidence_vector_ids),
            "chunk_count": len(evidence_chunks),
            "collection": LEGAL_COLLECTION,
            "caselaw_ref_count": len(caselaw_refs),
            "caselaw_chunk_count": len(caselaw_chunks),
            "caselaw_collection": CASELAW_COLLECTION,
            "context_budget_tokens": CONTEXT_BUDGET_TOKENS,
            # PR G — privileged retrieval + related-matters telemetry
            "privileged_vector_count": len(privileged_vector_ids),
            "privileged_chunk_count": len(privileged_chunks),
            "privileged_collection": PRIVILEGED_COLLECTION,
            "include_privileged_retrieval": include_privileged,
            "include_related_matters": include_related_matters,
            "related_matters_slugs": related_slugs,
        })

    # ── Pillar 4: Roster Snapshot ─────────────────────────────────────
    roster_snapshot = _build_roster_snapshot()

    _active_sessions[session_id] = {
        "status": "deliberating",
        "session_id": session_id,
        "case_brief": case_brief[:200],
        "personas_total": len(personas),
        "personas_completed": 0,
        "opinions": [],
        "started_at": datetime.now().isoformat(),
        "vector_count": len(vector_ids),
    }

    if progress_callback:
        await progress_callback({
            "type": "status",
            "message": f"Council of 9 convened. {len(personas)} legal personas deliberating "
                       f"(max 3 concurrent, {PERSONA_TIMEOUT_SECONDS}s timeout per seat). "
                       f"{len(vector_ids)} evidence vectors frozen.",
            "personas_total": len(personas),
        })

    opinions: List[LegalOpinion] = []

    async def _analyze_and_track(persona: LegalPersona):
        """
        Analyze a single persona with strict error handling.
        GUARANTEE: This function always emits persona_start AND persona_complete.
        It never raises — all exceptions are caught and converted to ERROR opinions.
        """
        t0 = time.time()

        if progress_callback:
            await progress_callback({
                "type": "persona_start",
                "seat": persona.seat,
                "name": persona.name,
                "slug": persona.slug,
                "archetype": persona.archetype,
            })

        try:
            opinion = await asyncio.wait_for(
                analyze_with_persona(persona, case_brief, frozen_context),
                timeout=PERSONA_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            elapsed = time.time() - t0
            logger.error(
                "Persona %s (seat %d) TIMED OUT after %.1fs",
                persona.name, persona.seat, elapsed,
            )
            opinion = _make_error_opinion(
                persona,
                f"Analysis timed out after {PERSONA_TIMEOUT_SECONDS}s",
                elapsed,
            )
        except Exception as exc:
            elapsed = time.time() - t0
            logger.error(
                "Persona %s (seat %d) CRASHED: %s",
                persona.name, persona.seat, exc,
                exc_info=True,
            )
            opinion = _make_error_opinion(
                persona,
                f"{type(exc).__name__}: {str(exc)[:200]}",
                elapsed,
            )

        opinions.append(opinion)

        _active_sessions[session_id]["personas_completed"] = len(opinions)
        _active_sessions[session_id]["opinions"] = [o.to_dict() for o in opinions]

        if progress_callback:
            await progress_callback({
                "type": "persona_complete",
                "seat": persona.seat,
                "name": persona.name,
                "slug": persona.slug,
                "opinion": opinion.to_dict(),
                "personas_completed": len(opinions),
                "personas_total": len(personas),
            })

    # Fan out with semaphore-throttled concurrency.
    # return_exceptions=False because _analyze_and_track never raises.
    tasks = [_analyze_and_track(p) for p in personas]
    await asyncio.gather(*tasks)

    opinions.sort(key=lambda o: o.seat)

    consensus = compute_consensus(opinions)
    elapsed = time.time() - deliberation_start

    result = {
        "status": "complete",
        "session_id": session_id,
        "case_brief": case_brief[:200],
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "opinions": [o.to_dict() for o in opinions],
        **consensus,
    }

    # PR G — surface the privilege state on the final result + append the
    # FOR YOUR EYES ONLY warning block when any privileged chunk was retrieved.
    # Both the structured flag and the warning text are needed: the structured
    # flag drives UI rendering, the text block ensures any rendered/exported
    # surface (PDF, copy-paste, downstream pipeline) carries the warning.
    result["contains_privileged"] = contains_privileged
    if contains_privileged:
        result["privileged_warning"] = FOR_YOUR_EYES_ONLY_WARNING
        existing_summary = result.get("consensus_summary") or ""
        result["consensus_summary"] = (
            (existing_summary + "\n\n" if existing_summary else "")
            + FOR_YOUR_EYES_ONLY_WARNING
        )

    # ── Pillar 3 + 4: Cryptographic Vault ─────────────────────────────
    event_id = None
    sha256_sig = None
    try:
        seat_opinion_dicts = [o.to_dict() for o in opinions]
        execution_time_ms = int(elapsed * 1000)

        loop = asyncio.get_running_loop()
        event_id, sha256_sig = await loop.run_in_executor(
            None,
            vault_deliberation,
            case_slug or "unspecified",
            case_number or None,
            trigger_type,
            vector_ids,
            context_chunks,
            case_brief,
            roster_snapshot,
            seat_opinion_dicts,
            consensus,
            execution_time_ms,
        )

        result["event_id"] = event_id
        result["sha256_signature"] = sha256_sig

        logger.info(
            "deliberation_vaulted  event_id=%s  signature=%s  elapsed_ms=%d",
            event_id, sha256_sig[:16], execution_time_ms,
        )
    except Exception as exc:
        logger.error("vault_write_failed  error=%s", exc, exc_info=True)
        result["vault_error"] = str(exc)[:200]

    _active_sessions[session_id] = result

    if progress_callback:
        await progress_callback({
            "type": "consensus",
            **consensus,
            "elapsed_seconds": round(elapsed, 1),
        })

        if event_id and sha256_sig:
            await progress_callback({
                "type": "vaulted",
                "event_id": event_id,
                "sha256_signature": sha256_sig,
                "vector_count": len(vector_ids),
                "execution_time_ms": int(elapsed * 1000),
            })

        await progress_callback({"type": "done", **result})

    return result


def list_personas_summary() -> List[Dict]:
    """Return summary info for all legal personas."""
    personas = LegalPersona.load_all()
    return [
        {
            "slug": p.slug,
            "name": p.name,
            "seat": p.seat,
            "archetype": p.archetype,
            "worldview": p.worldview[:200],
            "bias": p.bias,
            "focus_areas": p.focus_areas,
            "god_head_domain": p.god_head_domain,
        }
        for p in personas
    ]
