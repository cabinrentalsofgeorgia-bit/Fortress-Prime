"""
judge_runtime.py — Phase 4e.3 judge tier runtime (Ollama-LoRA served).

Evaluates sovereign responses inline via task-type specialized judge models.
<200ms p95 hard budget. Failure modes never block the response path.

JUDGE_ENABLED=false (default) → zero overhead, judge skipped entirely.

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
JUDGE_TIMEOUT_MS = int(os.getenv("JUDGE_TIMEOUT_MS", "200"))

# task_type → (ollama_model_name, ollama_host_ip)
# Populated as judges are trained and deployed.
_JUDGE_MAP: dict[str, tuple[str, str]] = {
    # VRS judges on spark-4 (192.168.0.106)
    "vrs_concierge":    ("vrs_concierge_judge",  "192.168.0.106"),
    "vrs_ota_response": ("vrs_ota_judge",         "192.168.0.106"),
    "pricing_math":     ("pricing_math_judge",    "192.168.0.106"),
    "market_research":  ("market_research_judge", "192.168.0.106"),
    # Legal judges on spark-1 (192.168.0.104)
    "legal_reasoning":  ("legal_reasoning_judge", "192.168.0.104"),
    "brief_drafting":   ("brief_drafting_judge",  "192.168.0.104"),
    # Code judge on spark-2 (192.168.0.100)
    "code_generation":  ("code_generation_judge", "192.168.0.100"),
    # Vision judge on spark-3 (192.168.0.105)
    "vision_damage":    ("vision_analysis_judge", "192.168.0.105"),
    "vision_photo":     ("vision_analysis_judge", "192.168.0.105"),
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
    Hard timeout: JUDGE_TIMEOUT_MS (default 200ms). Never raises.
    """
    t0 = time.perf_counter()

    if not JUDGE_ENABLED:
        return JudgeDecision(
            decision="confident", reasoning="judge_disabled",
            judge_model="none", latency_ms=0,
        )

    judge_info = _JUDGE_MAP.get(task_type)
    if judge_info is None:
        return JudgeDecision(
            decision="confident",
            reasoning=f"no_judge_for_task_type={task_type}",
            judge_model="none",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    model_name, host_ip = judge_info
    ollama_url  = f"http://{host_ip}:11434"
    timeout_s   = JUDGE_TIMEOUT_MS / 1000.0

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
                    task_type, model_name, JUDGE_TIMEOUT_MS)
        return JudgeDecision(
            decision="uncertain",
            reasoning=f"judge_timeout_{JUDGE_TIMEOUT_MS}ms",
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
