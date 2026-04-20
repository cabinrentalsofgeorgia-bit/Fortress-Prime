"""
Fortress Prime — Centralized Path Resolver
=============================================
Single source of truth for ALL data paths in the system.

Separates COMPUTE (Spark machines) from STATE (Synology NAS).
Every module imports paths from here — no more hardcoded Path(__file__).

ARCHITECTURE:
    Spark Machine (DGX/Spark 2):  Compute + GPU.   Runs the LLM.
    Synology NAS (192.168.0.103): Memory + State.   Holds the data.
    Laptop:                       Executive.        Reviews drafts.

STORAGE TIERS (Synology 1825+):
    ┌──────────────────────────────────────────────────────────────┐
    │  FAST LANE — NVMe (Volume 2)                                │
    │  Mount: /mnt/ai_fast          580 GB free                   │
    │  For:   ChromaDB vectors, hot indexes, active RAG caches    │
    │  Speed: ~3,000 MB/s sequential, ~500K IOPS random           │
    ├──────────────────────────────────────────────────────────────┤
    │  BRAIN — NVMe (Volume 2)                                    │
    │  Mount: /mnt/fortress_nas     580 GB free (same volume)     │
    │  For:   AI brain (logs, starred DB, cabins, config state)   │
    ├──────────────────────────────────────────────────────────────┤
    │  BULK — HDD RAID (Volume 1)                                 │
    │  Mount: /mnt/ai_bulk          56 TB free                    │
    │  For:   OCR archives, raw PDFs, Enterprise War Room, models │
    │  Speed: ~200 MB/s sequential (RAID), cheap per-TB storage   │
    └──────────────────────────────────────────────────────────────┘

RESOLUTION ORDER (Brain tier):
    1. Environment variable override (e.g., FORTRESS_DATA_DIR)
    2. NAS mount at /mnt/fortress_nas/fortress_data/ai_brain
    3. Local fallback at ./data (project root)

Usage:
    from src.fortress_paths import paths

    # Brain tier (AI state)
    db = paths.starred_db         # NAS: .../ai_brain/starred_responses.db
    logs = paths.logs_dir         # NAS: .../ai_brain/logs/

    # Fast tier (NVMe speed)
    chroma = paths.chroma_db      # /mnt/ai_fast/chroma_db
    cache = paths.fast_cache      # /mnt/ai_fast/cache

    # Bulk tier (HDD capacity)
    war = paths.war_room          # /mnt/ai_bulk/Enterprise_War_Room
    ocr = paths.ocr_archive       # /mnt/ai_bulk/ocr_archive

    # Status dashboard
    paths.print_status()
"""

import os
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict

logger = logging.getLogger("fortress.paths")

# =============================================================================
# CONSTANTS — MOUNT POINTS
# =============================================================================

# Project root (Fortress-Prime/)
PROJECT_ROOT = Path(__file__).parent.parent

# ── NAS Mount Points (Synology 1825+) ──

# Brain tier — Volume 2 / ai-data (NVMe, AI state)
NAS_MOUNT = Path("/mnt/fortress_nas")
NAS_AI_DIR = NAS_MOUNT / "fortress_data" / "ai_brain"

# Fast tier — LOCAL NVMe (was /mnt/ai_fast NFS, migrated 2026-02-10)
# ChromaDB and vector indexes MUST live on local disk for IOPS + stability.
# NFS introduced: NFS ghost files (.nfs*), WAL corruption on disk-full,
# HNSW pickle truncation on force-kill, and 577 GB bloat from stale handles.
FAST_MOUNT = Path("/home/admin/fortress_fast")
# Legacy NFS mount kept for reference (DO NOT USE for hot data)
_LEGACY_NFS_FAST = Path("/mnt/ai_fast")

# Bulk tier — Volume 1 / ai_bulk (HDD RAID, raw archives + models)
BULK_MOUNT = Path("/mnt/ai_bulk")

# ── Environment variable overrides ──
ENV_DATA_DIR = "FORTRESS_DATA_DIR"
ENV_FAST_DIR = "FORTRESS_FAST_DIR"
ENV_BULK_DIR = "FORTRESS_BULK_DIR"

