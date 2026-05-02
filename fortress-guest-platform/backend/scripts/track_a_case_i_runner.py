"""Phase B v0.1 case briefing runner (case-agnostic).

Originally landed as the Track A Case I dry-run runner; parameterized
for Wave 7 Case II reuse per Constitution §11.4 (case-specific
scaffolding is a forbidden pattern). Module rename to phase_b_runner.py
deferred as separate housekeeping (post-counsel-hire).

Behavior:

- Wraps Phase B v0.1 orchestrator (case_briefing_compose.compose) with
  a metric-capturing BrainClient subclass.
- Injects the custom BrainClient pointing at the frontier endpoint with
  served-model-name "nemotron-3-super".
- Captures per-section wall time, content + reasoning byte counts,
  grounding citations, format compliance.
- By default, fires ONE post-run LiteLLM call (legal-reasoning) to
  produce a §9 "Recommended Strategy" rewrite that overrides the
  orchestrator's intel-resolved §9 in the assembled brief. Pass
  `--skip-section-9-augmentation` to suppress this and emit the
  orchestrator's intel-rich §9 verbatim (required for Wave 7 Case II
  v1 where judge intel is doctrinally load-bearing — see GH issue
  for the architectural Path B fix).

Output: run dir populated under /tmp/phase-b-<case-slug>-<version>-<STAMP>/
        (or `--output-dir`) with sections/, raw/, metrics/, and the
        assembled brief. Brief is also copied to NAS at
        /mnt/fortress_nas/Corporate_Legal/Business_Legal/<case-slug>/filings/outgoing/.

Usage:
    cd /home/admin/Fortress-Prime/fortress-guest-platform
    .uv-venv/bin/python -m backend.scripts.track_a_case_i_runner \\
        --case-slug 7il-v-knight-ndga-i

    # Wave 7 Case II v1 (intel-rich §9 verbatim):
    .uv-venv/bin/python -m backend.scripts.track_a_case_i_runner \\
        --case-slug 7il-v-knight-ndga-ii \\
        --skip-section-9-augmentation
"""

from __future__ import annotations

import argparse
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
from backend.services.guardrails.faithfulness_judge import score as faithfulness_score


FRONTIER_BASE = "http://10.10.10.3:8000"
FRONTIER_MODEL = "nemotron-3-super"
LITELLM_BASE = "http://127.0.0.1:8002"
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "")

STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

# Slug → (display_prefix, version_tag) for the assembled brief filename. Keep the
# Case I baseline filename pattern stable so existing regression manifests still
# match. Heuristic fallback for unmapped slugs: uppercase, hyphens→underscores, v1.
_CASE_DISPLAY_MAP: dict[str, tuple[str, str]] = {
    "7il-v-knight-ndga-i": ("7IL_NDGA_I", "v3"),
    "7il-v-knight-ndga-ii": ("7IL_NDGA_II", "v1"),
}


def _slug_to_display(slug: str) -> tuple[str, str]:
    if slug in _CASE_DISPLAY_MAP:
        return _CASE_DISPLAY_MAP[slug]
    return (slug.upper().replace("-", "_"), "v1")


# Populated in main() from CLI args. Module-level for backward compatibility with
# the prior Track A Case I runner shape; future refactor should pass these through
# explicitly (separate housekeeping).
CASE_SLUG: str = ""
RUN_DIR: Path = Path("/tmp/phase-b-runner-uninitialized")
NAS_OUT_DIR: Path = Path("/mnt/fortress_nas/Corporate_Legal/Business_Legal/_uninitialized/filings/outgoing")


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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase B v0.1 case briefing runner. Wraps compose() with a "
        "metric-capturing BrainClient and (optionally) a post-run §9 augmentation pass.",
    )
    parser.add_argument(
        "--case-slug",
        required=True,
        help="Case slug (e.g. 7il-v-knight-ndga-i, 7il-v-knight-ndga-ii). "
        "Drives compose(case_slug), NAS output dir, and assembled-brief filename.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Run output directory. Defaults to /tmp/phase-b-<case-slug>-<version>-<STAMP>/.",
    )
    parser.add_argument(
        "--skip-section-9-augmentation",
        action="store_true",
        default=False,
        help="Suppress the post-compose §9 LiteLLM rewrite. Emit the orchestrator's "
        "intel-resolved §9 verbatim in the assembled brief. Required for Wave 7 Case II "
        "v1 where judge intel (Story bidirectional findings, Goldberg same-attorney "
        "signal, standing-order procedural posture) is doctrinally load-bearing. The "
        "post-compose pass currently replaces (rather than layers on) the intel-rich "
        "§9 — see GH issue for the architectural fix (Path B).",
    )
    parser.add_argument(
        "--sections",
        default="1,2,3,4,5,6,7,8,9,10",
        help="Sections to emit (compatibility flag; orchestrator currently runs all "
        "ten regardless of this value). Reserved for future per-section invocation.",
    )
    parser.add_argument(
        "--capture-reasoning",
        action="store_true",
        default=True,
        help="Capture per-section reasoning byte counts (always on; flag retained for "
        "compatibility with operator runbooks).",
    )
    parser.add_argument(
        "--faithfulness-check",
        action="store_true",
        default=False,
        help="Wave 5.6: after compose(), score each synthesis section's "
        "faithfulness against its retrieval packet via Super-120B-as-judge. "
        "Output to ${RUN_DIR}/faithfulness/section_*.json. Informational only; "
        "does NOT block generation. Mechanical sections (timeline, parties, "
        "evidence inventory, filing checklist) are skipped.",
    )
    return parser.parse_args(argv)


