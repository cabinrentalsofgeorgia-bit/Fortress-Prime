"""
Fortress Prime — Vision Indexer (DGX Image/Video Captioning Pipeline)
======================================================================
Turns the Muscle node's GPU into eyes that "see" every image on the NAS.

The LLM is blind to raw pixels. This pipeline fixes that by:
    1. Crawling Volume 2 for image/video files (.jpg, .png, .mp4, etc.)
    2. Deduplicating via SHA-256 hash (never re-process the same image)
    3. Sending each image to the DGX Vision model (LLaVA / Llama-3.2-Vision)
    4. Storing the AI-generated description so text search can find it

After this runs, the Captain can answer:
    "Find photos of the bathroom renovation from Jan 2025."
by searching text descriptions rather than trying to "see" images.

STORAGE BACKENDS:
    - SQLite (default): Portable, zero-config, stores in the scan directory.
    - PostgreSQL (--pg): Uses the Fortress DB for centralized access.

USAGE:
    python -m src.vision_indexer                                      # scan default NAS path
    python -m src.vision_indexer --scan-dir /mnt/volume2/ai_brain     # custom path
    python -m src.vision_indexer --batch-size 50                      # limit batch
    python -m src.vision_indexer --pg                                 # use PostgreSQL
    python -m src.vision_indexer --reindex                            # force re-caption all
    python -m src.vision_indexer --sidecar                            # also write .json sidecars

CLUSTER INTEGRATION:
    Uses config.py's Muscle node (Spark 1) for vision inference.
    The Captain (Spark 2) dispatches images to the Muscle's GPU.
"""

import os
import sys
import json
import time
import hashlib
import base64
import sqlite3
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

# =============================================================================
# CONFIGURATION
# =============================================================================

# Default scan directory (Volume 2 / AI Brain on NAS)
DEFAULT_SCAN_DIR = os.getenv(
    "FORTRESS_VISION_SCAN_DIR",
    "/mnt/volume2/ai_brain"
)

# Image/video extensions to process
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".heic", ".heif",
}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

# Directories to skip entirely
SKIP_DIRS = {
    "__pycache__", ".git", "node_modules", "@eaDir",
    ".Spotlight-V100", ".Trashes", ".fseventsd",
}

# Vision prompt — instruct the model for maximum forensic detail
VISION_PROMPT = (
    "Describe this image in extreme detail. "
    "Identify any construction defects, specific tools, equipment, or people visible. "
    "If it is a document, read and transcribe all visible text. "
    "If it contains a receipt, invoice, or contract, extract dates, amounts, "
    "parties, and key terms. "
    "Note the apparent setting, lighting conditions, and any timestamps or watermarks."
)

# =============================================================================
# LOGGING
# =============================================================================

logger = logging.getLogger("fortress.vision_indexer")


def _setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S")


# =============================================================================
# CLUSTER: VISION MODEL CLIENT
# =============================================================================

def _get_vision_client():
    """
    Import config.py and return the Muscle vision endpoint + model name.
    Falls back to environment variables if config is unavailable.
    """
    try:
        from config import (
            MUSCLE_NODE,
            MUSCLE_VISION_MODEL,
            MUSCLE_GENERATE_URL,
        )
        return {
            "generate_url": MUSCLE_GENERATE_URL,
            "model": MUSCLE_VISION_MODEL,
            "node": MUSCLE_NODE,
        }
    except ImportError:
        logger.warning("config.py not found — using environment variables")
        from config import SPARK_02_IP
        node = os.getenv("MUSCLE_NODE", f"http://{SPARK_02_IP}:11434")
        model = os.getenv("MUSCLE_VISION_MODEL", "llama3.2-vision:90b")
        return {
            "generate_url": f"{node}/api/generate",
            "model": model,
            "node": node,
        }