# ── Local fallbacks ──
LOCAL_DATA_DIR = PROJECT_ROOT / "data"
LOCAL_FAST_DIR = PROJECT_ROOT / "data" / "fast"
LOCAL_BULK_DIR = PROJECT_ROOT / "data" / "bulk"


# =============================================================================
# MOUNT HEALTH CHECK
# =============================================================================

def _is_mounted(path: Path) -> bool:
    """Check if a path is an active NFS/CIFS mount point."""
    try:
        return path.exists() and path.is_mount()
    except Exception:
        return False


def _is_writable(path: Path) -> bool:
    """Check if a path is writable (quick test)."""
    try:
        test_file = path / ".fortress_write_test"
        test_file.touch()
        test_file.unlink()
        return True
    except Exception:
        return False


# =============================================================================
# PATH RESOLVER
# =============================================================================

@dataclass
class FortressPaths:
    """
    Resolved paths for all Fortress Prime data across three storage tiers.

    Brain:  AI state (logs, starred DB, cabins)   — survives machine upgrades
    Fast:   NVMe hot data (ChromaDB, caches)      — speed for vector search
    Bulk:   HDD archives (OCR, PDFs, War Room)    — capacity for raw data
    """

    # Resolved base directories
    base_dir: Path          # Brain tier
    fast_dir: Path          # Fast tier
    bulk_dir: Path          # Bulk tier

    # Where each tier resolved from
    source: str             # Brain: "nas", "local", "env"
    fast_source: str = ""   # Fast: "nas", "local", "env"
    bulk_source: str = ""   # Bulk: "nas", "local", "env"

    # ── BRAIN TIER (AI state — NVMe Volume 2) ──

    @property
    def starred_db(self) -> Path:
        """Path to starred_responses.db (the learning brain)."""
        return self.base_dir / "starred_responses.db"

    @property
    def logs_dir(self) -> Path:
        """Directory for prompt execution logs (daily JSONL files)."""
        return self.base_dir / "logs"

    @property
    def gmail_watch_dir(self) -> Path:
        """Directory for Gmail watcher processing logs."""
        return self.base_dir / "logs" / "gmail_watcher"

    @property
    def rag_ingest_log_dir(self) -> Path:
        """Directory for RAG ingestion logs."""
        return self.base_dir / "logs" / "rag_ingest"

    @property
    def rag_query_log_dir(self) -> Path:
        """Directory for RAG query logs."""
        return self.base_dir / "logs" / "rag_query"

    @property
    def cabins_dir(self) -> Path:
        """Directory for cabin data YAML files."""
        return self.base_dir / "cabins"

    # ── FAST TIER (NVMe hot data — Vector DBs, caches) ──

    @property
    def chroma_db(self) -> Path:
        """ChromaDB persistent storage (NVMe for fast vector retrieval)."""
        return self.fast_dir / "chroma_db"

    @property
    def vector_db(self) -> Path:
        """General vector database storage (NVMe)."""
        return self.fast_dir / "vector_db"

    @property
    def fast_cache(self) -> Path:
        """Fast cache directory (embeddings, reranker results)."""
        return self.fast_dir / "cache"

    @property
    def ingestion_queue(self) -> Path:
        """Active ingestion working directory (NVMe for I/O-heavy processing)."""
        return self.fast_dir / "ingestion_queue"

    # ── BULK TIER (HDD archives — raw data, OCR output, models) ──

    @property
    def war_room(self) -> Path:
        """Enterprise War Room — all recovered/organized business documents."""
        return self.bulk_dir / "Enterprise_War_Room"

    @property
    def ocr_archive(self) -> Path:
        """OCR output archive — processed document text (write-once, read-many)."""
        return self.bulk_dir / "ocr_archive"

    @property
    def model_cache(self) -> Path:
        """Ollama model weights cache (large, cold, archival)."""
        return self.bulk_dir / "models"

    @property
    def raw_documents(self) -> Path:
        """Raw source documents before processing."""
        return self.bulk_dir / "raw_documents"

    # ── ALWAYS-LOCAL PATHS (never on NAS) ──

    @property
    def prompts_dir(self) -> Path:
        """Prompt templates — ALWAYS local (version-controlled code)."""
        return PROJECT_ROOT / "prompts"

    @property
    def credentials_dir(self) -> Path:
        """OAuth credentials — ALWAYS local (secrets never on shared storage)."""
        return PROJECT_ROOT / "credentials"

    # ── UTILITIES ──

    def ensure_dirs(self):
        """Create all required directories if they don't exist."""
        brain_dirs = [self.logs_dir, self.gmail_watch_dir, self.cabins_dir,
                      self.rag_ingest_log_dir, self.rag_query_log_dir]
        fast_dirs = [self.chroma_db, self.vector_db, self.fast_cache]
        bulk_dirs = [self.ocr_archive]

        for d in brain_dirs + fast_dirs + bulk_dirs:
            try:
                d.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.debug(f"Could not create {d}: {e}")

    def tier_status(self) -> Dict[str, dict]:
        """Return health status for each tier."""
        return {
            "brain": {
                "path": str(self.base_dir),
                "source": self.source,
                "mounted": _is_mounted(NAS_MOUNT),
                "writable": _is_writable(self.base_dir),
            },
            "fast": {
                "path": str(self.fast_dir),
                "source": self.fast_source,
                "mounted": _is_mounted(FAST_MOUNT),
                "writable": _is_writable(self.fast_dir),
            },
            "bulk": {
                "path": str(self.bulk_dir),
                "source": self.bulk_source,
                "mounted": _is_mounted(BULK_MOUNT),
                "writable": _is_writable(self.bulk_dir),
            },
        }

    def print_status(self):
        """Print where all data is resolved to across all tiers."""
        status = self.tier_status()

        print("=" * 72)
        print("  FORTRESS PRIME — STORAGE TIER MAP")
        print("=" * 72)

        tier_info = [
            ("BRAIN", "brain", "NVMe Vol2", "AI state, logs, starred DB, cabins",
             [("starred_db", self.starred_db),
              ("logs/", self.logs_dir),
              ("logs/gmail_watcher/", self.gmail_watch_dir),
              ("cabins/", self.cabins_dir)]),
            ("FAST", "fast", "NVMe Vol2", "ChromaDB vectors, caches, hot indexes",
             [("chroma_db/", self.chroma_db),
              ("vector_db/", self.vector_db),
              ("cache/", self.fast_cache)]),
            ("BULK", "bulk", "HDD Vol1", "OCR archives, War Room, raw documents",
             [("Enterprise_War_Room/", self.war_room),
              ("ocr_archive/", self.ocr_archive),
              ("models/", self.model_cache)]),
        ]

        for tier_name, tier_key, hardware, purpose, items in tier_info:
            s = status[tier_key]
            mounted = "MOUNTED" if s["mounted"] else "LOCAL"
            writable = "rw" if s["writable"] else "ro"

            print(f"\n  {'━' * 66}")
            print(f"  {tier_name} TIER ({hardware}) — {purpose}")
            print(f"  {'━' * 66}")
            print(f"  Source:  {s['source'].upper():<6} | Status: {mounted} ({writable})")
            print(f"  Path:    {s['path']}")

            for name, path in items:
                exists = "YES" if path.exists() else " - "
                print(f"    {name:<28} {exists:>3}  {path}")

        # Always-local
        print(f"\n  {'━' * 66}")
        print(f"  LOCAL (always on Spark machine — never on NAS)")
        print(f"  {'━' * 66}")
        for name, path in [("prompts/", self.prompts_dir), ("credentials/", self.credentials_dir)]:
            exists = "YES" if path.exists() else " - "
            print(f"    {name:<28} {exists:>3}  {path}")

        print(f"\n{'=' * 72}")


