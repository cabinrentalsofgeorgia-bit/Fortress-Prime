"""Phase A5 — single-call probe of BRAIN over the Fortress Legal RAG path.

Read-only, no Qdrant writes, no Council deliberation. Resolves a case slug,
freezes work-product (and optionally privileged) context, assembles a system
+ user prompt, streams BRAIN's response, and emits a JSON record with
retrieval, latency, and grounding metrics.

Usage::

    python -m backend.scripts.brain_rag_probe \\
      --case-slug 7il-v-knight-ndga-i \\
      --question "..." \\
      --max-tokens 2000 \\
      --top-k 15 \\
      --include-privileged \\
      --output /tmp/probe-a5-run1.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional, cast

from sqlalchemy import text as sa_text

from backend.api.legal_cases import _resolve_case_slug
from backend.services.brain_client import BrainClient, BrainClientError
from backend.services.ediscovery_agent import LegacySession
from backend.services.legal_council import (
    freeze_context,
    freeze_privileged_context,
)


PROBE_VERSION = "phase-a5-1"

LATENCY_GATE_SECONDS = 60.0
MIN_TOTAL_CHUNKS = 10
MIN_GROUNDING_CITATIONS = 3

SYSTEM_PROMPT = (
    "detailed thinking on\n\n"
    "You are a meticulous legal analyst supporting Fortress Prime's defense team. "
    "Answer ONLY from the CASE EVIDENCE blocks below. If the evidence does not "
    "answer the question, say so plainly. When citing evidence, refer to the "
    "bracketed source filename in the chunk header. Privileged chunks are "
    "marked [PRIVILEGED · ...]; do not paraphrase them outside this engagement."
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("brain_rag_probe")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase A5 BRAIN + RAG probe")
    p.add_argument("--case-slug", required=True)
    p.add_argument("--question", required=True)
    p.add_argument("--max-tokens", type=int, default=2000)
    p.add_argument("--top-k", type=int, default=15)
    p.add_argument("--include-privileged", action="store_true")
    p.add_argument("--privileged-top-k", type=int, default=10)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--output", required=True, help="Path to write JSON probe record")
    return p.parse_args()


async def _resolve_slug_and_related(slug: str) -> tuple[str, list[str]]:
    """Resolve the slug (alias-aware) and pull legal.cases.related_matters."""
    async with LegacySession() as session:
        canonical = await _resolve_case_slug(session, slug)
        r = await session.execute(
            sa_text("SELECT related_matters FROM legal.cases WHERE case_slug = :s"),
            {"s": canonical},
        )
        row = r.fetchone()
    related: list[str] = []
    if row and row[0]:
        raw = row[0]
        if isinstance(raw, list):
            related = [s for s in raw if isinstance(s, str) and s and s != canonical]
        elif isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    related = [s for s in parsed if isinstance(s, str) and s and s != canonical]
            except (TypeError, ValueError):
                related = []
    return canonical, related


async def _retrieve_workproduct(
    case_slug: str,
    related: list[str],
    question: str,
    top_k: int,
) -> tuple[list[str], list[str]]:
    primary_ids, primary_chunks = await freeze_context(
        case_brief=question, top_k=top_k, case_slug=case_slug
    )
    all_ids = list(primary_ids)
    all_chunks = list(primary_chunks)
    for rel_slug in related:
        ids, chunks = await freeze_context(case_brief=question, top_k=top_k, case_slug=rel_slug)
        all_ids.extend(ids)
        all_chunks.extend(chunks)
    return all_ids, all_chunks


async def _retrieve_privileged(
    case_slug: str,
    question: str,
    top_k: int,
) -> tuple[list[str], list[str]]:
    return await freeze_privileged_context(
        case_brief=question, top_k=top_k, case_slug=case_slug
    )


def _build_user_prompt(
    question: str,
    workproduct_chunks: list[str],
    privileged_chunks: list[str],
) -> str:
    sections: list[str] = []
    if workproduct_chunks:
        sections.append("=== CASE EVIDENCE (work product) ===\n" + "\n\n".join(workproduct_chunks))
    if privileged_chunks:
        sections.append(
            "=== CASE EVIDENCE (privileged communications, FYEO) ===\n"
            + "\n\n".join(privileged_chunks)
        )
    sections.append("=== QUESTION ===\n" + question)
    return "\n\n".join(sections)


def _detect_grounding(
    response_text: str,
    chunks: list[str],
) -> tuple[int, list[str]]:
    """Crude grounding: count chunk-source filenames that appear in the response.

    Each chunk header looks like ``[file_name] body`` or
    ``[PRIVILEGED · domain · role] [file_name] body``. We pull the bracketed
    filename token and look for substring hits in the response.
    """
    sources: list[str] = []
    for c in chunks:
        # Last bracketed token before the body — handles the privileged prefix.
        m = re.findall(r"\[([^\[\]]+)\]", c[:400])
        if not m:
            continue
        candidate = m[-1].strip()
        if candidate and candidate != "PRIVILEGED" and candidate not in sources:
            sources.append(candidate)
    matched = [s for s in sources if s and s in response_text]
    return len(matched), matched


def _approx_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


async def _run_probe(args: argparse.Namespace) -> dict[str, Any]:
    started_wall = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()

    canonical_slug, related = await _resolve_slug_and_related(args.case_slug)
    logger.info(
        "resolved_case_slug input=%s canonical=%s related_matters=%d",
        args.case_slug, canonical_slug, len(related),
    )

    wp_ids, wp_chunks = await _retrieve_workproduct(
        canonical_slug, related, args.question, args.top_k
    )
    if args.include_privileged:
        priv_ids, priv_chunks = await _retrieve_privileged(
            canonical_slug, args.question, args.privileged_top_k
        )
    else:
        priv_ids, priv_chunks = [], []

    logger.info(
        "retrieval_complete workproduct_chunks=%d privileged_chunks=%d",
        len(wp_chunks), len(priv_chunks),
    )

    user_prompt = _build_user_prompt(args.question, wp_chunks, priv_chunks)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    client = BrainClient()
    chunks_text: list[str] = []
    ttft: Optional[float] = None
    finish_reason = "stop"  # vLLM does not surface this in the delta stream; assume stop unless we see otherwise
    error: Optional[str] = None
    streaming_started = time.monotonic()

    try:
        iterator = cast(
            AsyncIterator[str],
            await client.chat(
                messages=messages,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                stream=True,
            ),
        )
        async for chunk in iterator:
            if ttft is None:
                ttft = time.monotonic() - streaming_started
            chunks_text.append(chunk)
    except BrainClientError as exc:
        error = str(exc)
        finish_reason = "error"
        logger.error("brain_call_failed error=%s", error)

    response_text = "".join(chunks_text)
    total_elapsed = time.monotonic() - started

    # Heuristic truncation guard: vLLM emits no [DONE] surrogate in finish_reason
    # for the streamed delta. We approximate finish_reason="length" when the
    # completion approaches the requested cap.
    if not error and _approx_tokens(response_text) >= int(args.max_tokens * 0.97):
        finish_reason = "length"

    grounded_count, grounded_sources = _detect_grounding(response_text, wp_chunks + priv_chunks)

    prompt_text = SYSTEM_PROMPT + "\n\n" + user_prompt
    prompt_tokens = _approx_tokens(prompt_text)
    completion_tokens = _approx_tokens(response_text)

    pass_conditions = {
        "retrieval_min_chunks": (len(wp_chunks) + len(priv_chunks)) >= MIN_TOTAL_CHUNKS,
        "finish_reason_stop": finish_reason == "stop",
        "grounding_min_citations": grounded_count >= MIN_GROUNDING_CITATIONS,
        "latency_under_gate": total_elapsed < LATENCY_GATE_SECONDS,
        "no_error": error is None,
    }
    overall_pass = all(pass_conditions.values())

    record = {
        "probe_version": PROBE_VERSION,
        "started_at_utc": started_wall,
        "case_slug_input": args.case_slug,
        "case_slug_canonical": canonical_slug,
        "related_matters": related,
        "question": args.question,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "top_k": args.top_k,
        "include_privileged": args.include_privileged,
        "retrieved_chunk_ids": {
            "work_product": wp_ids,
            "privileged": priv_ids,
        },
        "retrieved_chunk_counts": {
            "work_product": len(wp_chunks),
            "privileged": len(priv_chunks),
        },
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "ttft_seconds": ttft,
        "total_elapsed_seconds": round(total_elapsed, 3),
        "finish_reason": finish_reason,
        "contains_privileged": bool(priv_chunks),
        "response_text": response_text,
        "grounding_evidence": {
            "matched_count": grounded_count,
            "matched_sources": grounded_sources,
        },
        "pass_conditions": pass_conditions,
        "result": "PASS" if overall_pass else "FAIL",
        "error": error,
    }
    return record


def _print_summary(record: dict[str, Any]) -> None:
    pcounts = record["retrieved_chunk_counts"]
    ttft = record["ttft_seconds"]
    privileged_marker = "APPENDED" if record["contains_privileged"] else "NOT_NEEDED"
    print()
    print(f"PROBE A5 RESULT: {record['result']}")
    print()
    print(
        f"Retrieval:        {pcounts['work_product']} chunks from legal_ediscovery, "
        f"{pcounts['privileged']} from legal_privileged_communications"
    )
    fr = record["finish_reason"]
    print(f"Streaming:        finish_reason={fr}")
    print(
        f"Latency:          TTFT {ttft if ttft is not None else 'n/a'}s, "
        f"total {record['total_elapsed_seconds']}s (gate {LATENCY_GATE_SECONDS}s)"
    )
    print(f"Grounding:        {record['grounding_evidence']['matched_count']} citations matched against retrieved chunks")
    print(f"Privilege:        FYEO warning [{privileged_marker}]")
    if record.get("error"):
        print(f"Error:            {record['error']}")
    print()
    print(
        f"PASS = retrieval >= {MIN_TOTAL_CHUNKS} AND finish_reason=stop "
        f"AND grounding >= {MIN_GROUNDING_CITATIONS} AND latency < {int(LATENCY_GATE_SECONDS)}s"
    )


async def main() -> int:
    args = _parse_args()
    record = await _run_probe(args)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True)
    _print_summary(record)
    return 0 if record["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
