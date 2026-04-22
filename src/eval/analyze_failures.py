"""
analyze_failures.py — Phase 2: Failure mode analysis for legal/B.

Reads per-sample outputs from outputs.jsonl (produced by run_eval_v2 --save-outputs).
Categorizes failures into actionable failure modes.
Also audits training pair quality distribution.

Usage:
  python -m src.eval.analyze_failures \
      --outputs /mnt/fortress_nas/models/.../outputs.jsonl \
      --train-pairs /mnt/fortress_nas/legal-corpus/training-pairs/train.jsonl \
      [--additions-dir /mnt/fortress_nas/datasets/legal-instruct/additions-20260421/] \
      --domain legal/B \
      --threshold 0.60 \
      --out evals/audits/legal_b_failure_modes_20260422.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.eval.metrics.citations import extract_citations
from src.eval.metrics.topics import parse_topics, topic_f1


# ---------------------------------------------------------------------------
# Failure mode classifiers
# ---------------------------------------------------------------------------

def _classify_b_failure(sample: dict) -> str:
    """
    Categorize why a Pattern B sample scored low.
    Returns one of: format_failure, topic_mismatch, partial_match,
                    single_topic_vs_multi, hallucinated_topics, good_enough
    """
    output = sample.get("output", "")
    teacher = sample.get("teacher", "")
    sim = sample.get("metrics", {}).get("similarity", 1.0)
    format_ok = sample.get("metrics", {}).get("format_ok", True)
    topic_recall = sample.get("metrics", {}).get("topic_recall", 1.0)

    pred_topics = parse_topics(output)
    gold_topics = parse_topics(teacher)

    if not format_ok or not pred_topics:
        return "format_failure"

    if sim >= 0.60:
        return "good_enough"

    if len(gold_topics) > 3 and len(pred_topics) <= 1:
        return "single_topic_vs_multi"

    if topic_recall < 0.3:
        return "topic_mismatch"

    if 0.3 <= topic_recall < 0.7:
        return "partial_match"

    # Format ok, recall ok but similarity low → phrasing drift
    return "phrasing_drift"


def _classify_c_failure(sample: dict) -> str:
    """Categorize Pattern C failures."""
    citation_f1 = sample.get("metrics", {}).get("f1", 1.0)
    citation_recall = sample.get("metrics", {}).get("recall", 1.0)
    sim = sample.get("metrics", {}).get("similarity", 1.0)
    format_ok = sample.get("metrics", {}).get("citation_format_ok", True)

    if not format_ok:
        return "missing_under_prefix"
    if citation_f1 < 0.3 and sim > 0.60:
        return "wrong_citation_right_prose"
    if citation_recall < 0.5:
        return "citation_miss"
    if sim < 0.50:
        return "poor_overall"
    return "good_enough"


# ---------------------------------------------------------------------------
# Training pair audit
# ---------------------------------------------------------------------------

_PATTERN_B_TYPES = {
    "section_header": re.compile(r"^\s*\d+[\.\)]\s+[A-Z][a-z]"),
    "fact_pattern": re.compile(r"Given.*facts|Based on.*following", re.I),
    "stat_lookup": re.compile(r"O\.C\.G\.A\.|OCGA\s*§", re.I),
    "issue_spot": re.compile(r"key\s+legal\s+issues", re.I),
}


def audit_b_pairs(pairs: list[dict]) -> dict:
    """
    Classify each B pair by what it teaches:
      a. section→text_recall: pair provides case text, asks for section headers
      b. fact→section_lookup: pair asks for applicable statute given facts
      c. citation_paraphrase: pair involves paraphrasing cited statute text
      d. issue_spotting: pair identifies conceptual issues from case summary

    Returns distribution dict.
    """
    counts: Counter[str] = Counter()
    for pair in pairs:
        instr = pair.get("instruction", "")
        out = pair.get("output", "")

        if _PATTERN_B_TYPES["stat_lookup"].search(out):
            counts["citation_paraphrase"] += 1
        elif _PATTERN_B_TYPES["issue_spot"].search(instr):
            counts["section_header_extraction"] += 1
        elif _PATTERN_B_TYPES["fact_pattern"].search(instr):
            counts["fact_to_section"] += 1
        else:
            counts["section_header_extraction"] += 1  # default for B

    return dict(counts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_analysis(
    outputs_path: Path,
    train_pairs_path: Path,
    additions_dirs: list[Path],
    domain: str,
    sim_threshold: float,
    out_path: Path,
) -> None:
    # Load outputs
    outputs = [json.loads(l) for l in outputs_path.open() if l.strip()]
    domain_outputs = [o for o in outputs if o["domain"] == domain]
    print(f"Total outputs: {len(outputs)}, domain={domain}: {len(domain_outputs)}")

    # Separate failures
    failures = [o for o in domain_outputs
                if o["metrics"].get("similarity", 1.0) < sim_threshold]
    passing = [o for o in domain_outputs
               if o["metrics"].get("similarity", 1.0) >= sim_threshold]
    print(f"Failures (sim < {sim_threshold}): {len(failures)}/{len(domain_outputs)}")

    # Classify failures
    if domain == "legal/B":
        classify_fn = _classify_b_failure
    elif domain == "legal/C":
        classify_fn = _classify_c_failure
    else:
        classify_fn = lambda s: "unclassified"

    failure_cats: Counter[str] = Counter()
    for s in failures:
        failure_cats[classify_fn(s)] += 1

    # Load training B pairs
    train_b: list[dict] = []
    with train_pairs_path.open() as f:
        for l in f:
            r = json.loads(l)
            if r.get("pattern") == "B":
                train_b.append(r)

    for d in additions_dirs:
        for fname in ["new_b_pairs.jsonl", "eval_b.jsonl"]:
            p = d / fname
            if p.exists():
                with p.open() as f:
                    for l in f:
                        if l.strip():
                            r = json.loads(l)
                            if r.get("pattern") == "B" or "domain" in r:
                                train_b.append(r)

    pair_dist = audit_b_pairs(train_b)

    # Compute topic recall distribution across all B samples
    topic_recalls = [o["metrics"].get("topic_recall", 0.0)
                     for o in domain_outputs if "topic_recall" in o.get("metrics", {})]

    # Write report
    lines = [
        f"# Legal/B Failure Mode Analysis — 2026-04-22",
        "",
        f"## Domain: {domain}",
        f"- Total eval samples: {len(domain_outputs)}",
        f"- Passing (sim ≥ {sim_threshold}): {len(passing)}",
        f"- Failing (sim < {sim_threshold}): {len(failures)}",
        f"- Failure rate: {100*len(failures)/max(1,len(domain_outputs)):.1f}%",
        "",
        "## Failure Mode Distribution",
        "",
        "| Category | Count | % of failures |",
        "|---|---|---|",
    ]
    total_fail = max(1, len(failures))
    for cat, cnt in failure_cats.most_common():
        lines.append(f"| {cat} | {cnt} | {100*cnt/total_fail:.1f}% |")

    if topic_recalls:
        import statistics
        lines += [
            "",
            "## Topic Recall Distribution (legal/B)",
            f"- Mean topic recall: {statistics.mean(topic_recalls):.3f}",
            f"- Median: {statistics.median(topic_recalls):.3f}",
            f"- Samples with topic_recall=0: "
            f"{sum(1 for r in topic_recalls if r == 0)}",
            f"- Samples with topic_recall≥0.8: "
            f"{sum(1 for r in topic_recalls if r >= 0.8)}",
        ]

    lines += [
        "",
        "## Training Pair Type Distribution",
        "",
        "| Pair Type | Count | % |",
        "|---|---|---|",
    ]
    total_pairs = max(1, sum(pair_dist.values()))
    for ptype, cnt in sorted(pair_dist.items(), key=lambda x: -x[1]):
        lines.append(f"| {ptype} | {cnt} | {100*cnt/total_pairs:.1f}% |")

    lines += [
        "",
        "## Diagnosis",
        "",
        "### Pattern B Task Definition",
        "Pattern B = extract numbered section headers from court opinion text.",
        "Gold answers are section headers from each specific case — highly",
        "idiosyncratic per opinion. Task does NOT involve statute citation or OCGA lookup.",
        "",
        "### Root Cause Hypothesis",
    ]

    # Generate hypothesis based on failure distribution
    top_failure = failure_cats.most_common(1)[0][0] if failure_cats else "unknown"
    if top_failure == "phrasing_drift":
        lines.append(
            "**Primary failure: phrasing drift.** Model extracts conceptually correct "
            "topics but uses different phrasing than the gold section headers. "
            "Similarity metric penalizes correct answers."
        )
        lines.append("")
        lines.append("**Recommended fix:** This is partly a metric problem, not a model problem. "
                     "Switch to topic_f1 as primary metric for legal/B. "
                     "If retraining: add pairs where gold has varied phrasing for same concepts.")
    elif top_failure == "topic_mismatch":
        lines.append(
            "**Primary failure: topic mismatch.** Model extracts wrong section topics."
            " The pair-generation corpus needs more structural variety."
        )
    elif top_failure == "format_failure":
        lines.append(
            "**Primary failure: format failure.** Model fails to produce numbered list."
            " Need more training pairs reinforcing the numbered list format."
        )
    elif top_failure == "single_topic_vs_multi":
        lines.append(
            "**Primary failure: insufficient topic extraction.** Gold has 3+ topics but "
            "model outputs only 1. Need training pairs with multi-topic gold answers."
        )
    else:
        lines.append(f"Primary failure mode: {top_failure}. See table above.")

    lines += [
        "",
        "## Sample Low-Scoring B Outputs",
        "",
    ]
    for s in sorted(failures, key=lambda x: x["metrics"].get("similarity", 1.0))[:5]:
        sim = s["metrics"].get("similarity", 0.0)
        tr = s["metrics"].get("topic_recall", 0.0)
        lines.append(f"**Record {s['record_id']} (sim={sim:.3f}, topic_recall={tr:.3f}):**")
        lines.append(f"- Gold topics: {parse_topics(s['teacher'])}")
        lines.append(f"- Model topics: {parse_topics(s['output'])}")
        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    print(f"Report written to {out_path}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--outputs", required=True, type=Path)
    p.add_argument("--train-pairs", required=True, type=Path)
    p.add_argument("--additions-dir", action="append", dest="additions_dirs",
                   type=Path, default=[])
    p.add_argument("--domain", default="legal/B")
    p.add_argument("--threshold", type=float, default=0.60)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()

    run_analysis(
        outputs_path=args.outputs,
        train_pairs_path=args.train_pairs,
        additions_dirs=args.additions_dirs,
        domain=args.domain,
        sim_threshold=args.threshold,
        out_path=args.out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