# Sections excluded from faithfulness scoring per Wave 5.6 brief §11:
# §1/§3/§6/§10 are deterministic mechanical, §2 is deterministic timeline.
# Only synthesis sections (§4/§5/§7/§8/§9) are scored.
_FAITHFULNESS_SCORED_MODES = {"synthesis", "synthesis_augmented"}


async def main() -> int:
    args = _parse_args()
    global CASE_SLUG, RUN_DIR, NAS_OUT_DIR
    CASE_SLUG = args.case_slug
    display_prefix, version_tag = _slug_to_display(CASE_SLUG)
    if args.output_dir:
        RUN_DIR = Path(args.output_dir)
    else:
        RUN_DIR = Path(f"/tmp/phase-b-{CASE_SLUG}-{version_tag}-{STAMP}")
    NAS_OUT_DIR = Path(
        f"/mnt/fortress_nas/Corporate_Legal/Business_Legal/{CASE_SLUG}/filings/outgoing"
    )
    assembled_filename = f"Attorney_Briefing_Package_{display_prefix}_{version_tag}_{STAMP}.md"

    print(f"=== Phase B runner — {CASE_SLUG} {version_tag} {STAMP} ===", file=sys.stderr)
    print(f"  run_dir: {RUN_DIR}", file=sys.stderr)
    print(f"  nas_out: {NAS_OUT_DIR}", file=sys.stderr)
    if args.skip_section_9_augmentation:
        print("  §9 post-compose augmentation: SKIPPED (orchestrator §9 emitted verbatim)", file=sys.stderr)
    if args.faithfulness_check:
        print("  faithfulness-check: ON (Wave 5.6 rail)", file=sys.stderr)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "sections").mkdir(exist_ok=True)
    (RUN_DIR / "raw").mkdir(exist_ok=True)
    (RUN_DIR / "metrics").mkdir(exist_ok=True)
    if args.faithfulness_check:
        (RUN_DIR / "faithfulness").mkdir(exist_ok=True)
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
    faithfulness_results: dict[str, dict[str, Any]] = {}
    # In Phase B v0.1, every synthesis section grounds against the same
    # global packet (case_briefing_synthesizers.py line 344). The same packet
    # is therefore the right input to faithfulness scoring for every
    # synthesis section.
    if args.faithfulness_check:
        retrieval_packet_for_faithfulness = [
            {"source_id": cid, "text": ctext}
            for cid, ctext in zip(packet.work_product_chunk_ids, packet.work_product_chunk_texts)
        ] + [
            {"source_id": cid, "text": ctext}
            for cid, ctext in zip(packet.privileged_chunk_ids, packet.privileged_chunk_texts)
        ]
    else:
        retrieval_packet_for_faithfulness = []

    for sid, result in section_results.items():
        section_path = RUN_DIR / "sections" / f"{sid}.md"
        section_path.write_text(result.content, encoding="utf-8")
        score = score_section(sid, result.title, result.content)
        score["mode"] = result.mode
        score["operator_status"] = result.operator_status
        score["grounding_citations_count_from_orchestrator"] = len(result.grounding_citations)
        section_scores.append(score)

        if args.faithfulness_check and result.mode in _FAITHFULNESS_SCORED_MODES:
            judge_t0 = time.monotonic()
            judge_result = faithfulness_score(
                section_id=sid,
                generated_section=result.content,
                retrieval_packet=retrieval_packet_for_faithfulness,
            )
            judge_result["_faithfulness_wall_seconds"] = round(time.monotonic() - judge_t0, 2)
            (RUN_DIR / "faithfulness" / f"{sid}.json").write_text(
                json.dumps(judge_result, indent=2), encoding="utf-8"
            )
            faithfulness_results[sid] = judge_result
            print(
                f"  faithfulness {sid}: "
                f"grounded={judge_result.get('grounded_claims_count', '?')}, "
                f"unsupported={len(judge_result.get('unsupported_claims', []) or [])}, "
                f"partial={len(judge_result.get('partial_support_claims', []) or [])}, "
                f"wall={judge_result['_faithfulness_wall_seconds']}s",
                file=sys.stderr,
            )

    # Section 9 augmentation (post-compose). Suppressed by --skip-section-9-augmentation;
    # in that case the orchestrator's intel-resolved §9 flows through to the assembled brief.
    section_9_content: Optional[str] = None
    if not args.skip_section_9_augmentation:
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

        if args.faithfulness_check:
            sid_aug = "section_09_recommended_strategy_augmented"
            judge_t0 = time.monotonic()
            s9_judge = faithfulness_score(
                section_id=sid_aug,
                generated_section=section_9_content,
                retrieval_packet=retrieval_packet_for_faithfulness,
            )
            s9_judge["_faithfulness_wall_seconds"] = round(time.monotonic() - judge_t0, 2)
            (RUN_DIR / "faithfulness" / f"{sid_aug}.json").write_text(
                json.dumps(s9_judge, indent=2), encoding="utf-8"
            )
            faithfulness_results[sid_aug] = s9_judge
            print(
                f"  faithfulness {sid_aug}: "
                f"grounded={s9_judge.get('grounded_claims_count', '?')}, "
                f"unsupported={len(s9_judge.get('unsupported_claims', []) or [])}, "
                f"partial={len(s9_judge.get('partial_support_claims', []) or [])}, "
                f"wall={s9_judge['_faithfulness_wall_seconds']}s",
                file=sys.stderr,
            )

    # Assembled brief.
    # When §9 augmentation ran: replace the orchestrator's §9 with the post-compose rewrite.
    # When suppressed: pass the orchestrator's assembled output through unchanged so the
    # intel-resolved §9 reaches the assembled brief.
    assembled_orig = out_path.read_text(encoding="utf-8")
    if section_9_content is not None:
        section_9_marker_re = re.compile(
            r"(##\s*9\..*?Recommended Strategy.*?\n)(.*?)(?=\n##\s*\d+\.|\Z)",
            re.DOTALL | re.IGNORECASE,
        )
        if section_9_marker_re.search(assembled_orig):
            assembled_brief = section_9_marker_re.sub(
                lambda m: m.group(1) + "\n" + section_9_content + "\n",
                assembled_orig,
                count=1,
            )
        else:
            assembled_brief = assembled_orig + "\n\n## 9. Recommended Strategy (post-run augmentation)\n\n" + section_9_content + "\n"
    else:
        assembled_brief = assembled_orig

    assembled_path = RUN_DIR / assembled_filename
    assembled_path.write_text(assembled_brief, encoding="utf-8")
    nas_path = NAS_OUT_DIR / assembled_filename
    nas_path.write_text(assembled_brief, encoding="utf-8")

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
        "faithfulness_check_enabled": args.faithfulness_check,
        "faithfulness_results": faithfulness_results if args.faithfulness_check else None,
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

    if args.faithfulness_check:
        _write_faithfulness_run_report(RUN_DIR, faithfulness_results, overall_seconds)

    print(json.dumps({k: v for k, v in summary.items() if k not in ("section_scores", "brain_client_call_metrics", "faithfulness_results")}, indent=2))
    return 0


