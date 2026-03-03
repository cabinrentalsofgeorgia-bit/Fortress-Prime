"""
Fortress Prime — DIVISION FINANCE: "Ledger" Ingestion Engine
=============================================================
Turns 74k dumb files into a sovereign financial database.

THREE-PHASE APPROACH:
  Phase 1 (Path Intelligence):  Classifies ~80% of documents in seconds
                                using filepath patterns and naming conventions.
  Phase 2 (AI Deep Scan):       Extracts text from remaining PDFs with pdfplumber,
                                then sends to DeepSeek-R1 for structured extraction.
  Phase 3 (Vision OCR):         Sends scanned PDFs and images to LLaVA Vision 70B
                                for Sovereign OCR — reads documents the way a human would.

Database: SQLite (division_finance/fortress_ledger.db)
         + Postgres sync (fortress_db.general_ledger)
Table:    general_ledger

Usage:
    python division_finance/ingest_ledger.py                # Full run (Phase 1 + 2)
    python division_finance/ingest_ledger.py --phase1       # Path classification only
    python division_finance/ingest_ledger.py --phase2       # AI text extraction only
    python division_finance/ingest_ledger.py --vision       # Vision OCR (Phase 3)
    python division_finance/ingest_ledger.py --sync         # Sync SQLite -> Postgres
    python division_finance/ingest_ledger.py --stats        # Show current ledger stats
"""
import os
import re
import sys
import json
import time
import base64
import sqlite3
import logging
import requests
from datetime import datetime
from pathlib import Path

# Fortress Prompt System
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from prompts.loader import load_prompt

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)

# --- CONFIG ---
FINANCIAL_ROOT = "/mnt/fortress_nas/Enterprise_War_Room/Financial_Records"
DB_FILE = os.path.join(os.path.dirname(__file__), "fortress_ledger.db")
LOG_FILE = os.path.join(os.path.dirname(__file__), "ingest_ledger.log")

# AI Endpoints (Ollama)
R1_URL = "http://localhost:11434/api/generate"
R1_MODEL = "deepseek-r1:8b"

# Vision OCR (LLaVA — Sovereign OCR)
VISION_URL = "http://localhost:11434/api/generate"
VISION_MODEL = os.environ.get("VISION_MODEL", "llava:v1.6")

# Postgres sync target (fortress_db)
PG_HOST = os.environ.get("DB_HOST", "localhost")
PG_DB = os.environ.get("DB_NAME", "fortress_db")
PG_USER = os.environ.get("DB_USER", "miner_bot")
PG_PASS = os.environ.get("DB_PASSWORD", os.environ.get("DB_PASS", ""))
PG_PORT = os.environ.get("DB_PORT", "5432")

# Image extensions that Vision can read directly
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif"}

# File extensions that are actual financial documents
FINANCIAL_EXTENSIONS = {
    ".pdf", ".xlsx", ".xls", ".csv", ".doc", ".docx",
    ".pages", ".numbers", ".qbw", ".qbb", ".qbx",
    ".txt", ".rtf", ".tiff", ".tif", ".jpg", ".jpeg", ".png"
}

# Extensions to SKIP (system junk, not financial docs)
SKIP_EXTENSIONS = {
    ".plist", ".nib", ".strings", ".bom", ".yaml", ".yml",
    ".ds_store", ".icloud", ".info", ".sizes", ".gif",
    ".pkg", ".dmg", ".app", ".dylib", ".so", ".framework",
    ".emlx", ".eml", ".mbox",  # Emails handled by Comms division
    ".md", ".html", ".htm", ".css", ".js",  # Web files
    ".sqlite", ".db",  # Databases
    ".cr2", ".dng", ".xmp",  # Raw photos
    ".photoslibrary", ".lrcat",  # Photo library metadata
}

