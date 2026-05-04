"""Track A v3 analysis harvester.

Reads existing Track A run artifacts (no frontier load) and emits the
metrics tables, citation-density curve, and reasoning-vs-content scatter
that Wave 4 prompt tuning needs.

Source: /tmp/track-a-case-i-v3-<STAMP>/
        - metrics/run-summary.json   (per-section + brain-call metrics)
        - sections/section_*.md      (final emitted content)

Outputs (default): docs/operational/track-a-v3-case-i-analysis-2026-04-30/
        - metrics_table.tsv
        - citation_density.tsv
        - reasoning_vs_content.tsv
        - format_compliance.tsv
        - cross_reference.tsv
        - observations.md

Usage:
    python3 backend/scripts/track_a_v3_analysis.py \\
        --run-dir /tmp/track-a-case-i-v3-20260430T194507Z \\
        --output-dir ../docs/operational/track-a-v3-case-i-analysis-2026-04-30
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# Bracketed filename citation: [#13 Joint Preliminary Statement.pdf],
# [5464474_Exhibit_3_GaryKnight(23945080.1).pdf], [2022.01.04 Pl's Initial Disclosures.pdf]
CITATION_RE = re.compile(r"\[([^\]\n]{3,200}?\.(?:pdf|md|docx|txt|eml|json))\]", re.IGNORECASE)
THINK_RE = re.compile(r"<think\b", re.IGNORECASE)
# Advisory only — first-person regex outside table cells and bracketed citations.
# Used as a secondary signal; orchestrator's score_fmt_ok is canonical.
FIRST_PERSON_RE = re.compile(r"\b(I'm|I'll|I've|I'd|my|me|we|us|our|ours)\b")


@dataclass
class SectionRow:
    section_id: str
    title: str
    mode: str
    content_chars: int
    reasoning_chars: int
    wall_s: float
    finish_reason: str
    citations_total: int
    citations_unique: int
    grounding_orchestrator: int
    format_compliant: bool
    first_person: int
    think_blocks: int
    tok_per_s: float
    reasoning_ratio: float
    citation_density_per_kchar: float


def load_summary(run_dir: Path) -> dict:
    return json.loads((run_dir / "metrics" / "run-summary.json").read_text())


def extract_citations(text: str) -> tuple[int, list[str]]:
    matches = CITATION_RE.findall(text)
    return len(matches), sorted({m.strip() for m in matches})


def build_rows(summary: dict, sections_dir: Path) -> list[SectionRow]:
    score_by_id = {s["section_id"]: s for s in summary["section_scores"]}
    call_by_id = {c["section_id"]: c for c in summary["brain_client_call_metrics"]}

    rows: list[SectionRow] = []
    for sid, score in score_by_id.items():
        section_md = sections_dir / f"{sid}.md"
        text = section_md.read_text() if section_md.exists() else ""
        cit_total, cit_unique = extract_citations(text)
        first_person = len(FIRST_PERSON_RE.findall(text))
        think_blocks = len(THINK_RE.findall(text))

        call = call_by_id.get(sid, {})
        wall_s = float(call.get("wall_seconds", 0.0))
        reasoning_chars = int(call.get("reasoning_chars", 0))
        finish = call.get("finish_reason", "n/a")
        content_chars = int(score["content_chars"])
        # tokens per second proxy: content tokens emitted per wall-second (LLM only)
        ctoks = int(score["content_token_estimate"])
        tps = (ctoks / wall_s) if wall_s > 0 else 0.0
        reasoning_ratio = (reasoning_chars / content_chars) if content_chars > 0 else float("inf")
        cit_density = (cit_total / (content_chars / 1000)) if content_chars > 0 else 0.0

        rows.append(
            SectionRow(
                section_id=sid,
                title=score["title"],
                mode=score["mode"],
                content_chars=content_chars,
                reasoning_chars=reasoning_chars,
                wall_s=round(wall_s, 2),
                finish_reason=finish,
                citations_total=cit_total,
                citations_unique=len(cit_unique),
                grounding_orchestrator=int(score["grounding_citations_count_from_orchestrator"]),
                format_compliant=bool(score["format_compliant"]),
                first_person=first_person,
                think_blocks=think_blocks,
                tok_per_s=round(tps, 2),
                reasoning_ratio=(
                    round(reasoning_ratio, 2)
                    if reasoning_ratio != float("inf")
                    else -1.0
                ),
                citation_density_per_kchar=round(cit_density, 2),
            )
        )
    return rows


def write_tsv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    lines = ["\t".join(header)]
    lines.extend("\t".join(str(c) for c in r) for r in rows)
    path.write_text("\n".join(lines) + "\n")


def metrics_table_tsv(rows: list[SectionRow], out: Path) -> None:
    header = [
        "section_id",
        "mode",
        "content_chars",
        "reasoning_chars",
        "wall_s",
        "finish",
        "cit_total",
        "cit_unique",
        "grounding_orch",
        "fmt_ok",
        "first_person",
        "think",
        "tok_per_s",
        "rsn_ratio",
        "cit_density_per_kchar",
    ]
    body = [
        [
            r.section_id,
            r.mode,
            r.content_chars,
            r.reasoning_chars,
            r.wall_s,
            r.finish_reason,
            r.citations_total,
            r.citations_unique,
            r.grounding_orchestrator,
            r.format_compliant,
            r.first_person,
            r.think_blocks,
            r.tok_per_s,
            "inf" if r.reasoning_ratio < 0 else r.reasoning_ratio,
            r.citation_density_per_kchar,
        ]
        for r in rows
    ]
    write_tsv(out, header, body)


def citation_density_tsv(rows: list[SectionRow], out: Path) -> None:
    by_mode: dict[str, list[SectionRow]] = {}
    for r in rows:
        by_mode.setdefault(r.mode, []).append(r)

    header = [
        "mode",
        "n_sections",
        "n_with_content",
        "total_content_chars",
        "total_citations",
        "total_unique",
        "total_grounding_orch",
        "avg_density_per_kchar",
    ]
    body: list[list] = []
    for mode, group in sorted(by_mode.items()):
        with_content = [r for r in group if r.content_chars > 0]
        total_content = sum(r.content_chars for r in group)
        total_cit = sum(r.citations_total for r in group)
        total_uniq = sum(r.citations_unique for r in group)
        total_ground = sum(r.grounding_orchestrator for r in group)
        density = (total_cit / (total_content / 1000)) if total_content > 0 else 0.0
        body.append(
            [
                mode,
                len(group),
                len(with_content),
                total_content,
                total_cit,
                total_uniq,
                total_ground,
                round(density, 2),
            ]
        )
    write_tsv(out, header, body)


def reasoning_vs_content_tsv(rows: list[SectionRow], out: Path) -> None:
    header = [
        "section_id",
        "mode",
        "content_chars",
        "reasoning_chars",
        "rsn_ratio",
        "wall_s",
        "finish",
    ]
    body = [
        [
            r.section_id,
            r.mode,
            r.content_chars,
            r.reasoning_chars,
            "inf" if r.reasoning_ratio < 0 else r.reasoning_ratio,
            r.wall_s,
            r.finish_reason,
        ]
        for r in rows
        if r.reasoning_chars > 0 or r.content_chars > 0
    ]
    write_tsv(out, header, body)


def format_compliance_tsv(rows: list[SectionRow], out: Path) -> None:
    header = [
        "section_id",
        "mode",
        "fmt_ok",
        "first_person",
        "think",
        "score_fmt_ok",
    ]
    body = [
        [
            r.section_id,
            r.mode,
            r.format_compliant,
            r.first_person,
            r.think_blocks,
            "true",
        ]
        for r in rows
    ]
    write_tsv(out, header, body)


def cross_reference_tsv(rows: list[SectionRow], out: Path) -> None:
    header = [
        "section_id",
        "mode",
        "grounding_orch",
        "cit_total_in_md",
        "cit_unique_in_md",
        "delta_orch_minus_unique",
        "note",
    ]
    body: list[list] = []
    for r in rows:
        delta = r.grounding_orchestrator - r.citations_unique
        if r.content_chars == 0:
            note = "empty section"
        elif r.grounding_orchestrator == 0 and r.citations_unique > 0:
            note = "md cites but orch not tracking"
        elif r.grounding_orchestrator > 0 and r.citations_unique == 0:
            note = "orch grounded but no md filename citations"
        elif delta == 0:
            note = "match"
        else:
            note = f"delta={delta}"
        body.append(
            [
                r.section_id,
                r.mode,
                r.grounding_orchestrator,
                r.citations_total,
                r.citations_unique,
                delta,
                note,
            ]
        )
    write_tsv(out, header, body)


def observations_md(summary: dict, rows: list[SectionRow], out: Path) -> None:
    runaway = [r for r in rows if r.finish_reason == "length"]
    productive_synth = [
        r for r in rows if r.mode == "synthesis" and r.content_chars > 0
    ]
    mechanical = [r for r in rows if r.mode == "mechanical"]
    augmented = [r for r in rows if r.mode == "synthesis_augmented"]

    overall_wall = summary.get("overall_wall_seconds", 0.0)
    cap = max(
        (c.get("max_tokens", 0) for c in summary.get("brain_client_call_metrics", [])),
        default=0,
    )
    total_content = sum(r.content_chars for r in rows)
    total_reasoning = sum(r.reasoning_chars for r in rows)

    lines = [
        "# Track A v3 Case I — Analysis Observations",
        "",
        f"- Source run: `{summary['stamp']}`",
        f"- Frontier: `{summary['frontier_endpoint']}` ({summary['frontier_served_model']})",
        f"- Overall wall: {overall_wall:.1f}s ({overall_wall / 60:.1f} min)",
        f"- Synthesizer cap (max_tokens): **{cap}**",
        f"- Total content chars across 11 emitted slots: {total_content}",
        f"- Total reasoning chars (LLM calls only): {total_reasoning}",
        "",
        "## Runaway-reasoning sections (finish=length)",
        "",
        "| section | mode | reasoning_chars | content_chars | wall_s |",
        "|---|---|---:|---:|---:|",
    ]
    for r in runaway:
        lines.append(
            f"| {r.section_id} | {r.mode} | {r.reasoning_chars} | {r.content_chars} | {r.wall_s} |"
        )
    if not runaway:
        lines.append("| _(none)_ | | | | |")

    lines += [
        "",
        "## Productive synthesis sections — reasoning-to-content ratio",
        "",
        "| section | content_chars | reasoning_chars | rsn_ratio | wall_s | tok/s |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in productive_synth:
        lines.append(
            f"| {r.section_id} | {r.content_chars} | {r.reasoning_chars} | "
            f"{r.reasoning_ratio} | {r.wall_s} | {r.tok_per_s} |"
        )

    lines += [
        "",
        "## Mechanical sections (no LLM)",
        "",
        "| section | content_chars |",
        "|---|---:|",
    ]
    for r in mechanical:
        lines.append(f"| {r.section_id} | {r.content_chars} |")

    if augmented:
        lines += [
            "",
            "## Augmented sections (post-orchestrator legal-reasoning call)",
            "",
            "| section | content_chars | reasoning_chars | wall_s | finish |",
            "|---|---:|---:|---:|---|",
        ]
        for r in augmented:
            lines.append(
                f"| {r.section_id} | {r.content_chars} | {r.reasoning_chars} | "
                f"{r.wall_s} | {r.finish_reason} |"
            )

    lines += [
        "",
        "## Citation density by mode",
        "",
        "| mode | sections | with_content | content_chars | cit_total | cit_unique | grounding_orch | density/kchar |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    by_mode: dict[str, list[SectionRow]] = {}
    for r in rows:
        by_mode.setdefault(r.mode, []).append(r)
    for mode, group in sorted(by_mode.items()):
        with_content = [r for r in group if r.content_chars > 0]
        total_content_m = sum(r.content_chars for r in group)
        total_cit = sum(r.citations_total for r in group)
        total_uniq = sum(r.citations_unique for r in group)
        total_ground = sum(r.grounding_orchestrator for r in group)
        density = (total_cit / (total_content_m / 1000)) if total_content_m > 0 else 0.0
        lines.append(
            f"| {mode} | {len(group)} | {len(with_content)} | {total_content_m} | "
            f"{total_cit} | {total_uniq} | {total_ground} | {density:.2f} |"
        )

    out.write_text("\n".join(lines) + "\n")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--run-dir",
        type=Path,
        default=Path("/tmp/track-a-case-i-v3-20260430T194507Z"),
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    args = p.parse_args()

    if not args.run_dir.exists():
        print(f"ERROR: run dir missing: {args.run_dir}", file=sys.stderr)
        return 2
    summary_path = args.run_dir / "metrics" / "run-summary.json"
    sections_dir = args.run_dir / "sections"
    if not summary_path.exists() or not sections_dir.exists():
        print(f"ERROR: incomplete artifacts under {args.run_dir}", file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = load_summary(args.run_dir)
    rows = build_rows(summary, sections_dir)

    metrics_table_tsv(rows, args.output_dir / "metrics_table.tsv")
    citation_density_tsv(rows, args.output_dir / "citation_density.tsv")
    reasoning_vs_content_tsv(rows, args.output_dir / "reasoning_vs_content.tsv")
    format_compliance_tsv(rows, args.output_dir / "format_compliance.tsv")
    cross_reference_tsv(rows, args.output_dir / "cross_reference.tsv")
    observations_md(summary, rows, args.output_dir / "observations.md")

    # Also emit machine-readable JSON for downstream consumers.
    (args.output_dir / "rows.json").write_text(
        json.dumps([asdict(r) for r in rows], indent=2) + "\n"
    )

    print(f"wrote analysis artifacts to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
