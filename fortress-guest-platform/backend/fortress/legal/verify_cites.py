#!/usr/bin/env python3
"""
CLI: python -m fortress.legal.verify_cites <draft_file> [--output-report <path>] [--no-llm]

Reads a draft text file, runs citation verification, prints report to stdout,
and writes JSON report to --output-report path if specified.

Exit code 0 = all citations pass Level 1+2 (passed_gate=True).
Exit code 1 = failures found.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure project root is importable
_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]  # backend/fortress/legal/verify_cites.py -> parents[3] = project root
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.legal.cite_verifier import (  # type: ignore[import-not-found]
    DraftVerificationReport,
    VerificationStatus,
    verify_draft,
)


def _format_report(report: DraftVerificationReport) -> str:
    """Format the report as a human-readable string."""
    lines = [
        "=" * 70,
        "FORTRESS LEGAL — CITATION VERIFICATION REPORT",
        "=" * 70,
        f"Draft ID    : {report.draft_id}",
        f"Verified at : {report.verified_at}",
        f"Gate        : {'PASS' if report.passed_gate else 'FAIL'}",
        "",
        "SUMMARY",
        "-" * 40,
        f"  Total citations  : {report.total_citations}",
        f"  Verified         : {report.passed}",
        f"  Not found (L1)   : {report.failed_level1}",
        f"  Misquoted (L3)   : {report.failed_level3}",
        f"  Uncheckable      : {report.uncheckable}",
        "",
        "CITATIONS",
        "-" * 40,
    ]

    for i, cite in enumerate(report.citations, start=1):
        status_icon = {
            VerificationStatus.VERIFIED: "✓",
            VerificationStatus.NOT_FOUND: "✗",
            VerificationStatus.MISQUOTED: "⚠",
            VerificationStatus.UNCHECKABLE: "?",
        }.get(cite.final_status, "?")

        lines.append(f"\n[{i}] {status_icon} {cite.final_status.value}")
        lines.append(f"    Type       : {cite.citation_type.value}")
        lines.append(f"    Raw        : {cite.raw[:120]}")
        lines.append(f"    Level 1    : {cite.level1_status.value}")
        lines.append(f"    Level 3    : {cite.level3_status.value}")
        lines.append(f"    Notes      : {cite.verification_notes[:200]}")
        if cite.level2_source_url:
            lines.append(f"    Source URL : {cite.level2_source_url}")

    lines += [
        "",
        "=" * 70,
        f"GATE RESULT: {'PASS — All citations verified or uncheckable' if report.passed_gate else 'FAIL — One or more citations failed verification'}",
        "=" * 70,
    ]
    return "\n".join(lines)


async def _run(
    draft_file: str,
    output_report: str | None,
    no_llm: bool,
) -> int:
    """Main async logic. Returns exit code."""
    draft_path = Path(draft_file)
    if not draft_path.exists():
        print(f"ERROR: File not found: {draft_file}", file=sys.stderr)
        return 2
    if not draft_path.is_file():
        print(f"ERROR: Not a file: {draft_file}", file=sys.stderr)
        return 2

    draft_text = draft_path.read_text(encoding="utf-8", errors="replace")

    print(f"Verifying citations in: {draft_path.name}")
    print(f"LLM extraction: {'disabled' if no_llm else 'enabled'}")
    print()

    try:
        report = await verify_draft(
            draft_text,
            use_llm_extraction=not no_llm,
            use_llm_support_check=not no_llm,
        )
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # Print human-readable report
    print(_format_report(report))

    # Write JSON report if requested
    if output_report:
        report_data = {
            "draft_id": report.draft_id,
            "verified_at": report.verified_at,
            "total_citations": report.total_citations,
            "passed": report.passed,
            "failed_level1": report.failed_level1,
            "failed_level3": report.failed_level3,
            "uncheckable": report.uncheckable,
            "passed_gate": report.passed_gate,
            "citations": [
                {
                    "raw": c.raw,
                    "citation_type": c.citation_type.value,
                    "proposition": c.proposition,
                    "level1_status": c.level1_status.value,
                    "level2_text": c.level2_text,
                    "level2_source_url": c.level2_source_url,
                    "level3_status": c.level3_status.value,
                    "final_status": c.final_status.value,
                    "verification_notes": c.verification_notes,
                }
                for c in report.citations
            ],
            "corrected_draft": report.corrected_draft,
        }
        out_path = Path(output_report)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
        print(f"\nJSON report written to: {out_path}")

    return 0 if report.passed_gate else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fortress Legal citation verifier CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m fortress.legal.verify_cites motion.txt\n"
            "  python -m fortress.legal.verify_cites motion.txt --output-report /tmp/report.json\n"
            "  python -m fortress.legal.verify_cites motion.txt --no-llm\n"
        ),
    )
    parser.add_argument(
        "draft_file",
        help="Path to the draft text file to verify",
    )
    parser.add_argument(
        "--output-report",
        metavar="PATH",
        default=None,
        help="Write JSON report to this path",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        default=False,
        help="Disable LLM extraction and support checks (regex only, faster)",
    )

    args = parser.parse_args()
    exit_code = asyncio.run(
        _run(
            draft_file=args.draft_file,
            output_report=args.output_report,
            no_llm=args.no_llm,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
