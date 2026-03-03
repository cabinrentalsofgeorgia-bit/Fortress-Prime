"""
Fortress Prime — DIVISION ENGINEERING: Blueprint Ingestion Engine
==================================================================
Digitizing the drawings. Turning blueprints, specs, and permits into
a sovereign engineering database.

THREE-PHASE APPROACH (battle-tested pipeline from Steward/Ledger):
  Phase 1 (Path Intelligence):  Classifies documents by filepath patterns —
                                floor plans, site plans, HVAC, permits, etc.
  Phase 2 (AI Deep Scan):       Extracts text with pdfplumber, sends to R1
                                for structured extraction (sheet #, discipline,
                                scale, revision, project details).
  Phase 3 (Vision OCR):         Sends scanned drawings to LLaVA for
                                Sovereign OCR — reads title blocks, notes,
                                dimensions the way an architect would.

Database: Postgres (fortress_db) — engineering schema
Tables:   engineering.drawings, engineering.projects, engineering.permits

Usage:
    python division_engineering/ingest_blueprints.py               # Full Phase 1
    python division_engineering/ingest_blueprints.py --phase1      # Path classification
    python division_engineering/ingest_blueprints.py --phase2      # AI text extraction
    python division_engineering/ingest_blueprints.py --vision      # Vision OCR (Phase 3)
    python division_engineering/ingest_blueprints.py --stats       # Show stats
    python division_engineering/ingest_blueprints.py --init        # Create tables only
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

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)

# --- CONFIG ---
DIVISION_NAME = "The Architect"

# NAS source directories for engineering documents
# Full-portfolio scan: all 93 property directories + engineering archives
_CROG_ROOT = "/mnt/fortress_nas/Business_Prime/CROG/Cabin Rentals Of Georgia"

ENGINEERING_ROOTS = [
    # ── Enterprise War Room ──────────────────────────────────
    "/mnt/fortress_nas/Enterprise_War_Room/Engineering",
    "/mnt/fortress_nas/Enterprise_War_Room/Construction",
    "/mnt/fortress_nas/Enterprise_War_Room/Blueprints",
    "/mnt/fortress_nas/Enterprise_War_Room/Permits",
    "/mnt/fortress_nas/Enterprise_War_Room/Property_Records",
    "/mnt/fortress_nas/Enterprise_War_Room/Properties",
    # ── Drawing Archives ─────────────────────────────────────
    f"{_CROG_ROOT}/Toccoa Heights Plats Master files",
    f"{_CROG_ROOT}/PLATS",
    f"{_CROG_ROOT}/cabin plans",
    f"{_CROG_ROOT}/Lots 9,22,23,24",
    # ── Property-Specific Folders (each cabin's full doc set) ─
    f"{_CROG_ROOT}/Above The Pines",
    f"{_CROG_ROOT}/Aska Adventure Lodge",
    f"{_CROG_ROOT}/Aska Adventure Outpost",
    f"{_CROG_ROOT}/Bears Den",
    f"{_CROG_ROOT}/Bella Vista Lodge",
    f"{_CROG_ROOT}/Buckhorn Lodge",
    f"{_CROG_ROOT}/Cadence Ridge",
    f"{_CROG_ROOT}/Casa Bella",
    f"{_CROG_ROOT}/Crooked Creek Cabin",
    f"{_CROG_ROOT}/Deja View",
    f"{_CROG_ROOT}/Fallen Timber",
    f"{_CROG_ROOT}/Five Peaks Cabin",
    f"{_CROG_ROOT}/Majestic Lake",
    f"{_CROG_ROOT}/Majestic Mountain Lodge",
    f"{_CROG_ROOT}/Melancholy moose Lodge",
    f"{_CROG_ROOT}/Morningstar Vista",
    f"{_CROG_ROOT}/Noontootla Creek Property",
    f"{_CROG_ROOT}/Outlaw Ridge",
    f"{_CROG_ROOT}/Paradise Found",
    f"{_CROG_ROOT}/RiverView Lodge",
    f"{_CROG_ROOT}/Rivers Edge",
    f"{_CROG_ROOT}/Rolling River Cabin",
    f"{_CROG_ROOT}/Royal Mountain Lodge",
    f"{_CROG_ROOT}/Sanctuary",
    f"{_CROG_ROOT}/Serendipity on Noontootla",
    f"{_CROG_ROOT}/Solitude",
    f"{_CROG_ROOT}/Toccoa Heights Cabin",
    f"{_CROG_ROOT}/Echoes By The Lake",
    f"{_CROG_ROOT}/Escape The Rat Race Getaway",
    # ── Business / Legal / Corporate ─────────────────────────
    f"{_CROG_ROOT}/146 Depot Street",
    f"{_CROG_ROOT}/Appraisals",
    f"{_CROG_ROOT}/Cabin Partnership",
    f"{_CROG_ROOT}/Corporate Documents",
    f"{_CROG_ROOT}/Henderson Matter",
    f"{_CROG_ROOT}/Orr Matter",
    f"{_CROG_ROOT}/Theft of Services",
    f"{_CROG_ROOT}/Management contracts for cabin rental",
    # ── Operations / Finance ─────────────────────────────────
    f"{_CROG_ROOT}/cabin management",
    f"{_CROG_ROOT}/construction spreadsheet",
    f"{_CROG_ROOT}/Cleaning",
    f"{_CROG_ROOT}/Housekeeping Procedures",
    f"{_CROG_ROOT}/Credit Card Disputes",
    f"{_CROG_ROOT}/Disputes",
]

LOG_FILE = os.path.join(os.path.dirname(__file__), "ingest_blueprints.log")

# AI Endpoints (Ollama)
R1_URL = "http://localhost:11434/api/generate"
R1_MODEL = "deepseek-r1:8b"

# Vision OCR (LLaVA)
from config import SPARK_02_IP
VISION_URL = os.environ.get(
    "VISION_URL",
    f"http://{SPARK_02_IP}:11434/api/generate"  # Muscle node (Spark 1)
)
VISION_MODEL = os.environ.get("VISION_MODEL", "llama3.2-vision:90b")

# Postgres
PG_HOST = os.environ.get("DB_HOST", "localhost")
PG_DB = os.environ.get("DB_NAME", "fortress_db")
PG_USER = os.environ.get("DB_USER", "miner_bot")
PG_PASS = os.environ.get("DB_PASSWORD", os.environ.get("DB_PASS", ""))
PG_PORT = os.environ.get("DB_PORT", "5432")

# File extensions for engineering documents
ENGINEERING_EXTENSIONS = {
    ".pdf", ".dwg", ".dxf", ".dgn",            # CAD / drawings
    ".jpg", ".jpeg", ".png", ".tiff", ".tif",   # Scanned plans
    ".doc", ".docx", ".xlsx", ".xls",           # Specs & reports
    ".rvt", ".ifc",                             # BIM
    ".rtf", ".csv",
}

# Extensions to SKIP
SKIP_EXTENSIONS = {
    ".plist", ".nib", ".strings", ".bom", ".yaml", ".yml",
    ".ds_store", ".icloud", ".info", ".sizes", ".gif",
    ".pkg", ".dmg", ".app", ".dylib", ".so", ".framework",
    ".emlx", ".eml", ".mbox",
    ".md", ".html", ".htm", ".css", ".js",
    ".sqlite", ".db",
    ".cr2", ".dng", ".xmp",
    ".gz", ".zip", ".tar",
    ".mp4", ".mov", ".avi", ".mp3", ".wav",
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
    "/.Trash/",
    "/node_modules/",
    "/site-packages/",
    "/Photos Library/",
    "/Lightroom Library/",
    "/Video_Library/",
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


# ============================================================
# KNOWN PROPERTIES (inherited from Division Real Estate)
# ============================================================

PROPERTIES = [
    ("buckhorn", "Buckhorn Lodge", "Fannin"),
    ("crooked creek", "Crooked Creek", "Fannin"),
    ("morningstar", "Morningstar Vista", "Fannin"),
    ("five peaks", "Five Peaks", "Fannin"),
    ("riverview", "Riverview Lodge", "Fannin"),
    ("rolling river", "Rolling River", "Fannin"),
    ("majestic lake", "Majestic Lake", "Fannin"),
    ("majestic mountain", "Majestic Lake", "Fannin"),
    ("solitude", "Solitude", "Fannin"),
    ("bella vista", "Bella Vista", "Fannin"),
    ("rivers edge", "Rivers Edge", "Fannin"),
    ("melancholy moose", "Melancholy Moose", "Fannin"),
    ("aska escape", "Aska Escape", "Fannin"),
    ("blue ridge", "Blue Ridge", "Fannin"),
    ("toccoa heights", "Toccoa Heights", "Fannin"),
    ("toccoa retreat", "Toccoa Retreat", "Fannin"),
    ("cadence ridge", "Cadence Ridge", "Fannin"),
    ("outlaw ridge", "Outlaw Ridge", "Fannin"),
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


# ============================================================
# DOCUMENT CLASSIFICATION PATTERNS (Engineering-Focused)
# ============================================================

DOC_TYPE_PATTERNS = [
    # Architectural
    (r'floor[\.\s_-]*plan', 'Floor_Plan', 'architectural'),
    (r'elevation', 'Elevation', 'architectural'),
    (r'section[\.\s_-]*(?:cut|detail|view)', 'Section', 'architectural'),
    (r'reflected[\.\s_-]*ceiling', 'Reflected_Ceiling_Plan', 'architectural'),
    (r'finish[\.\s_-]*schedule', 'Finish_Schedule', 'architectural'),
    (r'door[\.\s_-]*schedule', 'Door_Schedule', 'architectural'),
    (r'window[\.\s_-]*schedule', 'Window_Schedule', 'architectural'),
    (r'interior[\.\s_-]*elevation', 'Interior_Elevation', 'architectural'),
    (r'ada[\.\s_-]*(?:plan|compliance)', 'ADA_Compliance_Plan', 'architectural'),
    (r'renovation[\.\s_-]*plan', 'Renovation_Plan', 'architectural'),
    (r'as[\.\s_-]*built', 'As_Built', 'architectural'),
    (r'spec(?:ification)?[\.\s_-]*book', 'Specification_Book', 'architectural'),
    (r'(?:blueprint|arch[\.\s_-]*plan)', 'Floor_Plan', 'architectural'),

    # Civil
    (r'site[\.\s_-]*plan', 'Site_Plan', 'civil'),
    (r'grading[\.\s_-]*plan', 'Grading_Plan', 'civil'),
    (r'drainage[\.\s_-]*plan', 'Drainage_Plan', 'civil'),
    (r'utility[\.\s_-]*plan', 'Utility_Plan', 'civil'),
    (r'septic[\.\s_-]*(?:plan|design|layout)', 'Septic_Plan', 'civil'),
    (r'erosion[\.\s_-]*control', 'Erosion_Control_Plan', 'civil'),
    (r'storm[\.\s_-]*water', 'Stormwater_Plan', 'civil'),
    (r'topo(?:graphic)?[\.\s_-]*survey', 'Topographic_Survey', 'civil'),
    (r'boundary[\.\s_-]*survey', 'Boundary_Survey', 'civil'),
    (r'soil[\.\s_-]*(?:report|test|boring)', 'Soil_Report', 'civil'),
    (r'perc(?:olation)?[\.\s_-]*test', 'Percolation_Test', 'civil'),
    (r'wetland', 'Wetland_Delineation', 'civil'),
    (r'plat(?:s)?(?:\b|[_\-\./])', 'Topographic_Survey', 'civil'),
    (r'survey', 'Boundary_Survey', 'civil'),

    # Structural
    (r'foundation[\.\s_-]*plan', 'Foundation_Plan', 'structural'),
    (r'framing[\.\s_-]*plan', 'Framing_Plan', 'structural'),
    (r'structural[\.\s_-]*calc', 'Structural_Calculations', 'structural'),
    (r'load[\.\s_-]*(?:diagram|calc)', 'Load_Diagram', 'structural'),

    # Mechanical / MEP
    (r'hvac[\.\s_-]*(?:plan|layout|design)', 'HVAC_Plan', 'mechanical'),
    (r'hvac[\.\s_-]*(?:load|calc)', 'HVAC_Load_Calculation', 'mechanical'),
    (r'mechanical[\.\s_-]*plan', 'HVAC_Plan', 'mechanical'),
    (r'plumbing[\.\s_-]*plan', 'Plumbing_Plan', 'plumbing'),
    (r'electrical[\.\s_-]*plan', 'Electrical_Plan', 'electrical'),
    (r'panel[\.\s_-]*schedule', 'Panel_Schedule', 'electrical'),
    (r'fire[\.\s_-]*(?:protection|sprinkler)', 'Fire_Protection_Plan', 'fire_protection'),
    (r'hot[\.\s_-]*tub', 'Hot_Tub_Specification', 'mechanical'),
    (r'generator', 'Generator_Specification', 'electrical'),
    (r'energy[\.\s_-]*(?:calc|code|audit)', 'Energy_Calculation', 'mechanical'),

    # Permits & Inspections
    (r'building[\.\s_-]*permit', 'Building_Permit', 'general'),
    (r'mechanical[\.\s_-]*permit', 'Mechanical_Permit', 'mechanical'),
    (r'electrical[\.\s_-]*permit', 'Electrical_Permit', 'electrical'),
    (r'plumbing[\.\s_-]*permit', 'Plumbing_Permit', 'plumbing'),
    (r'septic[\.\s_-]*permit', 'Septic_Permit', 'civil'),
    (r'grading[\.\s_-]*permit', 'Grading_Permit', 'civil'),
    (r'inspection[\.\s_-]*(?:report|result)', 'Inspection_Report', 'general'),
    (r'certificate[\.\s_-]*of[\.\s_-]*occupancy', 'Certificate_of_Occupancy', 'general'),
    (r'variance[\.\s_-]*(?:request|application)', 'Variance_Request', 'general'),
    (r'(?:co\b|c[\.\s_-]*o[\.\s_-]*f[\.\s_-]*o)', 'Certificate_of_Occupancy', 'general'),

    # Project Management
    (r'cost[\.\s_-]*estimate', 'Cost_Estimate', 'general'),
    (r'change[\.\s_-]*order', 'Change_Order', 'general'),
    (r'rfi\b', 'Request_for_Information', 'general'),
    (r'submittal', 'Submittal', 'general'),
    (r'shop[\.\s_-]*drawing', 'Shop_Drawing', 'general'),
    (r'punch[\.\s_-]*list', 'Punch_List', 'general'),
    (r'warranty', 'Warranty', 'general'),

    # General engineering
    (r'engineering[\.\s_-]*report', 'Engineering_Report', 'general'),
    (r'permit', 'Building_Permit', 'general'),
    (r'inspection', 'Inspection_Report', 'general'),
]

# Sheet number prefix → discipline mapping (standard AIA convention)
SHEET_PREFIX_DISCIPLINE = {
    "G": "general",
    "C": "civil",
    "L": "landscape",
    "S": "structural",
    "A": "architectural",
    "I": "interior",
    "M": "mechanical",
    "P": "plumbing",
    "FP": "fire_protection",
    "E": "electrical",
    "T": "telecom",
}


def get_pg():
    """Connect to Postgres."""
    return psycopg2.connect(
        host=PG_HOST, database=PG_DB, user=PG_USER,
        password=PG_PASS, port=PG_PORT
    )


# ============================================================
# PHASE 1: PATH INTELLIGENCE CLASSIFIER
# ============================================================

def detect_property(path_lower):
    """Detect which property a file relates to from its path."""
    for pattern, name, county in PROPERTIES:
        if pattern in path_lower:
            return name
    return None


def detect_sheet_number(filename):
    """
    Extract sheet number from filename using AIA convention.
    e.g., "A-101 Floor Plan.pdf" → "A-101"
          "C201_Site_Plan.dwg"  → "C-201"
          "M-301.pdf"           → "M-301"
    """
    # Pattern: letter(s) followed by dash/underscore and digits
    match = re.search(r'([A-Z]{1,2})[\-_]?(\d{2,4})', filename.upper())
    if match:
        prefix = match.group(1)
        number = match.group(2)
        return f"{prefix}-{number}"
    return None


def detect_discipline_from_sheet(sheet_number):
    """Determine discipline from AIA sheet number prefix."""
    if not sheet_number:
        return None
    prefix = sheet_number.split("-")[0].upper()
    return SHEET_PREFIX_DISCIPLINE.get(prefix)


def detect_date_from_path(filepath, filename):
    """Try to extract a date from the filepath or filename."""
    combined = filepath + "/" + filename
    full_date = re.search(r'(\d{4})-(\d{2})-(\d{2})', combined)
    if full_date:
        return full_date.group(0)
    year_match = re.search(r'(?:^|[\/_\-\.])(\d{4})(?:[\/_\-\.]|$)', combined)
    if year_match:
        year = int(year_match.group(1))
        if 1990 <= year <= 2030:
            return f"{year}-01-01"
    return None


def classify_by_path(filepath):
    """Phase 1: Classify an engineering document using its path and filename."""
    path_lower = filepath.lower()
    filename = os.path.basename(filepath)
    ext = os.path.splitext(filename)[1].lower()

    result = {
        "file_path": filepath,
        "filename": filename,
        "extension": ext,
        "doc_type": "Unknown",
        "discipline": "general",
        "property_name": None,
        "sheet_number": None,
        "confidence": "path_match",
    }

    # Detect sheet number (AIA convention)
    sheet = detect_sheet_number(filename)
    if sheet:
        result["sheet_number"] = sheet
        disc = detect_discipline_from_sheet(sheet)
        if disc:
            result["discipline"] = disc

    # Detect document type
    for pattern, doc_type, discipline in DOC_TYPE_PATTERNS:
        if re.search(pattern, path_lower):
            result["doc_type"] = doc_type
            result["discipline"] = discipline
            break

    # AutoCAD files are always engineering drawings
    if ext in (".dwg", ".dxf", ".dgn"):
        if result["doc_type"] == "Unknown":
            result["doc_type"] = "CAD_Drawing"
        result["confidence"] = "extension_match"

    # BIM files
    if ext in (".rvt", ".ifc"):
        if result["doc_type"] == "Unknown":
            result["doc_type"] = "BIM_Model"
        result["confidence"] = "extension_match"

    # Detect property
    result["property_name"] = detect_property(path_lower)

    # Detect date
    result["recording_date"] = detect_date_from_path(filepath, filename)

    return result


def run_phase1(conn):
    """Phase 1: Walk all engineering files and classify by path."""
    print("\n" + "=" * 70)
    print(f"  [{DIVISION_NAME}] PHASE 1: PATH INTELLIGENCE SCAN")
    print("  Classifying engineering documents by filepath patterns...")
    print("=" * 70 + "\n")

    cur = conn.cursor()
    processed = 0
    classified = 0
    unknown = 0
    skipped_ext = 0
    skipped_exists = 0

    for root_dir in ENGINEERING_ROOTS:
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
                if ext and ext not in ENGINEERING_EXTENSIONS:
                    skipped_ext += 1
                    continue

                if ext in SKIP_EXTENSIONS:
                    skipped_ext += 1
                    continue

                # Skip system paths
                if any(seg in filepath for seg in SKIP_PATH_SEGMENTS):
                    skipped_ext += 1
                    continue

                # Skip if already in engineering.drawings
                cur.execute(
                    "SELECT id FROM engineering.drawings WHERE file_path = %s",
                    (filepath,),
                )
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
                    cur.execute(
                        "SELECT id FROM properties WHERE name = %s",
                        (result["property_name"],),
                    )
                    row = cur.fetchone()
                    if row:
                        property_id = row[0]

                # Insert into engineering.drawings
                cur.execute("""
                    INSERT INTO engineering.drawings
                    (property_id, discipline, doc_type, file_path, filename,
                     extension, file_size, sheet_number, confidence, phase)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                    ON CONFLICT (file_path) DO NOTHING
                """, (
                    property_id, result["discipline"], result["doc_type"],
                    result["file_path"], result["filename"], result["extension"],
                    file_size, result["sheet_number"], result["confidence"],
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


def ai_classify_engineering(text, filename):
    """Send document text to DeepSeek-R1 for engineering document extraction."""
    prompt = f"""Analyze this engineering/construction document and extract structured data.

