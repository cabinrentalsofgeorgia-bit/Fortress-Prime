"""Per-section synthesizer functions for `case_briefing_compose`.

Two flavors:

- **Mechanical** (sections 01, 03, 06, 10) — deterministic, template-driven,
  no LLM. Pulls from `GroundingPacket.case_metadata` and
  `GroundingPacket.curated_nas_files`. Always passes grounding-citation
  enforcement because it cites by document_id directly.

- **Synthesis** (sections 02, 04, 05, 07, 08) — call BrainClient with a
  packet-grounded prompt; reassemble streamed chunks; extract grounded
  citations from the response. Section 07 enforces a privilege-filter on
  defense-counsel correspondence (per Track A v2 framing).

Sections are intentionally template-bounded for v0.1 — the prompts are
self-contained and produce briefing-table-style output rather than free-form
prose. This keeps the orchestrator's first-iteration output predictable and
the live BRAIN dry-run tractable.
"""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator, Optional, cast

from backend.services.brain_client import BrainClient
from backend.services.case_briefing_compose import (
    GroundingPacket,
    SectionResult,
)


logger = logging.getLogger("case_briefing_synthesizers")


_SYSTEM_PROMPT = (
    "detailed thinking on\n\n"
    "You are a meticulous legal analyst supporting Fortress Prime's defense team. "
    "Answer ONLY from the CASE EVIDENCE blocks provided. Cite the bracketed source "
    "filename in each chunk header for every factual claim. Privileged chunks are "
    "marked [PRIVILEGED · ...]; do not paraphrase them outside this engagement. "
    "If the evidence does not answer a question, say so plainly — never invent.\n\n"
    "OUTPUT CONTRACT (Phase B v0.3): Use <think>...</think> for your reasoning "
    "ONLY. Place your final answer, including all citations, OUTSIDE the "
    "</think> closing tag. The text outside <think> is what becomes the "
    "section content; the text inside <think> will be stripped before "
    "delivery. Do not put bullet points, tables, headings, or factual "
    "citations inside <think>; those belong in the final answer outside "
    "the tags."
)


# ── Reasoning-trace stripping (Phase B v0.2 Pass 1) ──────────────────────────
#
# BRAIN (Nemotron-Super-49B-v1.5-fp8) emits visible <think>...</think> blocks
# by design — the system prompt's "detailed thinking on" turns this on, and
# the model uses the trace as a working memory before producing its actual
# answer. The trace is unsuitable for white-shoe-grade attorney briefs:
# it contains first-person planning prose ("Let me address...", "I should
# focus on..."), self-corrections, and meta-commentary that breaks the
# voice of a legal product.
#
# Pass 1 (this PR): strip the <think>...</think> tags + their contents.
# Pass 2 (deferred): handle first-person planning prose that survives
#   *outside* the tags. Tracked as a follow-up if the surviving count is
#   non-trivial.

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL)
# Truncated trace: <think> with no matching close tag. Strip from <think>
# to the next blank line (double-newline) or end of text — the model is
# either still trace-thinking when it ran out of tokens or the stream cut
# mid-thought; either way the partial trace is unusable downstream.
_UNCLOSED_THINK_RE = re.compile(r"<think>(?:(?!\n\n).)*(?:\n\n|\Z)", flags=re.DOTALL)
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")


def strip_reasoning_trace(text: str) -> str:
    """Remove BRAIN's <think>...</think> reasoning traces from synthesizer output.

    Pass 1 scope: tag-only stripping. First-person prose that survives
    outside <think> tags is intentionally preserved — Pass 2 (if needed) is
    a separate brief.

    Behavior:
    - Strip every closed `<think>...</think>` block (multiline-aware, greedy
      to the nearest `</think>`).
    - For an unclosed `<think>` (truncated mid-trace): strip from `<think>`
      to the next double-newline OR end of text, whichever comes first.
    - Collapse runs of 3+ consecutive newlines down to 2 (artifact cleanup).
    - Strip leading/trailing whitespace.

    Idempotent: running twice on the same text equals running once.
    """
    if not text:
        return text
    # 1. Strip closed blocks first (the common case).
    cleaned = _THINK_BLOCK_RE.sub("", text)
    # 2. Strip any remaining unclosed <think> (truncated stream).
    cleaned = _UNCLOSED_THINK_RE.sub("", cleaned)
    # 3. Collapse newline runs.
    cleaned = _EXCESS_NEWLINES_RE.sub("\n\n", cleaned)
    # 4. Trim outer whitespace.
    return cleaned.strip()


