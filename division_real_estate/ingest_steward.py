"""
Fortress Prime — DIVISION REAL ESTATE: "Steward" Ingestion Engine
==================================================================
Digitizing the dirt. Turning deeds, plats, and easements into a
sovereign property database.

THREE-PHASE APPROACH (same battle-tested pipeline as Ledger):
  Phase 1 (Path Intelligence):  Classifies documents by filepath patterns —
                                deeds, plats, surveys, easements, tax assessments.
  Phase 2 (AI Deep Scan):       Extracts text with pdfplumber, sends to DeepSeek-R1
                                for structured extraction (parcel IDs, book/page, dates).
  Phase 3 (Vision OCR):         Sends scanned deeds and images to LLaVA Vision for
                                Sovereign OCR — reads the ink the way a county clerk would.

Database: Postgres (fortress_db)
Tables:   properties, asset_docs, property_events

Usage:
    python division_real_estate/ingest_steward.py                # Full run (Phase 1)
    python division_real_estate/ingest_steward.py --phase1       # Path classification only
    python division_real_estate/ingest_steward.py --phase2       # AI text extraction
    python division_real_estate/ingest_steward.py --vision       # Vision OCR (Phase 3)
    python division_real_estate/ingest_steward.py --stats        # Show property stats
    python division_real_estate/ingest_steward.py --init         # Create tables only
"""
import os
import re
import sys
import json
import time
import base64
import logging
import requests
import psycopg2
from datetime import datetime

# Fortress Prompt System
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from prompts.loader import load_prompt

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)

# --- CONFIG ---
DIVISION_NAME = "Steward"

# NAS source directories (two property troves)
PROPERTY_ROOTS = [
    "/mnt/fortress_nas/Enterprise_War_Room/Property_Records",
    "/mnt/fortress_nas/Enterprise_War_Room/Properties",
]

LOG_FILE = os.path.join(os.path.dirname(__file__), "ingest_steward.log")

# AI Endpoints (Ollama)
R1_URL = "http://localhost:11434/api/generate"
R1_MODEL = "deepseek-r1:8b"

# Vision OCR (LLaVA — Sovereign OCR)
VISION_URL = "http://localhost:11434/api/generate"
VISION_MODEL = os.environ.get("VISION_MODEL", "llava:v1.6")

# Postgres (fortress_db)
PG_HOST = os.environ.get("DB_HOST", "localhost")
PG_DB = os.environ.get("DB_NAME", "fortress_db")
PG_USER = os.environ.get("DB_USER", "miner_bot")
PG_PASS = os.environ.get("DB_PASSWORD", os.environ.get("DB_PASS", ""))
PG_PORT = os.environ.get("DB_PORT", "5432")

# File extensions that are actual property documents
PROPERTY_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif",
    ".doc", ".docx", ".rtf", ".pages",
    ".dwg", ".dxf",  # AutoCAD drawings (plats, surveys)
    ".bmp", ".xlsx", ".xls", ".csv",
}

# Extensions to SKIP
SKIP_EXTENSIONS = {
    ".plist", ".nib", ".strings", ".bom", ".yaml", ".yml",
    ".ds_store", ".icloud", ".info", ".sizes", ".gif",
    ".pkg", ".dmg", ".app", ".dylib", ".so", ".framework",
    ".emlx", ".eml", ".mbox",
    ".md", ".html", ".htm", ".css", ".js",
    ".sqlite", ".db",
    ".cr2", ".dng", ".xmp",  # Raw photos
    ".gz", ".zip", ".tar",
    ".webtemplate", ".tmpl", ".xml",
    ".mp4", ".mov", ".avi", ".dv",  # Videos
    ".mp3", ".wav", ".aiff",  # Audio
}

# Path segments that indicate system/app data
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
    "/Video_Library/",
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


# ============================================================
# KNOWN PROPERTIES (from NAS path analysis)
# ============================================================

