"""Operator CLI for the Phase B drafting orchestrator.

Sub-commands:

    inspect   Print the curated set + grounding packet for a case (read-only).
    assemble  Re-assemble a markdown briefing package from previously-produced
              SectionResults (operator workflow after manual edits).
    section   Run Stage 2 for a single section (interactive review).
    compose   Full Stage 0 → Stage 4 pipeline.

v0.1 ships `inspect` + `assemble` + `compose` (non-interactive flag set);
the interactive `section` review-loop is a follow-up enhancement once the
live BRAIN dry-run cadence stabilizes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from backend.services.case_briefing_compose import (
    SectionResult,
    TEN_SECTIONS,
    compose,
    stage_0_curate,
    stage_1_grounding_packet,
    stage_4_assemble,
)


_DEFAULT_NAS_OUTPUT_ROOT = Path(
    "/mnt/fortress_nas/Corporate_Legal/Business_Legal"
)


def _output_dir_for(case_slug: str, override: str | None, dry_run: bool) -> Path:
    if override:
        return Path(override)
    if dry_run:
        return Path(f"/tmp/phase-b-{case_slug}")
    return _DEFAULT_NAS_OUTPUT_ROOT / case_slug / "filings" / "outgoing"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="case_briefing_cli",
        description="Phase B drafting orchestrator CLI",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="Print curated set + grounding packet (read-only)")
    p_inspect.add_argument("--case-slug", required=True)
    p_inspect.add_argument("--top-k", type=int, default=15)
    p_inspect.add_argument("--privileged-top-k", type=int, default=10)
    p_inspect.add_argument("--grounding-query", default=None)
    p_inspect.add_argument("--output", default=None, help="Write JSON to path; default stdout")

    p_compose = sub.add_parser("compose", help="Run Stage 0 → Stage 4 (non-interactive)")
    p_compose.add_argument("--case-slug", required=True)
    p_compose.add_argument("--output-dir", default=None)
    p_compose.add_argument("--dry-run", action="store_true",
                           help="Force output to /tmp/phase-b-<slug>/ regardless of --output-dir")
    p_compose.add_argument("--top-k", type=int, default=15)
    p_compose.add_argument("--privileged-top-k", type=int, default=10)
    p_compose.add_argument("--grounding-query", default=None)
    p_compose.add_argument("--mechanical-only", action="store_true",
                           help="Skip synthesis sections (BRAIN); produce mechanical+placeholder only")

    p_assemble = sub.add_parser("assemble", help="Re-assemble from saved SectionResult JSON")
    p_assemble.add_argument("--case-slug", required=True)
    p_assemble.add_argument("--sections-json", required=True,
                            help="Path to a JSON file produced by `inspect` or compose --output")
    p_assemble.add_argument("--output-dir", default=None)
    p_assemble.add_argument("--dry-run", action="store_true")
    p_assemble.add_argument("--version", type=int, default=None)

    return p.parse_args(argv)


async def _run_inspect(args: argparse.Namespace) -> int:
    curated = await stage_0_curate(args.case_slug)
    packet = await stage_1_grounding_packet(
        args.case_slug,
        curated,
        top_k=args.top_k,
        privileged_top_k=args.privileged_top_k,
        grounding_query=args.grounding_query,
    )
    record: dict[str, Any] = {
        "case_slug_input": packet.case_slug_input,
        "case_slug_canonical": packet.case_slug_canonical,
        "related_matters": packet.related_matters,
        "vault_documents_count": len(packet.vault_documents),
        "curated_clusters": _cluster_summary(curated),
        "work_product_chunks": len(packet.work_product_chunk_ids),
        "privileged_chunks": len(packet.privileged_chunk_ids),
        "contains_privileged": packet.contains_privileged,
        "case_metadata_keys": sorted(packet.case_metadata.keys()),
    }
    body = json.dumps(record, indent=2, default=str, sort_keys=True)
    if args.output:
        Path(args.output).write_text(body, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(body)
    return 0


def _cluster_summary(curated) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in curated.items:
        out[it.cluster] = out.get(it.cluster, 0) + 1
    return out


async def _run_compose(args: argparse.Namespace) -> int:
    if args.mechanical_only:
        # Limit TEN_SECTIONS to mechanical + operator_written only; skip synthesis.
        from backend.services.case_briefing_compose import (
            SECTION_MODE_MECHANICAL,
            SECTION_MODE_OPERATOR_WRITTEN,
        )
        sections_filtered = tuple(
            (sid, title, mode)
            for sid, title, mode in TEN_SECTIONS
            if mode in (SECTION_MODE_MECHANICAL, SECTION_MODE_OPERATOR_WRITTEN)
        )
    else:
        sections_filtered = tuple(TEN_SECTIONS)

    output_dir = _output_dir_for(args.case_slug, args.output_dir, args.dry_run)
    packet, results, out_path = await compose(
        args.case_slug,
        output_dir=output_dir,
        grounding_query=args.grounding_query,
        top_k=args.top_k,
        privileged_top_k=args.privileged_top_k,
        sections=sections_filtered,
    )
    print(f"wrote {out_path}")
    print(f"  sections_count       = {len(results)}")
    print(f"  contains_privileged  = {packet.contains_privileged}")
    print(f"  vault_documents      = {len(packet.vault_documents)}")
    print(f"  work_product_chunks  = {len(packet.work_product_chunk_ids)}")
    print(f"  privileged_chunks    = {len(packet.privileged_chunk_ids)}")
    return 0


async def _run_assemble(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.sections_json).read_text(encoding="utf-8"))
    # Caller is responsible for the sections JSON shape; this is for the
    # operator-edit workflow where they tweak generated sections and re-run
    # the assembler. Keep it permissive — just rebuild the dict.
    raw_sections = payload.get("sections", {})
    if not isinstance(raw_sections, dict):
        print("ERROR: sections-json must contain a 'sections' object", file=sys.stderr)
        return 2
    section_results: dict[str, SectionResult] = {}
    for sid, body in raw_sections.items():
        if not isinstance(body, dict):
            continue
        section_results[sid] = SectionResult(
            section_id=sid,
            title=body.get("title", sid),
            mode=body.get("mode", "synthesis"),
            content=body.get("content", ""),
            grounding_citations=list(body.get("grounding_citations") or []),
            retrieval_chunk_ids=list(body.get("retrieval_chunk_ids") or []),
            contains_privileged=bool(body.get("contains_privileged", False)),
            operator_status=body.get("operator_status", "edited"),
            fail_reason=body.get("fail_reason"),
        )
    # Rebuild a minimal packet for assembly
    from backend.services.case_briefing_compose import GroundingPacket
    packet = GroundingPacket(
        case_slug_input=args.case_slug,
        case_slug_canonical=payload.get("case_slug_canonical", args.case_slug),
        case_metadata=payload.get("case_metadata", {}),
        related_matters=payload.get("related_matters", []) or [],
        vault_documents=payload.get("vault_documents", []) or [],
        email_archive_hits=[],
        curated_nas_files=payload.get("curated_nas_files", []) or [],
        privileged_chunk_ids=payload.get("privileged_chunk_ids", []) or [],
        privileged_chunk_texts=payload.get("privileged_chunk_texts", []) or [],
        work_product_chunk_ids=payload.get("work_product_chunk_ids", []) or [],
        work_product_chunk_texts=payload.get("work_product_chunk_texts", []) or [],
        contains_privileged=bool(payload.get("contains_privileged", False)),
    )
    output_dir = _output_dir_for(args.case_slug, args.output_dir, args.dry_run)
    out_path = stage_4_assemble(
        packet, section_results, output_dir=output_dir, version=args.version
    )
    print(f"wrote {out_path}")
    return 0


async def _main(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.command == "inspect":
        return await _run_inspect(args)
    if args.command == "compose":
        return await _run_compose(args)
    if args.command == "assemble":
        return await _run_assemble(args)
    raise SystemExit(f"Unknown command {args.command!r}")


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
