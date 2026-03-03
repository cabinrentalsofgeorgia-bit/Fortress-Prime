"""
STREAMLINE PROPERTY SYNC — Daily Asset Bridge
================================================
Fortress Prime | Cabin Rentals of Georgia
Lead Architect: Gary M. Knight

Wakes up daily at 05:00 AM, pulls the latest cabin portfolio from
Streamline VRS, and upserts into the ops_properties table.

Captures: property metadata, GPS coordinates, rates, bedrooms/baths,
max occupancy, owner info, addresses, areas, and status.

Usage:
    python3 src/bridges/streamline_property_sync.py          # full sync
    python3 src/bridges/streamline_property_sync.py --init    # create table only
    python3 src/bridges/streamline_property_sync.py --show    # show current assets

Cron (05:00 daily):
    0 5 * * * /usr/bin/python3 /home/admin/Fortress-Prime/src/bridges/streamline_property_sync.py
"""

import os
import sys
import json
import logging
import argparse
import requests
import psycopg2
import psycopg2.extras
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
except ImportError:
    pass

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

# ---------------------------------------------------------------------------
# Streamline API Config (from .env)
# ---------------------------------------------------------------------------
TOKEN_KEY = os.getenv("STREAMLINE_TOKEN_KEY", "")
TOKEN_SECRET = os.getenv("STREAMLINE_TOKEN_SECRET", "")
API_URL = "https://web.streamlinevrs.com/api/json"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = "/mnt/fortress_nas/fortress_data/ai_brain/logs"
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("AssetSync")
logger.setLevel(logging.INFO)

_fh = logging.FileHandler(os.path.join(LOG_DIR, "asset_sync.log"))
_fh.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(_ch)


# ---------------------------------------------------------------------------
# Schema: ops_properties
# ---------------------------------------------------------------------------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ops_properties (
    id                  SERIAL PRIMARY KEY,
    streamline_id       INTEGER UNIQUE NOT NULL,
    property_id         TEXT UNIQUE NOT NULL,
    name                TEXT NOT NULL,
    unit_code           TEXT,
    status_name         TEXT DEFAULT 'Active',
    status_id           INTEGER DEFAULT 1,

    -- Location
    address             TEXT,
    address2            TEXT,
    city                TEXT,
    state_name          TEXT,
    zip                 TEXT,
    country_name        TEXT,
    latitude            NUMERIC(10, 7),
    longitude           NUMERIC(11, 7),
    location_area_name  TEXT,
    resort_area_name    TEXT,
    view_name           TEXT,

    -- Property Details
    bedrooms            NUMERIC(4, 1),
    bathrooms           NUMERIC(4, 1),
    max_occupants       INTEGER,
    max_adults          INTEGER,
    max_pets            INTEGER,
    lodging_type_id     INTEGER,
    square_feet         INTEGER,

    -- Owner
    company_id          INTEGER,
    owning_type_id      INTEGER,

    -- Operations
    wifi_name           TEXT,
    wifi_key            TEXT,
    lock_box_code       TEXT,
    lock_box_directions TEXT,
    comment             TEXT,

    -- Booking Config
    online_bookings     BOOLEAN DEFAULT TRUE,
    shortterm_enabled   BOOLEAN DEFAULT TRUE,
    longterm_enabled    BOOLEAN DEFAULT FALSE,
    coupons_enabled     BOOLEAN DEFAULT TRUE,
    discounts_enabled   BOOLEAN DEFAULT TRUE,

    -- SEO / Web
    seo_title           TEXT,
    flyer_url           TEXT,
    default_image_url   TEXT,
    description_short   TEXT,

    -- Metadata
    streamline_created  TIMESTAMP,
    last_reservation    TIMESTAMP,
    last_synced         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Raw JSON (full Streamline response for this property)
    raw_json            JSONB
);

