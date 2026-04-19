"""
judge_runtime.py — Phase 4e.3 judge tier runtime (Ollama-LoRA served).

Evaluates sovereign responses inline via task-type specialized judge models.
Per-task latency budgets (Path C, v5 decision #11). Failure modes never
block the response path.

JUDGE_ENABLED=false (default) → zero overhead, judge skipped entirely.

Per-task timeout budgets (_JUDGE_TIMEOUTS):
  Legal tasks  (high stakes, low volume)  → 1000 ms
  VRS tasks    (low stakes, high volume)  → 200 ms
  Code/market  (medium)                   → 300–500 ms
  Unknown task_type                       → JUDGE_TIMEOUT_MS env (default 200 ms)

_JUDGE_MAP is_active flag:
  False (default) → no judge trained yet → confident / no_judge_for_task_type
  True            → judge deployed, will call Ollama inline

Failure handling:
  timeout        → uncertain  (response may be fine, judge was slow)
  unreachable    → confident  (fail-open: serve sovereign response)
  malformed JSON → uncertain  (flag for QC)
  no judge yet   → confident  (expected state until judges trained)
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Literal, Optional

import httpx
from pydantic import BaseModel

log = logging.getLogger("judge_runtime")

JUDGE_ENABLED    = os.getenv("JUDGE_ENABLED",    "false").lower() == "true"
JUDGE_TIMEOUT_MS = int(os.getenv("JUDGE_TIMEOUT_MS", "200"))  # fallback for unknown task types

# Per-task latency budgets (ms). Legal tasks justify higher latency due to high stakes
# per query and low volume. VRS tasks need sub-200ms to stay off the hot path.
# Unknown task types fall back to JUDGE_TIMEOUT_MS (env default 200ms).
# v5 Decision #11 / Path C.
_JUDGE_TIMEOUTS: dict[str, int] = {
    # Legal (spark-1, qwen2.5:32b) — high stakes, low volume
    "legal_reasoning":   1000,
    "brief_drafting":    1000,
    "legal_citations":   1000,
    "contract_analysis": 1000,
    # VRS (spark-4, qwen2.5:7b) — low stakes, high volume
    "vrs_concierge":     200,
    "vrs_ota_response":  200,
    # Business intelligence
    "pricing_math":      300,
    "real_time":         300,
    "market_research":   500,
    "acquisitions_analysis": 500,
    # Code (spark-2, qwen2.5:7b)
    "code_generation":   500,
    "code_refactoring":  500,
    "code_debugging":    500,
    # Vision (spark-3, qwen2.5:7b)
    "vision_photo":      500,
    "vision_damage":     500,
}

# task_type → judge routing config.
# is_active=False: placeholder — no judge trained yet. Returns confident/no_judge_for_task_type.
# is_active=True:  judge deployed on target_node, will be called inline.
# All entries start is_active=False until training data accumulates and a judge is deployed.
_JUDGE_MAP: dict[str, dict] = {
    # VRS judges — spark-4 (192.168.0.106), qwen2.5:7b base
    "vrs_concierge":    {"judge_model": "vrs_concierge_judge",    "target_node": "192.168.0.106", "base_model": "qwen2.5:7b",  "is_active": False},
    "vrs_ota_response": {"judge_model": "vrs_ota_judge",          "target_node": "192.168.0.106", "base_model": "qwen2.5:7b",  "is_active": False},
    "pricing_math":     {"judge_model": "pricing_math_judge",     "target_node": "192.168.0.106", "base_model": "qwen2.5:7b",  "is_active": False},
    "market_research":  {"judge_model": "market_research_judge",  "target_node": "192.168.0.106", "base_model": "qwen2.5:7b",  "is_active": False},
    "real_time":        {"judge_model": "real_time_judge",        "target_node": "192.168.0.106", "base_model": "qwen2.5:7b",  "is_active": False},
    # Legal judges — spark-1 (192.168.0.104), qwen2.5:32b base (Path C)
    "legal_reasoning":   {"judge_model": "legal_reasoning_judge",   "target_node": "192.168.0.104", "base_model": "qwen2.5:32b", "is_active": False},
    "brief_drafting":    {"judge_model": "brief_drafting_judge",    "target_node": "192.168.0.104", "base_model": "qwen2.5:32b", "is_active": False},
    "legal_citations":   {"judge_model": "legal_citations_judge",   "target_node": "192.168.0.104", "base_model": "qwen2.5:32b", "is_active": False},
    "contract_analysis": {"judge_model": "contract_analysis_judge", "target_node": "192.168.0.104", "base_model": "qwen2.5:32b", "is_active": False},
    "acquisitions_analysis": {"judge_model": "acquisitions_analysis_judge", "target_node": "192.168.0.104", "base_model": "qwen2.5:32b", "is_active": False},
    # Code judges — spark-2 (192.168.0.100), qwen2.5:7b base
    "code_generation":  {"judge_model": "code_generation_judge",  "target_node": "192.168.0.100", "base_model": "qwen2.5:7b",  "is_active": False},
    "code_refactoring": {"judge_model": "code_refactoring_judge", "target_node": "192.168.0.100", "base_model": "qwen2.5:7b",  "is_active": False},
    "code_debugging":   {"judge_model": "code_debugging_judge",   "target_node": "192.168.0.100", "base_model": "qwen2.5:7b",  "is_active": False},
    # Vision judges — spark-3 (192.168.0.105), qwen2.5:7b base
    "vision_damage":    {"judge_model": "vision_analysis_judge",  "target_node": "192.168.0.105", "base_model": "qwen2.5:7b",  "is_active": False},
    "vision_photo":     {"judge_model": "vision_analysis_judge",  "target_node": "192.168.0.105", "base_model": "qwen2.5:7b",  "is_active": False},
}

_USER_PROMPT = (
    "Prompt: {prompt}\n\n"
    "Response: {response}\n\n"
    'Evaluate quality. Return JSON: {{"decision": "confident|uncertain|escalate", "reasoning": "..."}}'
)


class JudgeDecision(BaseModel):
    decision:    Literal["confident", "uncertain", "escalate"]
    reasoning:   str
    judge_model: str
    latency_ms:  int


def _parse(raw: str, model: str, latency_ms: int) -> JudgeDecision:
    """Parse judge JSON output. Falls back to uncertain on parse failure."""
    raw = raw.strip()
    # Try JSON parse first (expected format)
    try:
        # Handle responses that wrap JSON in markdown
        if "```" in raw:
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            raw   = raw[start:end] if start >= 0 and end > start else raw
        data = json.loads(raw)
        decision = data.get("decision", "").lower()
        if decision not in ("confident", "uncertain", "escalate"):
            raise ValueError(f"invalid decision: {decision!r}")
        return JudgeDecision(
            decision=decision,  # type: ignore[arg-type]
            reasoning=str(data.get("reasoning", ""))[:500],
            judge_model=model,
            latency_ms=latency_ms,
        )
    except (json.JSONDecodeError, ValueError, KeyError):
        pass

    # Fallback: keyword scan
    lower = raw.lower()
    for decision in ("escalate", "uncertain", "confident"):
        if decision in lower:
            return JudgeDecision(
                decision=decision,  # type: ignore[arg-type]
                reasoning=f"parsed from text: {raw[:100]}",
                judge_model=model,
                latency_ms=latency_ms,
            )

    log.debug("judge_malformed raw=%r", raw[:80])
    return JudgeDecision(
        decision="uncertain",
        reasoning=f"judge_malformed: {raw[:80]}",
        judge_model=model,
        latency_ms=latency_ms,
    )


async def judge_response(
    task_type: str,
    prompt: str,
    sovereign_response: str,
) -> JudgeDecision:
    """
    Evaluate sovereign response via specialized judge.
    Timeout is per-task from _JUDGE_TIMEOUTS (falls back to JUDGE_TIMEOUT_MS).
    Never raises.
    """
    t0 = time.perf_counter()

    if not JUDGE_ENABLED:
        return JudgeDecision(
            decision="confident", reasoning="judge_disabled",
            judge_model="none", latency_ms=0,
        )

    judge_info = _JUDGE_MAP.get(task_type)
    if judge_info is None or not judge_info.get("is_active", False):
        return JudgeDecision(
            decision="confident",
            reasoning=f"no_judge_for_task_type={task_type}",
            judge_model="none",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    model_name = judge_info["judge_model"]
    host_ip    = judge_info["target_node"]
    ollama_url = f"http://{host_ip}:11434"
    timeout_ms = _JUDGE_TIMEOUTS.get(task_type, JUDGE_TIMEOUT_MS)
    timeout_s  = timeout_ms / 1000.0
    log.debug("judge_timeout_selected task=%s timeout_ms=%d model=%s",
              task_type, timeout_ms, model_name)

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": model_name,
                    "messages": [{"role": "user", "content": _USER_PROMPT.format(
                        prompt=prompt[:600], response=sovereign_response[:600])}],
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 100},
                },
            )
            resp.raise_for_status()
            raw = ((resp.json().get("message") or {}).get("content") or "").strip()

        latency_ms = int((time.perf_counter() - t0) * 1000)
        decision = _parse(raw, model_name, latency_ms)
        log.debug("judge_ok task=%s model=%s decision=%s latency=%dms",
                  task_type, model_name, decision.decision, latency_ms)
        return decision

    except httpx.TimeoutException:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        log.warning("judge_timeout task=%s model=%s timeout=%dms",
                    task_type, model_name, timeout_ms)
        return JudgeDecision(
            decision="uncertain",
            reasoning=f"judge_timeout_{timeout_ms}ms",
            judge_model=model_name, latency_ms=latency_ms,
        )
    except (httpx.ConnectError, httpx.NetworkError):
        latency_ms = int((time.perf_counter() - t0) * 1000)
        log.warning("judge_unreachable task=%s model=%s host=%s",
                    task_type, model_name, host_ip)
        return JudgeDecision(
            decision="confident",  # fail-open: don't penalize response for judge being down
            reasoning="judge_unreachable",
            judge_model=model_name, latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        log.warning("judge_error task=%s model=%s error=%s",
                    task_type, model_name, str(exc)[:80])
        return JudgeDecision(
            decision="uncertain",
            reasoning=f"judge_error: {str(exc)[:60]}",
            judge_model=model_name, latency_ms=latency_ms,
        )
