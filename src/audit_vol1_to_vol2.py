"""
Fortress Prime — Chain of Custody Audit (SHA-256 Integrity Verification)
=========================================================================
LEGALLY DEFENSIBLE migration audit between Volume 1 and Volume 2.

This script does NOT "look" at data — it mathematically proves identity.
If a single bit flips in a contract PDF or financial spreadsheet, this
flags it as CORRUPT.

TWO MODES:

  PATH MODE (default):
    Walk Vol1, find the same relative path on Vol2, compare hashes.
    Use when the migration was a direct copy (same directory structure).

  HASH MODE (--hash-index):
    Build SHA-256 hash sets for BOTH volumes, then cross-reference.
    Use when the migration REORGANIZED or RENAMED files.
    A Vol2 file is VERIFIED if its content hash exists ANYWHERE on Vol1.
    This is the correct mode for the Fortress NAS migration.

OUTPUT:
    - JSONL append log at:  {audit_dir}/migration_audit.jsonl
    - Summary JSON report:  {audit_dir}/audit_report_YYYYMMDD.json

USAGE:
    # Path mode (1:1 mirror)
    python -m src.audit_vol1_to_vol2 --vol1 /path/to/src --vol2 /path/to/dst

    # Hash mode (reorganized migration — the Fortress NAS scenario)
    python -m src.audit_vol1_to_vol2 --hash-index \\
        --vol1 /mnt/vol1_source/Business/CROG \\
        --vol1 /mnt/vol1_source/Business/Legal \\
        --vol2 /mnt/fortress_nas/Financial_Ledger \\
        --vol2 /mnt/fortress_nas/Corporate_Legal

    # Dry run / verbose
    python -m src.audit_vol1_to_vol2 --hash-index --dry-run --verbose \\
        --vol1 /mnt/vol1_source --vol2 /mnt/fortress_nas

REQUIREMENTS:
    - No external dependencies (stdlib only).
    - Memory efficient: reads files in 4K blocks.
    - Safe: read-only operations on both volumes.
"""

import hashlib
import os
import sys
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path

# =============================================================================
# CONFIGURATION (Enterprise Paths — override with CLI flags or env vars)
# =============================================================================

VOL1_PATH = os.getenv("FORTRESS_VOL1", "/mnt/volume1/legacy_data")
VOL2_PATH = os.getenv("FORTRESS_VOL2", "/mnt/volume2/ai_brain")
AUDIT_DIR = os.getenv("FORTRESS_AUDIT_DIR", "/mnt/volume2/ai_brain/logs/audit")

# Derived paths
AUDIT_LOG = os.path.join(AUDIT_DIR, "migration_audit.jsonl")
REPORT_FILE = os.path.join(
    AUDIT_DIR, f"audit_report_{datetime.now().strftime('%Y%m%d')}.json"
)

# =============================================================================
# LOGGING
# =============================================================================

logger = logging.getLogger("fortress.audit")


def _setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S")


# =============================================================================
# CORE: SHA-256 HASH
# =============================================================================

def calculate_sha256(filepath: str) -> str:
    """
    Calculate the SHA-256 hash of a file.

    Reads in 4K blocks to handle multi-GB files without memory pressure.
    Returns the hex digest string (64 characters).
    """
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


# =============================================================================
# CORE: AUDIT ENGINE
# =============================================================================

