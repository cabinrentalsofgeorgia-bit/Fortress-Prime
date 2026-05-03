#!/usr/bin/env python3
from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import psycopg2

SHADOW_DSN = os.environ.get("POSTGRES_ADMIN_URI", "").replace("+asyncpg", "")
if not SHADOW_DSN:
    raise RuntimeError("POSTGRES_ADMIN_URI env var required")

ADDONS = [
    ("Early Check-In (1 hour)", "Arrive one hour before standard check-in time.", Decimal('50.00'), 'flat_fee'),
    ("Early Check-In (2 hours)", "Arrive two hours before standard check-in time.", Decimal('100.00'), 'flat_fee'),
    ("Late Check-Out (1 hour)", "Stay one extra hour beyond standard check-out.", Decimal('50.00'), 'flat_fee'),
    ("Late Check-Out (2 hours)", "Stay two extra hours beyond standard check-out.", Decimal('100.00'), 'flat_fee'),
    ("Firewood - 1/4 Face Cord", "Firewood delivered to your cabin.", Decimal('75.00'), 'flat_fee'),
    ("Firewood - 1/2 Face Cord", "Half face cord of firewood delivered to your cabin.", Decimal('125.00'), 'flat_fee'),
    ("Guided Trophy Fishing - Half Day", "Guided trophy fishing excursion (half day).", Decimal('250.00'), 'flat_fee'),
    ("Guided Trophy Fishing - Full Day", "Guided trophy fishing excursion (full day).", Decimal('425.00'), 'flat_fee'),
]


def main() -> None:
    conn = psycopg2.connect(SHADOW_DSN)
    try:
        cur = conn.cursor()
        inserted = 0
        updated = 0
        for name, description, price, pricing_model in ADDONS:
            cur.execute("SELECT id FROM vrs_add_ons WHERE name = %s LIMIT 1", (name,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    UPDATE vrs_add_ons
                    SET description = %s,
                        price = %s,
                        pricing_model = %s,
                        scope = 'global',
                        property_id = NULL,
                        is_active = true,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (description, price, pricing_model, row[0]),
                )
                updated += 1
            else:
                cur.execute(
                    """
                    INSERT INTO vrs_add_ons (id, name, description, price, pricing_model, scope, property_id, is_active, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'global', NULL, true, now(), now())
                    """,
                    (str(uuid4()), name, description, price, pricing_model),
                )
                inserted += 1
        conn.commit()
        print(f'Inserted: {inserted}, Updated: {updated}')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
