#!/usr/bin/env python3
"""
OCR Batch Processor — Fortress Prime
======================================
Converts scanned PDF documents to Markdown using Marker (GPU-accelerated OCR).
Preserves directory structure, tracks progress, and enables RAG re-ingestion.

Architecture:
    Source:  /mnt/ai_bulk/Enterprise_War_Room (scanned PDFs)
    Output:  /mnt/ai_bulk/Enterprise_War_Room_MD (clean Markdown)
    Engine:  Marker (surya-ocr) — reconstructs tables, headers, structure

Usage:
    # Process from a priority list
    python3 -m src.ocr_batch --list /tmp/ocr_priority_high.txt

    # Process a single directory
    python3 -m src.ocr_batch --source /mnt/ai_bulk/Enterprise_War_Room/Legal/Higginbotham

    # Dry run
    python3 -m src.ocr_batch --list /tmp/ocr_priority_high.txt --dry-run

    # Resume (skip already converted)
    python3 -m src.ocr_batch --list /tmp/ocr_priority_high.txt --resume
"""

import os
import sys
import json
import argparse
import subprocess
import time
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_BASE = "/mnt/ai_bulk/Enterprise_War_Room"
OUTPUT_BASE = "/mnt/ai_bulk/Enterprise_War_Room_MD"
LOG_DIR = "/mnt/fortress_nas/fortress_data/ai_brain/logs/ocr_batch"


# ---------------------------------------------------------------------------
# OCR Processing
# ---------------------------------------------------------------------------

def convert_pdf(pdf_path: str, output_dir: str) -> dict:
    """
    Convert a single PDF to Markdown using marker_single.
    Returns a dict with status and timing info.
    """
    start = time.time()
    result = {
        "file": pdf_path,
        "output_dir": output_dir,
        "status": "unknown",
        "elapsed": 0,
    }

    os.makedirs(output_dir, exist_ok=True)

    try:
        proc = subprocess.run(
            [
                "marker_single", pdf_path,
                "--output_format", "markdown",
                "--disable_image_extraction",
                "--output_dir", output_dir,
            ],
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max per file (dense scanned forms need time)
        )

        elapsed = time.time() - start
        result["elapsed"] = round(elapsed, 1)

        if proc.returncode == 0:
            # Check if output was created
            pdf_name = Path(pdf_path).stem
            md_path = os.path.join(output_dir, pdf_name, pdf_name + ".md")
            alt_md = os.path.join(output_dir, pdf_name + ".md")

            if os.path.exists(md_path):
                result["status"] = "success"
                result["output"] = md_path
                result["size"] = os.path.getsize(md_path)
            elif os.path.exists(alt_md):
                result["status"] = "success"
                result["output"] = alt_md
                result["size"] = os.path.getsize(alt_md)
            else:
                # Look for any .md file in the output dir
                for root, _, files in os.walk(output_dir):
                    for f in files:
                        if f.endswith(".md") and pdf_name.lower() in f.lower():
                            md_found = os.path.join(root, f)
                            result["status"] = "success"
                            result["output"] = md_found
                            result["size"] = os.path.getsize(md_found)
                            break
                    if result["status"] == "success":
                        break

                if result["status"] != "success":
                    result["status"] = "no_output"
                    result["stderr"] = proc.stderr[:500] if proc.stderr else ""
        else:
            result["status"] = "error"
            result["stderr"] = proc.stderr[:500] if proc.stderr else ""

    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["elapsed"] = 300
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def get_output_path(pdf_path: str) -> str:
    """Map source PDF path to output directory, preserving structure."""
    # /mnt/ai_bulk/Enterprise_War_Room/Legal/Higginbotham/file.pdf
    # -> /mnt/ai_bulk/Enterprise_War_Room_MD/Legal/Higginbotham/
    rel = os.path.relpath(pdf_path, SOURCE_BASE)
    return os.path.join(OUTPUT_BASE, os.path.dirname(rel))


def is_already_converted(pdf_path: str) -> bool:
    """Check if a markdown version already exists."""
    output_dir = get_output_path(pdf_path)
    pdf_name = Path(pdf_path).stem

    # Check various possible output locations
    candidates = [
        os.path.join(output_dir, pdf_name, pdf_name + ".md"),
        os.path.join(output_dir, pdf_name + ".md"),
    ]
    return any(os.path.exists(c) for c in candidates)


