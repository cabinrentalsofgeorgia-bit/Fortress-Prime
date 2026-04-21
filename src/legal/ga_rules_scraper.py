#!/usr/bin/env python3
"""
GA Court Rules PDF downloader and text extractor.
Downloads GA Supreme Court rules PDF, extracts text, parses into individual rules,
and outputs JSONL. Also attempts GA Court of Appeals and Uniform Superior Court Rules.
"""

import os
import re
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

try:
    import pypdf
    PDF_LIB = "pypdf"
except ImportError:
    import PyPDF2 as pypdf
    PDF_LIB = "PyPDF2"

OUTPUT_DIR = Path("/mnt/fortress_nas/datasets/legal-corpus/ga-rules")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SOURCES = [
    {
        "rule_set": "GA Supreme Court",
        "url": "https://www.gasupreme.us/wp-content/uploads/2026/03/SUPREME-COURT-RULES-_FINAL-FOR-WEB-POSTING.pdf",
        "filename": "ga-supreme-court-rules.pdf",
        "output_jsonl": "ga-supreme-court-rules.jsonl",
    },
    {
        "rule_set": "GA Court of Appeals",
        "url": "https://www.gaappeals.us/wp-content/uploads/2022/01/Rules-of-the-Georgia-Court-of-Appeals.pdf",
        "filename": "ga-court-of-appeals-rules.pdf",
        "output_jsonl": "ga-court-of-appeals-rules.jsonl",
    },
    {
        "rule_set": "GA Court of Appeals",
        "url": "https://www.gaappeals.us/wp-content/uploads/2023/01/Court-of-Appeals-Rules.pdf",
        "filename": "ga-court-of-appeals-rules.pdf",
        "output_jsonl": "ga-court-of-appeals-rules.jsonl",
    },
    {
        "rule_set": "Uniform Superior Court Rules",
        "url": "https://georgiacourts.gov/wp-content/uploads/2021/05/Uniform-Superior-Court-Rules.pdf",
        "filename": "ga-uniform-superior-court-rules.pdf",
        "output_jsonl": "ga-uniform-superior-court-rules.jsonl",
    },
    {
        "rule_set": "Uniform Superior Court Rules",
        "url": "https://georgiacourts.gov/wp-content/uploads/2022/01/Uniform-Superior-Court-Rules.pdf",
        "filename": "ga-uniform-superior-court-rules.pdf",
        "output_jsonl": "ga-uniform-superior-court-rules.jsonl",
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def download_pdf(url: str, dest_path: Path) -> bool:
    """Download a PDF from url to dest_path. Returns True on success."""
    if dest_path.exists() and dest_path.stat().st_size > 10000:
        print(f"  [SKIP] Already downloaded: {dest_path.name} ({dest_path.stat().st_size} bytes)")
        return True
    print(f"  [DL] Downloading {url}")
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                print(f"  [FAIL] HTTP {resp.status}")
                return False
            content = resp.read()
        if len(content) < 5000:
            print(f"  [FAIL] Response too small ({len(content)} bytes), probably not a PDF")
            return False
        dest_path.write_bytes(content)
        print(f"  [OK] Saved {dest_path.name} ({len(content)} bytes)")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract all text from a PDF file."""
    print(f"  [PDF] Extracting text from {pdf_path.name} using {PDF_LIB}")
    if PDF_LIB == "pypdf":
        reader = pypdf.PdfReader(str(pdf_path))
        pages_text = []
        for i, page in enumerate(reader.pages):
            try:
                t = page.extract_text() or ""
                pages_text.append(t)
            except Exception as e:
                print(f"    [WARN] Page {i} error: {e}")
        return "\n".join(pages_text)
    else:
        reader = pypdf.PdfFileReader(str(pdf_path))
        pages_text = []
        for i in range(reader.numPages):
            try:
                t = reader.getPage(i).extractText() or ""
                pages_text.append(t)
            except Exception as e:
                print(f"    [WARN] Page {i} error: {e}")
        return "\n".join(pages_text)


def parse_rules_ga_supreme(text: str, rule_set: str, source_url: str) -> list:
    """
    Parse GA Supreme Court rules from extracted PDF text.
    Rules start with patterns like: 'RULE 1.' or 'Rule 1.' or 'RULE 1 -' or just numbered headings.
    """
    rules = []
    fetched_at = datetime.now(timezone.utc).isoformat()

    # Normalize whitespace
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\r', '\n', text)

    # Try multiple patterns for rule boundaries
    # Pattern 1: RULE N. or Rule N. possibly with heading
    # Pattern 2: Rule N - Heading
    patterns = [
        r'(?:^|\n)(RULE\s+(\d+[A-Z]?(?:\.\d+)?)[.\s\-–—]+([^\n]+))',
        r'(?:^|\n)(Rule\s+(\d+[A-Z]?(?:\.\d+)?)[.\s\-–—]+([^\n]+))',
        r'(?:^|\n)(RULE\s+(\d+[A-Z]?(?:\.\d+)?)\.?\s*\n)',
    ]

    # Unified approach: split on rule headers
    combined_pattern = re.compile(
        r'(?:^|\n)((?:RULE|Rule)\s+(\d+[A-Z]?(?:\.\d+)?)[.\s\-–—:]*([^\n]*))',
        re.MULTILINE
    )

    matches = list(combined_pattern.finditer(text))
    print(f"  [PARSE] Found {len(matches)} rule headers in {rule_set}")

    if not matches:
        # Fallback: try numbered sections
        numbered_pattern = re.compile(
            r'(?:^|\n)(\d+\.\s+([A-Z][^\n]{5,60}))',
            re.MULTILINE
        )
        matches = list(numbered_pattern.finditer(text))
        print(f"  [PARSE-FALLBACK] Found {len(matches)} numbered sections")
        if not matches:
            # Store entire text as one record
            rules.append({
                "rule_set": rule_set,
                "rule_number": "Full Text",
                "heading": f"{rule_set} - Complete Text",
                "text": text.strip(),
                "source_url": source_url,
                "fetched_at": fetched_at,
            })
            return rules

    for i, match in enumerate(matches):
        rule_header = match.group(1).strip()
        rule_number_raw = match.group(2).strip()
        heading_raw = match.group(3).strip() if match.lastindex >= 3 else ""

        # Get text between this match and the next
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body_text = text[start:end].strip()

        # Clean up heading
        heading = re.sub(r'\s+', ' ', heading_raw).strip()
        if not heading and body_text:
            # Try to extract heading from first line of body
            first_line = body_text.split('\n')[0].strip()
            if len(first_line) < 120:
                heading = first_line

        full_text = (rule_header + "\n" + body_text).strip()

        if len(full_text) < 20:
            continue

        rules.append({
            "rule_set": rule_set,
            "rule_number": f"Rule {rule_number_raw}",
            "heading": heading[:250] if heading else f"Rule {rule_number_raw}",
            "text": full_text[:50000],
            "source_url": source_url,
            "fetched_at": fetched_at,
        })

    return rules


def write_jsonl(records: list, output_path: Path):
    """Write records to a JSONL file."""
    with open(output_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  [WRITE] Wrote {len(records)} records to {output_path.name}")


def process_source(source: dict) -> int:
    """Download, extract, parse, and write one source. Returns number of rules extracted."""
    rule_set = source["rule_set"]
    url = source["url"]
    pdf_path = OUTPUT_DIR / source["filename"]
    output_path = OUTPUT_DIR / source["output_jsonl"]

    print(f"\n=== Processing: {rule_set} ===")
    print(f"  URL: {url}")

    # Download
    if not download_pdf(url, pdf_path):
        return 0

    # Extract text
    try:
        text = extract_text_from_pdf(pdf_path)
        if len(text) < 500:
            print(f"  [WARN] Very little text extracted ({len(text)} chars)")
        else:
            print(f"  [OK] Extracted {len(text)} chars of text")
    except Exception as e:
        print(f"  [FAIL] PDF extraction error: {e}")
        return 0

    # Parse rules
    try:
        rules = parse_rules_ga_supreme(text, rule_set, url)
        print(f"  [PARSE] Parsed {len(rules)} rules")
    except Exception as e:
        print(f"  [FAIL] Parse error: {e}")
        return 0

    if not rules:
        print(f"  [WARN] No rules parsed")
        return 0

    # Write JSONL (append if file exists, otherwise create)
    if output_path.exists():
        existing_numbers = set()
        try:
            with open(output_path) as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        existing_numbers.add(rec.get("rule_number", ""))
                    except Exception:
                        pass
        except Exception:
            pass
        new_rules = [r for r in rules if r["rule_number"] not in existing_numbers]
        mode = "a"
    else:
        new_rules = rules
        mode = "w"

    with open(output_path, mode, encoding="utf-8") as f:
        for rec in new_rules:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"  [WRITE] Wrote {len(new_rules)} new records to {output_path.name}")
    return len(new_rules)


def main():
    print(f"GA Court Rules Scraper starting at {datetime.now().isoformat()}")
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"PDF library: {PDF_LIB}")

    # Track processed filenames to avoid double-processing same PDF
    processed_files = {}
    total_rules = 0
    results = {}

    for source in SOURCES:
        rule_set = source["rule_set"]
        pdf_name = source["filename"]
        out_jsonl = source["output_jsonl"]

        # If we already successfully downloaded+parsed this file, skip retry URLs
        if pdf_name in processed_files and processed_files[pdf_name] > 0:
            print(f"\n=== SKIP (already got {processed_files[pdf_name]} rules for {pdf_name}) ===")
            continue

        count = process_source(source)
        processed_files[pdf_name] = count
        if count > 0:
            results[rule_set] = results.get(rule_set, 0) + count
            total_rules += count
        time.sleep(1)

    print(f"\n{'='*60}")
    print(f"SUMMARY:")
    for rs, count in results.items():
        print(f"  {rs}: {count} rules")
    print(f"  TOTAL: {total_rules} rules across {len(results)} rule sets")
    print(f"  Output files in: {OUTPUT_DIR}")

    # Write a manifest
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rule_sets": results,
        "total_rules": total_rules,
        "output_dir": str(OUTPUT_DIR),
    }
    manifest_path = OUTPUT_DIR / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