# Path segments that indicate app/system data (not financial docs)
SKIP_PATH_SEGMENTS = [
    "/Application Support/",
    "/Caches/",
    "/Cache/",
    "/Service Worker/",
    "/WebKit/",
    "/IndexedDB/",
    "/GPUCache/",
    "/Preferences/com.",
    "/.Trash/",
    "/node_modules/",
    "/site-packages/",
    "/Photos Library.photoslibrary/",
    "/Lightroom Library.lrlibrary/",
]

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ============================================================
# DATABASE SCHEMA
# ============================================================
SCHEMA = """
CREATE TABLE IF NOT EXISTS general_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filepath TEXT UNIQUE,
    filename TEXT,
    extension TEXT,
    file_size INTEGER,
    doc_type TEXT,         -- Invoice, Receipt, Tax_Return, Statement, Deed, Contract, Unknown
    category TEXT,         -- Rental_Income, Operating_Expense, Tax_Filing, Personal, Property, Legal
    vendor TEXT,
    client_name TEXT,      -- Guest name on invoices
    date_detected TEXT,
    amount REAL,
    tax_year TEXT,
    cabin TEXT,            -- Property name (Solitude, Five Peaks, etc.)
    business TEXT,         -- CROG, Personal, Contractor
    confidence TEXT,       -- path_match, ai_extracted, manual
    raw_text TEXT,         -- First 2000 chars of extracted text
    ai_json TEXT,          -- Full AI extraction JSON (Phase 2)
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    phase INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_doc_type ON general_ledger(doc_type);
CREATE INDEX IF NOT EXISTS idx_category ON general_ledger(category);
CREATE INDEX IF NOT EXISTS idx_cabin ON general_ledger(cabin);
CREATE INDEX IF NOT EXISTS idx_tax_year ON general_ledger(tax_year);
CREATE INDEX IF NOT EXISTS idx_business ON general_ledger(business);
"""


def init_db():
    """Initialize the ledger database."""
    conn = sqlite3.connect(DB_FILE)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ============================================================
# PHASE 1: PATH INTELLIGENCE CLASSIFIER
# ============================================================

# Known cabin properties (from file path analysis)
CABINS = [
    "rivers edge", "five peaks", "solitude", "majestic lake", "morningstar vista",
    "morningstar", "buckhorn lodge", "buckhorn", "rolling river", "bella vista",
    "crooked creek", "riverview lodge", "riverview", "melancholy moose",
    "aska escape", "cloud 10", "toccoa retreat", "mountain laurel",
    "amber ridge", "whispering pines", "eagles nest", "bear creek",
    "hidden creek", "blue ridge", "cherry log"
]

# Document type patterns (applied to filepath + filename)
DOC_TYPE_PATTERNS = [
    # (pattern, doc_type, category)
    (r'invoice', 'Invoice', 'Rental_Income'),
    (r'receipt', 'Receipt', 'Operating_Expense'),
    (r'statement', 'Statement', 'Financial'),
    (r'1099', 'Tax_Form_1099', 'Tax_Filing'),
    (r'1040', 'Tax_Return', 'Tax_Filing'),
    (r'k[\-\s]?1', 'Tax_Form_K1', 'Tax_Filing'),
    (r'w[\-\s]?2', 'Tax_Form_W2', 'Tax_Filing'),
    (r'w[\-\s]?9', 'Tax_Form_W9', 'Tax_Filing'),
    (r'tax\s*return', 'Tax_Return', 'Tax_Filing'),
    (r'schedule[\s_]?[a-e]', 'Tax_Schedule', 'Tax_Filing'),
    (r'deed', 'Deed', 'Property'),
    (r'plat', 'Plat', 'Property'),
    (r'survey', 'Survey', 'Property'),
    (r'warranty', 'Warranty_Deed', 'Property'),
    (r'easement', 'Easement', 'Property'),
    (r'mortgage', 'Mortgage', 'Property'),
    (r'closing', 'Closing_Statement', 'Property'),
    (r'contract', 'Contract', 'Legal'),
    (r'agreement', 'Agreement', 'Legal'),
    (r'lease', 'Lease', 'Legal'),
    (r'quickbooks|\.qb[wxb]', 'QuickBooks', 'Accounting'),
    (r'ledger', 'Ledger', 'Accounting'),
    (r'bank.?statement', 'Bank_Statement', 'Financial'),
    (r'profit.?loss|p\s*&\s*l', 'Profit_Loss', 'Financial'),
    (r'balance.?sheet', 'Balance_Sheet', 'Financial'),
    (r'sales.?receipt|sales_receipt', 'Sales_Receipt', 'Rental_Income'),
]

# Business entity patterns
BUSINESS_PATTERNS = [
    (r'cabin\s*rentals?\s*of\s*georgia|crog|crog[\-_]', 'CROG'),
    (r'streamline|vrs', 'CROG_Streamline'),
    (r'nbbj|esa\s*flash|cooper\s*light', 'Contractor'),
    (r'personal|knight|gary', 'Personal'),
]


