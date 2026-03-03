#!/usr/bin/env python3
"""
FORTRESS PRIME — Sector Data Preparation & Snapshot Tool
=========================================================
Registers new sectors, generates context manifests, and snapshots
sector data for backup and TITAN context injection.

Mandatory workflow (Constitution rule IV-A.3):
    1. Update fortress_atlas.yaml
    2. Run: python tools/sector_ingest.py --snapshot
    3. THEN write the code

Usage:
    ./venv/bin/python tools/sector_ingest.py --snapshot              # Snapshot all sectors
    ./venv/bin/python tools/sector_ingest.py --sector crog --snapshot # Single sector
    ./venv/bin/python tools/sector_ingest.py --validate              # Validate atlas
    ./venv/bin/python tools/sector_ingest.py --manifest              # Generate context manifest
"""

import json
import os
import sys
import yaml
import logging
import psycopg2
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT

log = logging.getLogger("fortress.sector_ingest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [SECTOR] %(message)s")

ATLAS_PATH = Path(__file__).resolve().parent.parent / "fortress_atlas.yaml"
NAS_BASE = Path("/mnt/fortress_nas/sectors")


def load_atlas() -> dict:
    with open(ATLAS_PATH) as f:
        return yaml.safe_load(f)


def get_sectors() -> list:
    atlas = load_atlas()
    return atlas.get("fortress_prime", {}).get("sectors", [])


def validate_atlas() -> list:
    """Validate that the atlas is structurally sound."""
    issues = []
    try:
        sectors = get_sectors()
    except Exception as e:
        return [f"Cannot load atlas: {e}"]

    if not sectors:
        issues.append("No sectors defined")
        return issues

    slugs = set()
    codes = set()
    for s in sectors:
        slug = s.get("slug", "")
        code = s.get("code", "")
        if not slug:
            issues.append(f"Sector missing slug: {s}")
        if slug in slugs:
            issues.append(f"Duplicate slug: {slug}")
        slugs.add(slug)

        if not code:
            issues.append(f"Sector {slug} missing code")
        if code in codes:
            issues.append(f"Duplicate code: {code}")
        codes.add(code)

        if not s.get("name"):
            issues.append(f"Sector {slug} missing name")
        if not s.get("persona"):
            issues.append(f"Sector {slug} missing persona")

    return issues


def get_db_conn():
    config = {"dbname": DB_NAME, "user": DB_USER}
    if DB_HOST:
        config["host"] = DB_HOST
        config["port"] = DB_PORT
    if DB_PASS:
        config["password"] = DB_PASS
    return psycopg2.connect(**config)


def snapshot_sector(sector: dict) -> dict:
    """Generate a context snapshot for a sector."""
    slug = sector["slug"]
    schema = sector.get("db_schema", "public")
    log.info(f"Snapshotting sector: {slug} (schema: {schema})")

    snapshot = {
        "slug": slug,
        "name": sector["name"],
        "code": sector["code"],
        "schema": schema,
        "timestamp": datetime.utcnow().isoformat(),
        "tables": {},
        "email_stats": {},
    }

    try:
        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = %s ORDER BY tablename
        """, (schema,))
        tables = [r[0] for r in cur.fetchall()]
        for table in tables:
            cur.execute(f"SELECT count(*) FROM {schema}.{table}")
            count = cur.fetchone()[0]
            snapshot["tables"][table] = count

        email_divisions = sector.get("email_divisions", [])
        if email_divisions:
            for div in email_divisions:
                cur.execute(
                    "SELECT count(*) FROM email_archive WHERE division = %s",
                    (div,)
                )
                snapshot["email_stats"][div] = cur.fetchone()[0]

        cur.close()
        conn.close()
    except Exception as e:
        log.error(f"DB error for {slug}: {e}")
        snapshot["db_error"] = str(e)

    return snapshot


def save_snapshot(snapshot: dict, sector_slug: str):
    """Save snapshot to NAS sector directory."""
    sector_dir = NAS_BASE / sector_slug
    sector_dir.mkdir(parents=True, exist_ok=True)

    out_path = sector_dir / f"snapshot_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    log.info(f"Snapshot saved: {out_path}")
    return out_path


def generate_manifest() -> dict:
    """Generate a context manifest of all sectors for the Titan Executive."""
    sectors = get_sectors()
    manifest = {
        "generated": datetime.utcnow().isoformat(),
        "sectors": [],
    }
    for s in sectors:
        manifest["sectors"].append({
            "slug": s["slug"],
            "code": s["code"],
            "name": s["name"],
            "persona": s.get("persona", ""),
            "db_schema": s.get("db_schema", ""),
            "email_divisions": s.get("email_divisions", []),
            "qdrant_collections": s.get("qdrant_collections", []),
        })
    return manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fortress Sector Ingest Tool")
    parser.add_argument("--validate", action="store_true", help="Validate atlas")
    parser.add_argument("--snapshot", action="store_true", help="Snapshot sector data")
    parser.add_argument("--manifest", action="store_true", help="Generate context manifest")
    parser.add_argument("--sector", type=str, help="Target a specific sector slug")
    args = parser.parse_args()

    if args.validate:
        issues = validate_atlas()
        if issues:
            print("VALIDATION FAILED:")
            for i in issues:
                print(f"  - {i}")
            sys.exit(1)
        else:
            print("Atlas validation passed")

    elif args.snapshot:
        sectors = get_sectors()
        if args.sector:
            sectors = [s for s in sectors if s["slug"] == args.sector]
            if not sectors:
                print(f"Sector not found: {args.sector}")
                sys.exit(1)

        for sector in sectors:
            snap = snapshot_sector(sector)
            try:
                save_snapshot(snap, sector["slug"])
            except Exception as e:
                log.warning(f"Cannot save to NAS: {e} — printing to stdout")
                print(json.dumps(snap, indent=2))

    elif args.manifest:
        manifest = generate_manifest()
        print(json.dumps(manifest, indent=2))

    else:
        parser.print_help()