CREATE INDEX IF NOT EXISTS idx_ops_prop_name ON ops_properties(name);
CREATE INDEX IF NOT EXISTS idx_ops_prop_city ON ops_properties(city);
CREATE INDEX IF NOT EXISTS idx_ops_prop_status ON ops_properties(status_name);
CREATE INDEX IF NOT EXISTS idx_ops_prop_area ON ops_properties(location_area_name);
"""


# ---------------------------------------------------------------------------
# Streamline API Helper
# ---------------------------------------------------------------------------
def call_streamline(method: str, extra_params: dict = None) -> dict:
    """Call the Streamline VRS Legacy RPC API."""
    params = {"token_key": TOKEN_KEY, "token_secret": TOKEN_SECRET}
    if extra_params:
        params.update(extra_params)

    payload = {"methodName": method, "params": params}
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

    resp = requests.post(API_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _parse_timestamp(raw: str) -> datetime:
    """Parse Streamline's timestamp format."""
    if not raw:
        return None
    for fmt in ["%m/%d/%Y %H:%M:%S %Z", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"]:
        try:
            return datetime.strptime(raw.strip().split(" EST")[0].strip(), fmt.rstrip(" %Z"))
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# SYNC ENGINE
# ---------------------------------------------------------------------------
def init_schema():
    """Create the ops_properties table if it doesn't exist."""
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )
    cur = conn.cursor()

    # Check if table already exists
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'ops_properties'
        )
    """)
    exists = cur.fetchone()[0]

    if exists:
        logger.info("[SYNC] ops_properties table already exists — skipping creation.")
    else:
        cur.execute(SCHEMA_SQL)
        conn.commit()
        logger.info("[SYNC] ops_properties schema created.")

    cur.close()
    conn.close()


def sync_assets():
    """
    Pull all active properties from Streamline and upsert into ops_properties.
    """
    logger.info(f"[SYNC] Starting Asset Sync...")

    if not TOKEN_KEY or not TOKEN_SECRET:
        logger.error("[SYNC] Missing Streamline credentials in .env")
        return {"status": "FAILED", "reason": "Missing credentials"}

    # 1. Pull from Streamline
    try:
        result = call_streamline("GetPropertyList", {"status_id": 1})
    except Exception as e:
        logger.error(f"[SYNC] API call failed: {e}")
        return {"status": "FAILED", "reason": str(e)}

    # Check for API errors
    status = result.get("status", {})
    if status.get("code"):
        logger.error(f"[SYNC] API error: {status}")
        return {"status": "FAILED", "reason": status.get("description", "Unknown")}

    properties = result.get("data", {}).get("property", [])
    if not properties:
        logger.warning("[SYNC] No properties returned from Streamline.")
        return {"status": "EMPTY", "count": 0}

    logger.info(f"[SYNC] Retrieved {len(properties)} properties from Streamline.")

    # 2. Also pull owner list to enrich data
    try:
        owner_result = call_streamline("GetOwnerList")
        owners_raw = owner_result.get("data", {}).get("owner", [])
        # Build owner lookup by property name
        owner_map = {}
        for o in owners_raw:
            props = o.get("property", {})
            if isinstance(props, dict):
                props = [props]
            for p in props:
                pname = p.get("property_name", "")
                if pname:
                    owner_map[pname.lower()] = {
                        "owner_id": o.get("owner_id"),
                        "owner_name": f"{o.get('first_name', '')} {o.get('last_name', '')}".strip(),
                        "owner_email": o.get("email", ""),
                    }
    except Exception:
        owner_map = {}

    # 3. Upsert into PostgreSQL
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )
    cur = conn.cursor()

    synced = 0
    for p in properties:
        sid = p.get("id")
        name = p.get("name", "Unknown")

        # Generate a clean property_id slug
        prop_id = name.lower().replace(" ", "_").replace("'", "").replace("-", "_")

        created_dt = _parse_timestamp(p.get("creation_date", ""))
        last_res_dt = _parse_timestamp(p.get("last_reservation_update", ""))

        # Check if this property already exists by property_id or streamline_id
        cur.execute(
            "SELECT property_id FROM ops_properties WHERE streamline_id = %s",
            (sid,)
        )
        existing = cur.fetchone()

        if existing:
            # UPDATE existing row
            cur.execute("""
                UPDATE ops_properties SET
                    name = %s, internal_name = %s,
                    unit_code = %s, status_name = %s, status_id = %s,
                    address = %s, address2 = %s, city = %s, state_name = %s,
                    zip = %s, country_name = %s,
                    latitude = %s, longitude = %s,
                    location_area_name = %s, resort_area_name = %s, view_name = %s,
                    bedrooms = %s, bathrooms = %s,
                    max_occupants = %s, max_adults = %s, max_pets = %s,
                    lodging_type_id = %s, square_feet = %s,
                    company_id = %s, owning_type_id = %s,
                    access_code_wifi = %s, access_code_door = %s,
                    seo_title = %s, flyer_url = %s,
                    default_image_url = %s, description_short = %s,
                    last_reservation = %s,
                    last_synced = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP,
                    raw_json = %s
                WHERE streamline_id = %s
            """, (
                name, name,
                p.get("unit_code"), p.get("status_name", "Active"), p.get("status_id", 1),
                p.get("address"), p.get("address2"),
                p.get("city"), p.get("state_name"), p.get("zip"), p.get("country_name"),
                p.get("location_latitude"), p.get("location_longitude"),
                p.get("location_area_name"), p.get("location_resort_name"),
                p.get("view_name"),
                p.get("bedrooms_number"), p.get("bathrooms_number"),
                p.get("max_occupants"), p.get("max_adults"), p.get("max_pets"),
                p.get("lodging_type_id"), p.get("square_foots"),
                p.get("company_id"), p.get("owning_type_id"),
                p.get("wifi_security_key"), p.get("lock_box_code"),
                p.get("seo_title"), p.get("flyer_url"),
                p.get("default_image_path"), p.get("short_description"),
                last_res_dt,
                json.dumps(p, default=str),
                sid,
            ))
        else:
            # INSERT new row
            cur.execute("""
                INSERT INTO ops_properties (
                    streamline_id, property_id, name, internal_name,
                    unit_code, status_name, status_id,
                    address, address2, city, state_name, zip, country_name,
                    latitude, longitude,
                    location_area_name, resort_area_name, view_name,
                    bedrooms, bathrooms,
                    max_occupants, max_adults, max_pets,
                    lodging_type_id, square_feet, company_id, owning_type_id,
                    access_code_wifi, access_code_door,
                    seo_title, flyer_url, default_image_url, description_short,
                    streamline_created, last_reservation,
                    last_synced, updated_at,
                    raw_json
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                    %s
                )
            """, (
                sid, prop_id, name, name,
                p.get("unit_code"), p.get("status_name", "Active"), p.get("status_id", 1),
                p.get("address"), p.get("address2"),
                p.get("city"), p.get("state_name"), p.get("zip"), p.get("country_name"),
                p.get("location_latitude"), p.get("location_longitude"),
                p.get("location_area_name"), p.get("location_resort_name"),
                p.get("view_name"),
                p.get("bedrooms_number"), p.get("bathrooms_number"),
                p.get("max_occupants"), p.get("max_adults"), p.get("max_pets"),
                p.get("lodging_type_id"), p.get("square_foots"),
                p.get("company_id"), p.get("owning_type_id"),
                p.get("wifi_security_key"), p.get("lock_box_code"),
                p.get("seo_title"), p.get("flyer_url"),
                p.get("default_image_path"), p.get("short_description"),
                created_dt, last_res_dt,
                json.dumps(p, default=str),
            ))
        synced += 1

    conn.commit()
    cur.close()
    conn.close()

    logger.info(f"[SYNC] Complete. {synced} assets synced to ops_properties.")
    return {"status": "SYNCED", "count": synced}


def show_assets():
    """Display current ops_properties contents."""
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT streamline_id, name, city, location_area_name,
               bedrooms, bathrooms, max_occupants, status_name, last_synced
        FROM ops_properties
        ORDER BY name
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    print("=" * 72)
    print("  FORTRESS PRIME — ASSET REGISTRY")
    print("=" * 72)
    print(f"  Total Properties: {len(rows)}")
    print()

    for i, r in enumerate(rows, 1):
        print(f"  {i:3d}. {r['name']}")
        print(f"       ID: {r['streamline_id']} | {r['city']} | "
              f"Area: {r['location_area_name'] or '?'}")
        print(f"       Beds: {r['bedrooms']} | Baths: {r['bathrooms']} | "
              f"Max Occ: {r['max_occupants']} | Status: {r['status_name']}")
        print(f"       Last Synced: {r['last_synced']}")
        print()

    print("=" * 72)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Streamline Property Sync")
    parser.add_argument("--init", action="store_true", help="Create ops_properties table")
    parser.add_argument("--show", action="store_true", help="Show current asset registry")
    args = parser.parse_args()

    if args.init:
        init_schema()
        print("  ops_properties table created.")
    elif args.show:
        show_assets()
    else:
        init_schema()
        result = sync_assets()
        print()
        print("=" * 64)
        print(f"  ASSET SYNC: {result['status']}")
        if "count" in result:
            print(f"  Properties: {result['count']}")
        print("=" * 64)