PROPERTIES = [
    # (search_pattern, canonical_name, county)
    ("buckhorn", "Buckhorn Lodge", "Fannin"),
    ("crooked creek", "Crooked Creek", "Fannin"),
    ("morningstar", "Morningstar Vista", "Fannin"),
    ("five peaks", "Five Peaks", "Fannin"),
    ("riverview", "Riverview Lodge", "Fannin"),
    ("rolling river", "Rolling River", "Fannin"),      # SOLD 2025-05-30
    ("majestic lake", "Majestic Lake", "Fannin"),
    ("majestic mountain", "Majestic Lake", "Fannin"),  # alias — same property
    ("solitude", "Solitude", "Fannin"),
    ("bella vista", "Bella Vista", "Fannin"),
    ("rivers edge", "Rivers Edge", "Fannin"),
    ("melancholy moose", "Melancholy Moose", "Fannin"),
    ("aska escape", "Aska Escape", "Fannin"),
    ("blue ridge", "Blue Ridge", "Fannin"),
    ("toccoa heights", "Toccoa Heights", "Fannin"),
    ("toccoa retreat", "Toccoa Retreat", "Fannin"),
    ("cadence ridge", "Cadence Ridge", "Fannin"),
    ("outlaw ridge", "Outlaw Ridge", "Fannin"),        # SOLD 2025-05-30
    ("200 amber", "200 Amber Ridge", "Fannin"),
    ("200_amber", "200 Amber Ridge", "Fannin"),
    ("amber ridge", "Amber Ridge", "Fannin"),
    ("cloud 10", "Cloud 10", "Fannin"),
    ("eagles nest", "Eagles Nest", "Fannin"),
    ("mountain laurel", "Mountain Laurel", "Fannin"),
    ("whispering pines", "Whispering Pines", "Fannin"),
    ("bear creek", "Bear Creek", "Fannin"),
    ("hidden creek", "Hidden Creek", "Fannin"),
    ("cherry log", "Cherry Log", "Gilmer"),
]


# Document type classification patterns (property-focused)
DOC_TYPE_PATTERNS = [
    # (regex_pattern, doc_type)
    (r'warranty[\.\s_-]*deed', 'Warranty_Deed'),
    (r'security[\.\s_-]*deed', 'Security_Deed'),
    (r'quitclaim[\.\s_-]*deed', 'Quitclaim_Deed'),
    (r'quit[\.\s_-]*claim', 'Quitclaim_Deed'),
    (r'deed(?!\s*of\s*trust)', 'Legal_Deed'),
    (r'deed[\.\s_-]*of[\.\s_-]*trust', 'Deed_of_Trust'),
    (r'plat(?:s)?(?:\b|[_\-\./])', 'Survey_Plat'),
    (r'survey', 'Survey'),
    (r'easement', 'Legal_Easement'),
    (r'right[\.\s_-]*of[\.\s_-]*way', 'Right_of_Way'),
    (r'lien[\.\s_-]*release', 'Lien_Release'),
    (r'lien', 'Lien'),
    (r'mortgage', 'Mortgage'),
    (r'title[\.\s_-]*search|title[\.\s_-]*report', 'Title_Report'),
    (r'title[\.\s_-]*insurance|title[\.\s_-]*policy', 'Title_Insurance'),
    (r'closing[\.\s_-]*statement|closing[\.\s_-]*disclosure|hud[\.\s_-]*1', 'Closing_Statement'),
    (r'tax[\.\s_-]*(?:assess|bill|notice|appraisal)', 'Tax_Assessment'),
    (r'tax[\.\s_-]*exempt', 'Tax_Exemption'),
    (r'covenant', 'Covenant'),
    (r'restriction', 'Restriction'),
    (r'hoa|homeowner', 'HOA_Document'),
    (r'meeting[\.\s_-]*minutes', 'Meeting_Minutes'),
    (r'site[\.\s_-]*plan', 'Site_Plan'),
    (r'railroad|crossing', 'Railroad_Document'),
    (r'permit', 'Permit'),
    (r'inspection', 'Inspection_Report'),
    (r'appraisal', 'Appraisal'),
    (r'insurance', 'Insurance'),
    (r'contract|agreement', 'Contract'),
    (r'invoice|receipt', 'Financial'),
    (r'letter|correspondence|ltr', 'Correspondence'),
]