Filename: {filename}

Document text (first pages):
---
{text[:3000]}
---

Extract the following as JSON:
{{
    "doc_type": "the specific document type (Floor_Plan, Site_Plan, HVAC_Plan, Building_Permit, etc.)",
    "discipline": "architectural|civil|structural|mechanical|electrical|plumbing|fire_protection|general",
    "sheet_number": "AIA sheet number if visible (e.g., A-101, C-201, M-301) or null",
    "title": "drawing/document title if visible or null",
    "revision": "revision number/letter if visible or null",
    "scale": "drawing scale if visible (e.g., 1/4\\\" = 1'-0\\\") or null",
    "property_name": "property name if identifiable or null",
    "project_name": "project name if visible or null",
    "architect": "architect/engineer of record if visible or null",
    "permit_number": "permit number if this is a permit document or null",
    "date": "document date in YYYY-MM-DD format if visible or null"
}}

Respond with ONLY the JSON object."""

    payload = {
        "model": R1_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 800}
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


def run_phase_cad(conn, limit=500):
    """Phase 1.5: Direct CAD file parsing via read_drawing for DWG/DXF files."""
    print("\n" + "=" * 70)
    print(f"  [{DIVISION_NAME}] PHASE 1.5: CAD DRAWING INTELLIGENCE")
    print(f"  Parsing DWG/DXF files with ezdxf for structured extraction...")
    print("=" * 70 + "\n")

    from division_engineering.read_drawing import read_drawing

    cur = conn.cursor()
    cur.execute("""
        SELECT id, file_path, filename, extension FROM engineering.drawings
        WHERE extension IN ('.dwg', '.dxf')
          AND confidence NOT IN ('cad_parsed', 'ai_extracted', 'vision_ocr')
          AND phase <= 1
        ORDER BY file_size DESC
        LIMIT %s
    """, (limit,))
    targets = cur.fetchall()

    if not targets:
        print("   No unprocessed CAD files. Phase 1.5 complete.")
        return

    print(f"   {len(targets)} CAD files queued for ezdxf parsing.\n")
    extracted = 0
    failed = 0

    for i, (row_id, filepath, filename, ext) in enumerate(targets):
        print(f"   [{i+1}/{len(targets)}] {filename[:55]}...", end=" ", flush=True)

        try:
            result = read_drawing(filepath)
        except Exception as e:
            print(f"(error: {e})")
            failed += 1
            continue

        if not result.get("readable", False):
            if result.get("needs_vision_ocr"):
                print("(DWG-only → queued for Vision OCR)")
                cur.execute(
                    "UPDATE engineering.drawings SET phase = 2, "
                    "confidence = 'needs_vision_ocr' WHERE id = %s",
                    (row_id,),
                )
            else:
                print(f"(unreadable: {result.get('error', '?')})")
                failed += 1
            continue

        # Extract classification and title block
        cls = result.get("classification", {})
        tb = result.get("title_block", {})
        survey = result.get("survey_calls", [])

        # Build AI JSON with full drawing intelligence
        ai_data = {
            "cad_reader": True,
            "layers": [l["name"] for l in result.get("layers", [])],
            "layer_count": result.get("layer_count", 0),
            "entity_types": result.get("entity_types", {}),
            "total_entities": result.get("total_entities", 0),
            "text_count": result.get("text_count", 0),
            "meaningful_text_count": result.get("meaningful_text_count", 0),
            "title_block": tb,
            "survey_call_count": len(survey),
            "dxf_version": result.get("dxf_version"),
        }
        if result.get("source_dwg"):
            ai_data["source_dwg"] = result["source_dwg"]

        # Compose meaningful text for OCR column
        ocr_text_parts = result.get("meaningful_text", [])[:100]
        ocr_text = "\n".join(ocr_text_parts) if ocr_text_parts else None

        cur.execute("""
            UPDATE engineering.drawings SET
                doc_type   = COALESCE(%s, doc_type),
                discipline = COALESCE(%s, discipline),
                title      = COALESCE(%s, title),
                scale      = %s,
                confidence = 'cad_parsed',
                ocr_text   = COALESCE(%s, ocr_text),
                ai_json    = %s,
                phase      = 2
            WHERE id = %s
        """, (
            cls.get("doc_type") if cls.get("doc_type") != "Unknown" else None,
            cls.get("discipline") if cls.get("discipline") != "general" else None,
            tb.get("project") or tb.get("owner"),
            tb.get("scale"),
            ocr_text,
            json.dumps(ai_data),
            row_id,
        ))
        extracted += 1
        dtype = cls.get("doc_type", "?")
        disc = cls.get("discipline", "")
        ents = result.get("total_entities", 0)
        print(f"-> {dtype} ({disc}) [{ents} entities]")

        if (i + 1) % 50 == 0:
            conn.commit()
            print(f"\n   --- Checkpoint: {extracted} parsed ---\n")

    conn.commit()
    print(f"\n   PHASE 1.5 COMPLETE: Parsed {extracted}/{len(targets)} CAD files.")
    if failed:
        print(f"   ({failed} files could not be read)")


def run_phase2(conn, limit=500):
    """Phase 2: AI-powered deep scan of unclassified engineering PDFs."""
    print("\n" + "=" * 70)
    print(f"  [{DIVISION_NAME}] PHASE 2: AI DEEP SCAN (DeepSeek-R1)")
    print(f"  Processing up to {limit} unclassified engineering PDFs...")
    print("=" * 70 + "\n")

    cur = conn.cursor()
    cur.execute("""
        SELECT id, file_path, filename FROM engineering.drawings
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
            cur.execute(
                "UPDATE engineering.drawings SET phase = 2, "
                "ocr_text = '(no extractable text)' WHERE id = %s",
                (row_id,),
            )
            continue

        ai_result = ai_classify_engineering(text, filename)
        if ai_result:
            cur.execute("""
                UPDATE engineering.drawings SET
                    doc_type = COALESCE(%s, doc_type),
                    discipline = COALESCE(%s, discipline),
                    sheet_number = COALESCE(%s, sheet_number),
                    title = %s,
                    revision = %s,
                    scale = %s,
                    confidence = 'ai_extracted',
                    ocr_text = %s,
                    ai_json = %s,
                    phase = 2
                WHERE id = %s
            """, (
                ai_result.get("doc_type"),
                ai_result.get("discipline"),
                ai_result.get("sheet_number"),
                ai_result.get("title"),
                ai_result.get("revision"),
                ai_result.get("scale"),
                text[:3000],
                json.dumps(ai_result),
                row_id,
            ))
            extracted += 1
            dtype = ai_result.get("doc_type", "?")
            disc = ai_result.get("discipline", "")
            print(f"-> {dtype} ({disc})")
        else:
            cur.execute(
                "UPDATE engineering.drawings SET phase = 2, ocr_text = %s WHERE id = %s",
                (text[:3000], row_id),
            )
            print("(AI extraction failed)")

        if (i + 1) % 25 == 0:
            conn.commit()
            print(f"\n   --- Checkpoint: {extracted} extracted so far ---\n")

    conn.commit()
    print(f"\n   PHASE 2 COMPLETE: AI extracted data from "
          f"{extracted}/{len(unknowns)} documents.")


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
        images = convert_from_path(
            filepath, first_page=page_num + 1,
            last_page=page_num + 1, dpi=dpi,
        )
        if images:
            buf = io.BytesIO()
            images[0].save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        logging.warning(f"PDF-to-image conversion failed: {filepath} — {e}")
    return None