def detect_cabin(path_lower):
    """Detect which cabin property a file relates to."""
    for cabin in CABINS:
        if cabin in path_lower:
            return cabin.title()
    return None


def detect_date(path, filename):
    """Try to extract a date from the filepath or filename."""
    combined = path + "/" + filename
    # Pattern: YYYY or YY in folder names like "2024", "07.07", "dec.06"
    year_match = re.search(r'(?:^|/)(\d{4})(?:/|$|\.|_)', combined)
    if year_match:
        year = int(year_match.group(1))
        if 1990 <= year <= 2030:
            return str(year)
    # Pattern: Month.YY like "12.07" or "dec.06"
    month_year = re.search(r'(\d{2})\.(\d{2})(?:/|$)', combined)
    if month_year:
        yy = int(month_year.group(2))
        return f"20{yy:02d}" if yy < 50 else f"19{yy:02d}"
    return None


def detect_client_name(filename):
    """Try to extract a guest/client name from the filename."""
    # Patterns like: arlene.pdf, joseph.moore.pdf, melissa.fincher.pdf
    name = os.path.splitext(filename)[0]
    # Remove common prefixes
    name = re.sub(r'^(Invoice_?\d*_?from_?|ML\.\d{2}\.\d{2}\.|RVL\.\d{2}\.\d{2}\.)', '', name)
    # If what's left looks like a name (letters, dots, spaces)
    if re.match(r'^[a-zA-Z][a-zA-Z\.\s\-]+$', name) and len(name) > 2:
        return name.replace('.', ' ').strip().title()
    return None


def classify_by_path(filepath):
    """Phase 1: Classify a file using ONLY its path and name."""
    path_lower = filepath.lower()
    filename = os.path.basename(filepath)
    filename_lower = filename.lower()
    ext = os.path.splitext(filename)[1].lower()

    result = {
        "filepath": filepath,
        "filename": filename,
        "extension": ext,
        "doc_type": "Unknown",
        "category": "Uncategorized",
        "vendor": None,
        "client_name": None,
        "date_detected": None,
        "cabin": None,
        "business": None,
        "confidence": "path_match",
    }

    # Detect document type
    for pattern, doc_type, category in DOC_TYPE_PATTERNS:
        if re.search(pattern, path_lower):
            result["doc_type"] = doc_type
            result["category"] = category
            break

    # Detect cabin
    result["cabin"] = detect_cabin(path_lower)

    # If file is in an invoices folder of a cabin, it's a rental invoice
    if result["cabin"] and "invoices" in path_lower:
        result["doc_type"] = "Invoice"
        result["category"] = "Rental_Income"

    # Detect business entity
    for pattern, biz in BUSINESS_PATTERNS:
        if re.search(pattern, path_lower):
            result["business"] = biz
            break

    # Detect date
    result["date_detected"] = detect_date(filepath, filename)

    # Detect client name (mostly for rental invoices)
    if result["doc_type"] == "Invoice":
        result["client_name"] = detect_client_name(filename)

    return result