# ============================================================
# DATABASE SCHEMA
# ============================================================

SCHEMA_SQL = """
-- 1. PROPERTIES (The Master Table — v1.1: Sovereign Asset Registry)
CREATE TABLE IF NOT EXISTS properties (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    ownership_status VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',  -- OWNED, MANAGED, UNKNOWN
    address VARCHAR(255),
    parcel_id VARCHAR(50),
    county VARCHAR(50) DEFAULT 'Fannin',
    acres NUMERIC(5,2),
    acquisition_date DATE,
    cost_basis NUMERIC(12,2),           -- Original purchase price
    current_value NUMERIC(12,2),        -- For Net Worth calculation
    depreciation_start DATE,            -- When depreciation clock started
    owner_contact_info JSONB,           -- For MANAGED cabins (owner emails/phones)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. ASSET_DOCS (The Document Repository)
CREATE TABLE IF NOT EXISTS asset_docs (
    id SERIAL PRIMARY KEY,
    property_id INTEGER REFERENCES properties(id),
    property_name TEXT,
    doc_type VARCHAR(50),
    file_path TEXT UNIQUE,
    filename TEXT,
    extension TEXT,
    file_size BIGINT,
    ocr_text TEXT,
    recording_date DATE,
    book_page VARCHAR(50),
    grantor TEXT,
    grantee TEXT,
    parcel_id VARCHAR(50),
    confidence TEXT,
    ai_json TEXT,
    phase INTEGER DEFAULT 1,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ad_property_id ON asset_docs(property_id);
CREATE INDEX IF NOT EXISTS idx_ad_doc_type ON asset_docs(doc_type);
CREATE INDEX IF NOT EXISTS idx_ad_property_name ON asset_docs(property_name);

-- 3. PROPERTY_EVENTS (Timeline)
CREATE TABLE IF NOT EXISTS property_events (
    id SERIAL PRIMARY KEY,
    property_id INTEGER REFERENCES properties(id),
    event_type VARCHAR(50),
    event_date DATE,
    status VARCHAR(20) DEFAULT 'PENDING',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pe_property_id ON property_events(property_id);
CREATE INDEX IF NOT EXISTS idx_pe_event_type ON property_events(event_type);
"""


def get_pg():
    """Connect to Postgres."""
    return psycopg2.connect(
        host=PG_HOST, database=PG_DB, user=PG_USER,
        password=PG_PASS, port=PG_PORT
    )


def init_schema():
    """Create Steward tables in Postgres."""
    print(f"\n[{DIVISION_NAME}] Initializing schema in fortress_db...")
    conn = get_pg()
    cur = conn.cursor()
    cur.execute(SCHEMA_SQL)
    conn.commit()
    print(f"[{DIVISION_NAME}] Tables created: properties, asset_docs, property_events")

    # Seed known properties
    for _, name, county in PROPERTIES:
        cur.execute("""
            INSERT INTO properties (name, county, ownership_status)
            VALUES (%s, %s, 'UNKNOWN')
            ON CONFLICT (name) DO NOTHING
        """, (name, county))
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM properties")
    count = cur.fetchone()[0]
    print(f"[{DIVISION_NAME}] {count} properties registered.")

    conn.close()
    return conn


# ============================================================
# PHASE 1: PATH INTELLIGENCE CLASSIFIER
# ============================================================

def detect_property(path_lower):
    """Detect which property a file relates to from its path."""
    for pattern, name, county in PROPERTIES:
        if pattern in path_lower:
            return name
    return None


def detect_date_from_path(filepath, filename):
    """Try to extract a date from the filepath or filename."""
    combined = filepath + "/" + filename
    # YYYY-MM-DD pattern
    full_date = re.search(r'(\d{4})-(\d{2})-(\d{2})', combined)
    if full_date:
        return full_date.group(0)
    # YYYY pattern
    year_match = re.search(r'(?:^|[\/_\-\.])(\d{4})(?:[\/_\-\.]|$)', combined)
    if year_match:
        year = int(year_match.group(1))
        if 1990 <= year <= 2030:
            return f"{year}-01-01"
    return None


