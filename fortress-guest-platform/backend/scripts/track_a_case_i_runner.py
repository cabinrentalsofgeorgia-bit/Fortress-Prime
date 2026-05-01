"""Track A Case I dry-run runner.

Per Phase 9 follow-up brief
(`docs/operational/track-a-phase-b-v01-case-i-dryrun-brief.md`):

- Wraps Phase B v0.1 orchestrator (case_briefing_compose.compose)
  with a metric-capturing BrainClient subclass.
- Injects the custom BrainClient pointing at the spark-3+spark-4
  TP=2 frontier endpoint with served-model-name "nemotron-3-super"
  (D2 option (b) — constructor injection; no orchestrator
  modification per brief §11).
- Captures per-section wall time, content + reasoning byte counts
  (proxy for token counts since stream=True), grounding citations,
  format compliance (first-person prose / <think> leakage).
- After compose() finishes, fires ONE post-run LiteLLM call
  (legal-reasoning, reasoning_effort=high, max_tokens=5000) to
  generate Section 9 ("Recommended Strategy") — the orchestrator
  emits a placeholder for that section.
- Assembles full v3 brief, replaces Section 9 placeholder with the
  augmentation output, writes assembled brief to NAS.

Output: run dir populated under /tmp/track-a-case-i-v3-<STAMP>/
        with sections/, raw/, metrics/.

Usage (run on spark-2 in fortress-guest-platform venv):
    cd /home/admin/Fortress-Prime/fortress-guest-platform
    .uv-venv/bin/python -m backend.scripts.track_a_case_i_runner
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional, Union

import httpx

ROOT = Path("/home/admin/Fortress-Prime/fortress-guest-platform")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from backend.services.brain_client import BrainClient
from backend.services.case_briefing_compose import compose
from backend.services.case_briefing_synthesizers import _SYNTHESIS_PROMPTS, _SYSTEM_PROMPT, _build_synthesis_user_prompt


CASE_SLUG = "7il-v-knight-ndga-i"
FRONTIER_BASE = "http://10.10.10.3:8000"
FRONTIER_MODEL = "nemotron-3-super"
LITELLM_BASE = "http://127.0.0.1:8002"
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "")

STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
RUN_DIR = Path(f"/tmp/track-a-case-i-v3-{STAMP}")
NAS_OUT_DIR = Path("/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/filings/outgoing")


class MetricCapturingBrainClient(BrainClient):
    """BrainClient subclass that times each chat() call and records token estimates."""

    def __init__(self, *args, metrics_log: list[dict[str, Any]] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.metrics_log: list[dict[str, Any]] = metrics_log if metrics_log is not None else []

    async def chat(
        self,
        messages: list[dict],
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        stream: bool = True,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        *,
        enable_thinking: Optional[bool] = None,
        low_effort: Optional[bool] = None,
        thinking_token_budget: Optional[int] = None,
        force_nonempty_content: Optional[bool] = None,
        top_p: Optional[float] = None,
        reasoning_effort: Optional[str] = None,
        thinking: Optional[bool] = None,
    ) -> Union[AsyncIterator[str], dict]:
        # Identify section from the user prompt's INSTRUCTION block content match (best-effort)
        user_prompt_full = ""
        for m in messages:
            if m.get("role") == "user":
                user_prompt_full = m.get("content", "")
                break
        inferred_section = "?"
        for sid, prompt in _SYNTHESIS_PROMPTS.items():
            if prompt[:80] in user_prompt_full:
                inferred_section = sid
                break

        prompt_chars = sum(len(m.get("content", "")) for m in messages)
        started = time.monotonic()
        wall_iso_start = datetime.now(timezone.utc).isoformat()
        effective_max = max_tokens if max_tokens is not None else self.default_max_tokens

        result = await super().chat(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=stream,
            transport=transport,
            enable_thinking=enable_thinking,
            low_effort=low_effort,
            thinking_token_budget=thinking_token_budget,
            force_nonempty_content=force_nonempty_content,
            top_p=top_p,
            reasoning_effort=reasoning_effort,
            thinking=thinking,
        )

        if stream and hasattr(result, "__aiter__"):
            collected_chunks: list[str] = []
            client_ref = self
            async def _wrapped() -> AsyncIterator[str]:
                async for chunk in result:  # type: ignore
                    collected_chunks.append(chunk)
                    yield chunk
                ended = time.monotonic()
                content_text = "".join(collected_chunks)
                client_ref.metrics_log.append({
                    "section_id": inferred_section,
                    "wall_seconds": round(ended - started, 2),
                    "wall_started_utc": wall_iso_start,
                    "wall_ended_utc": datetime.now(timezone.utc).isoformat(),
                    "prompt_chars": prompt_chars,
                    "max_tokens": effective_max,
                    "temperature": temperature,
                    "content_chars": len(content_text),
                    "content_token_estimate": len(content_text) // 4,
                    "reasoning_chars": len(client_ref.last_reasoning or ""),
                    "finish_reason": client_ref.last_finish_reason,
                    "enable_thinking": enable_thinking,
                    "low_effort": low_effort,
                    "thinking_token_budget": thinking_token_budget,
                    "force_nonempty_content": force_nonempty_content,
                    "top_p": top_p,
                    "stream": True,
                })
            return _wrapped()
        else:
            ended = time.monotonic()
            content_text = ""
            try:
                content_text = result["choices"][0]["message"].get("content", "") if isinstance(result, dict) else ""
            except (KeyError, IndexError, TypeError):
                pass
            self.metrics_log.append({
                "section_id": inferred_section,
                "wall_seconds": round(ended - started, 2),
                "wall_started_utc": wall_iso_start,
                "wall_ended_utc": datetime.now(timezone.utc).isoformat(),
                "prompt_chars": prompt_chars,
                "max_tokens": effective_max,
                "temperature": temperature,
                "content_chars": len(content_text),
                "content_token_estimate": len(content_text) // 4,
                "reasoning_chars": len(self.last_reasoning or ""),
                "finish_reason": self.last_finish_reason,
                "enable_thinking": enable_thinking,
                "low_effort": low_effort,
                "thinking_token_budget": thinking_token_budget,
                "force_nonempty_content": force_nonempty_content,
                "top_p": top_p,
                "stream": False,
                "usage": result.get("usage") if isinstance(result, dict) else None,
            })
            return result


# Format-compliance regexes (Phase 7 smoke methodology)
_FIRSTPERSON_PATTERNS = re.compile(
    r"\bLet me\b|\bI'll\b|\bI'm going to\b|\bI need to\b|\bWait,\b|\bLet's\b|\bFirst, I\b|\bMy analysis\b",
    re.IGNORECASE,
)
_THINK_BLOCK_PATTERN = re.compile(r"</?think>", re.IGNORECASE)
_CITATION_FILENAME_PATTERN = re.compile(r"\[#?[A-Za-z0-9_().,'\- ]+\.(pdf|md|eml|txt|json)\]")
_CITATION_PARA_PATTERN = re.compile(r"¶\s*\d+|\bEx\.\s*[A-Z]\b|\bExhibit\s+[A-Z]\b|\bDoc\.\s*\d+")
_CITATION_CASE_LAW = re.compile(r"\d+\s+[A-Z]\.\d+\s+\d+|\d+\s+S\.E\.\d+\s+\d+|\d+\s+F\.\d+\s+\d+")


def score_section(section_id: str, title: str, content: str) -> dict[str, Any]:
    fp_matches = _FIRSTPERSON_PATTERNS.findall(content)
    think_matches = _THINK_BLOCK_PATTERN.findall(content)
    file_cites = _CITATION_FILENAME_PATTERN.findall(content)
    para_cites = _CITATION_PARA_PATTERN.findall(content)
    case_cites = _CITATION_CASE_LAW.findall(content)
    file_unique = sorted(set(_CITATION_FILENAME_PATTERN.findall(content)))
    return {
        "section_id": section_id,
        "title": title,
        "content_chars": len(content),
        "content_token_estimate": len(content) // 4,
        "first_person_matches_in_content": len(fp_matches),
        "first_person_examples": fp_matches[:5],
        "think_block_matches_in_content": len(think_matches),
        "citation_filename_count": len(file_cites),
        "citation_filename_unique": len(file_unique),
        "citation_filename_unique_list": file_unique,
        "citation_paragraph_count": len(para_cites),
        "citation_caselaw_count": len(case_cites),
        "format_compliant": len(fp_matches) == 0 and len(think_matches) == 0,
    }


def post_run_section_9_augmentation(
    section_9_user_prompt: str,
    out_log: list[dict[str, Any]],
) -> str:
    """Section 9 (Recommended Strategy) is operator_written placeholder in the orchestrator.
    Per D1 handling: fire ONE direct LiteLLM call against legal-reasoning alias.
    """
    if not LITELLM_MASTER_KEY:
        out_log.append({"section_id": "section_09_recommended_strategy", "error": "no LITELLM_MASTER_KEY"})
        return "**[Section 9 augmentation skipped — LITELLM_MASTER_KEY not in env]**"

    # Phase 3 per-section policy for §9 (doctrinal): top-level chat_template_kwargs
    # via LiteLLM passthrough (PR #330 Probe DL confirmed reasoning_content survives).
    payload = {
        "model": "legal-reasoning",
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": section_9_user_prompt},
        ],
        "max_tokens": 8000,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": True, "low_effort": True},
    }
    started = time.monotonic()
    try:
        req = urllib.request.Request(
            f"{LITELLM_BASE}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {LITELLM_MASTER_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        out_log.append({
            "section_id": "section_09_recommended_strategy",
            "error": f"augmentation failed: {e}",
            "wall_seconds": round(time.monotonic() - started, 2),
        })
        return f"**[Section 9 augmentation failed: {e}]**"

    msg = data["choices"][0]["message"]
    content = msg.get("content", "") or ""
    # LiteLLM exposes reasoning under reasoning_content; vLLM-direct under reasoning.
    reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
    out_log.append({
        "section_id": "section_09_recommended_strategy",
        "wall_seconds": round(time.monotonic() - started, 2),
        "content_chars": len(content),
        "reasoning_chars": len(reasoning),
        "usage": data.get("usage"),
        "finish_reason": data["choices"][0].get("finish_reason"),
        "augmentation_method": "direct LiteLLM legal-reasoning, post-orchestrator",
    })
    return content


async def main() -> int:
    print(f"=== Track A Case I dry-run — {STAMP} ===", file=sys.stderr)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "sections").mkdir(exist_ok=True)
    (RUN_DIR / "raw").mkdir(exist_ok=True)
    (RUN_DIR / "metrics").mkdir(exist_ok=True)
    NAS_OUT_DIR.mkdir(parents=True, exist_ok=True)

    metrics_log: list[dict[str, Any]] = []
    custom_brain = MetricCapturingBrainClient(
        base_url=FRONTIER_BASE,
        model=FRONTIER_MODEL,
        metrics_log=metrics_log,
    )

    overall_start = time.monotonic()
    print(f"Calling compose() with case_slug={CASE_SLUG}, output_dir={RUN_DIR / 'compose-output'}", file=sys.stderr)
    packet, section_results, out_path = await compose(
        CASE_SLUG,
        output_dir=RUN_DIR / "compose-output",
        brain_client=custom_brain,
    )
    overall_seconds = round(time.monotonic() - overall_start, 2)
    print(f"compose() done in {overall_seconds}s. out_path={out_path}", file=sys.stderr)

    # Write each section content + score
    section_scores: list[dict[str, Any]] = []
    for sid, result in section_results.items():
        section_path = RUN_DIR / "sections" / f"{sid}.md"
        section_path.write_text(result.content, encoding="utf-8")
        score = score_section(sid, result.title, result.content)
        score["mode"] = result.mode
        score["operator_status"] = result.operator_status
        score["grounding_citations_count_from_orchestrator"] = len(result.grounding_citations)
        section_scores.append(score)

    # Section 9 augmentation
    print("Section 9 augmentation via legal-reasoning…", file=sys.stderr)
    section_9_user_prompt = _build_synthesis_user_prompt(
        prompt_template=(
            "Identify the recommended litigation strategy for this case. Order recommendations "
            "by urgency. For each: (a) what action, (b) why now, (c) supporting evidence with "
            "bracketed-filename citations, (d) blocking dependencies. If a recommendation is "
            "speculative or thin on evidence, flag it as such."
        ),
        case_metadata=packet.case_metadata,
        work_product_chunks=packet.work_product_chunk_texts,
        privileged_chunks=packet.privileged_chunk_texts,
    )
    section_9_content = post_run_section_9_augmentation(section_9_user_prompt, metrics_log)
    (RUN_DIR / "sections" / "section_09_recommended_strategy_augmented.md").write_text(section_9_content, encoding="utf-8")
    s9_score = score_section("section_09_recommended_strategy_augmented", "9. Recommended Strategy (augmented)", section_9_content)
    s9_score["mode"] = "synthesis_augmented"
    s9_score["operator_status"] = "draft"
    s9_score["grounding_citations_count_from_orchestrator"] = 0
    section_scores.append(s9_score)

    # Assembled v3 brief — reuse orchestrator's assembled output, replace Section 9 placeholder
    assembled_orig = out_path.read_text(encoding="utf-8")
    section_9_marker_re = re.compile(
        r"(##\s*9\..*?Recommended Strategy.*?\n)(.*?)(?=\n##\s*\d+\.|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    if section_9_marker_re.search(assembled_orig):
        assembled_v3 = section_9_marker_re.sub(
            lambda m: m.group(1) + "\n" + section_9_content + "\n",
            assembled_orig,
            count=1,
        )
    else:
        assembled_v3 = assembled_orig + "\n\n## 9. Recommended Strategy (post-run augmentation)\n\n" + section_9_content + "\n"

    assembled_path = RUN_DIR / f"Attorney_Briefing_Package_7IL_NDGA_I_v3_{STAMP}.md"
    assembled_path.write_text(assembled_v3, encoding="utf-8")
    nas_path = NAS_OUT_DIR / f"Attorney_Briefing_Package_7IL_NDGA_I_v3_{STAMP}.md"
    nas_path.write_text(assembled_v3, encoding="utf-8")

    summary = {
        "case_slug": CASE_SLUG,
        "stamp": STAMP,
        "overall_wall_seconds": overall_seconds,
        "frontier_endpoint": FRONTIER_BASE,
        "frontier_served_model": FRONTIER_MODEL,
        "compose_output_path": str(out_path),
        "assembled_v3_local": str(assembled_path),
        "assembled_v3_nas": str(nas_path),
        "section_scores": section_scores,
        "brain_client_call_metrics": metrics_log,
        "ten_sections_modes": {
            "section_01_case_summary": "mechanical (deterministic; no LLM)",
            "section_02_critical_timeline": "synthesis (LLM)",
            "section_03_parties_and_counsel": "mechanical (deterministic; no LLM)",
            "section_04_claims_analysis": "synthesis (LLM)",
            "section_05_key_defenses_identified": "synthesis (LLM)",
            "section_06_evidence_inventory": "mechanical (deterministic; no LLM)",
            "section_07_email_intelligence_report": "synthesis (LLM)",
            "section_08_financial_exposure_analysis": "synthesis (LLM)",
            "section_09_recommended_strategy": "operator_written placeholder (orchestrator) + post-run legal-reasoning augmentation (this runner)",
            "section_10_filing_checklist": "mechanical (deterministic; no LLM)",
        },
    }
    (RUN_DIR / "metrics" / "run-summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("section_scores", "brain_client_call_metrics")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