def describe_image(
    image_path: str,
    client: dict,
    prompt: str = VISION_PROMPT,
    timeout: int = 300,
) -> Optional[str]:
    """
    Send an image to the Muscle node's vision model and get a text description.

    The image is base64-encoded and sent via Ollama's /api/generate endpoint.

    Args:
        image_path: Path to the image file.
        client:     Dict with 'generate_url', 'model', 'node'.
        prompt:     The instruction prompt for the vision model.
        timeout:    Request timeout in seconds.

    Returns:
        The AI-generated description string, or None on failure.
    """
    import requests

    try:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to read image {image_path}: {e}")
        return None

    payload = {
        "model": client["model"],
        "prompt": prompt,
        "images": [image_b64],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 4096,
        },
    }

    try:
        resp = requests.post(
            client["generate_url"],
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except requests.exceptions.Timeout:
        logger.error(f"Timeout processing {image_path} (>{timeout}s)")
        return None
    except requests.exceptions.ConnectionError:
        logger.error(
            f"Cannot reach Muscle node at {client['node']}. "
            f"Is the vision model running?"
        )
        return None
    except Exception as e:
        logger.error(f"Vision inference failed for {image_path}: {e}")
        return None


# =============================================================================
# HASHING (Deduplication)
# =============================================================================

def calculate_sha256(filepath: str) -> str:
    """SHA-256 hash of a file, read in 4K blocks."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(block)
    return sha256_hash.hexdigest()


# =============================================================================
# STORAGE: SQLite Backend
# =============================================================================

class SQLiteIndex:
    """
    Lightweight SQLite index for vision captions.
    Stored alongside the scanned directory for portability.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._init_table()

    def _init_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS vision_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filepath TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                sha256 TEXT NOT NULL UNIQUE,
                file_size INTEGER,
                file_ext TEXT,
                description TEXT,
                model_used TEXT,
                indexed_at TEXT NOT NULL,
                processing_time_s REAL
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sha256 ON vision_index(sha256)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_relative_path ON vision_index(relative_path)"
        )
        self.conn.commit()

    def has_hash(self, sha256: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM vision_index WHERE sha256 = ?", (sha256,)
        ).fetchone()
        return row is not None

    def insert(self, record: dict):
        self.conn.execute(
            """INSERT OR REPLACE INTO vision_index
               (filepath, relative_path, sha256, file_size, file_ext,
                description, model_used, indexed_at, processing_time_s)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record["filepath"],
                record["relative_path"],
                record["sha256"],
                record["file_size"],
                record["file_ext"],
                record["description"],
                record["model_used"],
                record["indexed_at"],
                record["processing_time_s"],
            ),
        )
        self.conn.commit()

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM vision_index").fetchone()
        return row[0] if row else 0

    def search(self, query: str, limit: int = 20) -> list:
        """Basic text search across descriptions."""
        rows = self.conn.execute(
            """SELECT relative_path, description, indexed_at
               FROM vision_index
               WHERE description LIKE ?
               ORDER BY indexed_at DESC
               LIMIT ?""",
            (f"%{query}%", limit),
        ).fetchall()
        return [
            {"path": r[0], "description": r[1], "indexed_at": r[2]}
            for r in rows
        ]

    def close(self):
        self.conn.close()


# =============================================================================
# STORAGE: PostgreSQL Backend
# =============================================================================

class PostgresIndex:
    """
    PostgreSQL index for vision captions.
    Uses the Fortress DB for centralized, searchable access.
    """

    def __init__(self):
        import psycopg2
        from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

        self.conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
        self._init_table()

    def _init_table(self):
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vision_index (
                id SERIAL PRIMARY KEY,
                filepath TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                sha256 TEXT NOT NULL UNIQUE,
                file_size BIGINT,
                file_ext TEXT,
                description TEXT,
                model_used TEXT,
                indexed_at TIMESTAMP NOT NULL,
                processing_time_s REAL
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_vision_sha256 ON vision_index(sha256)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_vision_relpath ON vision_index(relative_path)"
        )
        self.conn.commit()

    def has_hash(self, sha256: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM vision_index WHERE sha256 = %s", (sha256,))
        return cur.fetchone() is not None

    def insert(self, record: dict):
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO vision_index
               (filepath, relative_path, sha256, file_size, file_ext,
                description, model_used, indexed_at, processing_time_s)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (sha256) DO UPDATE SET
                   description = EXCLUDED.description,
                   model_used = EXCLUDED.model_used,
                   indexed_at = EXCLUDED.indexed_at,
                   processing_time_s = EXCLUDED.processing_time_s""",
            (
                record["filepath"],
                record["relative_path"],
                record["sha256"],
                record["file_size"],
                record["file_ext"],
                record["description"],
                record["model_used"],
                record["indexed_at"],
                record["processing_time_s"],
            ),
        )
        self.conn.commit()

    def count(self) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM vision_index")
        row = cur.fetchone()
        return row[0] if row else 0

    def search(self, query: str, limit: int = 20) -> list:
        cur = self.conn.cursor()
        cur.execute(
            """SELECT relative_path, description, indexed_at
               FROM vision_index
               WHERE description ILIKE %s
               ORDER BY indexed_at DESC
               LIMIT %s""",
            (f"%{query}%", limit),
        )
        return [
            {"path": r[0], "description": r[1], "indexed_at": str(r[2])}
            for r in cur.fetchall()
        ]

    def close(self):
        self.conn.close()


