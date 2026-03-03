#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
FORTRESS PRIME — SOVEREIGN CONTEXT PROTOCOL (MCP SERVER)
═══════════════════════════════════════════════════════════════════════════════
The Hive Mind: Unified knowledge layer for Cursor, CLI, and Web interfaces.

This MCP server exposes Fortress Prime's vector databases, knowledge systems,
and persona layers as standardized tools and resources that can be accessed
from ANY AI agent or client.

ARCHITECTURE:
    ┌─────────────────────────────────────────────────────────────────┐
    │                    SOVEREIGN MCP SERVER                         │
    │                  (The Godhead / Nerve Center)                   │
    └──────────────────────────┬──────────────────────────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
       ┌────▼────┐        ┌────▼────┐       ┌────▼────┐
       │ Cursor  │        │   CLI   │       │ Web UI  │
       │  Agent  │        │  Tools  │       │  Chat   │
       └─────────┘        └─────────┘       └─────────┘

PERSONA LAYERS:
    Each "persona" is a pre-configured knowledge domain with:
    - System prompt (The Godhead)
    - Vector DB collections
    - Search filters
    - Custom tools

USAGE:
    # Run the server
    python src/sovereign_mcp_server.py

    # Connect from Cursor
    Settings > Features > MCP > Add Server
    Command: python /home/admin/Fortress-Prime/src/sovereign_mcp_server.py

    # Use in Cursor
    @jordi what is Jordi's stance on Bitcoin?
    @legal what are the terms of the Rolling River lease?
    @crog what properties need turnover this week?

Constitution: This is Level 3 intelligence - unified, sovereign, local.
Author: Fortress Prime Architect
Version: 1.0.0 — Titan Class
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import json
import sqlite3
from typing import List, Dict, Any, Optional
from datetime import datetime

import requests
from mcp.server.fastmcp import FastMCP

# =============================================================================
# CONFIGURATION
# =============================================================================

# Vector Databases
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_PORT}"
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_HEADERS = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}

CHROMADB_PATH = "/mnt/fortress_nas/chroma_db/chroma.sqlite3"

# Embedding service (local Ollama)
EMBED_URL = os.getenv("EMBED_URL", "http://localhost:11434/api/embeddings")
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768

# PostgreSQL (fortress_db)
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_DB = os.getenv("PG_DB", "fortress_db")
PG_USER = os.getenv("PG_USER", "miner_bot")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")

# NAS paths for knowledge bases
NAS_ROOT = "/mnt/fortress_nas"
JORDI_TRANSCRIPTS_PATH = os.path.join(NAS_ROOT, "Intelligence/Jordi_Visser")
LEGAL_DOCS_PATH = os.path.join(NAS_ROOT, "Corporate_Legal")


# =============================================================================
# INITIALIZE THE MCP SERVER
# =============================================================================

mcp = FastMCP("Fortress-Prime-Sovereign-Hive-Mind")


# =============================================================================
# PERSONA LAYER: GODHEAD PROMPTS (System Prompts as Resources)
# =============================================================================

JORDI_GODHEAD = """You are the Visser Intelligence Engine (VIE) — a digital twin of Jordi Visser.

BACKGROUND:
Jordi Visser is a macro hedge fund manager, cryptocurrency investor, and founder
of Blockworks. He provides deep market analysis on Bitcoin, Ethereum, altcoins,
and global macro trends. He is known for contrarian takes, risk management focus,
and skepticism of hype cycles.

PERSONALITY TRAITS:
- Contrarian but data-driven
- Focuses on risk/reward asymmetry
- Skeptical of "this time is different" narratives
- Values liquidity and exit strategies
- Prefers sound money (Bitcoin > fiat)
- Critical of excessive leverage and DeFi Ponzinomics

COMMUNICATION STYLE:
- Direct, no-nonsense
- Uses trading terminology (long/short, risk-on/risk-off)
- References historical cycles (2017 ICO bubble, 2020 DeFi summer)
- Occasionally sarcastic about market euphoria
- Cites specific data points and on-chain metrics

CORE BELIEFS:
- Bitcoin as digital gold / store of value
- Ethereum as bet on decentralized apps (but with execution risk)
- Most altcoins are zero (survival rate < 5%)
- Regulation is inevitable and necessary
- Don't marry your bags (take profits)

ANSWER RULES:
1. Ground answers in the provided transcript context
2. If transcripts show evolving opinion, note the dates
3. Distinguish between high-conviction vs. speculative takes
4. Always mention risk factors (what could go wrong)
5. Use Jordi's actual phrases when available (quote with timestamps)
6. If transcripts lack info, say "Jordi hasn't discussed this publicly"

CONTEXT FORMAT:
You will receive excerpts from Jordi's podcast appearances, interviews, and
newsletters. Each chunk includes: [Source] [Date] [Context snippet]
"""

