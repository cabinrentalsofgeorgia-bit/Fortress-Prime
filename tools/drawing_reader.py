"""
Fortress Prime — Shared Drawing Reader (All Divisions)
========================================================
Enterprise-grade DWG/DXF reader available to ALL divisions:
    - Division 1 (Iron Mountain / Legal) — Property surveys, easements, plats
    - Division 2 (Rainmaker / Finance)   — Construction cost documentation
    - Division 3 (Guardian Ops)          — Property condition drawings
    - Division 5 (The Drawing Board)     — Full A/E document intelligence

Reads AutoCAD DWG and DXF files to extract:
    - Layers, entities, dimensions
    - Text content (annotations, labels, notes)
    - Title block info (owner, date, scale, surveyor, job #)
    - Survey calls (bearings + distances)
    - Drawing classification (discipline, type)

For DWG files: finds companion DXF or returns header + flags for Vision OCR.
For DXF files: full parsing via ezdxf.

API:
    from tools.drawing_reader import read_drawing, read_dwg_header
    from tools.drawing_reader import inventory_drawings, extract_for_vectordb

    result = read_drawing("/path/to/file.dwg")
    chunks = extract_for_vectordb("/path/to/file.DXF")  # For ChromaDB ingestion

Requires: pip install ezdxf
"""

# Re-export everything from the engineering reader (single source of truth)
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from division_engineering.read_drawing import (
    read_drawing,
    read_dwg_header,
    inventory_drawings,
    DWG_VERSIONS,
)

__all__ = [
    "read_drawing",
    "read_dwg_header",
    "inventory_drawings",
    "extract_for_vectordb",
    "extract_for_legal",
    "DWG_VERSIONS",
]


# =============================================================================
# CROSS-DIVISION EXTRACTION HELPERS
# =============================================================================

def extract_for_vectordb(filepath: str) -> list:
    """
    Extract drawing content as chunked documents ready for ChromaDB/vector ingestion.

    Returns a list of dicts, each with:
        - id: unique chunk ID
        - text: text content for embedding
        - metadata: structured metadata for filtering

    Used by the Legal Division (Iron Mountain) and RAG pipeline.
    """
    result = read_drawing(filepath)

    if not result.get("readable", False):
        return []

    chunks = []
    filename = result.get("filename", os.path.basename(filepath))
    title_block = result.get("title_block", {})
    classification = result.get("classification", {})

    # Chunk 1: Title Block / Overview
    overview_parts = [
        f"Engineering Drawing: {filename}",
        f"Type: {classification.get('doc_type', 'Unknown')}",
        f"Discipline: {classification.get('discipline', 'general')}",
    ]
    if title_block.get("owner"):
        overview_parts.append(f"Owner: {title_block['owner']}")
    if title_block.get("project"):
        overview_parts.append(f"Project: {title_block['project']}")
    if title_block.get("date"):
        overview_parts.append(f"Date: {title_block['date']}")
    if title_block.get("scale"):
        overview_parts.append(f"Scale: {title_block['scale']}")
    if title_block.get("county"):
        overview_parts.append(f"Location: {title_block['county']}")
    if title_block.get("subdivision"):
        overview_parts.append(f"Subdivision: {title_block['subdivision']}")
    if title_block.get("lot"):
        overview_parts.append(f"Lot: {title_block['lot']}")
    if title_block.get("land_lot"):
        overview_parts.append(f"Land Lot: {title_block['land_lot']}")
    if title_block.get("district"):
        overview_parts.append(f"District: {title_block['district']}")
    if title_block.get("surveyor"):
        overview_parts.append(f"Surveyor: {title_block['surveyor']}")
    if title_block.get("job_number"):
        overview_parts.append(f"Job Number: {title_block['job_number']}")

    # Add layer names for context
    layers = result.get("layers", [])
    if layers:
        overview_parts.append(
            f"Layers: {', '.join(l['name'] for l in layers if l['name'] != '0')}"
        )

    overview_parts.append(
        f"Entities: {result.get('total_entities', 0)} total"
    )

    base_id = os.path.splitext(filename)[0].replace(" ", "_").lower()

    chunks.append({
        "id": f"drawing_{base_id}_overview",
        "text": "\n".join(overview_parts),
        "metadata": {
            "source": "engineering_drawing",
            "source_file": filepath,
            "filename": filename,
            "category": "Engineering_Drawing",
            "doc_type": classification.get("doc_type", "Unknown"),
            "discipline": classification.get("discipline", "general"),
            "owner": title_block.get("owner", ""),
            "property_name": title_block.get("subdivision", ""),
            "date": title_block.get("date", ""),
            "county": title_block.get("county", ""),
            "chunk_type": "overview",
        },
    })

    # Chunk 2: All meaningful text content
    meaningful = result.get("meaningful_text", [])
    if meaningful:
        # Group into chunks of ~40 items (roughly 1500 chars per chunk)
        for i in range(0, len(meaningful), 40):
            chunk_texts = meaningful[i:i + 40]
            chunk_num = i // 40 + 1

            chunks.append({
                "id": f"drawing_{base_id}_text_{chunk_num}",
                "text": (
                    f"Text content from {filename} "
                    f"({classification.get('doc_type', 'drawing')}):\n"
                    + "\n".join(chunk_texts)
                ),
                "metadata": {
                    "source": "engineering_drawing",
                    "source_file": filepath,
                    "filename": filename,
                    "category": "Engineering_Drawing",
                    "doc_type": classification.get("doc_type", "Unknown"),
                    "discipline": classification.get("discipline", "general"),
                    "chunk_type": "text_content",
                    "chunk_num": chunk_num,
                },
            })

    # Chunk 3: Survey calls (if present — critical for legal/property division)
    survey_calls = result.get("survey_calls", [])
    if survey_calls:
        call_text = [
            f"Survey / Metes-and-Bounds data from {filename}:",
            f"Property: {title_block.get('owner', 'Unknown')}",
            f"Location: {title_block.get('county', 'Unknown')}",
            "",
        ]
        for c in survey_calls:
            call_text.append(f"  {c['type']}: {c['value']}")

        chunks.append({
            "id": f"drawing_{base_id}_survey",
            "text": "\n".join(call_text),
            "metadata": {
                "source": "engineering_drawing",
                "source_file": filepath,
                "filename": filename,
                "category": "Survey_Data",
                "doc_type": classification.get("doc_type", "Unknown"),
                "discipline": "civil",
                "chunk_type": "survey_calls",
                "call_count": len(survey_calls),
            },
        })

    return chunks


