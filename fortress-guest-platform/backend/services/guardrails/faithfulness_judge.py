"""Wave 5.6 — RAG Faithfulness Judge.

Scores a generated brief section's claims against the retrieval packet that
grounded it. Uses Super-120B via the LiteLLM gateway; deterministic settings
(temperature 0, no extended thinking) for structural classification work.

Returns a dict matching the schema in `faithfulness_prompts.JUDGE_PROMPT_TEMPLATE`.
On parse failure, retries once with a stricter prompt; on second failure
returns `{"error": "parse_failed", "raw": <output>}` — the rail never raises
to the caller for content reasons. HTTP errors return `{"error": "http_error",
...}`. The runner consuming this never blocks generation on faithfulness.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from .faithfulness_prompts import JUDGE_PROMPT_TEMPLATE, STRICTER_RETRY_SUFFIX

logger = logging.getLogger(__name__)

LITELLM_BASE = os.getenv("LITELLM_BASE", "http://127.0.0.1:8002")
LITELLM_KEY = os.getenv("LITELLM_MASTER_KEY", "")
JUDGE_ALIAS = os.getenv("FAITHFULNESS_ALIAS", "legal-faithfulness")
# legal-faithfulness is the default judge alias: deterministic settings
# baked in (temperature=0, max_tokens=2000, enable_thinking=false). LiteLLM
# does NOT propagate extra_body.chat_template_kwargs overrides to vLLM, so
# the alias-level config is the only reliable way to disable thinking.
# Override via FAITHFULNESS_ALIAS env if a different model is preferred.

JUDGE_TIMEOUT_S = int(os.getenv("FAITHFULNESS_TIMEOUT_S", "600"))
MAX_TOKENS = int(os.getenv("FAITHFULNESS_MAX_TOKENS", "2000"))
# Empirically, frontier nemotron-3-super at TP=2 produces ~12-15 output
# tokens/sec without extended thinking. At MAX_TOKENS=2000 the worst case
# is ~150s of generation, plus prefill of long packets. 600s gives 4x
# headroom; brief §6.4 hard stop fires on >30% wall-add per section, so
# the runner-side budget is the real ceiling.


def _render_prompt(
    section_id: str,
    generated_section: str,
    retrieval_packet: list[dict[str, Any]] | list[str],
) -> str:
    """Render the judge prompt. Uses str.replace (not .format) because the
    JSON example in the template contains literal braces."""
    chunks: list[str] = []
    for i, c in enumerate(retrieval_packet):
        if isinstance(c, dict):
            source = c.get("source_id") or c.get("source") or c.get("file_name") or "unknown"
            text = c.get("text") or c.get("content") or ""
            chunks.append(f"[chunk {i + 1}, source={source}]\n{text}")
        else:
            chunks.append(f"[chunk {i + 1}]\n{c}")
    packet_str = "\n\n".join(chunks)
    return (
        JUDGE_PROMPT_TEMPLATE
        .replace("{section_id}", section_id)
        .replace("{generated_section}", generated_section)
        .replace("{retrieval_packet}", packet_str)
    )


def _call_judge(prompt: str) -> str:
    if not LITELLM_KEY:
        raise RuntimeError("LITELLM_MASTER_KEY env var is required for the faithfulness judge")
    with httpx.Client(timeout=JUDGE_TIMEOUT_S) as client:
        resp = client.post(
            f"{LITELLM_BASE}/v1/chat/completions",
            headers={"Authorization": f"Bearer {LITELLM_KEY}"},
            json={
                "model": JUDGE_ALIAS,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": MAX_TOKENS,
                "temperature": 0,
                # response_format forces vLLM to constrain output to a JSON
                # object. Combined with the alias-level enable_thinking=false,
                # this is what gets us short, clean JSON instead of a
                # thinking-style ramble that exhausts max_tokens.
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def _parse_judge_output(raw: str) -> dict[str, Any]:
    """Parse the judge's JSON output. Strips markdown fences if present
    despite the prompt asking for none."""
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0].rstrip()
        if cleaned.lstrip().startswith("json"):
            cleaned = cleaned.lstrip()[4:].lstrip()
    # Some models wrap JSON in extra prose; find first { ... matching }
    start = cleaned.find("{")
    if start > 0:
        cleaned = cleaned[start:]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("judge JSON parse failed: %s", e)
        return {"error": "parse_failed", "raw": raw, "exception": str(e)}


def score(
    section_id: str,
    generated_section: str,
    retrieval_packet: list[dict[str, Any]] | list[str],
) -> dict[str, Any]:
    """Score a generated section's faithfulness against its retrieval packet.

    Returns a dict matching the JUDGE_PROMPT schema, or an error dict on
    failure. Never raises for content reasons.
    """
    if not generated_section or not generated_section.strip():
        return {"error": "empty_section", "section_id": section_id}
    if not retrieval_packet:
        return {"error": "empty_packet", "section_id": section_id}

    prompt = _render_prompt(section_id, generated_section, retrieval_packet)

    try:
        raw = _call_judge(prompt)
    except httpx.HTTPError as e:
        logger.error("judge HTTP error on %s: %s", section_id, e)
        return {"error": "http_error", "section_id": section_id, "exception": str(e)}

    parsed = _parse_judge_output(raw)

    if parsed.get("error") == "parse_failed":
        retry_prompt = prompt + STRICTER_RETRY_SUFFIX
        try:
            raw_retry = _call_judge(retry_prompt)
        except httpx.HTTPError as e:
            logger.error("judge retry HTTP error on %s: %s", section_id, e)
            return {"error": "http_error_on_retry", "section_id": section_id, "exception": str(e)}
        parsed = _parse_judge_output(raw_retry)

    return parsed
