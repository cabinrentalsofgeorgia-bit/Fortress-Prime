"""
Fortress Prime - MailPlus Sentinel

Scans the Enterprise Data Lake directory and stores per-folder file counts
into Postgres (`fortress_db`) table `enterprise_lake_index`.

Run:
  python /home/admin/fortress-prime/src/mailplus_sentinel.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Tuple

import psycopg2
from psycopg2.extras import execute_batch


MAILPLUS_ROOT = "/home/admin/fortress-prime/mnt/synology/MailPlus"


@dataclass(frozen=True)
class FolderStat:
    folder_path: str
    folder_name: str
    file_count: int


def _walk_error_handler(error_instance):
    """Error handler for os.walk that skips directories we can't access."""
    # This will be called when os.walk encounters an error accessing a directory
    # We'll skip it by removing it from the dirs list (handled in the walk loop)
    pass


def _count_files_recursive_aggressive(folder_path: str) -> int:
    """Aggressively count files, ignoring permission errors."""
    total = 0
    try:
        for root, dirs, files in os.walk(folder_path, onerror=_walk_error_handler, followlinks=False):
            try:
                # Count files in current directory
                total += len(files)
            except (PermissionError, OSError):
                # Skip this directory if we can't read it
                continue
            
            # Filter out directories we can't access to prevent os.walk from trying them
            dirs_to_remove = []
            for d in dirs:
                dir_path = os.path.join(root, d)
                try:
                    # Try to access the directory - if we can't, remove it from dirs list
                    os.listdir(dir_path)
                except (PermissionError, OSError):
                    dirs_to_remove.append(d)
            
            # Remove inaccessible directories from dirs list
            for d in dirs_to_remove:
                dirs.remove(d)
                
    except (PermissionError, OSError) as e:
        # If we can't even start walking, return 0
        return 0
    except Exception as e:
        # Catch any other errors and continue
        print(f"      ⚠️  Walk error in {folder_path}: {e}")
        return total  # Return what we've counted so far
    
    return total


def scan_mailplus_vault(root_path: str = MAILPLUS_ROOT) -> List[FolderStat]:
    """Aggressively scan MailPlus directory tree, counting all files recursively."""
    if not os.path.isdir(root_path):
        raise FileNotFoundError(f"MailPlus path not found: {root_path}")

    stats: List[FolderStat] = []
    processed_paths = set()
    
    # Walk the entire tree and count files per top-level folder
    try:
        # First, get top-level directories
        top_level_dirs = []
        try:
            with os.scandir(root_path) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            top_level_dirs.append(entry.path)
                    except (PermissionError, OSError):
                        continue
        except (PermissionError, OSError) as e:
            print(f"⚠️  Warning: Cannot scan top-level: {e}")
            return stats
        
        # Count files in each top-level directory recursively
        for folder_path in sorted(top_level_dirs):
            folder_name = os.path.basename(folder_path.rstrip(os.sep))
            
            # Skip if already processed
            if folder_path in processed_paths:
                continue
            processed_paths.add(folder_path)
            
            try:
                count = _count_files_recursive_aggressive(folder_path)
                stats.append(FolderStat(folder_path=folder_path, folder_name=folder_name, file_count=count))
                if count > 0:
                    print(f"   📁 {folder_name}: {count:,} files")
            except Exception as e:
                print(f"   ⚠️  Error counting {folder_name}: {e}")
                stats.append(FolderStat(folder_path=folder_path, folder_name=folder_name, file_count=0))
    
    except Exception as e:
        print(f"🚨 Critical error during scan: {e}")
        raise
    
    return stats


def _get_db_connection():
    # Defaults aligned with existing Fortress scripts; can be overridden via env vars.
    host = os.getenv("FORTRESS_DB_HOST", "localhost")
    db = os.getenv("FORTRESS_DB_NAME", "fortress_db")
    user = os.getenv("FORTRESS_DB_USER", "miner_bot")
    password = os.getenv("FORTRESS_DB_PASS", os.getenv("DB_PASS", ""))
    return psycopg2.connect(host=host, database=db, user=user, password=password)


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS enterprise_lake_index (
              id SERIAL PRIMARY KEY,
              folder_path TEXT UNIQUE NOT NULL,
              folder_name TEXT NOT NULL,
              file_count BIGINT NOT NULL,
              scanned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
    conn.commit()


def upsert_folder_stats(conn, stats: Iterable[FolderStat]) -> int:
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # store naive timestamp
    rows: List[Tuple[str, str, int, datetime]] = [
        (s.folder_path, s.folder_name, int(s.file_count), now) for s in stats
    ]
    if not rows:
        return 0

    sql = """
        INSERT INTO enterprise_lake_index (folder_path, folder_name, file_count, scanned_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (folder_path)
        DO UPDATE SET
          folder_name = EXCLUDED.folder_name,
          file_count = EXCLUDED.file_count,
          scanned_at = EXCLUDED.scanned_at;
    """
    with conn.cursor() as cur:
        execute_batch(cur, sql, rows, page_size=200)
    conn.commit()
    return len(rows)


def main() -> int:
    print("🛡️  MailPlus Sentinel starting...")
    print(f"📂 Root: {MAILPLUS_ROOT}")
    print("🔍 Aggressive scan mode: Ignoring permission errors, counting all files...")

    try:
        stats = scan_mailplus_vault(MAILPLUS_ROOT)
    except Exception as e:
        print(f"🚨 Scan failed: {e}")
        return 1

    total_files = sum(s.file_count for s in stats)
    print(f"\n✅ Discovered {len(stats)} top-level folders, {total_files:,} total files (recursive).")
    
    if total_files == 0:
        print("⚠️  WARNING: Found 0 files. Check permissions or path.")

    try:
        conn = _get_db_connection()
    except Exception as e:
        print(f"🚨 DB connect failed: {e}")
        return 2

    try:
        ensure_schema(conn)
        upserted = upsert_folder_stats(conn, stats)
        print(f"💾 Upserted {upserted} rows into enterprise_lake_index.")
    except Exception as e:
        print(f"🚨 DB write failed: {e}")
        return 3
    finally:
        try:
            conn.close()
        except Exception:
            pass

    print("🏁 Sentinel complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

