#!/usr/bin/env python3
"""
Copies blocked_days from fortress_guest into fortress_shadow,
remapping property_id via streamline_property_id.

The API reads from fortress_shadow but blocked_days were synced
into fortress_guest. This script bridges the gap.
"""

import os

import psycopg2
from datetime import date

GUEST_DSN = os.environ.get("FORTRESS_GUEST_DSN")
SHADOW_DSN = os.environ.get("FORTRESS_SHADOW_DSN")
if not GUEST_DSN or not SHADOW_DSN:
    raise RuntimeError("FORTRESS_GUEST_DSN and FORTRESS_SHADOW_DSN env vars required")


def main():
    guest_conn = psycopg2.connect(GUEST_DSN)
    shadow_conn = psycopg2.connect(SHADOW_DSN)

    try:
        guest_cur = guest_conn.cursor()
        shadow_cur = shadow_conn.cursor()

        # Build streamline_id -> shadow UUID map
        shadow_cur.execute(
            "SELECT id, streamline_property_id FROM properties WHERE is_active = true"
        )
        shadow_map = {}
        for row in shadow_cur.fetchall():
            if row[1]:
                shadow_map[str(row[1])] = row[0]
        print(f"Shadow properties: {len(shadow_map)}")

        # Build guest streamline_id -> guest UUID map
        guest_cur.execute(
            "SELECT id, streamline_property_id FROM properties WHERE is_active = true"
        )
        guest_to_streamline = {}
        for row in guest_cur.fetchall():
            if row[1]:
                guest_to_streamline[row[0]] = str(row[1])
        print(f"Guest properties: {len(guest_to_streamline)}")

        # Fetch all blocked_days from guest
        guest_cur.execute(
            "SELECT property_id, start_date, end_date, block_type, confirmation_code, source "
            "FROM blocked_days"
        )
        guest_blocked = guest_cur.fetchall()
        print(f"Guest blocked_days: {len(guest_blocked)}")

        # Check existing shadow blocked_days
        shadow_cur.execute("SELECT count(*) FROM blocked_days")
        existing = shadow_cur.fetchone()[0]
        print(f"Existing shadow blocked_days: {existing}")

        # Remap and insert
        inserted = 0
        skipped = 0
        for row in guest_blocked:
            guest_prop_id, start_dt, end_dt, block_type, conf_code, source = row
            streamline_id = guest_to_streamline.get(guest_prop_id)
            if not streamline_id:
                skipped += 1
                continue
            shadow_prop_id = shadow_map.get(streamline_id)
            if not shadow_prop_id:
                skipped += 1
                continue

            shadow_cur.execute(
                """
                INSERT INTO blocked_days (id, property_id, start_date, end_date, block_type, confirmation_code, source, created_at, updated_at)
                VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, now(), now())
                ON CONFLICT (property_id, start_date, end_date, block_type) DO NOTHING
                """,
                (shadow_prop_id, start_dt, end_dt, block_type, conf_code, source),
            )
            inserted += 1

        shadow_conn.commit()
        print(f"Inserted: {inserted}, Skipped: {skipped}")

        # Verify
        shadow_cur.execute(
            "SELECT p.slug, count(bd.id) "
            "FROM blocked_days bd JOIN properties p ON bd.property_id = p.id "
            "GROUP BY p.slug ORDER BY p.slug"
        )
        print("\nShadow blocked_days per cabin:")
        for row in shadow_cur.fetchall():
            print(f"  {row[0]}: {row[1]}")

    finally:
        guest_conn.close()
        shadow_conn.close()


if __name__ == "__main__":
    main()