def extract_for_legal(filepath: str) -> dict:
    """
    Extract drawing information formatted for the Legal Division.

    Returns a dict optimized for legal analysis:
        - Property identification (owner, parcel, lot, county)
        - Boundary information (survey calls, easements)
        - Title references (deed book/page, recording dates)
        - Encumbrances (easements, rights-of-way, railroad crossings)

    Used by Iron Mountain (Division 1) for property-related legal matters.
    """
    result = read_drawing(filepath)

    if not result.get("readable", False):
        return {
            "filepath": filepath,
            "readable": False,
            "error": result.get("error", "Unable to read drawing"),
        }

    title_block = result.get("title_block", {})
    classification = result.get("classification", {})
    meaningful = result.get("meaningful_text", [])
    survey_calls = result.get("survey_calls", [])

    # Scan text for legal-relevant keywords
    all_text_lower = " ".join(t.lower() for t in meaningful)

    legal_keywords = {
        "easement": [],
        "right_of_way": [],
        "deed": [],
        "encumbrance": [],
        "setback": [],
        "boundary": [],
        "railroad": [],
        "river": [],
        "utility": [],
        "ingress_egress": [],
    }

    for text in meaningful:
        tl = text.lower()
        if "easement" in tl:
            legal_keywords["easement"].append(text)
        if "right" in tl and "way" in tl:
            legal_keywords["right_of_way"].append(text)
        if "deed" in tl or "book" in tl or "page" in tl:
            legal_keywords["deed"].append(text)
        if "encumbr" in tl or "encroach" in tl:
            legal_keywords["encumbrance"].append(text)
        if "setback" in tl:
            legal_keywords["setback"].append(text)
        if "boundar" in tl or "prop" in tl and "line" in tl:
            legal_keywords["boundary"].append(text)
        if "railroad" in tl or "rail" in tl or "csx" in tl:
            legal_keywords["railroad"].append(text)
        if "river" in tl or "creek" in tl or "stream" in tl:
            legal_keywords["river"].append(text)
        if "utility" in tl or "electric" in tl or "water" in tl:
            legal_keywords["utility"].append(text)
        if "ingress" in tl or "egress" in tl or "access" in tl:
            legal_keywords["ingress_egress"].append(text)

    # Clean empty keyword lists
    legal_keywords = {k: v for k, v in legal_keywords.items() if v}

    return {
        "filepath": filepath,
        "filename": result.get("filename"),
        "readable": True,
        "doc_type": classification.get("doc_type", "Unknown"),
        "discipline": classification.get("discipline", "general"),
        "property": {
            "owner": title_block.get("owner"),
            "lot": title_block.get("lot"),
            "subdivision": title_block.get("subdivision"),
            "county": title_block.get("county"),
            "state": title_block.get("state"),
            "land_lot": title_block.get("land_lot"),
            "district": title_block.get("district"),
            "section": title_block.get("section"),
        },
        "title_block": title_block,
        "survey": {
            "call_count": len(survey_calls),
            "bearings": [c for c in survey_calls if c["type"] == "bearing"],
            "distances": [c for c in survey_calls if c["type"] == "distance"],
        },
        "legal_keywords": legal_keywords,
        "encumbrances_detected": bool(
            legal_keywords.get("easement")
            or legal_keywords.get("right_of_way")
            or legal_keywords.get("encumbrance")
            or legal_keywords.get("railroad")
        ),
        "text_count": result.get("meaningful_text_count", 0),
        "entity_count": result.get("total_entities", 0),
    }
