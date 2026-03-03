#!/usr/bin/env python3
"""
Module CF-04: Treasury — CFO Extractor Agent v3.0
====================================================
Cabin Rentals of Georgia | Crog-Fortress-AI
Data Sovereignty: ALL inference local. No cloud APIs. No remote GPU.

MISSION:
    Autonomously process 9,899 PDFs from the Financial Ledger on the NAS.
    Extract vendor, amount, date, category from every invoice/receipt/tax doc.
    Output a structured CSV ready for forensic accounting analysis.

THE v3.0 UPGRADE:
    - CUT THE CORD: No more Remote GPU. Captain's local brain only.
    - RESILIENT: Encrypted PDFs skipped cleanly. Image-only PDFs flagged for OCR.
    - RESUMABLE: Tracks processed files. Survives restarts across a 9,899-file run.
    - FAST: DeepSeek-R1:8b for throughput (~30s/file = ~3 days for full ledger).
    - AUDITABLE: Every decision logged to JSONL for forensic review.

USAGE:
    # Full batch (resumes automatically)
    python3 src/cfo_extractor.py \\
        --batch /mnt/fortress_nas/Financial_Ledger \\
        --csv /mnt/fortress_nas/fortress_data/ai_brain/logs/cfo_extractor/financial_audit.csv

    # Dry run (count files, don't process)
    python3 src/cfo_extractor.py \\
        --batch /mnt/fortress_nas/Financial_Ledger --csv out.csv --dry-run

    # Force re-process everything (ignore resume)
    python3 src/cfo_extractor.py \\
        --batch /mnt/fortress_nas/Financial_Ledger --csv out.csv --no-resume

Author: Fortress Prime Architect
Version: 3.0.0
"""

import os
import sys
import argparse
import csv
import json
import re
import time
import hashlib
from datetime import datetime
from pathlib import Path

import requests
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError

# =============================================================================
# CONFIGURATION — LOCAL BRAIN ONLY
# =============================================================================

# Captain Node's local Ollama — NO REMOTE CALLS
# Uses /api/chat (not /api/generate) to properly handle DeepSeek-R1 thinking
LLM_URL = "http://localhost:11434/api/chat"
MODEL = os.getenv("CFO_MODEL", "deepseek-r1:8b")

# Timeouts (generous for local inference on large docs)
LLM_TIMEOUT = (10, 300)  # (connect, read) seconds

# Token budget: R1 models use ~2000 tokens for thinking + ~200 for the JSON answer
NUM_PREDICT = 2048

# Text extraction limits
MAX_TEXT_CHARS = 4000     # Truncate to fit R1:8b context window
MIN_TEXT_CHARS = 50       # Below this = image-only PDF, needs OCR
MAX_FILE_SIZE_MB = 100    # Skip files larger than this

# Paths
LOG_DIR = "/mnt/fortress_nas/fortress_data/ai_brain/logs/cfo_extractor"

# CSV columns
CSV_HEADER = [
    "filename", "date", "vendor_name", "total_amount",
    "tax_deductible", "category", "summary", "status",
    "processed_by", "source_path", "processed_at",
]

# =============================================================================
# SYSTEM PROMPT — FORENSIC ACCOUNTANT
# =============================================================================

SYSTEM_PROMPT = """You are a forensic accountant for a cabin rental property management company.
Extract these fields from the document text into JSON format ONLY:

{
  "date": "YYYY-MM-DD or null if unknown",
  "vendor_name": "Company or person name",
  "total_amount": 0.00,
  "tax_deductible": true or false,
  "category": "one of: Materials, Labor, Legal, Insurance, Utilities, Taxes, Rental_Income, Maintenance, Travel, Office, Uncategorized",
  "summary": "One sentence summary of the document"
}

RULES:
- Return ONLY valid JSON. No markdown. No explanation.
- If a field is missing, use null.
- total_amount must be a number (float), not a string.
- For tax returns, extract the total tax liability or refund amount.
- For invoices, extract the total due.
- For receipts, extract the total paid.
- If the document is not financial, set category to "Uncategorized" and total_amount to 0."""


# =============================================================================
# RESPONSE CLEANING
# =============================================================================

def clean_llm_response(text: str) -> str:
    """
    Strip <think> tags (DeepSeek R1) and markdown fences.
    Required per SOW Behavioral Protocol #5.
    """
    # Remove thinking blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Remove markdown code fences
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    return text.strip()