_DEFENSE_COUNSEL_DOMAINS = (
    "mhtlegal.com",
    "fgplaw.com",
    "msp-lawfirm.com",
    "msplawfirm.com",
    "dralaw.com",
)
_DEFENSE_COUNSEL_NAMES = (
    "underwood",
    "podesta",
    "sanker",
    "argo",
)


# ── Mechanical synthesizers ───────────────────────────────────────────────────

def synthesize_mechanical(section_id: str, packet: GroundingPacket) -> str:
    if section_id == "section_01_case_summary":
        return _section_01_case_summary(packet)
    if section_id == "section_03_parties_and_counsel":
        return _section_03_parties_and_counsel(packet)
    if section_id == "section_06_evidence_inventory":
        return _section_06_evidence_inventory(packet)
    if section_id == "section_10_filing_checklist":
        return _section_10_filing_checklist(packet)
    raise ValueError(f"Unknown mechanical section {section_id!r}")


def operator_written_placeholder(title: str) -> str:
    return (
        f"> **[TO BE WRITTEN BY OPERATOR]** — {title} is reserved for "
        "counsel-operator deliberation, not automated synthesis. The facts "
        "the strategy must address are below; the strategic decisions are "
        "intentionally left for human / counsel judgment.\n\n"
        "_Phase B orchestrator left this section as a deliberate placeholder "
        "(per Case II Build Plan §B6 / §5.4 of the Phase B brief)._"
    )


def _section_01_case_summary(packet: GroundingPacket) -> str:
    cm = packet.case_metadata
    rows: list[tuple[str, str]] = [
        ("Case Number", _scalar(cm.get("case_number"))),
        ("Court", _scalar(cm.get("court"))),
        ("Judge", _scalar(cm.get("judge"))),
        ("Case Type", _scalar(cm.get("case_type"))),
        ("Our Role", _scalar(cm.get("our_role"))),
        ("Status", _scalar(cm.get("status"))),
        ("Critical Date", _scalar(cm.get("critical_date"))),
        ("Plan Admin", _scalar(cm.get("plan_admin"))),
        ("Opposing Counsel (DB)", _scalar(cm.get("opposing_counsel"))),
        ("Petition Date", _scalar(cm.get("petition_date"))),
    ]
    out: list[str] = ["| Field | Detail |", "|---|---|"]
    for k, v in rows:
        out.append(f"| {k} | {v} |")
    if packet.related_matters:
        out.append(
            f"| Related Matters | {', '.join(f'`{s}`' for s in packet.related_matters)} |"
        )
    return "\n".join(out)


def _section_03_parties_and_counsel(packet: GroundingPacket) -> str:
    cm = packet.case_metadata
    blocks: list[str] = []
    blocks.append("### 3.1 Plaintiff / Counsel of Record")
    blocks.append("")
    blocks.append(f"- **Plaintiff:** {_scalar(cm.get('case_name'))}")
    blocks.append(f"- **Opposing counsel (per legal.cases):** {_scalar(cm.get('opposing_counsel'))}")
    blocks.append("")
    blocks.append("### 3.2 Defendant Posture")
    blocks.append("")
    blocks.append(f"- **Our role:** {_scalar(cm.get('our_role'))}")
    blocks.append(f"- **Case status:** {_scalar(cm.get('status'))}")
    blocks.append("")
    blocks.append("> Counsel-continuity timeline (defense-side history) is operator-curated when "
                  "available; absent operator input, this section pulls only from `legal.cases` "
                  "and does not assert facts beyond that row.")
    return "\n".join(blocks)


