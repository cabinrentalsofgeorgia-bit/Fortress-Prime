"""
LEGAL STEWARD — Document Indexing Agent for Fortress JD (S05)
==============================================================
Fortress Prime | Turns cold NAS storage into hot vector memory.

Wraps the CF-03 CounselorCRM ingestion pipeline in the OODA pattern.
Scans /mnt/fortress_nas/Corporate_Legal/ and division_legal/knowledge_base/,
extracts text, chunks it, embeds locally via nomic-embed-text, and pushes
vectors into Qdrant legal_library.

Unlike a dumb crawler, the Steward:
    1. Tracks what's indexed vs what's new (incremental by file hash)
    2. Classifies documents into 12 legal categories
    3. Reports gaps (failed extractions, empty documents)
    4. Logs everything to system_post_mortems (Article III)
    5. Can be run on-demand or scheduled via cron

Usage:
    # Full index (resume mode — skip already-indexed files)
    python3 -m src.agents.legal_steward

    # Full re-index (ignore resume)
    python3 -m src.agents.legal_steward --full-reindex

    # Dry run (count and classify only)
    python3 -m src.agents.legal_steward --dry-run

    # Index a specific subdirectory
    python3 -m src.agents.legal_steward --source /mnt/fortress_nas/Corporate_Legal/Leases/

    # Also index Georgia statutes
    python3 -m src.agents.legal_steward --include-statutes

Governing Documents:
    CONSTITUTION.md  — Article I (zero cloud), Article III (OODA mandate)
    fortress_atlas.yaml — S05 nas_paths
"""

from __future__ import annotations

import os
import sys
import logging
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("agents.legal_steward")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# I. PYDANTIC MODELS
# =============================================================================

class IndexingStats(BaseModel):
    """Results of a Steward indexing run."""
    files_discovered: int = 0
    files_ingested: int = 0
    files_skipped: int = 0
    files_empty: int = 0
    files_errored: int = 0
    chunks_created: int = 0
    qdrant_total_vectors: int = 0
    duration_seconds: float = 0.0
    categories: dict = Field(default_factory=dict)
    source_dir: str = ""
    dry_run: bool = False


class StewardReport(BaseModel):
    """Complete report from the Steward agent."""
    stats: IndexingStats
    success: bool = False
    error: Optional[str] = None
    audit_trail: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = Field(default="fortress_local")


# =============================================================================
# II. OODA NODE IMPLEMENTATIONS
# =============================================================================

