"""
Fortress Prime — Engineering Drawing Reader
==============================================
Reads DWG and DXF files (AutoCAD drawings) and extracts structured
intelligence: layers, entities, text content, title block info,
metes-and-bounds calls, dimensions, and annotations.

For DWG files:
    - Checks for a companion .DXF file first (common in archives)
    - Falls back to DWG header parsing for basic metadata
    - Queues for Vision OCR if no DXF available (LLaVA reads the rendering)

For DXF files:
    - Full parsing via ezdxf: layers, entities, text, dimensions
    - Extracts title block information
    - Identifies survey calls (bearings + distances)
    - Classifies drawing discipline by layer names

Requires: pip install ezdxf

Usage:
    python division_engineering/read_drawing.py <filepath>
    python division_engineering/read_drawing.py --all       # Read all on NAS
    python division_engineering/read_drawing.py --summary   # Inventory report

API Usage:
    from division_engineering.read_drawing import read_drawing, read_dwg_header
    result = read_drawing("/path/to/file.DXF")
    header = read_dwg_header("/path/to/file.dwg")
"""

import json
import os
import re
import struct
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("division_engineering.read_drawing")

# DWG version map
DWG_VERSIONS = {
    "AC1032": ("AutoCAD 2018+", "R2018"),
    "AC1027": ("AutoCAD 2013-2017", "R2013"),
    "AC1024": ("AutoCAD 2010-2012", "R2010"),
    "AC1021": ("AutoCAD 2007-2009", "R2007"),
    "AC1018": ("AutoCAD 2004-2006", "R2004"),
    "AC1015": ("AutoCAD 2000-2002", "R2000"),
    "AC1014": ("AutoCAD R14", "R14"),
    "AC1012": ("AutoCAD R13", "R13"),
    "AC1009": ("AutoCAD R12/LT2", "R12"),
    "AC1006": ("AutoCAD R10", "R10"),
    "AC1004": ("AutoCAD R9", "R9"),
    "AC1003": ("AutoCAD R2.6", "R2.6"),
    "AC1002": ("AutoCAD R2.5", "R2.5"),
}


# =============================================================================
# DWG HEADER READER (Binary format — always works)
# =============================================================================

def read_dwg_header(filepath: str) -> Dict[str, Any]:
    """
    Read the header of a DWG file to extract version and basic metadata.
    Works on any DWG file regardless of version.

    Returns:
        Dict with version, format, size, and any extractable metadata.
    """
    result = {
        "filepath": filepath,
        "filename": os.path.basename(filepath),
        "extension": os.path.splitext(filepath)[1].lower(),
        "file_size": 0,
        "format": "dwg",
        "dwg_version_code": None,
        "dwg_version_name": None,
        "dwg_release": None,
        "readable": False,
    }

    try:
        result["file_size"] = os.path.getsize(filepath)
    except OSError:
        result["error"] = "File not found or inaccessible"
        return result

    try:
        with open(filepath, "rb") as f:
            header = f.read(32)

        if len(header) < 6:
            result["error"] = "File too small to be a valid DWG"
            return result

        version_code = header[:6].decode("ascii", errors="replace")
        result["dwg_version_code"] = version_code

        if version_code in DWG_VERSIONS:
            name, release = DWG_VERSIONS[version_code]
            result["dwg_version_name"] = name
            result["dwg_release"] = release
            result["readable"] = True
        else:
            result["dwg_version_name"] = f"Unknown ({version_code})"
            result["error"] = f"Unrecognized DWG version: {version_code}"

    except Exception as e:
        result["error"] = str(e)

    # Check for companion DXF file
    dxf_path = _find_companion_dxf(filepath)
    if dxf_path:
        result["companion_dxf"] = dxf_path
        result["has_dxf"] = True
    else:
        result["has_dxf"] = False

    return result


def _find_companion_dxf(dwg_path: str) -> Optional[str]:
    """
    Look for a companion DXF file next to a DWG file.
    AutoCAD often saves both formats. Checks case-insensitive.
    """
    base = os.path.splitext(dwg_path)[0]

    for ext in (".DXF", ".dxf", ".Dxf"):
        candidate = base + ext
        if os.path.isfile(candidate):
            return candidate

    return None