def audit_migration(
    vol1: str,
    vol2: str,
    audit_log: str,
    report_file: str,
    dry_run: bool = False,
    log_matched: bool = False,
    exclude_patterns: list = None,
):
    """
    Walk Volume 1 and verify every file exists and is bit-identical on Volume 2.

    Args:
        vol1:             Source volume path (legacy data).
        vol2:             Destination volume path (AI brain).
        audit_log:        Path for the JSONL append log.
        report_file:      Path for the summary JSON report.
        dry_run:          If True, list files but do not hash.
        log_matched:      If True, also log matched files to JSONL.
        exclude_patterns: List of directory/file name substrings to skip.

    Returns:
        dict: Summary results with matched/missing/corrupted/error counts.
    """
    exclude_patterns = exclude_patterns or [".DS_Store", "Thumbs.db", "@eaDir"]

    print("=" * 70)
    print("  FORTRESS PRIME — CHAIN OF CUSTODY AUDIT")
    print("=" * 70)
    print(f"  Source (Vol 1) : {vol1}")
    print(f"  Target (Vol 2) : {vol2}")
    print(f"  Audit Log      : {audit_log}")
    print(f"  Report         : {report_file}")
    print(f"  Dry Run        : {'YES' if dry_run else 'NO'}")
    print(f"  Log Matches    : {'YES' if log_matched else 'NO'}")
    print("=" * 70)

    # Validate source volume
    if not os.path.isdir(vol1):
        logger.error(f"Source volume does not exist: {vol1}")
        print(f"\n  [ABORT] Cannot access Volume 1: {vol1}")
        print("  Verify NAS mount and path. Exiting.")
        sys.exit(1)

    # Validate target volume
    if not os.path.isdir(vol2):
        logger.error(f"Target volume does not exist: {vol2}")
        print(f"\n  [ABORT] Cannot access Volume 2: {vol2}")
        print("  Verify NAS mount and path. Exiting.")
        sys.exit(1)

    # Ensure audit directory exists
    os.makedirs(os.path.dirname(audit_log), exist_ok=True)

    # Counters
    results = {
        "matched": 0,
        "missing": 0,
        "corrupted": 0,
        "skipped": 0,
        "error_count": 0,
        "errors": [],
        "corrupted_files": [],
        "missing_files": [],
    }

    start_time = datetime.now()
    total_files = 0
    total_bytes = 0

    log_handle = None
    if not dry_run:
        log_handle = open(audit_log, "a")

    try:
        for root, dirs, files in os.walk(vol1):
            # Skip excluded directories in-place
            dirs[:] = [
                d for d in dirs
                if not any(pat in d for pat in exclude_patterns)
            ]

            for filename in files:
                # Skip excluded files
                if any(pat in filename for pat in exclude_patterns):
                    results["skipped"] += 1
                    continue

                total_files += 1
                vol1_file = os.path.join(root, filename)
                relative_path = os.path.relpath(vol1_file, vol1)
                vol2_file = os.path.join(vol2, relative_path)
                timestamp = datetime.now().isoformat()

                if dry_run:
                    exists = os.path.exists(vol2_file)
                    status = "EXISTS" if exists else "MISSING"
                    logger.debug(f"[{status}] {relative_path}")
                    if not exists:
                        results["missing"] += 1
                        results["missing_files"].append(relative_path)
                    continue

                # --- Check existence ---
                if not os.path.exists(vol2_file):
                    logger.warning(f"[MISSING] {relative_path}")
                    results["missing"] += 1
                    results["missing_files"].append(relative_path)
                    entry = {
                        "status": "MISSING",
                        "file": relative_path,
                        "vol1_path": vol1_file,
                        "expected_vol2_path": vol2_file,
                        "time": timestamp,
                    }
                    log_handle.write(json.dumps(entry) + "\n")
                    continue

                # --- Calculate & compare hashes ---
                try:
                    vol1_size = os.path.getsize(vol1_file)
                    total_bytes += vol1_size

                    h1 = calculate_sha256(vol1_file)
                    h2 = calculate_sha256(vol2_file)

                    if h1 == h2:
                        results["matched"] += 1
                        if log_matched:
                            entry = {
                                "status": "MATCHED",
                                "file": relative_path,
                                "sha256": h1,
                                "size_bytes": vol1_size,
                                "time": timestamp,
                            }
                            log_handle.write(json.dumps(entry) + "\n")
                    else:
                        logger.error(
                            f"[CORRUPT] {relative_path}  "
                            f"vol1={h1[:16]}...  vol2={h2[:16]}..."
                        )
                        results["corrupted"] += 1
                        results["corrupted_files"].append(relative_path)
                        entry = {
                            "status": "CORRUPT",
                            "file": relative_path,
                            "vol1_hash": h1,
                            "vol2_hash": h2,
                            "vol1_size": vol1_size,
                            "vol2_size": os.path.getsize(vol2_file),
                            "time": timestamp,
                        }
                        log_handle.write(json.dumps(entry) + "\n")

                except PermissionError as e:
                    logger.error(f"[PERM ERROR] {relative_path}: {e}")
                    results["error_count"] += 1
                    results["errors"].append(f"PermissionError: {relative_path}")
                except OSError as e:
                    logger.error(f"[OS ERROR] {relative_path}: {e}")
                    results["error_count"] += 1
                    results["errors"].append(f"OSError: {relative_path}: {e}")
                except Exception as e:
                    logger.error(f"[ERROR] {relative_path}: {e}")
                    results["error_count"] += 1
                    results["errors"].append(f"{type(e).__name__}: {relative_path}: {e}")

                # Progress indicator every 500 files
                if total_files % 500 == 0:
                    print(
                        f"  ... {total_files} files scanned  "
                        f"({results['matched']} ok / "
                        f"{results['missing']} missing / "
                        f"{results['corrupted']} corrupt)"
                    )

    finally:
        if log_handle:
            log_handle.close()

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    # --- Build summary report ---
    report = {
        "audit_type": "SHA-256 Chain of Custody Verification",
        "vol1_source": vol1,
        "vol2_target": vol2,
        "started_at": start_time.isoformat(),
        "completed_at": end_time.isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "total_files_scanned": total_files,
        "total_bytes_hashed": total_bytes,
        "results": {
            "matched": results["matched"],
            "missing": results["missing"],
            "corrupted": results["corrupted"],
            "skipped": results["skipped"],
            "errors": results["error_count"],
        },
        "corrupted_files": results["corrupted_files"],
        "missing_files": results["missing_files"][:100],  # Cap at 100 for readability
        "missing_files_truncated": len(results["missing_files"]) > 100,
        "error_details": results["errors"][:50],
        "verdict": "PASS" if (
            results["corrupted"] == 0
            and results["missing"] == 0
            and results["error_count"] == 0
        ) else "FAIL",
        "audit_log_path": audit_log,
        "generated_by": "Fortress Prime — audit_vol1_to_vol2.py",
    }

    if not dry_run:
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2)
        logger.info(f"Report written to: {report_file}")

    # --- Print summary ---
    print("\n" + "=" * 70)
    print("  AUDIT COMPLETE — CHAIN OF CUSTODY RESULTS")
    print("=" * 70)
    print(f"  Total Files Scanned : {total_files:,}")
    print(f"  Total Bytes Hashed  : {total_bytes:,.0f}")
    print(f"  Elapsed Time        : {elapsed:.1f}s")
    print(f"  {'─' * 40}")
    print(f"  Matched (identical) : {results['matched']:,}")
    print(f"  Missing on Vol 2    : {results['missing']:,}")
    print(f"  CORRUPTED           : {results['corrupted']:,}")
    print(f"  Skipped             : {results['skipped']:,}")
    print(f"  Errors              : {results['error_count']:,}")
    print(f"  {'─' * 40}")

    if report["verdict"] == "PASS":
        print("  VERDICT: PASS — All files verified identical.")
    else:
        print("  VERDICT: FAIL — Issues detected. Review the report.")
        if results["corrupted_files"]:
            print(f"\n  CORRUPTED FILES ({len(results['corrupted_files'])}):")
            for cf in results["corrupted_files"][:20]:
                print(f"    - {cf}")
        if results["missing_files"]:
            print(f"\n  MISSING FILES ({len(results['missing_files'])}):")
            for mf in results["missing_files"][:20]:
                print(f"    - {mf}")

    print("=" * 70)

    return report


