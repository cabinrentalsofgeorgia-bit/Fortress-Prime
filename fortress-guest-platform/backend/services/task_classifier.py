"""
task_classifier.py — Phase 4e.2 three-tier task type classifier.

Tier 1: source_module hint (deterministic, 0ms)
Tier 2: keyword pattern matching (deterministic, <1ms)
Tier 3: qwen2.5:0.5b small LLM fallback via Ollama (500ms timeout)

Returns a task_type string from _TASK_TYPES.
Always returns "generic" on any failure — never raises, never blocks.
"""
from __future__ import annotations

import logging
import os

import httpx

from backend.services.task_types import (
    _DESCRIPTIVE_PATTERNS,
    _KEYWORD_PATTERNS,
    _MODULE_TO_TASK,
    _PRICING_PATTERNS,
    _TASK_TYPES,
)

log = logging.getLogger("task_classifier")

_CLASSIFIER_MODEL   = os.getenv("TASK_CLASSIFIER_MODEL",    "qwen2.5:0.5b")
_CLASSIFIER_TIMEOUT = float(os.getenv("TASK_CLASSIFIER_TIMEOUT_MS", "500")) / 1000.0
_OLLAMA_URL         = os.getenv("TASK_CLASSIFIER_OLLAMA_URL", "http://192.168.0.100:11434")

_VALID_TYPES_STR = ", ".join(sorted(_TASK_TYPES - {"generic"}))

_CLASSIFIER_PROMPT = """\
Classify the following prompt into exactly one task type.
Return ONLY the task type label, nothing else. No explanation.

Valid task types: {types}

Prompt: {prompt}

Task type:"""


def _detect_content_mismatch(tier1_type: str, prompt: str) -> "str | None":
    """
    Override Tier 1 when prompt content strongly contradicts the module hint.

    Currently only fires for pricing_math: quote_engine is multi-purpose —
    it generates both pricing calculations and property descriptions/marketing
    copy. When the prompt contains no pricing signal but clear descriptive
    signal (listing copy, amenity descriptions, "what does X look like"),
    reclassify to vrs_concierge rather than training the model that
    marketing copy == pricing_math.

    Returns corrected task_type string or None (keep Tier 1 result).

    Decision logged in docs/IRON_DOME_ARCHITECTURE.md Phase 4e.2.
    """
    if tier1_type != "pricing_math":
        return None

    has_pricing = any(p.search(prompt) for p in _PRICING_PATTERNS)
    if has_pricing:
        return None

    has_descriptive = any(p.search(prompt) for p in _DESCRIPTIVE_PATTERNS)
    if has_descriptive:
        log.debug(
            "task_classifier.tier1_override tier1=%s → vrs_concierge "
            "(descriptive signal, no pricing signal)",
            tier1_type,
        )
        return "vrs_concierge"

    return None


def _llm_classify(prompt: str) -> str:
    """
    Call qwen2.5:0.5b on spark-2 Ollama to classify the task type.
    Timeout: TASK_CLASSIFIER_TIMEOUT_MS (default 500ms).
    Returns "generic" on any failure or invalid response.
    """
    payload = {
        "model": _CLASSIFIER_MODEL,
        "prompt": _CLASSIFIER_PROMPT.format(
            types=_VALID_TYPES_STR,
            prompt=prompt[:600],
        ),
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 20},
    }
    try:
        resp = httpx.post(
            f"{_OLLAMA_URL.rstrip('/')}/api/generate",
            json=payload,
            timeout=_CLASSIFIER_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip().lower()
        # Accept only the first token-ish word, strip punctuation
        candidate = raw.split()[0].rstrip(".,;:!?") if raw.split() else ""
        if candidate in _TASK_TYPES:
            return candidate
        log.debug("task_classifier.llm_invalid_response raw=%r", raw[:60])
    except httpx.TimeoutException:
        log.debug("task_classifier.llm_timeout model=%s", _CLASSIFIER_MODEL)
    except Exception as exc:
        log.debug("task_classifier.llm_error error=%s", str(exc)[:100])
    return "generic"


def classify_task_type(
    source_module: str,
    prompt: str,
    response: str = "",
) -> str:
    """
    Classify the task type for a capture. Three-tier, never raises.

    Tier 1: source_module hint (deterministic)
    Tier 2: keyword patterns on combined prompt+response (deterministic)
    Tier 3: qwen2.5:0.5b LLM fallback (500ms timeout)

    Returns a string from _TASK_TYPES. Defaults to "generic" on failure.
    """
    try:
        # Tier 1: source module — then check for content mismatch
        tier1: str | None = None
        if source_module and source_module in _MODULE_TO_TASK:
            tier1 = _MODULE_TO_TASK[source_module]
        elif source_module:
            # prefix match: "legal_council_of_9/seat_1/..." → legal_reasoning
            for module_key, task in _MODULE_TO_TASK.items():
                if source_module.startswith(module_key):
                    tier1 = task
                    break

        if tier1 is not None:
            override = _detect_content_mismatch(tier1, prompt)
            return override if override is not None else tier1

        # Tier 2: keyword patterns
        combined = f"{prompt} {response}".lower()
        for pattern, task in _KEYWORD_PATTERNS:
            if pattern.search(combined):
                return task

        # Tier 3: small LLM fallback
        return _llm_classify(prompt)

    except Exception as exc:
        log.warning("task_classifier.classify_failed error=%s — returning generic", str(exc)[:100])
        return "generic"
