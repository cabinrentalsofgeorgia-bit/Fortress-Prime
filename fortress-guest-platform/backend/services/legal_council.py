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
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

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

ANTHROPIC_PROXY = os.getenv("ANTHROPIC_PROXY_URL", "http://localhost:5100/v1")
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/",
)
HYDRA_URL = os.getenv("HYDRA_FALLBACK_URL", "http://192.168.0.100/hydra/v1")
SWARM_URL = os.getenv("SWARM_URL", "http://192.168.0.100/v1")

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
HYDRA_MODEL = os.getenv("HYDRA_MODEL", "deepseek-r1:70b")
SWARM_MODEL = os.getenv("SWARM_MODEL", "qwen2.5:7b")

ALLOW_CLOUD_LLM = os.getenv("ALLOW_CLOUD_LLM", "false").lower() == "true"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_AI_API_KEY", ""))

# MoE seat-to-provider routing: distributes load across Anthropic, Gemini, and local DGX
# to prevent single-provider rate-limit crashes.
SEAT_ROUTING = {
    1: {"provider": "ANTHROPIC", "role": "The Senior Litigator"},
    2: {"provider": "ANTHROPIC", "role": "The Contract Auditor"},
    3: {"provider": "GEMINI",    "role": "The Statutory Scholar"},
    4: {"provider": "SWARM",     "role": "The E-Discovery Forensic"},
    5: {"provider": "ANTHROPIC", "role": "The Devil's Advocate"},
    6: {"provider": "SWARM",     "role": "The Compliance Officer"},
    7: {"provider": "HYDRA",     "role": "The Local Counsel"},
    8: {"provider": "GEMINI",    "role": "The Risk Assessor"},
    9: {"provider": "HYDRA",     "role": "The Chief Justice"},
}

# With MoE distribution: Anthropic=3, Gemini=2, HYDRA=2, SWARM=2
# Each provider can handle its share without rate-limit pressure.
_LLM_SEMAPHORE = asyncio.Semaphore(9)

# Per-persona hard timeout matches GODHEAD 300s ceiling for deep reasoning seats
PERSONA_TIMEOUT_SECONDS = 300

HTTPX_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)

logger.info(
    "legal_council_config  allow_cloud=%s  anthropic_proxy=%s  hydra=%s  swarm=%s",
    ALLOW_CLOUD_LLM, ANTHROPIC_PROXY, HYDRA_URL, SWARM_URL,
)


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
            vector_collection=data.get("vector_collection", "legal_library"),
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
            except Exception as e:
                logger.warning("Failed to load persona %s: %s", fname, e)
        personas.sort(key=lambda p: p.seat)
        return personas