def observe(state: dict) -> dict:
    """OBSERVE: Discover files, classify, and count."""
    now = datetime.now(timezone.utc).isoformat()
    source_dir = state.get("_source_dir", "/mnt/fortress_nas/Corporate_Legal/")
    include_statutes = state.get("_include_statutes", False)

    try:
        import importlib.util
        ingest_path = PROJECT_ROOT / "Modules" / "CF-03_CounselorCRM" / "ingest_docs.py"
        spec = importlib.util.spec_from_file_location("cf03_ingest", str(ingest_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        files = mod.discover_files(source_dir)
        if include_statutes:
            statute_dir = str(PROJECT_ROOT / "division_legal" / "knowledge_base")
            statute_files = mod.discover_files(statute_dir)
            files.extend(statute_files)

        # Classify
        categories = {}
        for f in files:
            cat = mod.classify_document(f)
            categories[cat] = categories.get(cat, 0) + 1

        state["_files"] = files
        state["_categories"] = categories
        state["_ingest_mod"] = mod

        state["observation"] = (
            f"Discovered {len(files)} documents in {source_dir}. "
            f"Categories: {dict(sorted(categories.items(), key=lambda x: -x[1]))}."
        )
        state["confidence"] = 0.8 if files else 0.1

    except Exception as e:
        state["observation"] = f"FAILED: Cannot load ingestion module: {e}"
        state["confidence"] = 0.0
        state["_files"] = []
        logger.error(f"Steward observe failed: {e}")

    state["audit_trail"].append(
        f"[{now}] OBSERVE: {len(state.get('_files', []))} files discovered"
    )
    return state


def orient(state: dict) -> dict:
    """ORIENT: Check Qdrant health, determine what's new vs indexed."""
    now = datetime.now(timezone.utc).isoformat()
    mod = state.get("_ingest_mod")
    full_reindex = state.get("_full_reindex", False)

    if not mod or not state.get("_files"):
        state["orientation"] = "No files to index or module unavailable."
        state["audit_trail"].append(f"[{now}] ORIENT: No files")
        return state

    try:
        # Check Qdrant
        if not mod.ensure_collection():
            state["orientation"] = "FAILED: Qdrant collection could not be created."
            state["confidence"] = 0.0
            state["audit_trail"].append(f"[{now}] ORIENT: Qdrant FAILED")
            return state

        # Check embedding model
        test = mod.get_embedding("test")
        if test is None:
            state["orientation"] = "FAILED: Embedding model unreachable."
            state["confidence"] = 0.0
            state["audit_trail"].append(f"[{now}] ORIENT: Embedding FAILED")
            return state

        # Get already-indexed hashes
        if full_reindex:
            skip_hashes = set()
        else:
            skip_hashes = mod.get_indexed_hashes()

        state["_skip_hashes"] = skip_hashes

        new_count = 0
        for f in state["_files"]:
            fid = mod.file_hash(f)
            if fid not in skip_hashes:
                new_count += 1

        existing_count = mod.get_collection_count()

        state["orientation"] = (
            f"Qdrant OK ({existing_count} vectors). "
            f"Embedding OK. "
            f"{new_count} new files to index "
            f"({len(skip_hashes)} already indexed)."
        )

    except Exception as e:
        state["orientation"] = f"FAILED: Pre-flight check error: {e}"
        state["confidence"] = 0.0

    state["audit_trail"].append(f"[{now}] ORIENT: {state['orientation'][:150]}")
    return state


def decide(state: dict) -> dict:
    """DECIDE: Proceed with indexing or abort."""
    now = datetime.now(timezone.utc).isoformat()

    if state.get("confidence", 0) < 0.3:
        state["decision"] = "ABORT: Pre-flight checks failed."
    elif state.get("_dry_run"):
        state["decision"] = "DRY RUN: Report classification only, no indexing."
    elif not state.get("_files"):
        state["decision"] = "ABORT: No files discovered."
    else:
        state["decision"] = (
            f"PROCEED: Index {len(state['_files'])} files "
            f"into Qdrant legal_library."
        )

    state["audit_trail"].append(f"[{now}] DECIDE: {state['decision'][:100]}")
    return state


def act(state: dict) -> dict:
    """ACT: Run the CF-03 ingestion pipeline with OODA tracking."""
    now = datetime.now(timezone.utc).isoformat()
    mod = state.get("_ingest_mod")
    files = state.get("_files", [])
    skip_hashes = state.get("_skip_hashes", set())

    if "ABORT" in state.get("decision", "") or state.get("_dry_run"):
        stats = IndexingStats(
            files_discovered=len(files),
            categories=state.get("_categories", {}),
            source_dir=state.get("_source_dir", ""),
            dry_run=state.get("_dry_run", False),
        )
        state["_stats"] = stats
        state["action_result"] = (
            f"{'DRY RUN' if state.get('_dry_run') else 'ABORTED'}: "
            f"{len(files)} files discovered, 0 ingested."
        )
        state["audit_trail"].append(f"[{now}] ACT: {state['action_result']}")
        return state

    # Run ingestion
    t0 = time.time()
    ingest_stats = {"ingested": 0, "skipped": 0, "empty": 0, "errors": 0, "chunks": 0}

    for idx, filepath in enumerate(files, 1):
        fid = mod.file_hash(filepath)
        if fid in skip_hashes:
            ingest_stats["skipped"] += 1
            continue

        try:
            ok = mod.ingest_file(filepath, fid, ingest_stats)
            if ok and idx % 25 == 0:
                logger.info(f"  [{idx}/{len(files)}] Indexed {filepath.name}")
        except Exception as e:
            ingest_stats["errors"] += 1
            logger.warning(f"  Failed: {filepath.name}: {e}")

    duration = time.time() - t0
    final_count = mod.get_collection_count()

    stats = IndexingStats(
        files_discovered=len(files),
        files_ingested=ingest_stats["ingested"],
        files_skipped=ingest_stats["skipped"],
        files_empty=ingest_stats["empty"],
        files_errored=ingest_stats["errors"],
        chunks_created=ingest_stats["chunks"],
        qdrant_total_vectors=final_count,
        duration_seconds=round(duration, 1),
        categories=state.get("_categories", {}),
        source_dir=state.get("_source_dir", ""),
    )
    state["_stats"] = stats

    state["action_result"] = (
        f"SUCCESS: Indexed {stats.files_ingested} files "
        f"({stats.chunks_created} chunks) in {duration:.0f}s. "
        f"Qdrant total: {final_count} vectors. "
        f"Errors: {stats.files_errored}."
    )
    state["audit_trail"].append(f"[{now}] ACT: {state['action_result'][:200]}")
    return state


# =============================================================================
# III. AGENT ASSEMBLY
# =============================================================================

def run_steward(
    source_dir: str = "/mnt/fortress_nas/Corporate_Legal/",
    full_reindex: bool = False,
    dry_run: bool = False,
    include_statutes: bool = False,
) -> StewardReport:
    """
    High-level API: Run the Legal Steward to index documents.

    Uses run_ooda_sequence (sequential runner) instead of LangGraph StateGraph
    to preserve internal state keys (_files, _ingest_mod, _skip_hashes) that
    LangGraph's TypedDict channels would drop between nodes.

    Returns a StewardReport with full stats and OODA audit trail.
    """
    from src.sovereign_ooda import make_initial_state, run_ooda_sequence

    initial = make_initial_state(sector="legal", query=f"steward:index:{source_dir}")
    initial["_source_dir"] = source_dir
    initial["_full_reindex"] = full_reindex
    initial["_dry_run"] = dry_run
    initial["_include_statutes"] = include_statutes

    result_state = run_ooda_sequence(
        state=initial,
        observe_fn=observe,
        orient_fn=orient,
        decide_fn=decide,
        act_fn=act,
    )

    stats = result_state.get("_stats", IndexingStats())

    return StewardReport(
        stats=stats,
        success="SUCCESS" in result_state.get("action_result", ""),
        error=result_state.get("action_result") if "FAILED" in result_state.get("action_result", "") else None,
        audit_trail=result_state.get("audit_trail", []),
    )


# =============================================================================
# IV. CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Legal Steward — Document Indexing Agent for Fortress JD"
    )
    parser.add_argument(
        "--source", default="/mnt/fortress_nas/Corporate_Legal/",
        help="Source directory to scan (default: Corporate_Legal)",
    )
    parser.add_argument("--full-reindex", action="store_true", help="Re-index all files")
    parser.add_argument("--dry-run", action="store_true", help="Count and classify only")
    parser.add_argument("--include-statutes", action="store_true",
                        help="Also index division_legal/knowledge_base/ GA statutes")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    print("=" * 65)
    print("  LEGAL STEWARD — DOCUMENT INDEXING AGENT")
    print(f"  Source: {args.source}")
    print(f"  Mode: {'DRY RUN' if args.dry_run else 'FULL REINDEX' if args.full_reindex else 'INCREMENTAL'}")
    print("=" * 65)

    report = run_steward(
        source_dir=args.source,
        full_reindex=args.full_reindex,
        dry_run=args.dry_run,
        include_statutes=args.include_statutes,
    )

    s = report.stats
    print(f"\n  Files discovered:  {s.files_discovered}")
    print(f"  Files ingested:    {s.files_ingested}")
    print(f"  Files skipped:     {s.files_skipped}")
    print(f"  Chunks created:    {s.chunks_created}")
    print(f"  Qdrant vectors:    {s.qdrant_total_vectors}")
    print(f"  Duration:          {s.duration_seconds:.0f}s")
    if s.categories:
        print(f"\n  Categories:")
        for cat, count in sorted(s.categories.items(), key=lambda x: -x[1]):
            print(f"    {cat:<25} {count:>5}")
    print()


if __name__ == "__main__":
    main()