# =============================================================================
# DXF FULL READER (ezdxf — complete entity extraction)
# =============================================================================

def read_drawing(filepath: str) -> Dict[str, Any]:
    """
    Read a DWG or DXF file and extract all structured content.

    For DWG files: reads the companion DXF if available, or returns header only.
    For DXF files: full extraction of layers, entities, text, dimensions.

    Returns:
        Comprehensive dict with drawing metadata, layers, entities, text content,
        survey calls, title block info, and classification.
    """
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".dwg":
        return _read_dwg(filepath)
    elif ext in (".dxf",):
        return _read_dxf(filepath)
    else:
        return {"error": f"Unsupported file type: {ext}", "filepath": filepath}


def _read_dwg(filepath: str) -> Dict[str, Any]:
    """Read a DWG file — uses companion DXF if available."""
    header = read_dwg_header(filepath)

    if header.get("has_dxf"):
        logger.info(f"DWG has companion DXF: {header['companion_dxf']}")
        dxf_result = _read_dxf(header["companion_dxf"])
        dxf_result["source_dwg"] = filepath
        dxf_result["dwg_header"] = header
        return dxf_result

    # No companion DXF — return header info and flag for Vision OCR
    header["note"] = (
        "DWG binary format requires conversion to DXF for full parsing. "
        "No companion DXF found. Queue for Vision OCR (LLaVA) to read "
        "the rendered drawing, or convert using ODA File Converter."
    )
    header["needs_vision_ocr"] = True
    return header


def _read_dxf(filepath: str) -> Dict[str, Any]:
    """Full DXF reading with ezdxf."""
    try:
        import ezdxf
    except ImportError:
        return {
            "error": "ezdxf not installed. Run: pip install ezdxf",
            "filepath": filepath,
        }

    result = {
        "filepath": filepath,
        "filename": os.path.basename(filepath),
        "extension": os.path.splitext(filepath)[1].lower(),
        "file_size": os.path.getsize(filepath),
        "format": "dxf",
        "readable": True,
    }

    try:
        doc = ezdxf.readfile(filepath)
    except Exception as e:
        result["error"] = f"Failed to parse DXF: {e}"
        result["readable"] = False
        return result

    result["dxf_version"] = doc.dxfversion
    result["encoding"] = doc.encoding

    # ── LAYERS ───────────────────────────────────────────────────
    layers = []
    for layer in doc.layers:
        layers.append({
            "name": layer.dxf.name,
            "color": layer.dxf.color,
        })
    result["layers"] = layers
    result["layer_count"] = len(layers)

    # ── ENTITIES ─────────────────────────────────────────────────
    msp = doc.modelspace()
    entity_types = {}
    total_entities = 0
    for entity in msp:
        t = entity.dxftype()
        entity_types[t] = entity_types.get(t, 0) + 1
        total_entities += 1

    result["entity_types"] = entity_types
    result["total_entities"] = total_entities

    # ── TEXT EXTRACTION ──────────────────────────────────────────
    all_text = []
    for e in msp:
        if e.dxftype() == "TEXT":
            text = e.dxf.text.strip()
            if text:
                all_text.append({
                    "text": text,
                    "height": round(e.dxf.height, 2),
                    "layer": e.dxf.layer,
                    "x": round(e.dxf.insert.x, 2),
                    "y": round(e.dxf.insert.y, 2),
                    "type": "TEXT",
                })
        elif e.dxftype() == "MTEXT":
            text = e.text.strip()
            if text:
                h = getattr(e.dxf, "char_height", 0)
                all_text.append({
                    "text": text,
                    "height": round(h, 2) if h else 0,
                    "layer": e.dxf.layer,
                    "x": round(e.dxf.insert.x, 2),
                    "y": round(e.dxf.insert.y, 2),
                    "type": "MTEXT",
                })

    # Sort by height descending (most important text first)
    all_text.sort(key=lambda t: -t["height"])
    result["text_entities"] = all_text
    result["text_count"] = len(all_text)

    # ── TITLE BLOCK EXTRACTION ───────────────────────────────────
    title_block = _extract_title_block(all_text)
    result["title_block"] = title_block

    # ── SURVEY CALLS EXTRACTION ──────────────────────────────────
    survey_calls = _extract_survey_calls(all_text)
    if survey_calls:
        result["survey_calls"] = survey_calls
        result["survey_call_count"] = len(survey_calls)

    # ── DRAWING CLASSIFICATION ───────────────────────────────────
    classification = _classify_drawing(layers, all_text, entity_types)
    result["classification"] = classification

    # ── MEANINGFUL TEXT (filtered, deduplicated) ─────────────────
    meaningful = []
    seen = set()
    for t in all_text:
        txt = t["text"]
        if len(txt) > 2 and txt not in seen:
            seen.add(txt)
            meaningful.append(txt)

    result["meaningful_text"] = meaningful[:200]
    result["meaningful_text_count"] = len(meaningful)

    return result