# =============================================================================
# SIDECAR JSON WRITER
# =============================================================================

def write_sidecar(image_path: str, record: dict):
    """
    Write a .json sidecar file next to the image.
    e.g., IMG_001.jpg -> IMG_001.json
    """
    sidecar_path = os.path.splitext(image_path)[0] + ".json"
    sidecar_data = {
        "source_file": os.path.basename(image_path),
        "sha256": record["sha256"],
        "description": record["description"],
        "model": record["model_used"],
        "indexed_at": record["indexed_at"],
        "processing_time_s": record["processing_time_s"],
    }
    try:
        with open(sidecar_path, "w") as f:
            json.dump(sidecar_data, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to write sidecar {sidecar_path}: {e}")


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def run_vision_indexer(
    scan_dir: str,
    use_pg: bool = False,
    batch_size: int = 0,
    reindex: bool = False,
    write_sidecars: bool = False,
    image_only: bool = False,
):
    """
    Crawl a directory, caption every image with the DGX vision model,
    and store descriptions in the index.

    Args:
        scan_dir:        Root directory to scan for images.
        use_pg:          Use PostgreSQL instead of SQLite.
        batch_size:      Max images to process (0 = unlimited).
        reindex:         Force re-captioning even if hash exists.
        write_sidecars:  Write .json sidecar files next to images.
        image_only:      Skip video files, images only.
    """
    # Determine valid extensions
    valid_exts = set(IMAGE_EXTENSIONS)
    if not image_only:
        valid_exts |= VIDEO_EXTENSIONS

    print("=" * 70)
    print("  FORTRESS PRIME — VISION INDEXER (DGX Pipeline)")
    print("=" * 70)
    print(f"  Scan Directory : {scan_dir}")
    print(f"  Valid Formats   : {', '.join(sorted(valid_exts))}")
    print(f"  Batch Size      : {'unlimited' if batch_size == 0 else batch_size}")
    print(f"  Storage Backend : {'PostgreSQL' if use_pg else 'SQLite'}")
    print(f"  Reindex         : {'YES' if reindex else 'NO'}")
    print(f"  Sidecars        : {'YES' if write_sidecars else 'NO'}")
    print("=" * 70)

    # Validate scan directory
    if not os.path.isdir(scan_dir):
        logger.error(f"Scan directory does not exist: {scan_dir}")
        print(f"\n  [ABORT] Cannot access: {scan_dir}")
        print("  Verify the NAS mount and path. Exiting.")
        sys.exit(1)

    # Initialize storage backend
    if use_pg:
        index = PostgresIndex()
        logger.info("Connected to PostgreSQL (Fortress DB)")
    else:
        db_path = os.path.join(scan_dir, "vision_index.db")
        index = SQLiteIndex(db_path)
        logger.info(f"SQLite index at: {db_path}")

    # Initialize vision client
    client = _get_vision_client()
    print(f"  Vision Model   : {client['model']}")
    print(f"  Muscle Node    : {client['node']}")
    print(f"  Existing Index : {index.count():,} entries")
    print("=" * 70)

    # Discover files
    print("\n  Discovering image/video files...")
    file_list = []
    for root, dirs, files in os.walk(scan_dir):
        # Skip system/hidden directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext in valid_exts:
                file_list.append(os.path.join(root, fname))

    print(f"  Found {len(file_list):,} files to evaluate.\n")

    if not file_list:
        print("  No image/video files found. Nothing to do.")
        index.close()
        return

    # Process loop
    processed = 0
    skipped = 0
    failed = 0
    start_time = time.time()

    for filepath in file_list:
        if 0 < batch_size <= processed:
            print(f"\n  Batch limit reached ({batch_size}). Stopping.")
            break

        relative_path = os.path.relpath(filepath, scan_dir)

        try:
            file_hash = calculate_sha256(filepath)
        except Exception as e:
            logger.error(f"Hash failed for {relative_path}: {e}")
            failed += 1
            continue

        # Deduplication check
        if not reindex and index.has_hash(file_hash):
            logger.debug(f"[SKIP] Already indexed: {relative_path}")
            skipped += 1
            continue

        # Skip video files for vision model (can't send raw video to Ollama)
        ext = os.path.splitext(filepath)[1].lower()
        if ext in VIDEO_EXTENSIONS:
            logger.info(f"[SKIP-VIDEO] {relative_path} (video captioning not yet supported)")
            skipped += 1
            continue

        # Send to vision model
        logger.info(f"[CAPTION] {relative_path}")
        t0 = time.time()
        description = describe_image(filepath, client)
        elapsed = round(time.time() - t0, 2)

        if description is None:
            logger.error(f"[FAIL] No description returned for {relative_path}")
            failed += 1
            continue

        # Build record
        record = {
            "filepath": filepath,
            "relative_path": relative_path,
            "sha256": file_hash,
            "file_size": os.path.getsize(filepath),
            "file_ext": ext,
            "description": description,
            "model_used": client["model"],
            "indexed_at": datetime.now().isoformat(),
            "processing_time_s": elapsed,
        }

        # Store
        try:
            index.insert(record)
        except Exception as e:
            logger.error(f"[DB ERROR] Failed to store {relative_path}: {e}")
            failed += 1
            continue

        # Optional sidecar
        if write_sidecars:
            write_sidecar(filepath, record)

        processed += 1
        print(
            f"  [{processed:>5}] {relative_path}  "
            f"({elapsed:.1f}s, {len(description)} chars)"
        )

    total_time = round(time.time() - start_time, 1)

    # Summary
    print("\n" + "=" * 70)
    print("  VISION INDEXER — COMPLETE")
    print("=" * 70)
    print(f"  Processed (new)    : {processed:,}")
    print(f"  Skipped (existing) : {skipped:,}")
    print(f"  Failed             : {failed:,}")
    print(f"  Total in Index     : {index.count():,}")
    print(f"  Elapsed            : {total_time:.1f}s")
    if processed > 0:
        print(f"  Avg per Image      : {total_time / processed:.1f}s")
    print("=" * 70)

    index.close()


# =============================================================================
# SEARCH CLI (bonus utility)
# =============================================================================

def search_index(scan_dir: str, query: str, use_pg: bool = False):
    """Search the vision index for matching descriptions."""
    if use_pg:
        index = PostgresIndex()
    else:
        db_path = os.path.join(scan_dir, "vision_index.db")
        if not os.path.exists(db_path):
            print(f"No index found at {db_path}. Run the indexer first.")
            return
        index = SQLiteIndex(db_path)

    results = index.search(query)
    print(f"\n  Search: \"{query}\" — {len(results)} result(s)\n")
    for i, r in enumerate(results, 1):
        print(f"  [{i}] {r['path']}")
        # Truncate long descriptions for display
        desc = r["description"]
        if len(desc) > 200:
            desc = desc[:200] + "..."
        print(f"      {desc}")
        print(f"      Indexed: {r['indexed_at']}\n")

    index.close()


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Fortress Prime — Vision Indexer (DGX Image Captioning)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.vision_indexer
  python -m src.vision_indexer --scan-dir /mnt/volume2/ai_brain/construction
  python -m src.vision_indexer --batch-size 50 --sidecar
  python -m src.vision_indexer --pg
  python -m src.vision_indexer --search "bathroom renovation"
        """,
    )
    parser.add_argument(
        "--scan-dir", default=DEFAULT_SCAN_DIR,
        help=f"Directory to scan for images (default: {DEFAULT_SCAN_DIR})",
    )
    parser.add_argument(
        "--batch-size", type=int, default=0,
        help="Max images to process per run (0 = unlimited)",
    )
    parser.add_argument(
        "--pg", action="store_true",
        help="Use PostgreSQL (Fortress DB) instead of SQLite",
    )
    parser.add_argument(
        "--reindex", action="store_true",
        help="Force re-captioning even if file hash already indexed",
    )
    parser.add_argument(
        "--sidecar", action="store_true",
        help="Write .json sidecar files next to each image",
    )
    parser.add_argument(
        "--image-only", action="store_true",
        help="Skip video files, process images only",
    )
    parser.add_argument(
        "--search", type=str, default=None,
        help="Search the index instead of indexing (e.g., --search 'bathroom tile')",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug-level logging",
    )

    args = parser.parse_args()
    _setup_logging(args.verbose)

    # Search mode
    if args.search:
        search_index(args.scan_dir, args.search, use_pg=args.pg)
        return

    # Index mode
    run_vision_indexer(
        scan_dir=args.scan_dir,
        use_pg=args.pg,
        batch_size=args.batch_size,
        reindex=args.reindex,
        write_sidecars=args.sidecar,
        image_only=args.image_only,
    )


if __name__ == "__main__":
    main()