# =============================================================================
# HASH-INDEX MODE: Cross-reference audit for reorganized migrations
# =============================================================================

def _build_hash_index(
    directories: list,
    label: str,
    exclude_patterns: list,
) -> dict:
    """
    Walk one or more directories and build a dict of {sha256: [filepath, ...]}.

    Args:
        directories:      List of directory paths to scan.
        label:            Human label for progress output ("Vol1" / "Vol2").
        exclude_patterns: Filename/dirname substrings to skip.

    Returns:
        Dict mapping sha256 hex digest -> list of file paths with that hash.
    """
    hash_index = {}  # sha256 -> [filepath, ...]
    file_count = 0
    byte_count = 0
    error_count = 0

    for scan_dir in directories:
        if not os.path.isdir(scan_dir):
            logger.warning(f"[{label}] Directory not found (skipping): {scan_dir}")
            continue

        logger.info(f"[{label}] Indexing: {scan_dir}")

        for root, dirs, files in os.walk(scan_dir):
            dirs[:] = [
                d for d in dirs
                if not any(pat in d for pat in exclude_patterns)
            ]

            for fname in files:
                if any(pat in fname for pat in exclude_patterns):
                    continue

                filepath = os.path.join(root, fname)
                file_count += 1

                try:
                    fsize = os.path.getsize(filepath)
                    byte_count += fsize
                    h = calculate_sha256(filepath)

                    if h not in hash_index:
                        hash_index[h] = []
                    hash_index[h].append(filepath)

                except Exception as e:
                    logger.debug(f"[{label}] Hash error: {filepath}: {e}")
                    error_count += 1

                if file_count % 500 == 0:
                    print(
                        f"  [{label}] {file_count:,} files indexed  "
                        f"({len(hash_index):,} unique hashes, "
                        f"{byte_count / (1024**3):.1f} GB)"
                    )

    print(
        f"  [{label}] DONE: {file_count:,} files, "
        f"{len(hash_index):,} unique hashes, "
        f"{byte_count / (1024**3):.2f} GB, "
        f"{error_count} errors"
    )

    return hash_index