def _resolve_tier(
    env_var: str,
    nas_mount: Path,
    nas_subdir: Path,
    local_fallback: Path,
    tier_name: str,
) -> tuple:
    """
    Generic tier resolver. Checks env -> NAS/NFS mount -> local dir -> fallback.

    Resolution order:
        1. Environment variable override
        2. Active NFS/CIFS mount point (is_mount() == True)
        3. Existing writable local directory (post-migration from NFS to local NVMe)
        4. Local fallback (create if needed)

    Returns:
        (Path, source_string): The resolved path and its origin.
    """
    # Priority 1: Environment variable
    env_dir = os.getenv(env_var)
    if env_dir:
        p = Path(env_dir)
        if p.exists():
            logger.info(f"{tier_name} dir from env: {p}")
            return p, "env"
        else:
            logger.warning(
                f"${env_var}={env_dir} does not exist. "
                f"Falling through to NAS/local."
            )

    # Priority 2: Active NFS/CIFS mount
    if _is_mounted(nas_mount):
        target = nas_subdir
        if target.exists():
            logger.info(f"{tier_name} dir from NAS mount: {target}")
            return target, "nas"
        else:
            try:
                target.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created NAS {tier_name} dir: {target}")
                return target, "nas"
            except PermissionError:
                logger.warning(
                    f"NAS mounted but cannot create {target}. "
                    f"Falling back to local."
                )
            except Exception as e:
                logger.warning(f"NAS {tier_name} dir creation failed: {e}.")

    # Priority 3: Existing local directory (post NFS→local migration)
    # After migrating from NFS to local NVMe (2026-02-10), the data directory
    # exists as a regular dir, not a mount point. Accept it if writable.
    if not _is_mounted(nas_mount) and nas_mount.exists() and nas_mount.is_dir():
        target = nas_subdir
        if target.exists() and _is_writable(target):
            logger.info(f"{tier_name} dir from local path: {target}")
            return target, "local-nvme"

    # Priority 4: Fallback (create if needed)
    local_fallback.mkdir(parents=True, exist_ok=True)
    logger.info(f"{tier_name} dir local fallback: {local_fallback}")
    return local_fallback, "local"