def vision_classify_engineering(filepath, ext):
    """Send an engineering drawing/document to LLaVA for Vision OCR."""
    if ext in IMAGE_EXTENSIONS:
        img_b64 = image_to_base64(filepath)
    elif ext == ".pdf":
        img_b64 = pdf_page_to_base64(filepath)
    else:
        return None

    if not img_b64:
        return None

    prompt = """You are an expert architectural & engineering document reader.
Analyze this drawing or document image and extract structured information.

Look for:
1. Title block information (project name, sheet number, scale, date, architect/engineer)
2. Document type (floor plan, site plan, elevation, HVAC plan, electrical plan, etc.)
3. Engineering discipline (architectural, civil, structural, mechanical, electrical, plumbing)
4. Key dimensions, notes, or specifications visible
5. Permit numbers, inspection stamps, or approval marks

Respond with ONLY a JSON object:
{
    "doc_type": "specific document type",
    "discipline": "engineering discipline",
    "sheet_number": "AIA sheet number or null",
    "title": "drawing title or null",
    "revision": "revision or null",
    "scale": "drawing scale or null",
    "project_name": "project name or null",
    "architect": "architect/engineer name or null",
    "permit_number": "permit number or null",
    "date": "YYYY-MM-DD or null",
    "key_notes": "brief summary of visible notes/specs or null"
}"""

    payload = {
        "model": VISION_MODEL,
        "prompt": prompt,
        "images": [img_b64],
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 800}
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
    """Phase 3: Vision OCR for scanned engineering documents."""
    print("\n" + "=" * 70)
    print(f"  [{DIVISION_NAME}] PHASE 3: VISION OCR (LLaVA — Sovereign OCR)")
    print(f"  Model: {VISION_MODEL}")
    print(f"  Processing up to {limit} documents...")
    print("=" * 70 + "\n")

    cur = conn.cursor()
    cur.execute("""
        SELECT id, file_path, filename, extension FROM engineering.drawings
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

        result = vision_classify_engineering(filepath, ext)
        if result:
            cur.execute("""
                UPDATE engineering.drawings SET
                    doc_type = COALESCE(%s, doc_type),
                    discipline = COALESCE(%s, discipline),
                    sheet_number = COALESCE(%s, sheet_number),
                    title = COALESCE(%s, title),
                    revision = COALESCE(%s, revision),
                    scale = COALESCE(%s, scale),
                    confidence = 'vision_ocr',
                    ai_json = %s,
                    phase = 3
                WHERE id = %s
            """, (
                result.get("doc_type"),
                result.get("discipline"),
                result.get("sheet_number"),
                result.get("title"),
                result.get("revision"),
                result.get("scale"),
                json.dumps(result),
                row_id,
            ))
            extracted += 1
            dtype = result.get("doc_type", "?")
            disc = result.get("discipline", "")
            print(f"-> {dtype} ({disc})")
        else:
            failed += 1
            cur.execute(
                "UPDATE engineering.drawings SET phase = 3 WHERE id = %s",
                (row_id,),
            )
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
    """Display comprehensive engineering document statistics."""
    cur = conn.cursor()

    print("\n" + "=" * 70)
    print(f"  THE ARCHITECT — ENGINEERING INTELLIGENCE REPORT")
    print("=" * 70)

    cur.execute("SELECT COUNT(*) FROM engineering.drawings")
    total = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(file_size), 0) FROM engineering.drawings")
    total_size = float(cur.fetchone()[0])
    print(f"\n  Total Documents: {total:,}  ({total_size / 1e9:.2f} GB)")

    # By Discipline
    print(f"\n  {'DISCIPLINE':<25} {'COUNT':>8}")
    print(f"  {'-'*35}")
    cur.execute("""
        SELECT discipline, COUNT(*) FROM engineering.drawings
        GROUP BY discipline ORDER BY COUNT(*) DESC
    """)
    for disc, count in cur.fetchall():
        print(f"  {disc:<25} {count:>8,}")

    # By Document Type
    print(f"\n  {'DOCUMENT TYPE':<30} {'COUNT':>8}")
    print(f"  {'-'*40}")
    cur.execute("""
        SELECT doc_type, COUNT(*) FROM engineering.drawings
        GROUP BY doc_type ORDER BY COUNT(*) DESC LIMIT 25
    """)
    for dtype, count in cur.fetchall():
        print(f"  {dtype:<30} {count:>8,}")

    # By Property
    print(f"\n  {'PROPERTY':<30} {'DOCS':>8}")
    print(f"  {'-'*40}")
    cur.execute("""
        SELECT COALESCE(p.name, '(Unlinked)'), COUNT(*)
        FROM engineering.drawings d
        LEFT JOIN properties p ON d.property_id = p.id
        GROUP BY p.name ORDER BY COUNT(*) DESC LIMIT 25
    """)
    for prop, count in cur.fetchall():
        print(f"  {prop:<30} {count:>8,}")

    # Phase breakdown
    cur.execute(
        "SELECT phase, COUNT(*) FROM engineering.drawings "
        "GROUP BY phase ORDER BY phase"
    )
    phases = cur.fetchall()
    phase_labels = {
        1: "Path Intelligence",
        2: "AI Deep Scan (R1)",
        3: "Vision OCR (LLaVA)",
    }
    print(f"\n  PROCESSING STATUS:")
    for phase, count in phases:
        label = phase_labels.get(phase, f"Phase {phase}")
        print(f"  Phase {phase} ({label}): {count:,} records")

    # Projects
    try:
        cur.execute("SELECT COUNT(*) FROM engineering.projects")
        proj_count = cur.fetchone()[0]
        if proj_count > 0:
            print(f"\n  Active Projects: {proj_count}")
    except Exception:
        conn.rollback()

    # Permits
    try:
        cur.execute(
            "SELECT COUNT(*) FROM engineering.permits "
            "WHERE status NOT IN ('closed', 'revoked')"
        )
        perm_count = cur.fetchone()[0]
        if perm_count > 0:
            print(f"  Active Permits: {perm_count}")
    except Exception:
        conn.rollback()

    print(f"\n{'='*70}\n")


# ============================================================
# MAIN
# ============================================================

def main():
    print(f"\n  FORTRESS PRIME: DIVISION ENGINEERING — BLUEPRINT INGESTION ENGINE")
    print(f"   Sources: {', '.join(ENGINEERING_ROOTS[:3])} ...")
    print(f"   Vision:  {VISION_MODEL} @ {VISION_URL}")

    limit = 500
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        limit = int(sys.argv[idx + 1])

    # Init schema first
    from division_engineering.schema import init_schema
    init_schema()

    if "--init" in sys.argv:
        return

    conn = get_pg()

    if "--stats" in sys.argv:
        show_stats(conn)
        conn.close()
        return

    if "--cad" in sys.argv:
        run_phase_cad(conn, limit=limit)
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

    # Default: Phase 1 + CAD parsing + stats
    unknowns = run_phase1(conn)
    run_phase_cad(conn, limit=limit)
    show_stats(conn)

    if unknowns > 0:
        print(f"\n   {unknowns:,} files still unclassified.")
        print(f"   Next steps:")
        print(f"     --cad                Parse DWG/DXF files (ezdxf)")
        print(f"     --phase2             AI text extraction (DeepSeek-R1)")
        print(f"     --vision             Vision OCR for scanned drawings (LLaVA)")
        print(f"   Use --limit N to control batch size (default 500)")

    conn.close()


if __name__ == "__main__":
    main()
