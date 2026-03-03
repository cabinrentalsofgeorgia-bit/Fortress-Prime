"""
Fortress Prime — Drawing Intelligence Bridge
================================================
Cross-division bridge that gives ALL divisions access to the
Engineering Drawing Reader and intelligence extraction.

This bridge is the single import point for any division needing
to read, search, or analyze DWG/DXF files:

    from src.bridges.drawing_bridge import (
        read_drawing,           # Read any DWG/DXF file
        search_drawings,        # Semantic search across indexed drawings
        extract_for_legal,      # Legal-specific extraction (surveys, easements)
        extract_for_vectordb,   # Get chunks ready for ChromaDB
        inventory_drawings,     # List all drawings on NAS
        get_drawing_from_db,    # Query PostgreSQL engineering.drawings
    )

Available to:
    - Division 1 (Iron Mountain / Legal)
    - Division 2 (Rainmaker / Finance)
    - Division 3 (Guardian Ops)
    - Division 4 (Real Estate)
    - Division 5 (The Drawing Board / Engineering)
    - Sovereign Intelligence
"""

import os
import sys
import json
import logging
from typing import Any, Dict, List, Optional

import requests
import psycopg2
import psycopg2.extras

# Ensure project root is importable
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logger = logging.getLogger("bridge.drawing")

# --- Re-export from shared tools ---
from tools.drawing_reader import (
    read_drawing,
    read_dwg_header,
    extract_for_vectordb,
    extract_for_legal,
    inventory_drawings,
    DWG_VERSIONS,
)

# --- Database config ---
PG_HOST = os.getenv("DB_HOST", "localhost")
PG_PORT = int(os.getenv("DB_PORT", "5432"))
PG_DB = os.getenv("DB_NAME", "fortress_db")
PG_USER = os.getenv("DB_USER", "miner_bot")
PG_PASS = os.getenv("DB_PASSWORD", "")

# --- Embedding ---
EMBED_URL = os.getenv("EMBED_URL", "http://localhost:11434/api/embeddings")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# --- ChromaDB ---
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8002"))
DRAWING_COLLECTION = "engineering_drawings"


def _get_db():
    """Get database connection with RealDictCursor."""
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB,
        user=PG_USER, password=PG_PASS,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


# =============================================================================
# DATABASE ACCESS (PostgreSQL)
# =============================================================================

def get_drawing_from_db(
    drawing_id: Optional[int] = None,
    filepath: Optional[str] = None,
    discipline: Optional[str] = None,
    doc_type: Optional[str] = None,
    property_name: Optional[str] = None,
    limit: int = 50,
) -> List[Dict]:
    """
    Query engineering drawings from PostgreSQL.

    Args:
        drawing_id: Specific drawing ID
        filepath: Specific file path
        discipline: Filter by discipline (civil, architectural, etc.)
        doc_type: Filter by document type (Boundary_Survey, Floor_Plan, etc.)
        property_name: Filter by property name (partial match)
        limit: Max results

    Returns:
        List of drawing records with full metadata.
    """
    conn = _get_db()
    cur = conn.cursor()

    query = """
        SELECT d.id, d.property_id, d.discipline, d.doc_type, d.file_path,
               d.filename, d.extension, d.file_size, d.sheet_number, d.title,
               d.scale, d.revision, d.confidence, d.phase, d.ocr_text,
               d.ai_json, d.created_at,
               p.name AS property_name
        FROM engineering.drawings d
        LEFT JOIN properties p ON d.property_id = p.id
        WHERE 1=1
    """
    params = []

    if drawing_id:
        query += " AND d.id = %s"
        params.append(drawing_id)
    if filepath:
        query += " AND d.file_path = %s"
        params.append(filepath)
    if discipline:
        query += " AND d.discipline = %s"
        params.append(discipline)
    if doc_type:
        query += " AND d.doc_type = %s"
        params.append(doc_type)
    if property_name:
        query += " AND (p.name ILIKE %s OR d.filename ILIKE %s)"
        params.extend([f"%{property_name}%", f"%{property_name}%"])

    query += " ORDER BY d.created_at DESC LIMIT %s"
    params.append(limit)

    try:
        cur.execute(query, params)
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Drawing DB query failed: {e}")
        return []
    finally:
        conn.close()


