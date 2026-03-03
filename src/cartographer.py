#!/usr/bin/env python3
"""
Operation Cartographer — Fortress Prime
==========================================
Identifies garbled OCR pages (plat maps, handwritten exhibits, images)
and routes them to Llama 3.2 Vision on the Muscle Node for visual analysis.

The Problem:
    Marker OCR reads text well but produces garbage on maps, plats, and
    hand-drawn exhibits (e.g., "HUHON X ELLUY RIVER MATERSHED").

The Solution:
    1. DETECT:  Scan Markdown output for low-confidence sections
    2. LOCATE:  Find the original PDF and identify which pages are garbled
    3. SEE:     Render those pages as images, send to Llama 3.2 Vision
    4. DESCRIBE: Get structured descriptions (property lines, easements, notes)
    5. INDEX:   Inject vision descriptions into ChromaDB fortress_knowledge

Architecture:
    Captain (this node) orchestrates
    Muscle (Spark 1, 192.168.0.104) runs Llama 3.2 Vision 90B

Usage:
    # Scan all OCR output and process garbled pages
    python3 -m src.cartographer

    # Process a specific Markdown file
    python3 -m src.cartographer --file /mnt/ai_bulk/Enterprise_War_Room_MD/.../doc.md

    # Dry run (identify but don't process)
    python3 -m src.cartographer --dry-run

    # Watch mode (continuous, like rag_live_ingest)
    python3 -m src.cartographer --watch
"""

import os
import io
import sys
import json
import time
import base64
import argparse
import requests
from pathlib import Path
from datetime import datetime

import chromadb
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Directories
OCR_OUTPUT_DIR = Path("/mnt/ai_bulk/Enterprise_War_Room_MD")
SOURCE_PDF_DIR = Path("/mnt/ai_bulk/Enterprise_War_Room")
LOG_DIR = Path("/mnt/fortress_nas/fortress_data/ai_brain/logs/cartographer")
PROCESSED_LOG = LOG_DIR / "cartographer_processed.json"

# ChromaDB
DB_DIR = "/mnt/ai_fast/chroma_db"
COLLECTION_NAME = "fortress_knowledge"

# Embedding (Captain - local)
EMBED_MODEL = "nomic-embed-text"
EMBED_URL = "http://localhost:11434"

# Vision (Muscle - Spark 1)
MUSCLE_IP = os.getenv("WORKER_IP", "192.168.0.104")
MUSCLE_PORT = int(os.getenv("MUSCLE_PORT", "11434"))
MUSCLE_URL = f"http://{MUSCLE_IP}:{MUSCLE_PORT}"
VISION_MODEL = "llama3.2-vision:90b"

# Detection thresholds
ALPHA_RATIO_THRESHOLD = 0.45   # Below this = likely garbled (map/image)
MIN_LINE_LENGTH = 30           # Only analyze lines longer than this
GARBLED_LINES_THRESHOLD = 3    # Need at least this many garbled lines to flag a section
MIN_SECTION_LENGTH = 50        # Minimum text length to consider a section

# Vision prompt for plat maps and exhibits
VISION_PROMPT_MAP = """Analyze this image from a legal document. It may be a:
- Property plat map or survey
- Hand-drawn boundary diagram  
- Legal exhibit with handwritten annotations
- Scanned form or table

Describe in detail:
1. If it is a MAP: Describe all property lines, lot numbers, road names, easements, 
   dimensions (footage), compass directions, and any handwritten notes or annotations.
2. If it is a FORM/TABLE: Extract all fields, values, dates, and signatures.
3. If it is a LETTER with poor scan quality: Transcribe the readable portions.

Be specific about measurements (e.g., "20' easement"), names, lot numbers, and 
geographic features (rivers, roads). This information will be used for legal research."""

VISION_PROMPT_EXHIBIT = """This is a scanned legal exhibit. Analyze the image and describe:
1. What type of document is this? (plat map, deed, letter, form, receipt, etc.)
2. Extract ALL readable text, names, dates, and reference numbers.
3. If it contains a map or diagram, describe the spatial layout, measurements, 
   and any labeled features (roads, lots, easements, waterways).
4. Note any handwritten annotations or signatures.

Be thorough — this description will replace garbled OCR text in a legal knowledge base."""


# ---------------------------------------------------------------------------
# Detection: Find garbled sections in Markdown
# ---------------------------------------------------------------------------