def classify_by_path(filepath):
    """Phase 1: Classify a property document using its path and filename."""
    path_lower = filepath.lower()
    filename = os.path.basename(filepath)
    ext = os.path.splitext(filename)[1].lower()

    result = {
        "file_path": filepath,
        "filename": filename,
        "extension": ext,
        "doc_type": "Unknown",
        "property_name": None,
        "recording_date": None,
        "confidence": "path_match",
    }

    # Detect document type
    for pattern, doc_type in DOC_TYPE_PATTERNS:
        if re.search(pattern, path_lower):
            result["doc_type"] = doc_type
            break

    # Detect property
    result["property_name"] = detect_property(path_lower)

    # Detect date
    result["recording_date"] = detect_date_from_path(filepath, filename)

    return result


def run_phase1(conn):
    """Phase 1: Walk all property files and classify by path."""
    print("\n" + "=" * 70)
    print(f"  [{DIVISION_NAME}] PHASE 1: PATH INTELLIGENCE SCAN")
    print("  Classifying property documents by filepath patterns...")
    print("=" * 70 + "\n")

    cur = conn.cursor()
    processed = 0
    classified = 0
    unknown = 0
    skipped_ext = 0
    skipped_exists = 0

    for root_dir in PROPERTY_ROOTS:
        if not os.path.isdir(root_dir):
            print(f"   WARNING: {root_dir} not found, skipping.")
            continue
        print(f"   Scanning: {root_dir}")

        for root, dirs, files in os.walk(root_dir):
            for f in files:
                filepath = os.path.join(root, f)
                ext = os.path.splitext(f)[1].lower()

                # Skip hidden files
                if f.startswith('.'):
                    skipped_ext += 1
                    continue

                # Whitelist approach
                if ext and ext not in PROPERTY_EXTENSIONS:
                    skipped_ext += 1
                    continue

                if ext in SKIP_EXTENSIONS:
                    skipped_ext += 1
                    continue

                # Skip system paths
                if any(seg in filepath for seg in SKIP_PATH_SEGMENTS):
                    skipped_ext += 1
                    continue

                # Skip if already in DB
                cur.execute("SELECT id FROM asset_docs WHERE file_path = %s", (filepath,))
                if cur.fetchone():
                    skipped_exists += 1
                    continue

                # Classify
                result = classify_by_path(filepath)
                file_size = 0
                try:
                    file_size = os.path.getsize(filepath)
                except OSError:
                    pass

                # Look up property_id
                property_id = None
                if result["property_name"]:
                    cur.execute("SELECT id FROM properties WHERE name = %s",
                                (result["property_name"],))
                    row = cur.fetchone()
                    if row:
                        property_id = row[0]

                # Insert into asset_docs
                cur.execute("""
                    INSERT INTO asset_docs
                    (property_id, property_name, doc_type, file_path, filename,
                     extension, file_size, recording_date, confidence, phase)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                    ON CONFLICT (file_path) DO NOTHING
                """, (
                    property_id, result["property_name"], result["doc_type"],
                    result["file_path"], result["filename"], result["extension"],
                    file_size, result["recording_date"], result["confidence"]
                ))

                if result["doc_type"] != "Unknown":
                    classified += 1
                else:
                    unknown += 1

                processed += 1
                if processed % 2000 == 0:
                    conn.commit()
                    print(f"   Scanned {processed:,} files... "
                          f"({classified:,} classified, {unknown:,} unknown)")

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

def extract_pdf_text(filepath, max_pages=3):
    """Extract text from the first N pages of a PDF."""
    try:
        import pdfplumber
        text = ""
        with pdfplumber.open(filepath) as pdf:
            for i, page in enumerate(pdf.pages[:max_pages]):
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text[:4000]
    except Exception as e:
        logging.warning(f"PDF extraction failed: {filepath} — {e}")
        return None