def get_drawing_stats() -> Dict[str, Any]:
    """Get summary statistics for the engineering drawing registry."""
    conn = _get_db()
    cur = conn.cursor()

    stats = {}
    try:
        cur.execute("SELECT COUNT(*) AS total FROM engineering.drawings")
        stats["total"] = cur.fetchone()["total"]

        cur.execute("""
            SELECT discipline, COUNT(*) as count
            FROM engineering.drawings
            GROUP BY discipline ORDER BY count DESC
        """)
        stats["by_discipline"] = {r["discipline"]: r["count"] for r in cur.fetchall()}

        cur.execute("""
            SELECT doc_type, COUNT(*) as count
            FROM engineering.drawings
            GROUP BY doc_type ORDER BY count DESC LIMIT 15
        """)
        stats["by_doc_type"] = {r["doc_type"]: r["count"] for r in cur.fetchall()}

        cur.execute("""
            SELECT extension, COUNT(*) as count
            FROM engineering.drawings
            GROUP BY extension ORDER BY count DESC
        """)
        stats["by_extension"] = {r["extension"]: r["count"] for r in cur.fetchall()}

        cur.execute("""
            SELECT confidence, COUNT(*) as count
            FROM engineering.drawings
            GROUP BY confidence ORDER BY count DESC
        """)
        stats["by_confidence"] = {r["confidence"]: r["count"] for r in cur.fetchall()}

    except Exception as e:
        logger.error(f"Drawing stats query failed: {e}")
    finally:
        conn.close()

    return stats


# =============================================================================
# VECTOR SEARCH (ChromaDB)
# =============================================================================

def search_drawings(
    query: str,
    discipline: Optional[str] = None,
    doc_type: Optional[str] = None,
    top_k: int = 8,
) -> List[Dict]:
    """
    Semantic search across indexed engineering drawings in ChromaDB.

    Works from any division — searches the shared fortress_docs collection.

    Args:
        query: Natural language search query
        discipline: Optional discipline filter
        doc_type: Optional document type filter
        top_k: Number of results

    Returns:
        List of search results with text, metadata, and relevance scores.
    """
    import chromadb

    try:
        # Generate embedding
        resp = requests.post(
            EMBED_URL,
            json={"model": EMBED_MODEL, "prompt": query[:2000]},
            timeout=30,
        )
        resp.raise_for_status()
        embedding = resp.json().get("embedding", [])
        if not embedding:
            return []
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return []

    try:
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        collection = client.get_collection(DRAWING_COLLECTION)

        # Build where filter
        where_filters = [{"source": "engineering_drawing"}]
        if discipline:
            where_filters.append({"discipline": discipline})
        if doc_type:
            where_filters.append({"doc_type": doc_type})

        where = where_filters[0] if len(where_filters) == 1 else {"$and": where_filters}

        results = collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
            where=where,
        )

        hits = []
        if results.get("documents") and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                dist = results["distances"][0][i] if results.get("distances") else None
                hits.append({
                    "text": doc,
                    "metadata": meta,
                    "distance": round(dist, 4) if dist else None,
                    "relevance": round(1.0 - (dist or 0), 4),
                })
        return hits

    except Exception as e:
        logger.error(f"Drawing search failed: {e}")
        return []


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def find_surveys_for_property(property_name: str) -> List[Dict]:
    """Find all survey drawings associated with a property."""
    # Try database first
    db_results = get_drawing_from_db(
        doc_type="Boundary_Survey", property_name=property_name
    )
    if not db_results:
        db_results = get_drawing_from_db(
            discipline="civil", property_name=property_name
        )

    # Also try vector search
    vector_results = search_drawings(
        f"boundary survey plat {property_name}",
        discipline="civil",
        top_k=5,
    )

    return {
        "database_results": db_results,
        "vector_results": vector_results,
    }


def find_drawings_with_easements() -> List[Dict]:
    """Find all drawings that mention easements or rights-of-way."""
    return search_drawings(
        "easement right of way encroachment property line boundary",
        top_k=10,
    )


def get_property_engineering_summary(property_name: str) -> Dict[str, Any]:
    """
    Get a complete engineering summary for a property.

    Aggregates all drawings, compliance records, MEP systems,
    and active projects. Used by Legal for property-related matters.
    """
    drawings = get_drawing_from_db(property_name=property_name, limit=100)

    # Summarize by discipline
    disciplines = {}
    for d in drawings:
        disc = d.get("discipline", "general")
        if disc not in disciplines:
            disciplines[disc] = []
        disciplines[disc].append({
            "filename": d["filename"],
            "doc_type": d["doc_type"],
            "title": d.get("title"),
        })

    return {
        "property": property_name,
        "total_drawings": len(drawings),
        "by_discipline": disciplines,
        "cad_files": [d for d in drawings if d["extension"] in (".dwg", ".dxf")],
        "surveys": [d for d in drawings if "survey" in (d.get("doc_type") or "").lower()],
    }