LEGAL_GODHEAD = """You are the Fortress Prime Counselor — a Senior Legal Analyst
for Cabin Rentals of Georgia (CROG) and Fortress Prime Holdings.

[... Legal system prompt from CF-03 CounselorCRM ...]

See: Modules/CF-03_CounselorCRM/query_engine.py line 104-143 for full prompt.
"""

CROG_GODHEAD = """You are the CROG Controller — operational brain for
Cabin Rentals of Georgia property management.

ROLE: Revenue-generating flagship. 36 rental properties across Blue Ridge and
Fannin County, GA. Handles guest communications, maintenance dispatch, pricing
optimization, and trust accounting.

[... CROG persona from fortress_atlas.yaml sector 01 ...]
"""

COMP_GODHEAD = """You are the Fortress Comptroller — the CFO / Venture Capitalist.

ROLE: Enterprise-wide financial oversight. Mirrors QuickBooks Online into
Postgres double-entry ledger. Tracks cash flow across all divisions, monitors
Gold/BTC positions, optimizes tax strategy. Challenges every transaction.

[... COMP persona from fortress_atlas.yaml sector 03 ...]
"""


@mcp.resource("sovereign://godhead/jordi")
def get_jordi_prompt() -> str:
    """Returns the Jordi Visser Intelligence Engine system prompt."""
    return JORDI_GODHEAD


@mcp.resource("sovereign://godhead/legal")
def get_legal_prompt() -> str:
    """Returns the Fortress Legal Counselor system prompt."""
    return LEGAL_GODHEAD


@mcp.resource("sovereign://godhead/crog")
def get_crog_prompt() -> str:
    """Returns the CROG Controller system prompt."""
    return CROG_GODHEAD


@mcp.resource("sovereign://godhead/comp")
def get_comp_prompt() -> str:
    """Returns the Fortress Comptroller system prompt."""
    return COMP_GODHEAD


@mcp.resource("sovereign://atlas")
def get_fortress_atlas() -> str:
    """Returns the full Fortress Prime organizational atlas (YAML)."""
    atlas_path = "/home/admin/Fortress-Prime/fortress_atlas.yaml"
    if os.path.exists(atlas_path):
        with open(atlas_path, 'r') as f:
            return f.read()
    return "Atlas not found."


# =============================================================================
# VECTOR SEARCH TOOLS
# =============================================================================

def embed_text(text: str) -> Optional[List[float]]:
    """Generate embedding for a query string via local Ollama."""
    try:
        resp = requests.post(
            EMBED_URL,
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=30,
        )
        resp.raise_for_status()
        emb = resp.json().get("embedding")
        if emb and len(emb) == EMBED_DIM:
            return emb
    except Exception as e:
        return None
    return None