# =============================================================================
# INTELLIGENT EXTRACTION
# =============================================================================

def _extract_title_block(text_entities: List[Dict]) -> Dict[str, Any]:
    """
    Extract title block information from text entities.

    Looks for common patterns: project name, date, scale, surveyor/architect,
    county, state, job number, lot/parcel info.
    """
    block = {
        "owner": None,
        "project": None,
        "date": None,
        "scale": None,
        "surveyor": None,
        "job_number": None,
        "county": None,
        "state": None,
        "subdivision": None,
        "lot": None,
        "section": None,
        "district": None,
        "land_lot": None,
    }

    all_texts = [(t["text"], t["height"]) for t in text_entities]

    for text, height in all_texts:
        text_lower = text.lower()

        # Scale
        if re.search(r'scale\s*[:\s]*1"?\s*=', text, re.I):
            block["scale"] = text.strip()

        # Date patterns
        date_match = re.search(
            r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+\d{1,2},?\s+\d{4}',
            text, re.I,
        )
        if date_match:
            block["date"] = date_match.group(0)

        # County
        if "county" in text_lower and "ga" in text_lower:
            block["county"] = text.strip()
            block["state"] = "Georgia"
        elif "fannin" in text_lower:
            block["county"] = "Fannin County"
            block["state"] = "Georgia"

        # Land lot / district / section
        ll_match = re.search(r'l\.?l\.?\s*(\d+)', text, re.I)
        if ll_match:
            block["land_lot"] = ll_match.group(1)

        dist_match = re.search(r'dist\.?\s*(\d+)', text, re.I)
        if dist_match:
            block["district"] = dist_match.group(1)

        sect_match = re.search(r'sect\.?\s*(\d+)', text, re.I)
        if sect_match:
            block["section"] = sect_match.group(1)

        # Lot number
        lot_match = re.search(r'lot\s+(\d+\s*[a-z]?)', text, re.I)
        if lot_match:
            block["lot"] = lot_match.group(1).strip()

        # Subdivision
        if "s/d" in text_lower or "s\\d" in text_lower or "subdivision" in text_lower:
            block["subdivision"] = text.strip()

        # Job number
        jn_match = re.search(r'(jn\s*\d+|job\s*#?\s*\d+)', text, re.I)
        if jn_match:
            block["job_number"] = jn_match.group(0)

        # Largest text is often the owner/title
        if height >= 10 and not block["owner"]:
            block["owner"] = text.strip()

    # Second pass for project description (text with "survey for", "plan for", etc.)
    for text, height in all_texts:
        if re.search(r'(survey|plan|plat|crossing|design)\s+(for|of)', text, re.I):
            block["project"] = text.strip()
            break

    # Clean up None values
    return {k: v for k, v in block.items() if v is not None}