# ═══════════════════════════════════════════════════════════════════════
# LLM Inference (Anthropic via Claude Proxy, with HYDRA fallback)
# ═══════════════════════════════════════════════════════════════════════

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
    Falls back through: Primary → HYDRA → SWARM → empty.
    Respects the semaphore for concurrency control.
    """
    if not model:
        model = ANTHROPIC_MODEL
    if not base_url:
        base_url = ANTHROPIC_PROXY

    async with _LLM_SEMAPHORE:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
            # Primary: specified endpoint (Anthropic proxy or HYDRA)
            try:
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }

                resp = await client.post(
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        return content, model

                logger.warning(
                    "Primary LLM %s returned %d, falling back to HYDRA",
                    model, resp.status_code,
                )
            except Exception as e:
                logger.warning("Primary LLM %s failed: %s, falling back to HYDRA", model, e)

            # Fallback: HYDRA (R1-70B via Nginx LB)
            if base_url != HYDRA_URL:
                try:
                    payload = {
                        "model": HYDRA_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                    resp = await client.post(
                        f"{HYDRA_URL}/chat/completions",
                        json=payload,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if content:
                            return content, f"HYDRA ({HYDRA_MODEL})"
                except Exception as e:
                    logger.error("HYDRA fallback failed: %s", e)

            # Last resort: SWARM
            try:
                payload = {
                    "model": SWARM_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                resp = await client.post(
                    f"{SWARM_URL}/chat/completions",
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        return content, f"SWARM ({SWARM_MODEL})"
            except Exception as e:
                logger.error("SWARM fallback also failed: %s", e)

    return "", "none"


def _extract_json_block(raw: str) -> dict:
    """Robust JSON extraction that handles markdown fences and nested braces."""
    cleaned = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    else:
        start = cleaned.find("{")
        if start == -1:
            raise ValueError("No JSON object found in response")
        depth, end = 0, start
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
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

Your worldview:
{persona.worldview}

Your biases and focus:
{chr(10).join(f'- {b}' for b in persona.bias)}

Focus areas:
{chr(10).join(f'- {f}' for f in persona.focus_areas)}
"""

    user_prompt = f"""CASE BRIEF FOR ANALYSIS:
{case_brief}

{f"ADDITIONAL CONTEXT:{chr(10)}{context}" if context else ""}

Analyze this case through your specialized lens and provide your assessment.

Format your response as JSON:
{{
  "signal": "STRONG_DEFENSE | DEFENSE | NEUTRAL | WEAK | VULNERABLE",
  "conviction": 0.85,
  "reasoning": "Your detailed analysis...",
  "defense_arguments": ["argument 1", "argument 2"],
  "risk_factors": ["risk 1", "risk 2"],
  "recommended_actions": ["action 1", "action 2"]
}}
"""

    t0 = time.time()

    # MoE routing: each seat dispatches to its designated provider
    routing = SEAT_ROUTING.get(persona.seat, {})
    provider = routing.get("provider", "HYDRA") if ALLOW_CLOUD_LLM else "HYDRA"

    if provider == "ANTHROPIC":
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        text, model = await _call_llm(
            system_prompt, user_prompt,
            model=ANTHROPIC_MODEL,
            base_url=ANTHROPIC_PROXY,
            api_key=api_key,
        )
    elif provider == "GEMINI" and GEMINI_API_KEY:
        text, model = await _call_llm(
            system_prompt, user_prompt,
            model=GEMINI_MODEL,
            base_url=GEMINI_BASE_URL,
            api_key=GEMINI_API_KEY,
        )
    elif provider == "SWARM":
        text, model = await _call_llm(
            system_prompt, user_prompt,
            model=SWARM_MODEL,
            base_url=SWARM_URL,
        )
    else:
        text, model = await _call_llm(
            system_prompt, user_prompt,
            model=HYDRA_MODEL,
            base_url=HYDRA_URL,
        )

    elapsed = time.time() - t0
    logger.info(
        "Seat %d (%s) completed via %s in %.1fs",
        persona.seat, persona.name, provider, elapsed,
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

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
EMBED_URL = os.getenv("EMBED_URL", "http://192.168.0.100/api/embeddings")
EMBED_MODEL = "nomic-embed-text"
LEGAL_COLLECTION = "legal_library"


async def _embed_text(text: str) -> Optional[List[float]]:
    """Embed text via nomic-embed-text through the Nginx LB."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(
                EMBED_URL,
                json={"model": EMBED_MODEL, "prompt": text[:8000]},
            )
            resp.raise_for_status()
            vec = resp.json().get("embedding", [])
            if len(vec) >= 384:
                return vec
            logger.warning("embed_dim_unexpected  got=%d", len(vec))
        except Exception as e:
            logger.warning("embed_failed_lb  error=%s", str(e)[:200])

        # Fallback: direct Ollama on Captain
        try:
            resp = await client.post(
                "http://localhost:11434/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text[:8000]},
            )
            resp.raise_for_status()
            vec = resp.json().get("embedding", [])
            if len(vec) >= 384:
                return vec
        except Exception as e:
            logger.error("embed_failed_all  error=%s", str(e)[:200])
    return None


async def freeze_context(
    case_brief: str,
    top_k: int = 20,
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

    headers = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}
    body = {
        "vector": query_vec,
        "limit": top_k,
        "with_payload": True,
        "with_vector": False,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{QDRANT_URL}/collections/{LEGAL_COLLECTION}/points/search",
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
            source = payload.get("source_file", payload.get("filename", "unknown"))
            context_chunks.append(f"[{source}] {text}")

    logger.info(
        "freeze_context_complete  vectors=%d  chunks=%d  top_score=%.3f",
        len(vector_ids), len(context_chunks),
        results[0].get("score", 0.0) if results else 0.0,
    )
    return vector_ids, context_chunks


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
        "ANTHROPIC": ANTHROPIC_MODEL,
        "GEMINI": GEMINI_MODEL,
        "HYDRA": HYDRA_MODEL,
        "SWARM": SWARM_MODEL,
    }

    seats = []
    for seat_num, routing in SEAT_ROUTING.items():
        provider = routing["provider"] if ALLOW_CLOUD_LLM else "HYDRA"
        model_id = model_map.get(provider, HYDRA_MODEL)
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

    # ── Pillar 2: Context Freezing ────────────────────────────────────
    vector_ids, context_chunks = await freeze_context(case_brief, top_k=20)

    frozen_context = "\n\n".join(context_chunks) if context_chunks else context
    if context and context_chunks:
        frozen_context = f"{context}\n\n--- RETRIEVED EVIDENCE ---\n\n{frozen_context}"

    if progress_callback:
        await progress_callback({
            "type": "context_frozen",
            "vector_count": len(vector_ids),
            "chunk_count": len(context_chunks),
            "collection": LEGAL_COLLECTION,
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