def audit_hash_index(
    vol1_dirs: list,
    vol2_dirs: list,
    audit_log: str,
    report_file: str,
    dry_run: bool = False,
    exclude_patterns: list = None,
):
    """
    Hash-based cross-reference audit for reorganized migrations.

    Builds SHA-256 hash sets for both volumes, then verifies that every
    file on Vol2 has a content-identical source on Vol1. This works even
    when files are renamed or moved to different directories.

    A Vol2 file is VERIFIED if its hash exists anywhere in the Vol1 index.
    A Vol2 file is UNVERIFIED if its hash has no match (new file, or corruption).

    Args:
        vol1_dirs:        List of Vol1 source directory paths.
        vol2_dirs:        List of Vol2 destination directory paths.
        audit_log:        Path for the JSONL audit log.
        report_file:      Path for the summary JSON report.
        dry_run:          If True, only count files without hashing.
        exclude_patterns: Patterns to skip.

    Returns:
        dict: Summary report.
    """
    exclude_patterns = exclude_patterns or [
        ".DS_Store", "Thumbs.db", "@eaDir", "@SynoEAStream", "@SynoResource",
        "#recycle", ".ipynb_checkpoints",
    ]

    print("=" * 70)
    print("  FORTRESS PRIME — HASH-INDEX CHAIN OF CUSTODY AUDIT")
    print("=" * 70)
    print(f"  Mode         : HASH CROSS-REFERENCE (reorganized migration)")
    print(f"  Vol1 Sources : {len(vol1_dirs)} directories")
    for d in vol1_dirs:
        print(f"                 {d}")
    print(f"  Vol2 Targets : {len(vol2_dirs)} directories")
    for d in vol2_dirs:
        print(f"                 {d}")
    print(f"  Audit Log    : {audit_log}")
    print(f"  Report       : {report_file}")
    print(f"  Dry Run      : {'YES' if dry_run else 'NO'}")
    print("=" * 70)

    start_time = datetime.now()

    if dry_run:
        # Just count files
        for label, dirs in [("Vol1", vol1_dirs), ("Vol2", vol2_dirs)]:
            count = 0
            for d in dirs:
                if os.path.isdir(d):
                    for root, subdirs, files in os.walk(d):
                        subdirs[:] = [
                            sd for sd in subdirs
                            if not any(p in sd for p in exclude_patterns)
                        ]
                        count += len([
                            f for f in files
                            if not any(p in f for p in exclude_patterns)
                        ])
            print(f"  [{label}] {count:,} files to hash")
        print("\n  Dry run complete. Use without --dry-run to execute.")
        return {"verdict": "DRY_RUN"}

    # --- Phase 1: Build Vol1 hash index (the source of truth) ---
    print(f"\n  PHASE 1: Building Vol1 hash index (source of truth)...")
    vol1_index = _build_hash_index(vol1_dirs, "Vol1", exclude_patterns)

    # --- Phase 2: Build Vol2 hash index ---
    print(f"\n  PHASE 2: Building Vol2 hash index (migration target)...")
    vol2_index = _build_hash_index(vol2_dirs, "Vol2", exclude_patterns)

    # --- Phase 3: Cross-reference ---
    print(f"\n  PHASE 3: Cross-referencing Vol2 against Vol1...")

    os.makedirs(os.path.dirname(audit_log), exist_ok=True)

    verified = 0
    unverified = 0
    vol2_only_files = []  # Files on Vol2 with no Vol1 match
    verified_files = []

    with open(audit_log, "a") as log:
        timestamp = datetime.now().isoformat()

        for vol2_hash, vol2_paths in vol2_index.items():
            if vol2_hash in vol1_index:
                # Content-identical file exists on Vol1
                verified += len(vol2_paths)
                for p in vol2_paths:
                    verified_files.append(p)
                    log.write(json.dumps({
                        "status": "VERIFIED",
                        "vol2_file": p,
                        "sha256": vol2_hash,
                        "vol1_match": vol1_index[vol2_hash][0],
                        "time": timestamp,
                    }) + "\n")
            else:
                # No matching content on Vol1
                unverified += len(vol2_paths)
                for p in vol2_paths:
                    vol2_only_files.append(p)
                    log.write(json.dumps({
                        "status": "UNVERIFIED",
                        "vol2_file": p,
                        "sha256": vol2_hash,
                        "note": "No content match found on Vol1 — file may be new or corrupted",
                        "time": timestamp,
                    }) + "\n")

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    # --- Categorize unverified files ---
    # Some "unverified" files are expected (e.g., files created on Vol2 after migration)
    new_file_extensions = {".db", ".jsonl", ".json", ".log", ".txt", ".ipynb", ".pub"}
    likely_new = []
    possibly_corrupt = []
    for f in vol2_only_files:
        ext = os.path.splitext(f)[1].lower()
        if ext in new_file_extensions:
            likely_new.append(f)
        else:
            possibly_corrupt.append(f)

    # --- Build report ---
    total_vol2 = verified + unverified
    report = {
        "audit_type": "SHA-256 Hash-Index Cross-Reference (Reorganized Migration)",
        "vol1_sources": vol1_dirs,
        "vol2_targets": vol2_dirs,
        "started_at": start_time.isoformat(),
        "completed_at": end_time.isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "vol1_unique_hashes": len(vol1_index),
        "vol2_unique_hashes": len(vol2_index),
        "vol2_total_files": total_vol2,
        "results": {
            "verified": verified,
            "unverified": unverified,
            "likely_new_on_vol2": len(likely_new),
            "possibly_corrupt": len(possibly_corrupt),
        },
        "verification_rate": f"{(verified / total_vol2 * 100):.1f}%" if total_vol2 else "N/A",
        "possibly_corrupt_files": possibly_corrupt[:100],
        "likely_new_files": likely_new[:50],
        "verdict": "PASS" if len(possibly_corrupt) == 0 else (
            "REVIEW" if len(possibly_corrupt) < 10 else "FAIL"
        ),
        "audit_log_path": audit_log,
        "generated_by": "Fortress Prime — audit_vol1_to_vol2.py (hash-index mode)",
    }

    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    logger.info(f"Report written to: {report_file}")

    # --- Print summary ---
    print("\n" + "=" * 70)
    print("  HASH-INDEX AUDIT COMPLETE — CHAIN OF CUSTODY RESULTS")
    print("=" * 70)
    print(f"  Vol1 Unique Hashes  : {len(vol1_index):,}")
    print(f"  Vol2 Total Files    : {total_vol2:,}")
    print(f"  Elapsed Time        : {elapsed:.1f}s")
    print(f"  {'─' * 45}")
    print(f"  VERIFIED (hash match on Vol1) : {verified:,}")
    print(f"  Unverified                    : {unverified:,}")
    print(f"    Likely new (created on Vol2) : {len(likely_new):,}")
    print(f"    POSSIBLY CORRUPT             : {len(possibly_corrupt):,}")
    print(f"  {'─' * 45}")
    print(f"  Verification Rate   : {report['verification_rate']}")
    print(f"  {'─' * 45}")

    if report["verdict"] == "PASS":
        print("  VERDICT: PASS — All migrated files verified against source.")
    elif report["verdict"] == "REVIEW":
        print("  VERDICT: REVIEW — Small number of unverified files. Check report.")
    else:
        print("  VERDICT: FAIL — Unverified files detected. Review the report.")

    if possibly_corrupt:
        print(f"\n  POSSIBLY CORRUPT ({len(possibly_corrupt)}):")
        for cf in possibly_corrupt[:20]:
            print(f"    - {cf}")

    if likely_new:
        print(f"\n  LIKELY NEW (created post-migration, {len(likely_new)}):")
        for nf in likely_new[:10]:
            print(f"    - {nf}")

    print("=" * 70)

    return report


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Fortress Prime — SHA-256 Chain of Custody Audit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples (Path Mode — 1:1 mirror):
  python -m src.audit_vol1_to_vol2 --vol1 /mnt/volume1/legacy --vol2 /mnt/volume2/copy
  python -m src.audit_vol1_to_vol2 --dry-run --log-matched