def ai_classify_property(text, filename):
    """Send document text to DeepSeek-R1 for property document extraction."""
    tmpl = load_prompt("steward_classifier")
    prompt = tmpl.render(filename=filename, document_text=text[:3000])

    payload = {
        "model": R1_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 600}
    }

    try:
        res = requests.post(R1_URL, json=payload, timeout=120)
        if res.status_code == 200:
            response = res.json().get("response", "")
            if "<think>" in response:
                parts = response.split("</think>")
                response = parts[-1].strip() if len(parts) > 1 else response
            json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
    except json.JSONDecodeError:
        pass
    except Exception as e:
        logging.error(f"AI classify error: {e}")
    return None


def run_phase2(conn, limit=500):
    """Phase 2: AI-powered deep scan of unclassified property PDFs."""
    print("\n" + "=" * 70)
    print(f"  [{DIVISION_NAME}] PHASE 2: AI DEEP SCAN (DeepSeek-R1)")
    print(f"  Processing up to {limit} unclassified PDFs...")
    print("=" * 70 + "\n")

    cur = conn.cursor()
    cur.execute("""
        SELECT id, file_path, filename FROM asset_docs
        WHERE doc_type = 'Unknown' AND extension = '.pdf' AND phase = 1
        ORDER BY file_size DESC
        LIMIT %s
    """, (limit,))
    unknowns = cur.fetchall()

    if not unknowns:
        print("   No unclassified PDFs remaining. Phase 2 complete.")
        return

    print(f"   {len(unknowns)} PDFs queued for AI analysis.\n")
    extracted = 0

    for i, (row_id, filepath, filename) in enumerate(unknowns):
        print(f"   [{i+1}/{len(unknowns)}] {filename[:55]}...", end=" ", flush=True)

        text = extract_pdf_text(filepath)
        if not text or len(text.strip()) < 20:
            print("(no text)")
            cur.execute("UPDATE asset_docs SET phase = 2, ocr_text = '(no extractable text)' WHERE id = %s",
                        (row_id,))
            continue

        ai_result = ai_classify_property(text, filename)
        if ai_result:
            cur.execute("""
                UPDATE asset_docs SET
                    doc_type = COALESCE(%s, doc_type),
                    property_name = COALESCE(%s, property_name),
                    grantor = %s,
                    grantee = %s,
                    parcel_id = COALESCE(%s, parcel_id),
                    book_page = %s,
                    recording_date = COALESCE(%s::DATE, recording_date),
                    confidence = 'ai_extracted',
                    ocr_text = %s,
                    ai_json = %s,
                    phase = 2
                WHERE id = %s
            """, (
                ai_result.get("doc_type"),
                ai_result.get("property_name"),
                ai_result.get("grantor"),
                ai_result.get("grantee"),
                ai_result.get("parcel_id"),
                ai_result.get("book_page"),
                ai_result.get("recording_date"),
                text[:3000],
                json.dumps(ai_result),
                row_id
            ))
            extracted += 1
            dtype = ai_result.get("doc_type", "?")
            prop = ai_result.get("property_name", "")
            print(f"-> {dtype}" + (f" ({prop})" if prop else ""))
        else:
            cur.execute("UPDATE asset_docs SET phase = 2, ocr_text = %s WHERE id = %s",
                        (text[:3000], row_id))
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
    """Convert an image file to base64 for Vision API."""
    try:
        with open(filepath, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logging.warning(f"Failed to read image: {filepath} — {e}")
        return None


def pdf_page_to_base64(filepath, page_num=0, dpi=200):
    """Convert a PDF page to base64-encoded PNG for Vision API."""
    try:
        from pdf2image import convert_from_path
        import io
        images = convert_from_path(filepath, first_page=page_num + 1,
                                   last_page=page_num + 1, dpi=dpi)
        if images:
            buf = io.BytesIO()
            images[0].save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        logging.warning(f"PDF-to-image conversion failed: {filepath} — {e}")
    return None


def vision_classify_property(filepath, ext):
    """Send a property document image to LLaVA for OCR classification."""
    if ext in IMAGE_EXTENSIONS:
        img_b64 = image_to_base64(filepath)
    elif ext == ".pdf":
        img_b64 = pdf_page_to_base64(filepath)
    else:
        return None

    if not img_b64:
        return None

    tmpl = load_prompt("steward_vision_ocr")
    prompt = tmpl.render()

    payload = {
        "model": VISION_MODEL,
        "prompt": prompt,
        "images": [img_b64],
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 600}
    }

    try:
        res = requests.post(VISION_URL, json=payload, timeout=180)
        if res.status_code == 200:
            response = res.json().get("response", "")
            if "<think>" in response:
                parts = response.split("</think>")
                response = parts[-1].strip() if len(parts) > 1 else response
            json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
    except json.JSONDecodeError:
        pass
    except Exception as e:
        logging.error(f"Vision OCR error: {e}")
    return None