def analyze_md_quality(md_path: str) -> list:
    """
    Analyze a Markdown file for garbled sections.
    Returns a list of dicts describing each garbled section with context.
    """
    text = Path(md_path).read_text(errors="replace")
    lines = text.split("\n")
    
    garbled_sections = []
    current_section = None
    current_header = "[Root]"
    garbled_lines_in_section = 0
    section_start = 0
    
    for i, line in enumerate(lines):
        # Track headers
        stripped = line.strip()
        if stripped.startswith("#"):
            # Save previous section if garbled
            if current_section and garbled_lines_in_section >= GARBLED_LINES_THRESHOLD:
                garbled_sections.append(current_section)
            
            current_header = stripped.lstrip("#").strip()
            current_section = {
                "header": current_header,
                "start_line": i,
                "end_line": i,
                "garbled_count": 0,
                "total_lines": 0,
                "sample_garbled": [],
            }
            garbled_lines_in_section = 0
            section_start = i
            continue
        
        if not stripped or len(stripped) < MIN_LINE_LENGTH:
            continue
            
        # Calculate alpha ratio for this line
        alpha_count = sum(1 for c in stripped if c.isalpha())
        alpha_ratio = alpha_count / len(stripped)
        
        if current_section is None:
            current_section = {
                "header": current_header,
                "start_line": 0,
                "end_line": i,
                "garbled_count": 0,
                "total_lines": 0,
                "sample_garbled": [],
            }
        
        current_section["total_lines"] += 1
        current_section["end_line"] = i
        
        if alpha_ratio < ALPHA_RATIO_THRESHOLD:
            garbled_lines_in_section += 1
            current_section["garbled_count"] = garbled_lines_in_section
            if len(current_section["sample_garbled"]) < 3:
                current_section["sample_garbled"].append(
                    f"L{i}: alpha={alpha_ratio:.2f} | {stripped[:100]}"
                )
    
    # Don't forget the last section
    if current_section and garbled_lines_in_section >= GARBLED_LINES_THRESHOLD:
        garbled_sections.append(current_section)
    
    return garbled_sections


def find_source_pdf(md_path: str) -> str:
    """
    Given a Markdown path in Enterprise_War_Room_MD, find the original PDF
    in Enterprise_War_Room.
    """
    md_p = Path(md_path)
    
    # The MD path structure is:
    # /mnt/ai_bulk/Enterprise_War_Room_MD/.../DocName/DocName.md
    # The PDF path is:
    # /mnt/ai_bulk/Enterprise_War_Room/.../DocName.pdf
    
    # Walk up to find the relative path
    try:
        rel = md_p.relative_to(OCR_OUTPUT_DIR)
    except ValueError:
        return ""
    
    # The PDF name is the stem of the .md file
    pdf_name = md_p.stem + ".pdf"
    
    # Build the expected PDF path (remove the extra subdirectory Marker creates)
    # MD: .../subdir/DocName/DocName.md -> PDF: .../subdir/DocName.pdf
    parent_rel = rel.parent.parent  # Go up past the Marker subdirectory
    pdf_path = SOURCE_PDF_DIR / parent_rel / pdf_name
    
    if pdf_path.exists():
        return str(pdf_path)
    
    # Fallback: search for the PDF by name
    for p in SOURCE_PDF_DIR.rglob(pdf_name):
        return str(p)
    
    return ""


# ---------------------------------------------------------------------------
# Vision: Render PDF pages and send to Llama 3.2 Vision
# ---------------------------------------------------------------------------

def render_pdf_page(pdf_path: str, page_num: int, dpi: int = 200) -> str:
    """
    Render a specific page of a PDF to a base64-encoded PNG image.
    Uses pdf2image (poppler) for rendering.
    """
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(
            pdf_path,
            first_page=page_num + 1,  # pdf2image is 1-indexed
            last_page=page_num + 1,
            dpi=dpi,
        )
        if images:
            buf = io.BytesIO()
            images[0].save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")
    except ImportError:
        print("    [WARN] pdf2image not installed. Run: pip install pdf2image")
        print("    [WARN] Also needs: sudo apt install poppler-utils")
    except Exception as e:
        print(f"    [WARN] Failed to render page {page_num}: {e}")
    
    return ""


def render_all_pages(pdf_path: str, dpi: int = 200) -> list:
    """Render all pages of a PDF to base64 images. Returns list of (page_num, b64)."""
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(pdf_path, dpi=dpi)
        results = []
        for i, img in enumerate(images):
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            results.append((i, b64))
        return results
    except ImportError:
        print("    [WARN] pdf2image not installed.")
        return []
    except Exception as e:
        print(f"    [WARN] Failed to render PDF: {e}")
        return []