def _section_06_evidence_inventory(packet: GroundingPacket) -> str:
    by_cluster: dict[str, list[dict]] = {}
    for f in packet.curated_nas_files:
        by_cluster.setdefault(f.get("cluster", "other"), []).append(f)

    lines: list[str] = []
    lines.append("### 6.1 Curated Evidence Set (vault_documents)")
    lines.append("")
    lines.append(f"Total documents: **{len(packet.curated_nas_files)}**.")
    lines.append("")
    if by_cluster:
        lines.append("| Cluster | Count | Top documents |")
        lines.append("|---|---:|---|")
        for cluster in sorted(by_cluster):
            files = sorted(by_cluster[cluster], key=lambda f: -f.get("relevance", 0))[:3]
            top = "; ".join(f"`{f.get('file_name', '?')}`" for f in files)
            lines.append(f"| {cluster} | {len(by_cluster[cluster])} | {top} |")
        lines.append("")

    lines.append("### 6.2 Sovereign Retrieval Snapshot")
    lines.append("")
    lines.append(
        f"- Work-product chunks retrieved (from `legal_ediscovery`): "
        f"**{len(packet.work_product_chunk_ids)}**"
    )
    lines.append(
        f"- Privileged chunks retrieved (from `legal_privileged_communications`): "
        f"**{len(packet.privileged_chunk_ids)}**"
    )
    lines.append(
        f"- Related-matter case slugs included in retrieval: "
        f"{', '.join(f'`{s}`' for s in packet.related_matters) or '_none_'}"
    )
    return "\n".join(lines)


def _section_10_filing_checklist(packet: GroundingPacket) -> str:
    cm = packet.case_metadata
    critical_date = _scalar(cm.get("critical_date"))
    lines: list[str] = []
    lines.append("### 10.1 Immediate (within 7 days of brief delivery)")
    lines.append("")
    lines.append("- [ ] Confirm operator's preferred counsel candidate")
    lines.append("- [ ] Operator personal-records sweep complete (per Section 6.5 personal-sweep checklist if present)")
    lines.append("- [ ] Verify service of process status")
    lines.append("- [ ] Confirm related-matters scope")
    lines.append("")
    lines.append("### 10.2 Calendar pulls")
    lines.append("")
    lines.append(f"- Critical date on file: **{critical_date}**")
    if cm.get("petition_date"):
        lines.append(f"- Petition date: {_scalar(cm.get('petition_date'))}")
    lines.append("")
    lines.append("### 10.3 Discovery posture (within 30 days; coordinated with counsel)")
    lines.append("")
    lines.append("- [ ] Initial disclosures contract / objection plan")
    lines.append("- [ ] Custodian list locked")
    lines.append("- [ ] Privilege log seed populated from `legal_privileged_communications` retrieval")
    return "\n".join(lines)


def _scalar(v) -> str:
    if v is None:
        return "_unknown_"
    s = str(v)
    return s if s else "_unknown_"


# ── Synthesis synthesizers ────────────────────────────────────────────────────

async def synthesize_synthesis_section(
    section_id: str,
    packet: GroundingPacket,
    *,
    brain_client: BrainClient,
    max_tokens: int = 2000,
) -> SectionResult:
    """Run a BRAIN call against the packet and produce a SectionResult."""
    title_map = {
        "section_02_critical_timeline": "2. Critical Timeline",
        "section_04_claims_analysis": "4. Claims Analysis",
        "section_05_key_defenses_identified": "5. Key Defenses Identified",
        "section_07_email_intelligence_report": "7. Email Intelligence Report",
        "section_08_financial_exposure_analysis": "8. Financial Exposure Analysis",
    }
    title = title_map.get(section_id, section_id)
    prompt_template = _SYNTHESIS_PROMPTS[section_id]

    # Section 7 enforces a privilege filter on the chunks before they hit the
    # prompt: defense counsel correspondence is excluded.
    work_product_chunks = packet.work_product_chunk_texts
    privileged_chunks = packet.privileged_chunk_texts
    if section_id == "section_07_email_intelligence_report":
        work_product_chunks = [
            c for c in work_product_chunks if not _is_defense_counsel_chunk(c)
        ]

    user_prompt = _build_synthesis_user_prompt(
        prompt_template=prompt_template,
        case_metadata=packet.case_metadata,
        work_product_chunks=work_product_chunks,
        privileged_chunks=privileged_chunks if section_id != "section_07_email_intelligence_report" else [],
    )

    response = ""
    iterator = cast(
        AsyncIterator[str],
        await brain_client.chat(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.0,
            stream=True,
        ),
    )
    async for chunk in iterator:
        response += chunk

    # Phase B v0.2 Pass 1: strip BRAIN's <think>...</think> reasoning traces
    # before any downstream processing (citation detection, SectionResult).
    # Done before _detect_grounding_citations so the citation match runs
    # against the cleaned body — citations don't appear inside <think>
    # blocks (BRAIN doesn't cite mid-trace), but stripping first keeps
    # semantics clean and avoids any future trace-mining ambiguity.
    response = strip_reasoning_trace(response)

    grounded_citations, matched_sources = _detect_grounding_citations(
        response,
        work_product_chunks + (privileged_chunks if section_id != "section_07_email_intelligence_report" else []),
    )

    contains_privileged = (
        section_id != "section_07_email_intelligence_report"
        and any(privileged_chunks)
    )

    return SectionResult(
        section_id=section_id,
        title=title,
        mode="synthesis",
        content=response,
        grounding_citations=matched_sources,
        retrieval_chunk_ids=list(packet.work_product_chunk_ids) + list(packet.privileged_chunk_ids),
        contains_privileged=contains_privileged,
        operator_status="draft",
    )