def run_phase_vision(conn, limit=500):
    """Phase 3: Vision OCR for scanned property documents."""
    print("\n" + "=" * 70)
    print(f"  [{DIVISION_NAME}] PHASE 3: VISION OCR (LLaVA — Sovereign OCR)")
    print(f"  Model: {VISION_MODEL}")
    print(f"  Processing up to {limit} documents...")
    print("=" * 70 + "\n")

    cur = conn.cursor()
    cur.execute("""
        SELECT id, file_path, filename, extension FROM asset_docs
        WHERE (
            (phase <= 2 AND (ocr_text IS NULL OR ocr_text = '(no extractable text)')
             AND extension = '.pdf')
            OR
            (phase <= 1 AND extension IN ('.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp'))
        )
        AND confidence != 'vision_ocr'
        ORDER BY file_size ASC
        LIMIT %s
    """, (limit,))
    targets = cur.fetchall()

    if not targets:
        print("   No documents remaining for Vision OCR. Phase 3 complete.")
        return

    print(f"   {len(targets)} documents queued for Vision OCR.\n")
    extracted = 0
    failed = 0

    for i, (row_id, filepath, filename, ext) in enumerate(targets):
        print(f"   [{i+1}/{len(targets)}] {filename[:55]}...", end=" ", flush=True)

        try:
            fsize = os.path.getsize(filepath)
            if fsize > 50 * 1024 * 1024:
                print("(>50MB, skipped)")
                continue
        except OSError:
            print("(file missing)")
            continue

        result = vision_classify_property(filepath, ext)
        if result:
            cur.execute("""
                UPDATE asset_docs SET
                    doc_type = COALESCE(%s, doc_type),
                    property_name = COALESCE(%s, property_name),
                    grantor = %s,
                    grantee = %s,
                    parcel_id = COALESCE(%s, parcel_id),
                    book_page = %s,
                    recording_date = COALESCE(%s::DATE, recording_date),
                    confidence = 'vision_ocr',
                    ai_json = %s,
                    phase = 3
                WHERE id = %s
            """, (
                result.get("doc_type"),
                result.get("property_name"),
                result.get("grantor"),
                result.get("grantee"),
                result.get("parcel_id"),
                result.get("book_page"),
                result.get("recording_date"),
                json.dumps(result),
                row_id
            ))
            extracted += 1
            dtype = result.get("doc_type", "?")
            prop = result.get("property_name", "")
            print(f"-> {dtype}" + (f" ({prop})" if prop else ""))
        else:
            failed += 1
            cur.execute("UPDATE asset_docs SET phase = 3 WHERE id = %s", (row_id,))
            print("(vision failed)")

        if (i + 1) % 25 == 0:
            conn.commit()
            print(f"\n   --- Checkpoint: {extracted} extracted, {failed} failed ---\n")

        time.sleep(0.5)

    conn.commit()
    print(f"\n   PHASE 3 COMPLETE: Vision OCR extracted data from "
          f"{extracted}/{len(targets)} documents.")
    if failed:
        print(f"   ({failed} documents could not be read by Vision)")


# ============================================================
# STATS & REPORTING
# ============================================================