def ask_vision(image_b64: str, prompt: str) -> str:
    """
    Send an image to Llama 3.2 Vision on the Muscle Node.
    Returns the model's description.
    """
    payload = {
        "model": VISION_MODEL,
        "prompt": prompt,
        "images": [image_b64],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 2048,
        },
    }
    
    try:
        resp = requests.post(
            f"{MUSCLE_URL}/api/generate",
            json=payload,
            timeout=600,  # Vision on 90B can be slow
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except requests.exceptions.Timeout:
        return "[TIMEOUT] Vision model took too long on this page."
    except Exception as e:
        return f"[ERROR] Vision request failed: {e}"


# ---------------------------------------------------------------------------
# Indexing: Store vision descriptions in ChromaDB
# ---------------------------------------------------------------------------

def index_description(
    vector_db,
    description: str,
    source_pdf: str,
    md_file: str,
    page_num: int,
    section_header: str,
):
    """Store a vision-generated description in the fortress_knowledge collection."""
    from langchain_core.documents import Document
    
    if not description or description.startswith("[ERROR]") or description.startswith("[TIMEOUT]"):
        return False
    
    doc = Document(
        page_content=description,
        metadata={
            "source": Path(md_file).name.replace(".md", ".pdf"),
            "path": source_pdf or md_file,
            "page": page_num,
            "section": section_header,
            "origin": "vision_cartographer",
            "vision_model": VISION_MODEL,
            "ingested_at": datetime.now().isoformat(),
            # Extract category from path
            "category": _extract_category(md_file),
        },
    )
    
    vector_db.add_documents([doc])
    return True


def _extract_category(path: str) -> str:
    """Extract category (Legal, Financial, etc.) from file path."""
    parts = Path(path).parts
    for i, part in enumerate(parts):
        if part == "Enterprise_War_Room_MD" and i + 1 < len(parts):
            return parts[i + 1]
        if part == "Enterprise_War_Room" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


# ---------------------------------------------------------------------------
# State Management
# ---------------------------------------------------------------------------

def load_processed() -> set:
    if PROCESSED_LOG.exists():
        try:
            return set(json.load(PROCESSED_LOG.open()))
        except:
            return set()
    return set()


def save_processed(processed: set):
    PROCESSED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_LOG, "w") as f:
        json.dump(sorted(processed), f, indent=2)


def log_event(event: dict):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"cartographer_{datetime.now():%Y%m%d}.jsonl"
    event["timestamp"] = datetime.now().isoformat()
    with open(log_file, "a") as f:
        f.write(json.dumps(event) + "\n")


# ---------------------------------------------------------------------------
# Main Processing
# ---------------------------------------------------------------------------

def process_file(md_path: str, vector_db, dry_run: bool = False) -> dict:
    """
    Analyze one Markdown file. If garbled sections are found, render the
    original PDF pages and send them to Vision for description.
    """
    result = {
        "file": md_path,
        "garbled_sections": 0,
        "pages_sent_to_vision": 0,
        "descriptions_indexed": 0,
        "status": "clean",
    }
    
    # Step 1: Detect garbled sections
    garbled = analyze_md_quality(md_path)
    
    if not garbled:
        return result
    
    result["garbled_sections"] = len(garbled)
    result["status"] = "garbled"
    
    basename = Path(md_path).name
    print(f"    Found {len(garbled)} garbled section(s) in {basename}")
    for section in garbled:
        print(f"      Section: '{section['header']}' "
              f"({section['garbled_count']} garbled lines)")
        for sample in section["sample_garbled"]:
            print(f"        {sample}")
    
    if dry_run:
        return result
    
    # Step 2: Find the original PDF
    source_pdf = find_source_pdf(md_path)
    if not source_pdf:
        print(f"    [SKIP] Cannot find source PDF for {basename}")
        result["status"] = "no_source_pdf"
        return result
    
    print(f"    Source PDF: {Path(source_pdf).name}")
    
    # Step 3: Render all pages (we send the whole document since
    # garbled sections often correspond to exhibit pages)
    print(f"    Rendering PDF pages...")
    pages = render_all_pages(source_pdf, dpi=150)
    
    if not pages:
        print(f"    [SKIP] Could not render PDF pages")
        result["status"] = "render_failed"
        return result
    
    print(f"    Rendered {len(pages)} page(s). Sending to Vision...")
    
    # Step 4: Send exhibit/garbled pages to Vision
    # Strategy: For short docs (<=5 pages), send all pages.
    # For longer docs, try to identify the exhibit pages.
    pages_to_process = pages
    if len(pages) > 5:
        # For long documents, only process pages near garbled sections
        # Each garbled section maps roughly to a page range
        target_pages = set()
        total_lines = sum(1 for _ in Path(md_path).read_text(errors="replace").split("\n"))
        for section in garbled:
            # Estimate which page this section is on
            if total_lines > 0:
                page_estimate = int(section["start_line"] / total_lines * len(pages))
                # Add the estimated page and neighbors
                for offset in range(-1, 2):
                    pg = page_estimate + offset
                    if 0 <= pg < len(pages):
                        target_pages.add(pg)
        
        if target_pages:
            pages_to_process = [(pn, b64) for pn, b64 in pages if pn in target_pages]
            print(f"    Long document ({len(pages)} pages). "
                  f"Targeting {len(pages_to_process)} exhibit pages.")
    
    for page_num, img_b64 in pages_to_process:
        print(f"    [Vision] Page {page_num + 1}/{len(pages)}... ", end="", flush=True)
        
        description = ask_vision(img_b64, VISION_PROMPT_EXHIBIT)
        
        if description and not description.startswith("["):
            # Index the description
            success = index_description(
                vector_db=vector_db,
                description=description,
                source_pdf=source_pdf,
                md_file=md_path,
                page_num=page_num,
                section_header=garbled[0]["header"] if garbled else "Exhibit",
            )
            if success:
                result["descriptions_indexed"] += 1
                print(f"Indexed ({len(description)} chars)")
            else:
                print("Failed to index")
        else:
            print(f"No usable output")
        
        result["pages_sent_to_vision"] += 1
    
    result["status"] = "processed"
    return result