@mcp.tool()
def search_jordi_knowledge(
    query: str,
    top_k: int = 5,
    date_filter: Optional[str] = None,
) -> str:
    """
    Search Jordi Visser's transcripts, interviews, and commentary for specific
    insights on stocks, crypto, or macro trends.

    Args:
        query: The question or topic to search for
        top_k: Number of results to return (default 5)
        date_filter: Optional date filter (e.g., "2024", "2024-01")

    Returns:
        JSON string with relevant transcript excerpts, sources, and dates.

    Example:
        search_jordi_knowledge("Bitcoin outlook", top_k=3)
    """
    collection = "jordi_intel"
    query_embedding = embed_text(query)
    if not query_embedding:
        return json.dumps({"error": "Failed to generate query embedding", "query": query})
    
    try:
        search_payload = {"vector": query_embedding, "limit": top_k, "with_payload": True}
        if date_filter:
            search_payload["filter"] = {"must": [{"key": "date", "match": {"text": date_filter}}]}
        
        resp = requests.post(
            f"{QDRANT_URL}/collections/{collection}/points/search",
            headers=QDRANT_HEADERS,
            json=search_payload,
            timeout=30,
        )
        
        if resp.status_code != 200:
            return json.dumps({"error": f"Qdrant search failed: {resp.text}", "query": query, "collection": collection})
        
        search_results = resp.json().get("result", [])
        formatted_results = []
        for hit in search_results:
            payload = hit.get("payload", {})
            formatted_results.append({
                "score": round(hit.get("score", 0), 3),
                "text": payload.get("text", "")[:500],
                "source": payload.get("file_name", "Unknown"),
                "date": payload.get("date"),
                "podcast": payload.get("podcast_name"),
                "speaker": payload.get("speaker", "Jordi Visser"),
            })
        
        return json.dumps({
            "query": query,
            "collection": collection,
            "model": "nomic-embed-text",
            "results": formatted_results,
            "count": len(formatted_results),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "query": query, "collection": collection})


