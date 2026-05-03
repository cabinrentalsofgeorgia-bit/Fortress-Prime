#!/usr/bin/env python3
"""
Fetch property descriptions from Streamline and store them in
properties.ota_metadata->'description' in fortress_shadow.
"""

import os
import json
import hashlib
import hmac
import time
import requests
import psycopg2

SHADOW_DSN = os.environ.get("POSTGRES_ADMIN_URI", "").replace("+asyncpg", "")
STREAMLINE_URL = "https://web.streamlinevrs.com/api/json"
STREAMLINE_KEY = os.environ.get("STREAMLINE_API_KEY", "")
STREAMLINE_SECRET = os.environ.get("STREAMLINE_API_SECRET", "")
if not SHADOW_DSN:
    raise RuntimeError("POSTGRES_ADMIN_URI env var required")
if not STREAMLINE_KEY or not STREAMLINE_SECRET:
    raise RuntimeError("STREAMLINE_API_KEY and STREAMLINE_API_SECRET env vars required")


def streamline_call(method: str, params: dict | None = None) -> dict:
    ts = str(int(time.time()))
    sig = hmac.new(STREAMLINE_SECRET.encode(), ts.encode(), hashlib.sha256).hexdigest()
    payload = {
        "methodName": method,
        "params": {
            "api_key": STREAMLINE_KEY,
            "timestamp": ts,
            "signature": sig,
            **(params or {}),
        },
    }
    resp = requests.post(STREAMLINE_URL, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main():
    conn = psycopg2.connect(SHADOW_DSN)
    cur = conn.cursor()

    cur.execute("SELECT id, name, streamline_property_id, ota_metadata FROM properties WHERE is_active = true ORDER BY name")
    properties = cur.fetchall()
    print(f"Found {len(properties)} active properties")

    # Fetch all properties from Streamline in one call
    print("Fetching Streamline property list...")
    try:
        result = streamline_call("GetPropertyList")
        data = result.get("data", {})
        if isinstance(data, dict):
            sl_properties = data.get("property", [])
            if isinstance(sl_properties, dict):
                sl_properties = [sl_properties]
        else:
            sl_properties = []
        print(f"Streamline returned {len(sl_properties)} properties")
    except Exception as e:
        print(f"Streamline API call failed: {e}")
        print("Falling back to generating descriptions from amenity data...")
        sl_properties = []

    # Build streamline_id -> description map
    sl_desc_map: dict[str, str] = {}
    for sp in sl_properties:
        unit_id = str(sp.get("unit_id", sp.get("id", "")))
        desc = sp.get("description", "") or sp.get("short_description", "") or sp.get("long_description", "")
        if unit_id and desc:
            sl_desc_map[unit_id] = desc

    print(f"Descriptions found: {len(sl_desc_map)}")

    updated = 0
    generated = 0
    for prop_id, name, streamline_id, ota_metadata in properties:
        desc = sl_desc_map.get(str(streamline_id), "")

        if not desc:
            # Generate a basic description from the DB data
            cur.execute(
                """
                SELECT bedrooms, bathrooms, max_guests, address,
                  (SELECT string_agg(elem->>'amenity_name', ', ')
                   FROM jsonb_array_elements(amenities) elem
                   WHERE elem->>'amenity_show_on_website' = 'yes') as visible_amenities
                FROM properties WHERE id = %s
                """,
                (prop_id,),
            )
            row = cur.fetchone()
            if row:
                beds, baths, guests, addr, amenity_str = row
                parts = [f"<p>{name} is a stunning {beds}-bedroom, {baths}-bathroom cabin in Blue Ridge, GA that sleeps up to {guests} guests.</p>"]
                if amenity_str:
                    parts.append(f"<p>Property highlights include {amenity_str}.</p>")
                if addr:
                    parts.append(f"<p>Located at {addr} in the heart of the North Georgia mountains.</p>")
                parts.append("<p>Book your mountain getaway today and experience the best of Blue Ridge cabin living.</p>")
                desc = "\n".join(parts)
                generated += 1

        if desc:
            meta = ota_metadata if isinstance(ota_metadata, dict) else {}
            meta["description"] = desc
            cur.execute(
                "UPDATE properties SET ota_metadata = %s WHERE id = %s",
                (json.dumps(meta), prop_id),
            )
            updated += 1
            print(f"  {name}: {len(desc)} chars")

    conn.commit()
    print(f"\nUpdated: {updated} (API: {updated - generated}, Generated: {generated})")
    conn.close()


if __name__ == "__main__":
    main()