# ---------------------------------------------------------------------------
# Batch Processing
# ---------------------------------------------------------------------------

def run_batch(file_list: list[str], resume: bool = True, dry_run: bool = False):
    """Process a batch of PDF files."""
    print("=" * 60)
    print("  FORTRESS PRIME - OCR BATCH PROCESSOR")
    print("=" * 60)
    print(f"\n  Files:     {len(file_list)}")
    print(f"  Output:    {OUTPUT_BASE}")
    print(f"  Engine:    Marker (surya-ocr)")
    print(f"  Resume:    {'YES' if resume else 'NO'}")
    print()

    if dry_run:
        print("  [DRY RUN] Would process these files:")
        for f in file_list[:10]:
            print(f"    {f}")
        if len(file_list) > 10:
            print(f"    ... and {len(file_list) - 10} more")
        return

    # Filter already-converted if resume mode
    if resume:
        before = len(file_list)
        file_list = [f for f in file_list if not is_already_converted(f)]
        skipped = before - len(file_list)
        if skipped:
            print(f"  Skipping {skipped} already-converted files")
            print(f"  Remaining: {len(file_list)}")
            print()

    if not file_list:
        print("  Nothing to process. All files already converted.")
        return

    # Setup logging
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, f"ocr_{datetime.now():%Y%m%d_%H%M}.jsonl")

    stats = {"success": 0, "error": 0, "timeout": 0, "no_output": 0, "total_size": 0}
    start_time = time.time()

    for idx, pdf_path in enumerate(file_list, 1):
        # Progress
        elapsed = time.time() - start_time
        rate = stats["success"] / elapsed * 60 if elapsed > 0 and stats["success"] > 0 else 0
        eta = (len(file_list) - idx) / (rate / 60) / 60 if rate > 0 else 0

        basename = os.path.basename(pdf_path)
        print(f"  [{idx}/{len(file_list)}] {basename[:50]:<50} ", end="", flush=True)

        # Convert
        output_dir = get_output_path(pdf_path)
        result = convert_pdf(pdf_path, output_dir)

        # Track stats
        stats[result["status"]] = stats.get(result["status"], 0) + 1
        if result.get("size"):
            stats["total_size"] += result["size"]

        # Print result
        status_icon = {
            "success": "OK",
            "error": "ERR",
            "timeout": "TIMEOUT",
            "no_output": "EMPTY",
        }.get(result["status"], "???")

        print(f"{status_icon} ({result['elapsed']}s)")

        # Log
        with open(log_file, "a") as lf:
            result["timestamp"] = datetime.now().isoformat()
            lf.write(json.dumps(result) + "\n")

    # Summary
    total_elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("  OCR BATCH COMPLETE")
    print("=" * 60)
    print(f"  Duration:      {total_elapsed/60:.1f} minutes")
    print(f"  Successful:    {stats['success']}")
    print(f"  Errors:        {stats['error']}")
    print(f"  Timeouts:      {stats['timeout']}")
    print(f"  No output:     {stats.get('no_output', 0)}")
    print(f"  Total MD size: {stats['total_size'] / 1024 / 1024:.1f} MB")
    print(f"  Log:           {log_file}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fortress Prime OCR Batch Processor")
    parser.add_argument("--list", help="File with list of PDFs to process (one per line)")
    parser.add_argument("--source", help="Directory to scan for PDFs")
    parser.add_argument("--resume", action="store_true", default=True, help="Skip already converted")
    parser.add_argument("--no-resume", action="store_true", help="Process all files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed")
    parser.add_argument("--limit", type=int, help="Limit number of files to process")
    args = parser.parse_args()

    file_list = []

    if args.list:
        with open(args.list) as f:
            file_list = [line.strip() for line in f if line.strip() and os.path.exists(line.strip())]
    elif args.source:
        from src.rag_ingest import discover_files
        file_list = [str(f) for f in discover_files(args.source)]
    else:
        parser.error("Specify --list or --source")

    # Deduplicate
    file_list = list(dict.fromkeys(file_list))

    if args.limit:
        file_list = file_list[:args.limit]

    run_batch(
        file_list,
        resume=not args.no_resume,
        dry_run=args.dry_run,
    )