def extract_json_from_response(raw: str) -> dict:
    """
    Multiple fallback strategies to extract JSON from LLM output.
    LLMs are messy — we handle every common failure mode:
    - Markdown code fences (```json ... ```)
    - <think> tags from DeepSeek R1
    - Doubled double quotes (""key"" from confused tokenizer)
    - Trailing commas
    - Single quotes instead of double quotes
    - Extra text before/after JSON object
    """
    cleaned = clean_llm_response(raw)

    # Strategy 1: Direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Find JSON between first { and last }
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = cleaned[first_brace:last_brace + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        # Strategy 3: Fix doubled double-quotes (DeepSeek R1:8b quirk)
        # The model sometimes outputs: ""date"": ""2025-01-01""
        # Fix: replace "" with " then re-parse
        fixed = candidate
        fixed = re.sub(r'""([^"]*?)""', r'"\1"', fixed)  # ""value"" -> "value"
        fixed = re.sub(r',\s*}', '}', fixed)              # trailing comma
        fixed = re.sub(r',\s*]', ']', fixed)              # trailing comma in array
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

    # Strategy 4: Even more aggressive cleanup
    try:
        aggressive = cleaned
        aggressive = aggressive.replace('""', '"')     # all doubled quotes
        aggressive = aggressive.replace("'", '"')      # single quotes
        aggressive = re.sub(r',\s*}', '}', aggressive)
        aggressive = re.sub(r',\s*]', ']', aggressive)
        first = aggressive.find("{")
        last = aggressive.rfind("}")
        if first != -1 and last > first:
            return json.loads(aggressive[first:last + 1])
    except json.JSONDecodeError:
        pass

    # Strategy 5: Regex extract individual fields as a last resort
    try:
        data = {}
        # Try to extract key fields even from garbled JSON
        date_match = re.search(r'"?date"?\s*:\s*"?(\d{4}-\d{2}-\d{2})"?', cleaned)
        if date_match:
            data["date"] = date_match.group(1)
        vendor_match = re.search(r'"?vendor_name"?\s*:\s*"([^"]+)"', cleaned)
        if vendor_match:
            data["vendor_name"] = vendor_match.group(1)
        amount_match = re.search(r'"?total_amount"?\s*:\s*"?([\d.]+)"?', cleaned)
        if amount_match:
            data["total_amount"] = float(amount_match.group(1))
        cat_match = re.search(r'"?category"?\s*:\s*"([^"]+)"', cleaned)
        if cat_match:
            data["category"] = cat_match.group(1)
        tax_match = re.search(r'"?tax_deductible"?\s*:\s*(true|false)', cleaned, re.IGNORECASE)
        if tax_match:
            data["tax_deductible"] = tax_match.group(1).lower() == "true"
        summary_match = re.search(r'"?summary"?\s*:\s*"([^"]+)"', cleaned)
        if summary_match:
            data["summary"] = summary_match.group(1)

        if data and ("total_amount" in data or "vendor_name" in data):
            return data
    except Exception:
        pass

    raise json.JSONDecodeError("All JSON extraction strategies failed", cleaned, 0)


# =============================================================================
# PDF TEXT EXTRACTION
# =============================================================================

def extract_text_from_pdf(pdf_path: str) -> tuple:
    """
    Extract text from a PDF, handling every failure mode:
    - Encrypted PDFs -> skip cleanly
    - Image-only PDFs -> flag for OCR
    - Corrupted files -> skip with error
    - Oversized files -> skip with warning

    Returns: (text, status_code)
    """
    filepath = Path(pdf_path)

    # Guard: file size check
    try:
        size_mb = filepath.stat().st_size / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            return None, "SKIP_TOO_LARGE"
    except OSError:
        return None, "FILE_NOT_FOUND"

    try:
        reader = PdfReader(pdf_path)

        # Check if encrypted
        if reader.is_encrypted:
            try:
                # Try empty password (some PDFs are "encrypted" with no password)
                reader.decrypt("")
            except Exception:
                return None, "ENCRYPTED"

        text = ""
        for page in reader.pages:
            try:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            except Exception:
                continue  # Skip unreadable pages, keep going

        text = text.strip()

        if len(text) < MIN_TEXT_CHARS:
            return None, "NEEDS_OCR"

        # Truncate to fit LLM context
        return text[:MAX_TEXT_CHARS], "SUCCESS"

    except FileNotDecryptedError:
        return None, "ENCRYPTED"
    except Exception as e:
        err = str(e)[:100]
        return None, f"READ_ERROR:{err}"


# =============================================================================
# LOCAL LLM INFERENCE
# =============================================================================

def analyze_document(text: str) -> tuple:
    """
    Send document text to Captain's local DeepSeek-R1:8b for extraction.
    Returns: (parsed_dict, raw_response, status)
    """
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"DOCUMENT:\n{text}"},
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": NUM_PREDICT,
        },
    }

    try:
        resp = requests.post(LLM_URL, json=payload, timeout=LLM_TIMEOUT)
        resp.raise_for_status()
        msg = resp.json().get("message", {})
        # /api/chat separates thinking from content for DeepSeek-R1
        raw = msg.get("content", "")

        if not raw.strip():
            return None, raw, "EMPTY_RESPONSE"

        data = extract_json_from_response(raw)

        # Validate total_amount is numeric
        amt = data.get("total_amount")
        if amt is not None:
            try:
                data["total_amount"] = float(amt)
            except (TypeError, ValueError):
                data["total_amount"] = 0.0

        return data, raw, "EXTRACTED"

    except json.JSONDecodeError:
        return None, raw if 'raw' in dir() else "", "JSON_PARSE_ERROR"
    except requests.exceptions.Timeout:
        return None, "", "LLM_TIMEOUT"
    except requests.exceptions.ConnectionError:
        return None, "", "LLM_OFFLINE"
    except Exception as e:
        return None, "", f"LLM_ERROR:{str(e)[:80]}"