def _extract_survey_calls(text_entities: List[Dict]) -> List[Dict[str, Any]]:
    """
    Extract metes-and-bounds survey calls from text entities.

    Matches patterns like:
        N 61d53'30"W
        S 55%%d33'12"E
        325.28'
    """
    calls = []

    # AutoCAD uses %%d for the degree symbol
    bearing_pattern = re.compile(
        r'[NS]\s*\d+\s*(?:%%d|°|d)\s*\d+\'\s*\d+\"?\s*[EW]',
        re.I,
    )
    distance_pattern = re.compile(r'(\d+\.?\d*)\s*\'')

    for t in text_entities:
        text = t["text"]
        if bearing_pattern.search(text):
            calls.append({
                "type": "bearing",
                "value": text.strip(),
                "layer": t["layer"],
            })
        elif distance_pattern.search(text) and t["layer"] in ("CALLS", "BOUNDARY", "INFO"):
            match = distance_pattern.search(text)
            calls.append({
                "type": "distance",
                "value": text.strip(),
                "feet": float(match.group(1)),
                "layer": t["layer"],
            })

    return calls


def _classify_drawing(
    layers: List[Dict],
    text_entities: List[Dict],
    entity_types: Dict[str, int],
) -> Dict[str, Any]:
    """
    Classify the drawing by discipline and type based on its content.
    """
    layer_names = {l["name"].upper() for l in layers}
    all_text_lower = " ".join(t["text"].lower() for t in text_entities)

    discipline = "general"
    doc_type = "Unknown"
    confidence = 0.5

    # Survey / Plat indicators
    if (
        "TRAV" in layer_names or "CALLS" in layer_names or "BOUNDARY" in layer_names
    ):
        discipline = "civil"
        doc_type = "Boundary_Survey"
        confidence = 0.9
        if "plat" in all_text_lower:
            doc_type = "Survey_Plat"
        elif "topo" in all_text_lower:
            doc_type = "Topographic_Survey"

    # Railroad / crossing
    if "crossing" in all_text_lower or "railroad" in all_text_lower:
        discipline = "civil"
        doc_type = "Railroad_Crossing_Plan"
        confidence = 0.95

    # Floor plan
    if "floor" in all_text_lower and "plan" in all_text_lower:
        discipline = "architectural"
        doc_type = "Floor_Plan"
        confidence = 0.9

    # Site plan
    if "site" in all_text_lower and "plan" in all_text_lower:
        discipline = "civil"
        doc_type = "Site_Plan"
        confidence = 0.85

    # Check for elevation data
    if "elevation" in all_text_lower and "sea level" in all_text_lower:
        discipline = "civil"
        if doc_type == "Unknown":
            doc_type = "Topographic_Survey"
        confidence = max(confidence, 0.85)

    return {
        "discipline": discipline,
        "doc_type": doc_type,
        "confidence": confidence,
    }


# =============================================================================
# BATCH OPERATIONS
# =============================================================================