def run_cartographer(
    target_file: str = None,
    dry_run: bool = False,
    watch: bool = False,
):
    """Main entry point for Operation Cartographer."""
    print("=" * 60)
    print("  OPERATION CARTOGRAPHER")
    print("  Mapping the unmappable. Seeing what OCR cannot read.")
    print("=" * 60)
    print(f"  OCR output:   {OCR_OUTPUT_DIR}")
    print(f"  Source PDFs:   {SOURCE_PDF_DIR}")
    print(f"  Vision model:  {VISION_MODEL} @ {MUSCLE_URL}")
    print(f"  ChromaDB:      {DB_DIR} / {COLLECTION_NAME}")
    print(f"  Mode:          {'Dry run' if dry_run else 'Watch' if watch else 'Single pass'}")
    print("=" * 60)
    print()
    
    # Initialize ChromaDB + embeddings (only if not dry run)
    vector_db = None
    if not dry_run:
        embeddings = OllamaEmbeddings(model=EMBED_MODEL, base_url=EMBED_URL)
        vector_db = Chroma(
            persist_directory=DB_DIR,
            embedding_function=embeddings,
            collection_name=COLLECTION_NAME,
        )
    
    processed = load_processed()
    print(f"  Previously processed: {len(processed)} files\n")
    
    # Single file mode
    if target_file:
        print(f"  Targeting: {target_file}\n")
        result = process_file(target_file, vector_db, dry_run)
        log_event(result)
        _print_result(result)
        return
    
    # Scan / Watch loop
    total_garbled = 0
    total_vision = 0
    total_indexed = 0
    
    while True:
        # Find all Markdown files
        md_files = sorted(str(p) for p in OCR_OUTPUT_DIR.rglob("*.md") if p.is_file())
        new_files = [f for f in md_files if f not in processed]
        
        if not new_files:
            if watch:
                print(f"  No new files. Watching... "
                      f"({len(processed)} scanned, {total_indexed} vision-indexed)    ",
                      end="\r")
                time.sleep(30)
                continue
            else:
                print(f"  All {len(processed)} files scanned. "
                      f"Vision indexed: {total_indexed} descriptions.")
                break
        
        print(f"  Scanning {len(new_files)} new file(s)...\n")
        
        for idx, md_file in enumerate(new_files, 1):
            basename = Path(md_file).name
            print(f"  [{idx}/{len(new_files)}] {basename[:55]:<55}")
            
            result = process_file(md_file, vector_db, dry_run)
            log_event(result)
            
            total_garbled += result["garbled_sections"]
            total_vision += result["pages_sent_to_vision"]
            total_indexed += result["descriptions_indexed"]
            
            # Mark as processed regardless of outcome
            processed.add(md_file)
            save_processed(processed)
            
            if result["status"] == "clean":
                print(f"    [CLEAN] No garbled sections detected.\n")
        
        if not watch:
            break
    
    # Summary
    print("\n" + "=" * 60)
    print("  CARTOGRAPHER MISSION COMPLETE")
    print("=" * 60)
    print(f"  Files scanned:          {len(processed)}")
    print(f"  Garbled sections found:  {total_garbled}")
    print(f"  Pages sent to Vision:    {total_vision}")
    print(f"  Descriptions indexed:    {total_indexed}")
    print("=" * 60)


def _print_result(result: dict):
    """Pretty-print a single file result."""
    print(f"\n  Status:       {result['status']}")
    print(f"  Garbled:      {result['garbled_sections']} section(s)")
    print(f"  Vision pages: {result['pages_sent_to_vision']}")
    print(f"  Indexed:      {result['descriptions_indexed']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Operation Cartographer - Vision-enhanced OCR")
    parser.add_argument("--file", help="Process a specific Markdown file")
    parser.add_argument("--dry-run", action="store_true", help="Detect garbled sections without processing")
    parser.add_argument("--watch", action="store_true", help="Continuous watch mode")
    args = parser.parse_args()
    
    run_cartographer(
        target_file=args.file,
        dry_run=args.dry_run,
        watch=args.watch,
    )