# =============================================================================
# RESUME LOGIC
# =============================================================================

def load_processed_files(csv_path: str) -> set:
    """
    Load the set of full file paths already processed from the CSV.
    Uses source_path (full NAS path) to avoid false matches on duplicate
    filenames across different directories.
    Enables resume after restart — critical for a 9,899-file marathon.
    """
    processed = set()
    if not os.path.exists(csv_path):
        return processed

    try:
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Prefer full path for accurate resume
                full_path = row.get("source_path", "").strip()
                if full_path:
                    processed.add(full_path)
                else:
                    # Fallback to filename if source_path missing
                    fname = row.get("filename", "").strip()
                    if fname:
                        processed.add(fname)
    except Exception:
        pass

    return processed


# =============================================================================
# MAIN PROCESSING LOOP
# =============================================================================

def process_batch(batch_dir: str, csv_path: str, resume: bool = True, dry_run: bool = False):
    """
    Process every PDF in the Financial Ledger.
    Resilient. Resumable. Relentless.
    """
    print("=" * 70)
    print("  CF-04 TREASURY — CFO EXTRACTOR AGENT v3.0")
    print("  Local Brain: {} @ {}".format(MODEL, LLM_URL))
    print("  Data Sovereignty: ALL inference local. No cloud APIs.")
    print("=" * 70)

    # Discover all PDFs
    print(f"\n[1/3] Scanning {batch_dir}...")
    files = sorted(Path(batch_dir).rglob("*.pdf"))
    print(f"      Found {len(files)} PDF files")

    if not files:
        print("\n  No PDF files found. Exiting.")
        return

    if dry_run:
        # Show breakdown by subdirectory
        subdirs = {}
        for f in files:
            rel = f.relative_to(batch_dir)
            top = rel.parts[0] if len(rel.parts) > 1 else "root"
            subdirs[top] = subdirs.get(top, 0) + 1
        print("\n  Directory breakdown:")
        for d, count in sorted(subdirs.items(), key=lambda x: -x[1]):
            print(f"    {d:<40} {count:>6} files")
        print(f"    {'TOTAL':<40} {len(files):>6} files")
        print("\n  [DRY RUN] No files were processed.")
        return

    # Resume: load already-processed files
    skip_set = set()
    if resume:
        print(f"[2/3] Checking resume state...")
        skip_set = load_processed_files(csv_path)
        if skip_set:
            print(f"      Resuming: {len(skip_set)} files already processed")
        else:
            print(f"      Fresh start (no previous CSV found)")
    else:
        print(f"[2/3] Full re-process mode (no resume)")

    # Verify LLM is reachable
    print(f"[3/3] Testing local LLM ({MODEL})...")
    try:
        test_resp = requests.post(
            LLM_URL,
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": "Say OK"}],
                "stream": False,
                "options": {"num_predict": NUM_PREDICT},
            },
            timeout=(10, 60),
        )
        if test_resp.status_code == 200:
            content = test_resp.json().get("message", {}).get("content", "")
            print(f"      {MODEL}: ONLINE (test response: {len(content)} chars)")
        else:
            print(f"      WARNING: LLM returned HTTP {test_resp.status_code}")
    except Exception as e:
        print(f"      CRITICAL: Local LLM unreachable at {LLM_URL}")
        print(f"      Error: {e}")
        print(f"      Is Ollama running? Try: ollama serve")
        return

    # Initialize CSV
    os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
    file_exists = os.path.isfile(csv_path) and os.path.getsize(csv_path) > 0
    csv_file = open(csv_path, "a", newline="")
    writer = csv.writer(csv_file)
    if not file_exists:
        writer.writerow(CSV_HEADER)
        csv_file.flush()

    # Initialize JSONL audit log
    os.makedirs(LOG_DIR, exist_ok=True)
    audit_path = os.path.join(LOG_DIR, f"audit_{datetime.now():%Y%m%d_%H%M}.jsonl")

    # Stats
    stats = {
        "extracted": 0,
        "skipped_resume": 0,
        "encrypted": 0,
        "needs_ocr": 0,
        "read_errors": 0,
        "json_errors": 0,
        "llm_errors": 0,
        "total_amount": 0.0,
    }
    start_time = time.time()

    # --- THE MAIN LOOP ---
    print(f"\n{'='*70}")
    print(f"  PROCESSING {len(files)} FILES...")
    print(f"{'='*70}\n")

    remaining = [f for f in files if str(f) not in skip_set and f.name not in skip_set]
    stats["skipped_resume"] = len(files) - len(remaining)

    if stats["skipped_resume"] > 0:
        print(f"  (Skipping {stats['skipped_resume']} already-processed files)\n")

    for idx, filepath in enumerate(remaining, 1):
        filename = filepath.name
        elapsed = time.time() - start_time
        rate = stats["extracted"] / elapsed * 3600 if elapsed > 0 and stats["extracted"] > 0 else 0

        print(
            f"  [{idx}/{len(remaining)}] {filename[:55]:<55} ",
            end="", flush=True,
        )

        # --- STEP 1: Extract text ---
        text, read_status = extract_text_from_pdf(str(filepath))

        if read_status != "SUCCESS":
            # Track the failure type
            if read_status == "ENCRYPTED":
                stats["encrypted"] += 1
                print(f"SKIP (encrypted)")
            elif read_status == "NEEDS_OCR":
                stats["needs_ocr"] += 1
                print(f"SKIP (image-only, needs OCR)")
            elif read_status == "SKIP_TOO_LARGE":
                stats["read_errors"] += 1
                print(f"SKIP (>100MB)")
            else:
                stats["read_errors"] += 1
                print(f"ERR ({read_status[:40]})")

            # Log the skip to CSV
            writer.writerow([
                filename, "", "", 0.0, False, "",
                read_status, read_status,
                "N/A", str(filepath), datetime.now().isoformat(),
            ])
            csv_file.flush()

            # Audit log
            _audit_log(audit_path, filename, str(filepath), read_status, None)
            continue

        # --- STEP 2: Ask the Local AI ---
        data, raw_response, ai_status = analyze_document(text)

        if ai_status == "EXTRACTED" and data:
            amt = data.get("total_amount", 0.0) or 0.0
            vendor = data.get("vendor_name", "Unknown") or "Unknown"
            stats["extracted"] += 1
            stats["total_amount"] += abs(float(amt))

            print(f"${amt:>10,.2f}  {vendor[:25]}")

            writer.writerow([
                filename,
                data.get("date", ""),
                vendor,
                amt,
                data.get("tax_deductible", False),
                data.get("category", "Uncategorized"),
                (data.get("summary", "") or "")[:200],
                "EXTRACTED",
                MODEL,
                str(filepath),
                datetime.now().isoformat(),
            ])
            csv_file.flush()

            _audit_log(audit_path, filename, str(filepath), "EXTRACTED", data)

        elif ai_status == "JSON_PARSE_ERROR":
            stats["json_errors"] += 1
            print(f"PARSE_ERR")
            writer.writerow([
                filename, "", "", 0.0, False, "",
                f"JSON_ERROR: {raw_response[:80]}",
                "JSON_PARSE_ERROR",
                MODEL, str(filepath), datetime.now().isoformat(),
            ])
            csv_file.flush()
            _audit_log(audit_path, filename, str(filepath), "JSON_PARSE_ERROR", None)

        elif ai_status == "LLM_OFFLINE":
            stats["llm_errors"] += 1
            print(f"LLM_OFFLINE — waiting 30s...")
            writer.writerow([
                filename, "", "", 0.0, False, "", ai_status, ai_status,
                MODEL, str(filepath), datetime.now().isoformat(),
            ])
            csv_file.flush()
            _audit_log(audit_path, filename, str(filepath), ai_status, None)
            time.sleep(30)  # Back off and retry on next file

        else:
            stats["llm_errors"] += 1
            print(f"ERR ({ai_status[:40]})")
            writer.writerow([
                filename, "", "", 0.0, False, "",
                ai_status,
                ai_status,
                MODEL, str(filepath), datetime.now().isoformat(),
            ])
            csv_file.flush()
            _audit_log(audit_path, filename, str(filepath), ai_status, None)

        # Progress report every 50 files
        if idx % 50 == 0:
            elapsed_min = (time.time() - start_time) / 60
            print(f"\n  --- Progress: {idx}/{len(remaining)} | "
                  f"Extracted: {stats['extracted']} | "
                  f"$Total: ${stats['total_amount']:,.2f} | "
                  f"Rate: {rate:.0f}/hr | "
                  f"Elapsed: {elapsed_min:.1f}min ---\n")

    # --- SUMMARY ---
    csv_file.close()
    elapsed = time.time() - start_time
    elapsed_min = elapsed / 60

    print(f"\n{'='*70}")
    print(f"  CFO EXTRACTOR v3.0 — AUDIT COMPLETE")
    print(f"{'='*70}")
    print(f"  Duration:        {elapsed_min:.1f} minutes")
    print(f"  Files Scanned:   {len(files)}")
    print(f"  Resumed:         {stats['skipped_resume']} (previously processed)")
    print(f"  Extracted:       {stats['extracted']}")
    print(f"  Encrypted:       {stats['encrypted']} (skipped)")
    print(f"  Needs OCR:       {stats['needs_ocr']} (image-only)")
    print(f"  Read Errors:     {stats['read_errors']}")
    print(f"  JSON Errors:     {stats['json_errors']}")
    print(f"  LLM Errors:      {stats['llm_errors']}")
    print(f"  Total $ Found:   ${stats['total_amount']:,.2f}")
    print(f"  CSV:             {csv_path}")
    print(f"  Audit Log:       {audit_path}")
    print(f"  Model:           {MODEL} (LOCAL)")
    print(f"{'='*70}")

    # Success rate
    total_attempted = stats["extracted"] + stats["json_errors"] + stats["llm_errors"]
    if total_attempted > 0:
        success_pct = stats["extracted"] / total_attempted * 100
        print(f"  AI Success Rate: {success_pct:.1f}% ({stats['extracted']}/{total_attempted})")
    print(f"{'='*70}")