_SYNTHESIS_PROMPTS: dict[str, str] = {
    "section_02_critical_timeline": (
        "Produce a chronological timeline of dated events for this case, drawn ONLY "
        "from the case evidence below. Format as a markdown table with columns: "
        "Date | Event | Source. Cite the bracketed filename for each row."
    ),
    "section_04_claims_analysis": (
        "Identify each cause of action / count alleged against the operator. For each: "
        "(a) the elements as stated in the evidence, (b) the operator's likely defense theory "
        "from the evidence, (c) supporting + adverse evidence with bracketed-filename citations. "
        "Do not invent claims; stick to what the evidence says."
    ),
    "section_05_key_defenses_identified": (
        "List the affirmative defenses + non-affirmative defense theories supported by the "
        "evidence. For each: cite the supporting chunks by bracketed filename. Flag any defense "
        "where the evidence is thin or contradicted."
    ),
    "section_07_email_intelligence_report": (
        "Adversary correspondence + third-party-actor correspondence ONLY. "
        "Defense counsel correspondence has been excluded as privileged. Identify each "
        "adversary or third-party actor present in the evidence with the bracketed-filename "
        "citation for each appearance. If the substrate is thin, say so plainly."
    ),
    "section_08_financial_exposure_analysis": (
        "Compute or estimate financial exposure scenarios from the evidence: damages claimed, "
        "supporting amounts, attorney-fee exposure, settlement-anchor evidence. Cite by "
        "bracketed filename for every dollar figure."
    ),
}


def _build_synthesis_user_prompt(
    *,
    prompt_template: str,
    case_metadata: dict,
    work_product_chunks: list[str],
    privileged_chunks: list[str],
) -> str:
    parts: list[str] = []
    parts.append("=== CASE METADATA ===")
    for k in ("case_name", "case_number", "court", "judge", "our_role", "status"):
        v = case_metadata.get(k)
        if v:
            parts.append(f"- **{k}:** {v}")
    parts.append("")
    if work_product_chunks:
        parts.append("=== CASE EVIDENCE (work product) ===")
        parts.append("\n\n".join(work_product_chunks))
        parts.append("")
    if privileged_chunks:
        parts.append("=== CASE EVIDENCE (privileged communications, FYEO) ===")
        parts.append("\n\n".join(privileged_chunks))
        parts.append("")
    parts.append("=== INSTRUCTION ===")
    parts.append(prompt_template)
    return "\n".join(parts)


def _detect_grounding_citations(
    response: str,
    chunks: list[str],
) -> tuple[int, list[str]]:
    """Each chunk's header is `[file_name] body` (or `[PRIVILEGED · ...] [file_name] body`).
    Return (count, list of matched source filenames).
    """
    sources: list[str] = []
    for c in chunks:
        m = re.findall(r"\[([^\[\]]+)\]", c[:400])
        if not m:
            continue
        candidate = m[-1].strip()
        if candidate and candidate != "PRIVILEGED" and candidate not in sources:
            sources.append(candidate)
    matched = [s for s in sources if s and s in response]
    return len(matched), matched


def _is_defense_counsel_chunk(chunk_text: str) -> bool:
    """Return True if a chunk looks like operator-defense-counsel correspondence
    (Underwood / Podesta / Sanker / Argo and their email domains)."""
    head = chunk_text[:400].lower()
    if any(domain in head for domain in _DEFENSE_COUNSEL_DOMAINS):
        return True
    if any(name in head for name in _DEFENSE_COUNSEL_NAMES):
        return True
    return False