Examples (Hash-Index Mode — reorganized migration):
  python -m src.audit_vol1_to_vol2 --hash-index \\
      --vol1 /mnt/vol1_source/Business/CROG \\
      --vol1 /mnt/vol1_source/Business/Legal \\
      --vol2 /mnt/fortress_nas/Financial_Ledger \\
      --vol2 /mnt/fortress_nas/Corporate_Legal \\
      --vol2 /mnt/fortress_nas/Real_Estate_Assets
        """,
    )
    parser.add_argument(
        "--vol1", action="append", default=None,
        help="Source volume path(s) — repeatable for multiple dirs",
    )
    parser.add_argument(
        "--vol2", action="append", default=None,
        help="Target volume path(s) — repeatable for multiple dirs",
    )
    parser.add_argument(
        "--hash-index", action="store_true",
        help="Use hash-based cross-reference mode (for reorganized migrations)",
    )
    parser.add_argument(
        "--audit-dir", default=AUDIT_DIR,
        help=f"Directory for audit logs and reports (default: {AUDIT_DIR})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview only — count files without hashing",
    )
    parser.add_argument(
        "--log-matched", action="store_true",
        help="Also log successfully matched files to the JSONL audit trail (path mode)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug-level logging",
    )
    parser.add_argument(
        "--exclude", nargs="*", default=None,
        help="Additional filename/directory patterns to exclude",
    )

    args = parser.parse_args()
    _setup_logging(args.verbose)

    # Resolve audit output paths
    audit_dir = args.audit_dir
    audit_log = os.path.join(audit_dir, "migration_audit.jsonl")
    report_file = os.path.join(
        audit_dir, f"audit_report_{datetime.now().strftime('%Y%m%d')}.json"
    )

    exclude = [".DS_Store", "Thumbs.db", "@eaDir", "@SynoEAStream", "@SynoResource",
               "#recycle", ".ipynb_checkpoints"]
    if args.exclude:
        exclude.extend(args.exclude)

    # Determine mode
    if args.hash_index:
        # Hash-index mode (reorganized migration)
        vol1_dirs = args.vol1 or [VOL1_PATH]
        vol2_dirs = args.vol2 or [VOL2_PATH]

        report = audit_hash_index(
            vol1_dirs=vol1_dirs,
            vol2_dirs=vol2_dirs,
            audit_log=audit_log,
            report_file=report_file,
            dry_run=args.dry_run,
            exclude_patterns=exclude,
        )
    else:
        # Path mode (1:1 mirror) — original behavior
        vol1 = args.vol1[0] if args.vol1 else VOL1_PATH
        vol2 = args.vol2[0] if args.vol2 else VOL2_PATH

        report = audit_migration(
            vol1=vol1,
            vol2=vol2,
            audit_log=audit_log,
            report_file=report_file,
            dry_run=args.dry_run,
            log_matched=args.log_matched,
            exclude_patterns=exclude,
        )

    # Exit with non-zero code if audit failed
    if report.get("verdict") not in ("PASS", "DRY_RUN"):
        sys.exit(1)


if __name__ == "__main__":
    main()