def _audit_log(audit_path: str, filename: str, filepath: str, status: str, data: dict):
    """Append a line to the JSONL audit trail."""
    try:
        with open(audit_path, "a") as f:
            f.write(json.dumps({
                "filename": filename,
                "filepath": filepath,
                "status": status,
                "data": data,
                "model": MODEL,
                "timestamp": datetime.now().isoformat(),
            }) + "\n")
    except Exception:
        pass  # Never crash on logging


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CF-04 Treasury — CFO Extractor Agent v3.0 (Local Brain)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full batch (auto-resume)
  python3 src/cfo_extractor.py \\
      --batch /mnt/fortress_nas/Financial_Ledger \\
      --csv /mnt/fortress_nas/fortress_data/ai_brain/logs/cfo_extractor/financial_audit.csv

  # Dry run (count files)
  python3 src/cfo_extractor.py \\
      --batch /mnt/fortress_nas/Financial_Ledger --csv out.csv --dry-run
        """,
    )
    parser.add_argument(
        "--batch", required=True,
        help="Directory to scan for PDFs",
    )
    parser.add_argument(
        "--csv", required=True,
        help="Output CSV path",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count files without processing",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="Start fresh (ignore previously processed files)",
    )
    parser.add_argument(
        "--model", default=None,
        help=f"Override LLM model (default: {MODEL})",
    )
    args = parser.parse_args()

    if args.model:
        MODEL = args.model

    process_batch(
        batch_dir=args.batch,
        csv_path=args.csv,
        resume=not args.no_resume,
        dry_run=args.dry_run,
    )