def resolve_paths() -> FortressPaths:
    """
    Resolve all three storage tiers and return the FortressPaths singleton.
    Called once at module load; cached for the process lifetime.
    """
    # Brain tier — AI state (logs, starred DB, cabins)
    base_dir, source = _resolve_tier(
        ENV_DATA_DIR, NAS_MOUNT, NAS_AI_DIR, LOCAL_DATA_DIR, "Brain"
    )

    # Fast tier — NVMe hot data (ChromaDB, vector indexes, caches)
    fast_dir, fast_source = _resolve_tier(
        ENV_FAST_DIR, FAST_MOUNT, FAST_MOUNT, LOCAL_FAST_DIR, "Fast"
    )

    # Bulk tier — HDD archives (OCR, War Room, raw documents)
    bulk_dir, bulk_source = _resolve_tier(
        ENV_BULK_DIR, BULK_MOUNT, BULK_MOUNT, LOCAL_BULK_DIR, "Bulk"
    )

    fp = FortressPaths(
        base_dir=base_dir,
        fast_dir=fast_dir,
        bulk_dir=bulk_dir,
        source=source,
        fast_source=fast_source,
        bulk_source=bulk_source,
    )
    fp.ensure_dirs()
    return fp


# =============================================================================
# SINGLETON — Resolved once at import time
# =============================================================================

paths = resolve_paths()


# =============================================================================
# CONVENIENCE EXPORTS (for modules that import individual paths)
# =============================================================================

# Brain tier
STARRED_DB_PATH = paths.starred_db
LOGS_DIR = paths.logs_dir
CABINS_DIR = paths.cabins_dir
GMAIL_WATCH_DIR = paths.gmail_watch_dir
RAG_INGEST_LOG_DIR = paths.rag_ingest_log_dir
RAG_QUERY_LOG_DIR = paths.rag_query_log_dir
NAS_AI_BRAIN = str(NAS_AI_DIR)

# Fast tier (NVMe)
CHROMA_PATH = str(paths.chroma_db)
VECTOR_DB_PATH = str(paths.vector_db)
FAST_CACHE_DIR = paths.fast_cache

# Bulk tier (HDD)
WAR_ROOM_DIR = paths.war_room
OCR_ARCHIVE_DIR = paths.ocr_archive
MODEL_CACHE_DIR = paths.model_cache


# =============================================================================
# CLI: python -m src.fortress_paths
# =============================================================================

if __name__ == "__main__":
    paths.print_status()
