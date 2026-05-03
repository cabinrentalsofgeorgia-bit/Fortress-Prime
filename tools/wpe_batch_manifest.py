#!/usr/bin/env python3
"""Generate Wilson Pruitt Email Batch 001 source-control manifests.

Reads frozen Batch 001 source folders, hashes files, and writes repo-safe TSV
control files. It does not parse email bodies or decide privilege.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_NAS_ROOT = Path("/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/incoming/wilson-pruitt-email-intake-20260503")
DEFAULT_BATCH_ID = "WPE-BATCH-001"
SYSTEM_FILENAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
NATIVE_FORMATS = {".eml", ".msg", ".mbox", ".pst", ".ost"}
PDF_FORMATS = {".pdf"}
SCREENSHOT_FORMATS = {".png", ".jpg", ".jpeg", ".heic", ".tif", ".tiff"}

SOURCE_COLUMNS = ["batch_id", "intake_id", "source_family", "original_path", "original_filename", "file_format", "bytes", "sha256", "source_mailbox_or_custodian", "date_range", "date_copied", "copy_operator", "native_available", "fallback_type", "notes"]
PRIVILEGE_COLUMNS = ["batch_id", "intake_id", "original_path", "from_to_cc_summary", "subject_or_descriptor", "privilege_status", "screen_reason", "counsel_review_needed", "repo_safe_label", "next_action"]
ISSUE_COLUMNS = ["batch_id", "intake_id", "source_family", "privilege_status", "issue_tags", "target_workbench", "proof_gate_id", "promotion_status", "required_before_promotion", "notes"]

@dataclass(frozen=True)
class SourceFamily:
    folder: str
    intake_id: str
    label: str
    issue_tags: str
    target_workbench: str
    proof_gate_id: str

SOURCE_FAMILIES = [
    SourceFamily("01_wilson_pruitt_pre_closing", "WPE-20260503-001", "pre-closing Wilson Pruitt", "closing-delay;psa-repair-scope;professional-negligence-gate", "Closing delay chronology; PSA repair matrix; Wilson Pruitt proof matrix", "WP-GATE-002;WP-GATE-005"),
    SourceFamily("02_wilson_pruitt_post_closing", "WPE-20260503-002", "post-closing Wilson Pruitt", "post-closing-conduct;opposing-accusation;adverse-alignment;civil-conspiracy-gate", "Answer matrix; issue matrix; Wilson Pruitt proof matrix", "WP-GATE-006;WP-GATE-007"),
    SourceFamily("03_report_transmission", "WPE-20260503-003", "inspection report transmission", "inspection-report;case-i-overlap;professional-negligence-gate", "Inspection source status; inspection addenda; Wilson Pruitt proof matrix", "WP-GATE-004;WP-GATE-002"),
    SourceFamily("04_dee_mcbee_case_i", "WPE-20260503-004", "Dee McBee Case I", "inspection-report;case-i-overlap", "Case I-to-Case II overlap chart; inspection source status", "WP-GATE-004"),
    SourceFamily("05_terry_wilson_production", "WPE-20260503-005", "Terry Wilson production", "psa-repair-scope;inspection-report;case-i-overlap;professional-negligence-gate", "Terry Wilson repair pin; PSA repair matrix; Wilson Pruitt proof matrix", "WP-GATE-002;WP-GATE-004"),
    SourceFamily("06_easement_title_crossing", "WPE-20260503-006", "easement title crossing", "easement-title;post-closing-conduct;procedural-joinder-gate;privilege-waiver-gate", "Easement source map; DOT/GNRR source index; Wilson Pruitt proof matrix", "WP-GATE-003;WP-GATE-011;WP-GATE-012"),
    SourceFamily("99_unsorted_hold", "WPE-20260503-999", "unsorted hold", "counsel-review", "Unsorted hold; operator context required", "TBD"),
]

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def iso_utc_from_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()

def fallback_type(suffix: str) -> str:
    suffix = suffix.lower()
    if suffix in NATIVE_FORMATS:
        return "native"
    if suffix in PDF_FORMATS:
        return "PDF-fallback"
    if suffix in SCREENSHOT_FORMATS:
        return "screenshot-fallback"
    return "unknown-format"

def native_available(suffix: str) -> str:
    return "yes" if suffix.lower() in NATIVE_FORMATS else "no"

def iter_source_files(batch_root: Path, include_hidden: bool) -> Iterable[tuple[SourceFamily, Path]]:
    for family in SOURCE_FAMILIES:
        folder = batch_root / family.folder
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            if not include_hidden and (path.name.startswith(".") or path.name in SYSTEM_FILENAMES):
                continue
            yield family, path

def source_row(family: SourceFamily, path: Path, batch_id: str, copy_operator: str) -> dict[str, str]:
    suffix = path.suffix.lower() or "[none]"
    return {
        "batch_id": batch_id,
        "intake_id": family.intake_id,
        "source_family": family.label,
        "original_path": str(path),
        "original_filename": path.name,
        "file_format": suffix,
        "bytes": str(path.stat().st_size),
        "sha256": sha256_file(path),
        "source_mailbox_or_custodian": "TBD",
        "date_range": "TBD",
        "date_copied": iso_utc_from_mtime(path),
        "copy_operator": copy_operator,
        "native_available": native_available(suffix),
        "fallback_type": fallback_type(suffix),
        "notes": "Generated from frozen Batch 001 source folder; privilege screen required before merits review.",
    }

def privilege_row(source: dict[str, str]) -> dict[str, str]:
    return {
        "batch_id": source["batch_id"],
        "intake_id": source["intake_id"],
        "original_path": source["original_path"],
        "from_to_cc_summary": "TBD",
        "subject_or_descriptor": source["original_filename"],
        "privilege_status": "PENDING",
        "screen_reason": "Privilege/sensitivity screen required before issue tagging.",
        "counsel_review_needed": "YES",
        "repo_safe_label": "pending",
        "next_action": "Screen for attorney-client, work-product, settlement, and third-party counsel sensitivity.",
    }

def issue_row(source: dict[str, str], family: SourceFamily) -> dict[str, str]:
    return {
        "batch_id": source["batch_id"],
        "intake_id": source["intake_id"],
        "source_family": source["source_family"],
        "privilege_status": "PENDING",
        "issue_tags": family.issue_tags,
        "target_workbench": family.target_workbench,
        "proof_gate_id": family.proof_gate_id,
        "promotion_status": "HOLD",
        "required_before_promotion": "Original hash, attachment linkage if applicable, privilege screen, operator context, and proof-gate review.",
        "notes": "Generated queue row; do not promote until privilege status is source-controlled or counsel-approved.",
    }

def write_tsv(path: Path, columns: list[str], rows: list[dict[str, str]], dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate WPE Batch 001 manifest and queue TSV files.")
    parser.add_argument("--nas-root", type=Path, default=DEFAULT_NAS_ROOT)
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--copy-operator", default="operator")
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source-output", type=Path)
    parser.add_argument("--privilege-output", type=Path)
    parser.add_argument("--issue-output", type=Path)
    return parser.parse_args()

def main() -> int:
    args = parse_args()
    nas_root = args.nas_root
    batch_root = nas_root / "01_originals_frozen" / args.batch_id
    stamp = timestamp()
    source_output = args.source_output or nas_root / "00_README" / f"{args.batch_id}_SOURCE_MANIFEST_GENERATED_{stamp}.tsv"
    privilege_output = args.privilege_output or nas_root / "04_privilege_screen" / f"{args.batch_id}_PRIVILEGE_SCREEN_QUEUE_GENERATED_{stamp}.tsv"
    issue_output = args.issue_output or nas_root / "05_issue_tagged_review" / f"{args.batch_id}_ISSUE_TAGGING_QUEUE_GENERATED_{stamp}.tsv"
    if not batch_root.exists():
        print(f"Batch root does not exist: {batch_root}", file=sys.stderr)
        return 2
    sources: list[dict[str, str]] = []
    privileges: list[dict[str, str]] = []
    issues: list[dict[str, str]] = []
    for family, path in iter_source_files(batch_root, args.include_hidden):
        source = source_row(family, path, args.batch_id, args.copy_operator)
        sources.append(source)
        privileges.append(privilege_row(source))
        issues.append(issue_row(source, family))
    write_tsv(source_output, SOURCE_COLUMNS, sources, args.dry_run)
    write_tsv(privilege_output, PRIVILEGE_COLUMNS, privileges, args.dry_run)
    write_tsv(issue_output, ISSUE_COLUMNS, issues, args.dry_run)
    mode = "DRY RUN" if args.dry_run else "WROTE"
    print(f"{mode}: {len(sources)} source file(s) found under {batch_root}")
    print(f"source_manifest={source_output}")
    print(f"privilege_queue={privilege_output}")
    print(f"issue_queue={issue_output}")
    if not sources:
        print("No source exports are present yet. Copy files into Batch 001 source folders, then rerun.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