def _write_faithfulness_run_report(
    run_dir: Path,
    results: dict[str, dict[str, Any]],
    overall_wall_seconds: float,
) -> None:
    """Append a faithfulness summary table to ${RUN_DIR}/run-report.md per
    Wave 5.6 brief §6.6. Threshold for "flagged for v2 regen" is informational
    only; operator makes final triage call at v1 review (master plan §3.3)."""
    lines: list[str] = [
        "# Track A Case I — Run report",
        "",
        f"Run dir: `{run_dir}`",
        f"Overall compose wall: {overall_wall_seconds}s",
        "",
        "## Faithfulness Summary (Wave 5.6)",
        "",
        "| § | Mode | Grounded claims | Unsupported | Partial | Wall (s) | Summary |",
        "|---|---|---|---|---|---|---|",
    ]
    flagged: list[str] = []
    top_unsupported: list[tuple[str, str, str]] = []
    total_wall = 0.0
    for sid, r in sorted(results.items()):
        wall = r.get("_faithfulness_wall_seconds", 0.0) or 0.0
        total_wall += float(wall)
        if r.get("error"):
            lines.append(f"| {sid} | n/a | (error) | (error) | (error) | {wall} | {r.get('error')} |")
            continue
        grounded = r.get("grounded_claims_count", 0) or 0
        unsup = r.get("unsupported_claims", []) or []
        part = r.get("partial_support_claims", []) or []
        summ = (r.get("summary") or "").replace("|", "\\|")[:120]
        lines.append(f"| {sid} | synth | {grounded} | {len(unsup)} | {len(part)} | {wall} | {summ} |")
        if len(unsup) > 3 or len(part) > 5:
            flagged.append(f"- {sid} — {len(unsup)} unsupported, {len(part)} partial")
        for c in unsup:
            top_unsupported.append((sid, (c.get("claim", "") or "")[:160], c.get("reason", "") or ""))

    lines += [
        "",
        f"Total faithfulness wall across scored sections: {round(total_wall, 2)}s",
        "",
        "### Sections flagged for v2 regen (unsupported > 3 OR partial > 5):",
        "",
    ]
    if flagged:
        lines += flagged
    else:
        lines += ["- (none)"]

    if top_unsupported:
        lines += ["", "### Top unsupported claims (operator triage):", ""]
        for i, (sid, claim, reason) in enumerate(top_unsupported[:10], start=1):
            lines.append(f"{i}. [{sid}] \"{claim}\" — {reason}")

    lines += [
        "",
        "Threshold for \"flagged for v2 regen\" is informational only. Operator "
        "makes final triage call at v1 review per master plan §3.3.",
    ]
    (run_dir / "run-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
