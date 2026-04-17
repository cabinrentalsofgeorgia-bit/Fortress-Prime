#!/usr/bin/env python3
"""
Populate property_images in fortress_shadow from Streamline gallery API.

Fetches gallery images for each active property via GetPropertyGalleryImages,
maps them to the shadow DB UUIDs via streamline_property_id, and inserts
with display_order and is_hero flag.

Idempotent: deletes existing images per property before re-inserting.
"""

import json
import time
import requests
import psycopg2

SHADOW_DSN = "postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow"
STREAMLINE_URL = "https://web.streamlinevrs.com/api/json"
STREAMLINE_KEY = "f97677a4725bc121cf83011825b0ea46"
STREAMLINE_SECRET = "54f7236b53f30e60a28c7aaadd31e8f17b532e00"


def streamline_call(method: str, params: dict | None = None) -> dict:
    payload = {
        "methodName": method,
        "params": {
            "token_key": STREAMLINE_KEY,
            "token_secret": STREAMLINE_SECRET,
            **(params or {}),
        },
    }
    resp = requests.post(STREAMLINE_URL, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status", {})
    if status.get("code") in ("E0010", "E0011"):
        raise RuntimeError(f"Streamline auth error: {status}")
    return data


def fetch_gallery(unit_id: str) -> list[dict]:
    data = streamline_call("GetPropertyGalleryImages", {"unit_id": unit_id})
    raw = data.get("data", {})
    if isinstance(raw, dict):
        images = raw.get("image", [])
    elif isinstance(raw, list):
        images = raw
    else:
        images = []
    if isinstance(images, dict):
        images = [images]
    return images


def main():
    conn = psycopg2.connect(SHADOW_DSN)
    cur = conn.cursor()

    cur.execute(
        "SELECT id, name, slug, streamline_property_id FROM properties "
        "WHERE is_active = true AND streamline_property_id IS NOT NULL "
        "ORDER BY name"
    )
    properties = cur.fetchall()
    print(f"Found {len(properties)} active properties with Streamline IDs")

    total_inserted = 0
    for prop_id, name, slug, sl_id in properties:
        try:
            images = fetch_gallery(sl_id)
        except Exception as e:
            print(f"  {name}: FAILED ({e})")
            continue

        if not images:
            print(f"  {name}: 0 images from Streamline")
            continue

        cur.execute("DELETE FROM property_images WHERE property_id = %s", (prop_id,))

        for i, img in enumerate(images):
            legacy_url = img.get("original_path") or img.get("image_path") or ""
            sovereign_url = img.get("image_path") or legacy_url
            alt_text = img.get("title") or img.get("description") or ""
            if isinstance(alt_text, dict):
                alt_text = ""
            alt_text = str(alt_text).strip()[:512] or f"{name} - Photo {i + 1}"

            cur.execute(
                """
                INSERT INTO property_images (id, property_id, legacy_url, sovereign_url, display_order, alt_text, is_hero, status)
                VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, 'ingested')
                """,
                (prop_id, legacy_url, sovereign_url, i, alt_text, i == 0),
            )
            total_inserted += 1

        print(f"  {name}: {len(images)} images (sl_id={sl_id})")
        time.sleep(0.3)

    conn.commit()
    print(f"\nTotal images inserted: {total_inserted}")

    cur.execute(
        "SELECT p.slug, count(pi.id) as cnt, "
        "  (SELECT pi2.sovereign_url FROM property_images pi2 WHERE pi2.property_id = p.id AND pi2.is_hero = true LIMIT 1) as hero "
        "FROM properties p LEFT JOIN property_images pi ON pi.property_id = p.id "
        "WHERE p.is_active = true "
        "GROUP BY p.id, p.slug ORDER BY p.slug"
    )
    print("\nImage counts per cabin:")
    for row in cur.fetchall():
        hero_url = (row[2] or "")[:80]
        print(f"  {row[0]}: {row[1]} images, hero={hero_url}")

    conn.close()


if __name__ == "__main__":
    main()