def inventory_drawings(root_dirs: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Inventory all DWG/DXF files across the NAS.

    Returns summary stats and a list of all found files.
    """
    if root_dirs is None:
        root_dirs = [
            "/mnt/fortress_nas/Business_Prime/CROG",
            "/mnt/fortress_nas/Enterprise_War_Room",
        ]

    files = []
    for root_dir in root_dirs:
        if not os.path.isdir(root_dir):
            continue
        for root, dirs, filenames in os.walk(root_dir):
            for f in filenames:
                ext = os.path.splitext(f)[1].lower()
                if ext in (".dwg", ".dxf"):
                    filepath = os.path.join(root, f)
                    try:
                        size = os.path.getsize(filepath)
                    except OSError:
                        size = 0
                    files.append({
                        "filepath": filepath,
                        "filename": f,
                        "extension": ext,
                        "file_size": size,
                    })

    # Deduplicate by filename
    unique_names = set()
    unique_files = []
    for f in files:
        if f["filename"] not in unique_names:
            unique_names.add(f["filename"])
            unique_files.append(f)

    # Count by extension
    dwg_count = sum(1 for f in files if f["extension"] == ".dwg")
    dxf_count = sum(1 for f in files if f["extension"] == ".dxf")

    return {
        "total_files": len(files),
        "unique_files": len(unique_files),
        "dwg_count": dwg_count,
        "dxf_count": dxf_count,
        "total_size_bytes": sum(f["file_size"] for f in files),
        "files": unique_files,
    }


# =============================================================================
# CLI
# =============================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python read_drawing.py <filepath.dwg|.dxf>")
        print("  python read_drawing.py --summary")
        print("  python read_drawing.py --all")
        return

    arg = sys.argv[1]

    if arg == "--summary":
        inv = inventory_drawings()
        print(f"\n{'='*65}")
        print(f"  ENGINEERING DRAWING INVENTORY — NAS")
        print(f"{'='*65}")
        print(f"  Total files:  {inv['total_files']:,}")
        print(f"  Unique:       {inv['unique_files']:,}")
        print(f"  DWG files:    {inv['dwg_count']:,}")
        print(f"  DXF files:    {inv['dxf_count']:,}")
        print(f"  Total size:   {inv['total_size_bytes']/1e6:.1f} MB")
        print(f"\n  {'FILENAME':<55} {'EXT':>5} {'SIZE':>10}")
        print(f"  {'-'*72}")
        for f in sorted(inv["files"], key=lambda x: x["filename"]):
            print(
                f"  {f['filename']:<55} {f['extension']:>5} "
                f"{f['file_size']:>10,}"
            )
        print(f"\n{'='*65}\n")
        return

    if arg == "--all":
        inv = inventory_drawings()
        dxf_files = [f for f in inv["files"] if f["extension"] == ".dxf"]
        print(f"\nReading {len(dxf_files)} DXF files...\n")
        for f in dxf_files:
            result = read_drawing(f["filepath"])
            tb = result.get("title_block", {})
            cls = result.get("classification", {})
            print(
                f"  {f['filename']:<40} "
                f"{cls.get('discipline', '?'):<14} "
                f"{cls.get('doc_type', '?'):<25} "
                f"text:{result.get('text_count', 0):>4}  "
                f"ent:{result.get('total_entities', 0):>5}"
            )
            if tb.get("owner"):
                print(f"    Owner: {tb['owner']}")
            if tb.get("project"):
                print(f"    Project: {tb['project']}")
            if tb.get("date"):
                print(f"    Date: {tb['date']}")
        return

    # Single file read
    result = read_drawing(arg)

    print(f"\n{'='*70}")
    print(f"  ENGINEERING DRAWING ANALYSIS")
    print(f"{'='*70}")
    print(f"  File:     {result.get('filename', '?')}")
    print(f"  Size:     {result.get('file_size', 0):,} bytes")
    print(f"  Format:   {result.get('format', '?')}")

    if result.get("dxf_version"):
        print(f"  DXF Ver:  {result['dxf_version']}")
    if result.get("dwg_version_name"):
        print(f"  DWG Ver:  {result['dwg_version_name']}")

    # Classification
    cls = result.get("classification", {})
    if cls:
        print(f"\n  Classification:")
        print(f"    Discipline: {cls.get('discipline', '?')}")
        print(f"    Doc Type:   {cls.get('doc_type', '?')}")
        print(f"    Confidence: {cls.get('confidence', 0):.0%}")

    # Title block
    tb = result.get("title_block", {})
    if tb:
        print(f"\n  Title Block:")
        for k, v in tb.items():
            print(f"    {k:<15} {v}")

    # Layers
    layers = result.get("layers", [])
    if layers:
        print(f"\n  Layers ({len(layers)}):")
        for l in layers:
            print(f"    {l['name']:<25} color={l['color']}")

    # Entities
    et = result.get("entity_types", {})
    if et:
        print(f"\n  Entities ({result.get('total_entities', 0):,} total):")
        for etype, count in sorted(et.items(), key=lambda x: -x[1]):
            print(f"    {etype:<20} {count:>6,}")

    # Survey calls
    calls = result.get("survey_calls", [])
    if calls:
        print(f"\n  Survey Calls ({len(calls)}):")
        for c in calls[:20]:
            print(f"    {c['type']:<10} {c['value']}")

    # Meaningful text
    texts = result.get("meaningful_text", [])
    if texts:
        print(f"\n  Meaningful Text ({result.get('meaningful_text_count', 0)} unique items):")
        for t in texts[:40]:
            print(f"    {t[:80]}")

    if result.get("needs_vision_ocr"):
        print(f"\n  NOTE: {result.get('note', '')}")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