def show_stats(conn):
    """Display comprehensive property asset statistics."""
    cur = conn.cursor()

    print("\n" + "=" * 70)
    print(f"  STEWARD — SOVEREIGN PROPERTY INTELLIGENCE REPORT")
    print("=" * 70)

    cur.execute("SELECT COUNT(*) FROM asset_docs")
    total = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(file_size), 0) FROM asset_docs")
    total_size = float(cur.fetchone()[0])
    print(f"\n  Total Documents: {total:,}  ({total_size / 1e9:.2f} GB)")

    # By Document Type
    print(f"\n  {'DOCUMENT TYPE':<25} {'COUNT':>8}")
    print(f"  {'-'*35}")
    cur.execute("""
        SELECT doc_type, COUNT(*) FROM asset_docs
        GROUP BY doc_type ORDER BY COUNT(*) DESC
    """)
    for dtype, count in cur.fetchall():
        print(f"  {dtype:<25} {count:>8,}")

    # By Property
    print(f"\n  {'PROPERTY':<30} {'DOCS':>8}")
    print(f"  {'-'*40}")
    cur.execute("""
        SELECT COALESCE(property_name, '(Unlinked)'), COUNT(*)
        FROM asset_docs
        GROUP BY property_name ORDER BY COUNT(*) DESC LIMIT 25
    """)
    for prop, count in cur.fetchall():
        print(f"  {prop:<30} {count:>8,}")

    # Properties with deeds
    cur.execute("""
        SELECT property_name, COUNT(*) FROM asset_docs
        WHERE doc_type LIKE '%Deed%' AND property_name IS NOT NULL
        GROUP BY property_name ORDER BY COUNT(*) DESC
    """)
    deeds = cur.fetchall()
    if deeds:
        print(f"\n  {'PROPERTY':<30} {'DEEDS':>8}")
        print(f"  {'-'*40}")
        for prop, count in deeds:
            print(f"  {prop:<30} {count:>8,}")

    # Phase breakdown
    cur.execute("SELECT phase, COUNT(*) FROM asset_docs GROUP BY phase ORDER BY phase")
    phases = cur.fetchall()
    phase_labels = {1: "Path Intelligence", 2: "AI Deep Scan (R1)", 3: "Vision OCR (LLaVA)"}
    print(f"\n  PROCESSING STATUS:")
    for phase, count in phases:
        label = phase_labels.get(phase, f"Phase {phase}")
        print(f"  Phase {phase} ({label}): {count:,} records")

    # Pending counts
    cur.execute("""
        SELECT COUNT(*) FROM asset_docs
        WHERE doc_type = 'Unknown' AND extension = '.pdf'
    """)
    pending_pdf = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM asset_docs
        WHERE extension IN ('.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp')
        AND confidence != 'vision_ocr'
    """)
    pending_img = cur.fetchone()[0]

    if pending_pdf:
        print(f"\n  WARNING: {pending_pdf:,} PDFs awaiting classification (--phase2 or --vision)")
    if pending_img:
        print(f"  WARNING: {pending_img:,} images awaiting Vision OCR (--vision)")

    # Registered properties
    cur.execute("SELECT COUNT(*) FROM properties")
    prop_count = cur.fetchone()[0]
    print(f"\n  Registered Properties: {prop_count}")

    print(f"\n{'='*70}\n")


# ============================================================
# MAIN
# ============================================================

def main():
    print(f"🏛️  FORTRESS PRIME: DIVISION REAL ESTATE — STEWARD INGESTION ENGINE")
    print(f"   Sources: {', '.join(PROPERTY_ROOTS)}")
    print(f"   Vision:  {VISION_MODEL} @ {VISION_URL}")

    limit = 500
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        limit = int(sys.argv[idx + 1])

    # --- Init Only ---
    if "--init" in sys.argv:
        init_schema()
        return

    # Initialize schema (idempotent)
    init_schema()

    conn = get_pg()

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

    # Default: Phase 1 + stats
    unknowns = run_phase1(conn)
    show_stats(conn)

    if unknowns > 0:
        print(f"\n   {unknowns:,} files still unclassified.")
        print(f"   Next steps:")
        print(f"     --phase2             AI text extraction (DeepSeek-R1)")
        print(f"     --vision             Vision OCR for scanned deeds (LLaVA)")
        print(f"   Use --limit N to control batch size (default 500)")

    conn.close()


if __name__ == "__main__":
    main()