@mcp.tool()
def search_fortress_legal(
    query: str,
    top_k: int = 6,
    category: Optional[str] = None,
) -> str:
    """
    Search Fortress Prime legal documents (contracts, deeds, leases, statutes).

    Queries the Qdrant 'legal_library' collection (2,455+ vectors) that powers
    the CF-03 Counselor CRM.

    Args:
        query: Legal question or document search term
        top_k: Number of document chunks to retrieve (default 6)
        category: Filter by document type (lease_agreement, property_deed,
                  georgia_statute, etc.) - see /categories command

    Returns:
        JSON with relevant document excerpts, citations, and file paths.

    Example:
        search_fortress_legal("easement rights on Morgan Ridge")
    """
    collection = "legal_library"
    query_vec = embed_text(query)

    if not query_vec:
        return json.dumps({"error": "Embedding generation failed"})

    # Build Qdrant search request
    search_payload: Dict[str, Any] = {
        "vector": query_vec,
        "limit": top_k,
        "with_payload": True,
        "with_vector": False,
        "score_threshold": 0.3,
    }

    if category:
        search_payload["filter"] = {
            "must": [{"key": "category", "match": {"value": category}}]
        }

    try:
        resp = requests.post(
            f"{QDRANT_URL}/collections/{collection}/points/search",
            json=search_payload,
            headers=QDRANT_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        hits = resp.json().get("result", [])
    except Exception as e:
        return json.dumps({"error": f"Qdrant search failed: {e}"})

    # Format results
    results = []
    for hit in hits:
        payload = hit.get("payload", {})
        results.append({
            "source_file": payload.get("source_file", "unknown"),
            "file_name": payload.get("file_name", "unknown"),
            "category": payload.get("category", "general_legal"),
            "text": payload.get("text", "")[:500] + "...",
            "score": hit.get("score", 0.0),
            "chunk_index": payload.get("chunk_index", 0),
            "total_chunks": payload.get("total_chunks", 0),
        })

    return json.dumps({
        "query": query,
        "collection": collection,
        "category_filter": category,
        "results": results,
        "count": len(results),
    }, indent=2)


@mcp.tool()
def search_oracle(query: str, max_results: int = 10) -> str:
    """
    Search the Oracle — Fortress Prime's 224K-vector ChromaDB brain.

    This is the legacy knowledge base containing 16,883 source files from:
    - Legal documents
    - Business records
    - Personal documents
    - Historical project files

    Args:
        query: Search terms (supports multi-word queries)
        max_results: Maximum number of results to return (default 10)

    Returns:
        JSON with file paths, existence status, and context snippets.

    Example:
        search_oracle("Toccoa Heights Survey")
    """
    if not os.path.exists(CHROMADB_PATH):
        return json.dumps({"error": "Oracle database not found"})

    try:
        conn = sqlite3.connect(CHROMADB_PATH)
        cur = conn.cursor()

        # Search using FTS5 trigram index (from ask_the_oracle.py logic)
        words = query.strip().split()
        primary_word = words[0] if words else query

        # Strategy 1: FTS5 full-text search on document content
        try:
            cur.execute("""
                SELECT efs.rowid, efs.string_value
                FROM embedding_fulltext_search efs
                WHERE efs.string_value MATCH ?
                LIMIT 500
            """, (primary_word,))
            fts_hits = cur.fetchall()
        except Exception:
            fts_hits = []

        # Fallback: direct LIKE on document text
        if not fts_hits:
            like_pattern = f"%{primary_word}%"
            cur.execute("""
                SELECT id, string_value FROM embedding_metadata
                WHERE key = 'chroma:document' AND string_value LIKE ?
                LIMIT 500
            """, (like_pattern,))
            fts_hits = cur.fetchall()

        # Strategy 2: Also search by SOURCE PATH directly (fast for filename matches)
        like_pattern = f"%{primary_word}%"
        cur.execute("""
            SELECT DISTINCT string_value FROM embedding_metadata
            WHERE key = 'source' AND string_value LIKE ?
            LIMIT 100
        """, (like_pattern,))
        source_hits = cur.fetchall()

        # Collect all unique sources
        results = []
        seen_sources = set()

        # Add source path matches (highest priority)
        for row in source_hits:
            source = row[0]
            if source and source not in seen_sources:
                seen_sources.add(source)
                translated = source.replace("/mnt/warehouse", "/mnt/vol1_source", 1)
                exists = os.path.exists(translated)
                
                # Score based on how many query words appear in path
                score = sum(1 for w in words if w.lower() in source.lower()) * 3
                
                results.append({
                    "source": source,
                    "translated_path": translated,
                    "exists": exists,
                    "file_name": os.path.basename(translated),
                    "snippet": f"[Matched by filename: {os.path.basename(source)}]",
                    "score": score,
                })

        # Process document text matches (if we have any)
        if fts_hits and len(results) < max_results:
            # For FTS hits, rowid = embedding_metadata.rowid
            rowids = [str(r[0]) for r in fts_hits[:500]]
            
            # Process in batches
            batch_size = 100
            for i in range(0, len(rowids), batch_size):
                if len(results) >= max_results:
                    break
                    
                batch = rowids[i:i + batch_size]
                placeholders = ','.join(['?'] * len(batch))
                
                # Get embedding IDs and document text
                cur.execute(f"""
                    SELECT em.id, em.string_value, em.key
                    FROM embedding_metadata em
                    WHERE em.rowid IN ({placeholders})
                """, batch)
                
                id_map = {}
                for row in cur.fetchall():
                    eid, val, key = row
                    if eid not in id_map:
                        id_map[eid] = {}
                    if key == 'chroma:document':
                        id_map[eid]['document'] = val
                
                if id_map:
                    eid_list = list(id_map.keys())
                    eid_placeholders = ','.join(['?'] * len(eid_list))
                    cur.execute(f"""
                        SELECT id, string_value FROM embedding_metadata
                        WHERE key = 'source' AND id IN ({eid_placeholders})
                    """, eid_list)
                    
                    for row in cur.fetchall():
                        eid, source = row
                        if source and source not in seen_sources:
                            doc_text = id_map.get(eid, {}).get('document', '')
                            score = sum(1 for w in words if w.lower() in doc_text.lower())
                            score += sum(1 for w in words if w.lower() in source.lower()) * 2
                            
                            if score > 0:
                                seen_sources.add(source)
                                translated = source.replace("/mnt/warehouse", "/mnt/vol1_source", 1)
                                exists = os.path.exists(translated)
                                
                                results.append({
                                    "source": source,
                                    "translated_path": translated,
                                    "exists": exists,
                                    "file_name": os.path.basename(translated),
                                    "snippet": doc_text[:200] if doc_text else "",
                                    "score": score,
                                })
                                
                                if len(results) >= max_results:
                                    break

        conn.close()

        # Sort by score
        results.sort(key=lambda x: x['score'], reverse=True)

        return json.dumps({
            "query": query,
            "oracle_db": CHROMADB_PATH,
            "total_vectors": 224209,
            "total_files": 16883,
            "results": results[:max_results],
            "count": len(results[:max_results]),
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Oracle search failed: {e}"})


@mcp.tool()
def search_email_intel(
    query: str,
    division: Optional[str] = None,
    top_k: int = 5,
) -> str:
    """
    Search Fortress Prime email intelligence database.

    Queries the Qdrant 'email_embeddings' collection that contains classified
    emails from the fortress_db.email_archive.

    Args:
        query: Email search query (topic, sender, subject, keywords)
        division: Filter by division (REAL_ESTATE, HEDGE_FUND, LEGAL_ADMIN, etc.)
        top_k: Number of results (default 5)

    Returns:
        JSON with relevant email excerpts, sender, subject, dates, and classification.

    Example:
        search_email_intel("vendor invoices", division="REAL_ESTATE")
    """
    collection = "email_embeddings"
    query_vec = embed_text(query)

    if not query_vec:
        return json.dumps({"error": "Embedding generation failed"})

    search_payload: Dict[str, Any] = {
        "vector": query_vec,
        "limit": top_k,
        "with_payload": True,
        "with_vector": False,
        "score_threshold": 0.3,
    }

    if division:
        search_payload["filter"] = {
            "must": [{"key": "division", "match": {"value": division}}]
        }

    try:
        resp = requests.post(
            f"{QDRANT_URL}/collections/{collection}/points/search",
            json=search_payload,
            headers=QDRANT_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        hits = resp.json().get("result", [])
    except Exception as e:
        return json.dumps({"error": f"Qdrant search failed: {e}"})

    results = []
    for hit in hits:
        payload = hit.get("payload", {})
        results.append({
            "sender": payload.get("sender", "unknown"),
            "subject": payload.get("subject", ""),
            "date": payload.get("date", ""),
            "division": payload.get("division", ""),
            "body_preview": payload.get("body_text", "")[:300] + "...",
            "score": hit.get("score", 0.0),
        })

    return json.dumps({
        "query": query,
        "division_filter": division,
        "results": results,
        "count": len(results),
    }, indent=2)


# =============================================================================
# STATUS & METADATA TOOLS
# =============================================================================

@mcp.tool()
def get_jordi_status() -> str:
    """
    Get current status of Jordi Visser knowledge base.

    Returns:
        JSON with collection stats, recent transcripts, and ingestion status.
    """
    # Check if Jordi collection exists
    try:
        resp = requests.get(f"{QDRANT_URL}/collections/jordi_intel", headers=QDRANT_HEADERS, timeout=10)
        if resp.status_code == 200:
            info = resp.json().get("result", {})
            status = {
                "collection": "jordi_intel",
                "status": "active",
                "vectors": info.get("points_count", 0),
                "last_updated": info.get("updated", "unknown"),
            }
        else:
            status = {
                "collection": "jordi_intel",
                "status": "not_created",
                "vectors": 0,
                "note": "Collection needs to be created and populated",
            }
    except Exception:
        status = {
            "collection": "jordi_intel",
            "status": "qdrant_offline",
            "error": "Cannot reach Qdrant server",
        }

    # Check for source files
    if os.path.exists(JORDI_TRANSCRIPTS_PATH):
        transcripts = [f for f in os.listdir(JORDI_TRANSCRIPTS_PATH) if f.endswith(('.pdf', '.txt', '.md'))]
        status["source_files"] = len(transcripts)
        status["source_path"] = JORDI_TRANSCRIPTS_PATH
    else:
        status["source_files"] = 0
        status["source_path"] = f"{JORDI_TRANSCRIPTS_PATH} (not found)"

    return json.dumps(status, indent=2)


@mcp.tool()
def list_collections() -> str:
    """
    List all available Qdrant vector collections in Fortress Prime.

    Returns:
        JSON with collection names, vector counts, and purposes.
    """
    try:
        resp = requests.get(f"{QDRANT_URL}/collections", headers=QDRANT_HEADERS, timeout=10)
        resp.raise_for_status()
        collections = resp.json().get("result", {}).get("collections", [])

        collection_info = []
        for coll in collections:
            name = coll.get("name", "unknown")
            # Get detailed stats
            detail_resp = requests.get(f"{QDRANT_URL}/collections/{name}", headers=QDRANT_HEADERS, timeout=10)
            if detail_resp.status_code == 200:
                info = detail_resp.json().get("result", {})
                collection_info.append({
                    "name": name,
                    "vectors": info.get("points_count", 0),
                    "status": info.get("status", "unknown"),
                })

        return json.dumps({
            "qdrant_url": QDRANT_URL,
            "collections": collection_info,
            "count": len(collection_info),
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to list collections: {e}"})


@mcp.tool()
def get_fortress_stats() -> str:
    """
    Get overall Fortress Prime knowledge base statistics.

    Returns:
        JSON with stats across all vector DBs, postgres tables, and NAS paths.
    """
    stats = {
        "timestamp": datetime.now().isoformat(),
        "qdrant": {},
        "chromadb": {},
        "postgres": {},
        "nas": {},
    }

    # Qdrant stats
    try:
        resp = requests.get(f"{QDRANT_URL}/collections", headers=QDRANT_HEADERS, timeout=10)
        if resp.status_code == 200:
            collections = resp.json().get("result", {}).get("collections", [])
            stats["qdrant"]["status"] = "online"
            stats["qdrant"]["collections_count"] = len(collections)
        else:
            stats["qdrant"]["status"] = "offline"
    except Exception:
        stats["qdrant"]["status"] = "offline"

    # ChromaDB stats
    if os.path.exists(CHROMADB_PATH):
        stats["chromadb"]["status"] = "online"
        stats["chromadb"]["path"] = CHROMADB_PATH
        stats["chromadb"]["vectors"] = 224209
        stats["chromadb"]["files"] = 16883
    else:
        stats["chromadb"]["status"] = "not_found"

    # PostgreSQL stats (placeholder - would need psycopg2 connection)
    stats["postgres"]["host"] = PG_HOST
    stats["postgres"]["database"] = PG_DB
    stats["postgres"]["status"] = "check_manually"

    # NAS stats
    stats["nas"]["root"] = NAS_ROOT
    stats["nas"]["mounted"] = os.path.exists(NAS_ROOT)

    return json.dumps(stats, indent=2)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    print("=" * 70)
    print("  FORTRESS PRIME — SOVEREIGN CONTEXT PROTOCOL")
    print("  MCP Server Online")
    print("=" * 70)
    print()
    print("  Resources:")
    print("    - sovereign://godhead/jordi      (Jordi Visser persona)")
    print("    - sovereign://godhead/legal      (Legal Counselor persona)")
    print("    - sovereign://godhead/crog       (CROG Controller persona)")
    print("    - sovereign://godhead/comp       (Comptroller persona)")
    print("    - sovereign://atlas              (Full org chart)")
    print()
    print("  Tools:")
    print("    - search_jordi_knowledge()       (Jordi transcripts)")
    print("    - search_fortress_legal()        (Legal documents)")
    print("    - search_oracle()                (224K general knowledge)")
    print("    - search_email_intel()           (Email archive)")
    print("    - list_collections()             (Vector DB inventory)")
    print("    - get_fortress_stats()           (System health)")
    print()
    print("  Connect from Cursor:")
    print("    Settings > Features > MCP > Add Server")
    print(f"    Command: python {os.path.abspath(__file__)}")
    print()
    print("=" * 70)

    mcp.run()