def run_phase1(conn):
    """Phase 1: Walk all files and classify by path."""
    print("\n" + "=" * 70)
    print("  PHASE 1: PATH INTELLIGENCE SCAN")
    print("  Classifying 74k files by filepath patterns...")
    print("=" * 70 + "\n")

    c = conn.cursor()
    processed = 0
    skipped_ext = 0
    skipped_exists = 0
    classified = 0
    unknown = 0

    for root, dirs, files in os.walk(FINANCIAL_ROOT):
        for f in files:
            filepath = os.path.join(root, f)
            ext = os.path.splitext(f)[1].lower()

            # Skip hidden files (filenames starting with '.')
            if f.startswith('.'):
                skipped_ext += 1
                continue

            # Skip non-financial file types (whitelist approach)
            if ext and ext not in FINANCIAL_EXTENSIONS:
                skipped_ext += 1
                continue

            # Skip known junk extensions
            if ext in SKIP_EXTENSIONS:
                skipped_ext += 1
                continue

            # Skip app/system data directories
            if any(seg in filepath for seg in SKIP_PATH_SEGMENTS):
                skipped_ext += 1
                continue

            # Skip if already in DB
            c.execute("SELECT id FROM general_ledger WHERE filepath = ?", (filepath,))
            if c.fetchone():
                skipped_exists += 1
                continue

            # Classify
            result = classify_by_path(filepath)
            file_size = 0
            try:
                file_size = os.path.getsize(filepath)
            except:
                pass

            # Insert into DB
            c.execute("""
                INSERT OR IGNORE INTO general_ledger
                (filepath, filename, extension, file_size, doc_type, category,
                 vendor, client_name, date_detected, cabin, business, confidence, phase)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                result["filepath"], result["filename"], result["extension"],
                file_size, result["doc_type"], result["category"],
                result["vendor"], result["client_name"], result["date_detected"],
                result["cabin"], result["business"], result["confidence"]
            ))

            if result["doc_type"] != "Unknown":
                classified += 1
            else:
                unknown += 1

            processed += 1
            if processed % 5000 == 0:
                conn.commit()
                print(f"   Scanned {processed:,} files... ({classified:,} classified, {unknown:,} unknown)")

    conn.commit()

    print(f"\n   PHASE 1 COMPLETE:")
    print(f"   Files scanned:    {processed:,}")
    print(f"   Classified:       {classified:,}")
    print(f"   Unknown (Phase2): {unknown:,}")
    print(f"   Skipped (junk):   {skipped_ext:,}")
    print(f"   Skipped (exists): {skipped_exists:,}")

    return unknown


# ============================================================
# PHASE 2: AI DEEP SCAN (DeepSeek-R1 + pdfplumber)
# ============================================================

def extract_pdf_text(filepath, max_pages=2):
    """Extract text from the first N pages of a PDF."""
    try:
        import pdfplumber
        text = ""
        with pdfplumber.open(filepath) as pdf:
            for i, page in enumerate(pdf.pages[:max_pages]):
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text[:3000]  # Cap at 3000 chars
    except Exception as e:
        logging.warning(f"PDF extraction failed: {filepath} — {e}")
        return None


def ai_classify(text, filename):
    """Send document text to DeepSeek-R1 for structured extraction."""
    tmpl = load_prompt("ledger_classifier")
    prompt = tmpl.render(filename=filename, document_text=text[:2000])

    payload = {
        "model": R1_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 500}
    }

    try:
        res = requests.post(R1_URL, json=payload, timeout=120)
        if res.status_code == 200:
            response = res.json().get("response", "")
            # Strip thinking tags
            if "<think>" in response:
                parts = response.split("</think>")
                response = parts[-1].strip() if len(parts) > 1 else response
            # Extract JSON from response
            json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
    except json.JSONDecodeError:
        pass
    except Exception as e:
        logging.error(f"AI classify error: {e}")

    return None


def run_phase2(conn, limit=500):
    """Phase 2: AI-powered deep scan of unclassified PDFs."""
    print("\n" + "=" * 70)
    print("  PHASE 2: AI DEEP SCAN (DeepSeek-R1)")
    print(f"  Processing up to {limit} unclassified PDFs...")
    print("=" * 70 + "\n")

    c = conn.cursor()
    c.execute("""
        SELECT id, filepath, filename FROM general_ledger
        WHERE doc_type = 'Unknown' AND extension = '.pdf' AND phase = 1
        ORDER BY file_size DESC
        LIMIT ?
    """, (limit,))
    unknowns = c.fetchall()

    if not unknowns:
        print("   No unclassified PDFs remaining. Phase 2 complete.")
        return

    print(f"   {len(unknowns)} PDFs queued for AI analysis.\n")
    extracted = 0

    for i, (row_id, filepath, filename) in enumerate(unknowns):
        print(f"   [{i+1}/{len(unknowns)}] {filename[:60]}...", end=" ", flush=True)

        # Extract text from PDF
        text = extract_pdf_text(filepath)
        if not text or len(text.strip()) < 20:
            print("(no text)")
            c.execute("UPDATE general_ledger SET phase = 2, raw_text = '(no extractable text)' WHERE id = ?", (row_id,))
            continue

        # Send to AI
        ai_result = ai_classify(text, filename)
        if ai_result:
            c.execute("""
                UPDATE general_ledger SET
                    doc_type = COALESCE(?, doc_type),
                    category = COALESCE(?, category),
                    vendor = COALESCE(?, vendor),
                    amount = ?,
                    date_detected = COALESCE(?, date_detected),
                    tax_year = COALESCE(?, tax_year),
                    confidence = 'ai_extracted',
                    raw_text = ?,
                    ai_json = ?,
                    phase = 2
                WHERE id = ?
            """, (
                ai_result.get("doc_type"),
                ai_result.get("category"),
                ai_result.get("vendor"),
                ai_result.get("amount"),
                ai_result.get("date"),
                ai_result.get("tax_year"),
                text[:2000],
                json.dumps(ai_result),
                row_id
            ))
            extracted += 1
            print(f"-> {ai_result.get('doc_type', '?')} ({ai_result.get('vendor', 'unknown')})")
        else:
            c.execute("UPDATE general_ledger SET phase = 2, raw_text = ? WHERE id = ?",
                       (text[:2000], row_id))
            print("(AI extraction failed)")

        if (i + 1) % 25 == 0:
            conn.commit()
            print(f"\n   --- Checkpoint: {extracted} extracted so far ---\n")

    conn.commit()
    print(f"\n   PHASE 2 COMPLETE: AI extracted data from {extracted}/{len(unknowns)} documents.")


# ============================================================
# PHASE 3: VISION OCR (LLaVA — Sovereign OCR)
# ============================================================

def image_to_base64(filepath):
    """Convert an image file to base64 string for Vision API."""
    try:
        with open(filepath, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logging.warning(f"Failed to read image: {filepath} — {e}")
        return None


def pdf_page_to_base64(filepath, page_num=0, dpi=200):
    """Convert a single PDF page to a base64-encoded PNG for Vision API."""
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(filepath, first_page=page_num + 1,
                                   last_page=page_num + 1, dpi=dpi)
        if images:
            import io
            buf = io.BytesIO()
            images[0].save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        logging.warning(f"PDF-to-image conversion failed: {filepath} — {e}")
    return None


def vision_classify(filepath, ext):
    """Send a document image to LLaVA Vision for Sovereign OCR classification."""
    # Get base64 image
    if ext in IMAGE_EXTENSIONS:
        img_b64 = image_to_base64(filepath)
    elif ext == ".pdf":
        img_b64 = pdf_page_to_base64(filepath)
    else:
        return None

    if not img_b64:
        return None

    tmpl = load_prompt("ledger_vision_ocr")
    prompt = tmpl.render()

    payload = {
        "model": VISION_MODEL,
        "prompt": prompt,
        "images": [img_b64],
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 500}
    }

    try:
        res = requests.post(VISION_URL, json=payload, timeout=180)
        if res.status_code == 200:
            response = res.json().get("response", "")
            # Strip any thinking tags
            if "<think>" in response:
                parts = response.split("</think>")
                response = parts[-1].strip() if len(parts) > 1 else response
            # Extract JSON
            json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
    except json.JSONDecodeError:
        pass
    except Exception as e:
        logging.error(f"Vision OCR error: {e}")

    return None


def run_phase_vision(conn, limit=500):
    """Phase 3: Vision OCR — sends images/scanned PDFs to LLaVA for visual reading."""
    print("\n" + "=" * 70)
    print("  PHASE 3: VISION OCR (LLaVA — Sovereign OCR)")
    print(f"  Model: {VISION_MODEL}")
    print(f"  Processing up to {limit} documents that need visual reading...")
    print("=" * 70 + "\n")

    c = conn.cursor()

    # Target: files that Phase 2 couldn't extract text from, OR images never processed
    c.execute("""
        SELECT id, filepath, filename, extension FROM general_ledger
        WHERE (
            (phase <= 2 AND (raw_text IS NULL OR raw_text = '(no extractable text)') AND extension = '.pdf')
            OR
            (phase <= 1 AND extension IN ('.jpg', '.jpeg', '.png', '.tiff', '.tif'))
        )
        AND confidence != 'vision_ocr'
        ORDER BY file_size ASC
        LIMIT ?
    """, (limit,))
    targets = c.fetchall()

    if not targets:
        print("   No documents remaining for Vision OCR. Phase 3 complete.")
        return

    print(f"   {len(targets)} documents queued for Vision OCR.\n")
    extracted = 0
    failed = 0

    for i, (row_id, filepath, filename, ext) in enumerate(targets):
        print(f"   [{i+1}/{len(targets)}] {filename[:55]}...", end=" ", flush=True)

        # Check file exists and isn't too large (skip files > 50MB)
        try:
            fsize = os.path.getsize(filepath)
            if fsize > 50 * 1024 * 1024:
                print("(>50MB, skipped)")
                continue
        except OSError:
            print("(file missing)")
            continue

        # Send to Vision model
        result = vision_classify(filepath, ext)
        if result:
            c.execute("""
                UPDATE general_ledger SET
                    doc_type = COALESCE(?, doc_type),
                    category = COALESCE(?, category),
                    vendor = COALESCE(?, vendor),
                    client_name = COALESCE(?, client_name),
                    amount = COALESCE(?, amount),
                    date_detected = COALESCE(?, date_detected),
                    tax_year = COALESCE(?, tax_year),
                    confidence = 'vision_ocr',
                    ai_json = ?,
                    phase = 3
                WHERE id = ?
            """, (
                result.get("doc_type"),
                result.get("category"),
                result.get("vendor"),
                result.get("client_name"),
                result.get("amount"),
                result.get("date"),
                result.get("tax_year"),
                json.dumps(result),
                row_id
            ))
            extracted += 1
            dtype = result.get("doc_type", "?")
            amt = result.get("amount")
            amt_str = f" ${amt:,.2f}" if amt else ""
            print(f"-> {dtype}{amt_str}")
        else:
            failed += 1
            c.execute("UPDATE general_ledger SET phase = 3 WHERE id = ?", (row_id,))
            print("(vision failed)")

        # Checkpoint every 25 documents
        if (i + 1) % 25 == 0:
            conn.commit()
            print(f"\n   --- Checkpoint: {extracted} extracted, {failed} failed ---\n")

        # Brief pause to avoid overloading the GPU
        time.sleep(0.5)

    conn.commit()
    print(f"\n   PHASE 3 COMPLETE: Vision OCR extracted data from {extracted}/{len(targets)} documents.")
    if failed:
        print(f"   ({failed} documents could not be read by Vision)")


# ============================================================
# POSTGRES SYNC (SQLite -> fortress_db)
# ============================================================

def sync_to_postgres():
    """Sync the local SQLite ledger to the central Postgres fortress_db."""
    try:
        import psycopg2
    except ImportError:
        print("   psycopg2 not installed. Run: pip install psycopg2-binary")
        return

    print("\n" + "=" * 70)
    print("  POSTGRES SYNC: SQLite -> fortress_db.general_ledger")
    print("=" * 70 + "\n")

    if not os.path.exists(DB_FILE):
        print("   SQLite ledger not found. Run ingestion first.")
        return

    # Connect to both databases
    lite = sqlite3.connect(DB_FILE)
    lite.row_factory = sqlite3.Row

    try:
        pg = psycopg2.connect(
            host=PG_HOST, database=PG_DB, user=PG_USER,
            password=PG_PASS, port=PG_PORT
        )
        pg_cur = pg.cursor()
    except Exception as e:
        print(f"   Postgres connection failed: {e}")
        lite.close()
        return

    # Create the table in Postgres if it doesn't exist
    pg_cur.execute("""
        CREATE TABLE IF NOT EXISTS general_ledger (
            id SERIAL PRIMARY KEY,
            filepath TEXT UNIQUE,
            filename TEXT,
            extension TEXT,
            file_size BIGINT,
            doc_type TEXT,
            category TEXT,
            vendor TEXT,
            client_name TEXT,
            date_detected TEXT,
            amount NUMERIC(15, 2),
            tax_year TEXT,
            cabin TEXT,
            business TEXT,
            confidence TEXT,
            raw_text TEXT,
            ai_json TEXT,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            phase INTEGER DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_gl_doc_type ON general_ledger(doc_type);
        CREATE INDEX IF NOT EXISTS idx_gl_category ON general_ledger(category);
        CREATE INDEX IF NOT EXISTS idx_gl_cabin ON general_ledger(cabin);
        CREATE INDEX IF NOT EXISTS idx_gl_tax_year ON general_ledger(tax_year);
        CREATE INDEX IF NOT EXISTS idx_gl_business ON general_ledger(business);
    """)
    pg.commit()

    # Count existing Postgres records
    pg_cur.execute("SELECT COUNT(*) FROM general_ledger")
    pg_count = pg_cur.fetchone()[0]
    print(f"   Postgres currently has {pg_count:,} records.")

    # Get all SQLite records
    lite_cur = lite.cursor()
    lite_cur.execute("SELECT COUNT(*) FROM general_ledger")
    lite_count = lite_cur.fetchone()[0]
    print(f"   SQLite has {lite_count:,} records.")

    # Upsert: insert new records, update existing ones
    lite_cur.execute("""
        SELECT filepath, filename, extension, file_size, doc_type, category,
               vendor, client_name, date_detected, amount, tax_year, cabin,
               business, confidence, raw_text, ai_json, processed_at, phase
        FROM general_ledger
    """)

    synced = 0
    updated = 0
    batch_size = 500

    def sanitize_row(row):
        """Strip NUL bytes that Postgres rejects from string fields."""
        cleaned = []
        for val in row:
            if isinstance(val, str):
                cleaned.append(val.replace('\x00', ''))
            else:
                cleaned.append(val)
        return tuple(cleaned)

    rows = lite_cur.fetchmany(batch_size)
    while rows:
        for row in rows:
            row = sanitize_row(row)
            pg_cur.execute("""
                INSERT INTO general_ledger
                    (filepath, filename, extension, file_size, doc_type, category,
                     vendor, client_name, date_detected, amount, tax_year, cabin,
                     business, confidence, raw_text, ai_json, processed_at, phase)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (filepath) DO UPDATE SET
                    doc_type = EXCLUDED.doc_type,
                    category = EXCLUDED.category,
                    vendor = EXCLUDED.vendor,
                    client_name = EXCLUDED.client_name,
                    amount = EXCLUDED.amount,
                    tax_year = EXCLUDED.tax_year,
                    confidence = EXCLUDED.confidence,
                    raw_text = EXCLUDED.raw_text,
                    ai_json = EXCLUDED.ai_json,
                    phase = EXCLUDED.phase
            """, row)
            synced += 1

        pg.commit()
        print(f"   Synced {synced:,} records...", flush=True)
        rows = lite_cur.fetchmany(batch_size)

    pg_cur.execute("SELECT COUNT(*) FROM general_ledger")
    final_count = pg_cur.fetchone()[0]

    print(f"\n   SYNC COMPLETE:")
    print(f"   Postgres now has {final_count:,} records in general_ledger.")
    print(f"   ({synced:,} records processed)")

    pg.close()
    lite.close()
    print(f"\n{'='*70}\n")


# ============================================================
# STATS & REPORTING
# ============================================================

def show_stats(conn):
    """Display comprehensive ledger statistics."""
    c = conn.cursor()

    print("\n" + "=" * 70)
    print("  FORTRESS LEDGER — FINANCIAL INTELLIGENCE REPORT")
    print("=" * 70)

    # Total records
    c.execute("SELECT COUNT(*), SUM(file_size) FROM general_ledger")
    total, total_size = c.fetchone()
    total_size = total_size or 0
    print(f"\n  Total Records: {total:,}  ({total_size/1e9:.2f} GB)")

    # By Document Type
    print(f"\n  {'DOCUMENT TYPE':<25} {'COUNT':>8} {'SIZE (MB)':>12}")
    print(f"  {'-'*47}")
    c.execute("""
        SELECT doc_type, COUNT(*), SUM(file_size)
        FROM general_ledger GROUP BY doc_type ORDER BY COUNT(*) DESC
    """)
    for dtype, count, size in c.fetchall():
        size = (size or 0) / 1e6
        print(f"  {dtype:<25} {count:>8,} {size:>12,.1f}")

    # By Category
    print(f"\n  {'CATEGORY':<25} {'COUNT':>8}")
    print(f"  {'-'*35}")
    c.execute("SELECT category, COUNT(*) FROM general_ledger GROUP BY category ORDER BY COUNT(*) DESC")
    for cat, count in c.fetchall():
        print(f"  {cat:<25} {count:>8,}")

    # By Cabin
    print(f"\n  {'CABIN PROPERTY':<25} {'INVOICES':>8}")
    print(f"  {'-'*35}")
    c.execute("""
        SELECT cabin, COUNT(*) FROM general_ledger
        WHERE cabin IS NOT NULL GROUP BY cabin ORDER BY COUNT(*) DESC LIMIT 20
    """)
    for cabin, count in c.fetchall():
        print(f"  {cabin:<25} {count:>8,}")

    # By Business
    print(f"\n  {'BUSINESS ENTITY':<25} {'RECORDS':>8}")
    print(f"  {'-'*35}")
    c.execute("""
        SELECT COALESCE(business, '(Unassigned)'), COUNT(*) FROM general_ledger
        GROUP BY business ORDER BY COUNT(*) DESC
    """)
    for biz, count in c.fetchall():
        print(f"  {biz:<25} {count:>8,}")

    # By Tax Year
    c.execute("""
        SELECT date_detected, COUNT(*) FROM general_ledger
        WHERE date_detected IS NOT NULL GROUP BY date_detected ORDER BY date_detected
    """)
    years = c.fetchall()
    if years:
        print(f"\n  {'TAX YEAR':<25} {'DOCUMENTS':>8}")
        print(f"  {'-'*35}")
        for yr, count in years:
            print(f"  {yr:<25} {count:>8,}")

    # Revenue estimate (from amounts)
    c.execute("SELECT SUM(amount), COUNT(amount) FROM general_ledger WHERE amount IS NOT NULL AND category = 'Rental_Income'")
    rev_total, rev_count = c.fetchone()
    if rev_total:
        print(f"\n  REVENUE DETECTED: ${rev_total:,.2f} across {rev_count:,} documents")

    # Phase breakdown
    c.execute("SELECT phase, COUNT(*) FROM general_ledger GROUP BY phase")
    phases = c.fetchall()
    print(f"\n  PROCESSING STATUS:")
    phase_labels = {1: "Path Intelligence", 2: "AI Deep Scan (R1)", 3: "Vision OCR (LLaVA)"}
    for phase, count in phases:
        label = phase_labels.get(phase, f"Phase {phase}")
        print(f"  Phase {phase} ({label}): {count:,} records")

    # Unknowns still pending AI scan
    c.execute("SELECT COUNT(*) FROM general_ledger WHERE doc_type = 'Unknown' AND extension = '.pdf'")
    pending_pdf = c.fetchone()[0]
    c.execute("""
        SELECT COUNT(*) FROM general_ledger
        WHERE extension IN ('.jpg', '.jpeg', '.png', '.tiff', '.tif')
        AND confidence != 'vision_ocr'
    """)
    pending_img = c.fetchone()[0]

    if pending_pdf:
        print(f"\n  ⚠️  {pending_pdf:,} PDFs still awaiting AI classification (run --phase2 or --vision)")
    if pending_img:
        print(f"  ⚠️  {pending_img:,} images awaiting Vision OCR (run --vision)")

    print(f"\n{'='*70}\n")


# ============================================================
# MAIN
# ============================================================

def main():
    print("💰 FORTRESS PRIME: DIVISION FINANCE — LEDGER INGESTION ENGINE")
    print(f"   Database: {DB_FILE}")
    print(f"   Source:   {FINANCIAL_ROOT}")
    print(f"   Vision:   {VISION_MODEL} @ {VISION_URL}")

    # Parse --limit (shared across phases)
    limit = 500
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        limit = int(sys.argv[idx + 1])

    # --- Postgres Sync (no SQLite needed) ---
    if "--sync" in sys.argv:
        sync_to_postgres()
        return

    conn = init_db()

    if "--stats" in sys.argv:
        show_stats(conn)
        conn.close()
        return

    if "--phase2" in sys.argv:
        run_phase2(conn, limit=limit)
        show_stats(conn)
        conn.close()
        return

    if "--vision" in sys.argv:
        run_phase_vision(conn, limit=limit)
        show_stats(conn)
        conn.close()
        return

    if "--phase1" in sys.argv:
        run_phase1(conn)
        show_stats(conn)
        conn.close()
        return

    # Default: run Phase 1 + stats
    unknowns = run_phase1(conn)
    show_stats(conn)

    if unknowns > 0:
        print(f"\n   {unknowns:,} files still unclassified.")
        print(f"   Next steps:")
        print(f"     --phase2             AI text extraction (DeepSeek-R1)")
        print(f"     --vision             Vision OCR for scanned docs (LLaVA)")
        print(f"     --sync               Push ledger to Postgres (fortress_db)")
        print(f"   Use --limit N to control batch size (default 500)")

    conn.close()


if __name__ == "__main__":
    main()
