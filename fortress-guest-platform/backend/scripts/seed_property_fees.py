#!/usr/bin/env python3
"""Seed the sovereign fee and tax ledger for all active properties.

Run from the backend directory:
    python scripts/seed_property_fees.py

Fee calculation rules (sourced from Streamline invoice audit 2026-04-12):
  - Cleaning Fee:   flat per-property, multiply by 1 (see PROPERTY_CLEANING_FEE_OVERRIDES)
  - ADW:            $65.00 flat, non-taxable
  - DOT Tax:        $5.00 × nights (per-night rate; pricing_service multiplies by nights at quote time)
  - Processing Fee: 6% of taxable base (rent + cleaning + party fees; ADW and DOT Tax excluded)
  - County Tax:     6% of taxable base
  - State Tax:      7% of taxable base

Taxable base = base_rent + cleaning_fee + party_fee
               (ADW, DOT Tax, and Processing Fee are NOT in the taxable base)
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import psycopg2

SHADOW_DSN = "postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow"

# ── Global fees — applied uniformly to all active properties ──────────────────
# Each entry: (name, flat_amount, fee_type, percentage_rate, is_optional)
#   fee_type='flat'       → charge flat_amount (DOT Tax: pricing_service multiplies by nights)
#   fee_type='percentage' → charge (taxable_base × percentage_rate / 100)
GLOBAL_FEES: dict[str, tuple[str, Decimal, str, Decimal | None, bool]] = {
    'a0000001-0001-4000-8000-000000000003': (
        'Accidental Damage Waiver', Decimal('65.00'), 'flat', None, False,
    ),
    'a0000001-0001-4000-8000-000000000004': (
        # flat_amount is the PER-NIGHT rate; pricing_service.py multiplies by nights
        'DOT Tax', Decimal('5.00'), 'flat', None, False,
    ),
    'a0000001-0001-4000-8000-000000000005': (
        # 6% of taxable base (rent + cleaning + party fees)
        'Processing Fee', Decimal('0.00'), 'percentage', Decimal('6.000'), False,
    ),
    'a0000001-0001-4000-8000-000000000006': (
        'Early Check-In', Decimal('50.00'), 'flat', None, True,
    ),
    'a0000001-0001-4000-8000-000000000007': (
        'Late Check-Out', Decimal('50.00'), 'flat', None, True,
    ),
}

# ── Global taxes — applied uniformly to all active properties ─────────────────
# Replaces the old single "Fannin County Lodging Tax" at 12%.
# Taxable base = rent + cleaning + party fees (ADW/DOT Tax/Processing Fee excluded).
GLOBAL_TAXES: dict[str, tuple[str, Decimal]] = {
    'b0000001-0001-4000-8000-000000000001': ('County Tax', Decimal('6.00')),
    'b0000001-0001-4000-8000-000000000002': ('State Tax',  Decimal('7.00')),
}

# ── Authoritative cleaning fee schedule ───────────────────────────────────────
# Source: last-10 reservation modal per property (fortress_guest audit 2026-04-12).
# Properties marked needs_verification have <10 reservations or no reservation
# history and require manual confirmation before going live.
PROPERTY_CLEANING_FEE_OVERRIDES: dict[str, Decimal] = {
    'above-the-timberline':                  Decimal('325.00'),
    'aska-escape-lodge':                     Decimal('225.00'),
    'blue-ridge-lake-sanctuary':             Decimal('225.00'),
    'chase-mountain-dreams':                 Decimal('275.00'),  # needs_verification: only 10 reservations
    'cherokee-sunrise-on-noontootla-creek':  Decimal('185.00'),
    'cohutta-sunset':                        Decimal('250.00'),
    'creekside-green':                       Decimal('199.00'),
    'fallen-timber-lodge':                   Decimal('399.00'),
    'high-hopes':                            Decimal('275.00'),
    'restoration-luxury':                    Decimal('250.00'),  # needs_verification: no reservation history
    'riverview-lodge':                       Decimal('375.00'),
    'serendipity-on-noontootla-creek':       Decimal('375.00'),
    'skyfall':                               Decimal('285.00'),  # needs_verification: only 5 reservations
    'the-rivers-edge':                       Decimal('325.00'),
}


def main() -> None:
    conn = psycopg2.connect(SHADOW_DSN)
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT id::text, slug, bedrooms FROM properties WHERE is_active = true ORDER BY slug"
        )
        properties = cur.fetchall()
        print(f'Active properties: {len(properties)}')

        # ── Per-property cleaning fees ─────────────────────────────────────────
        inserted = 0
        updated = 0
        for prop_id, slug, bedrooms in properties:
            fee_amount = PROPERTY_CLEANING_FEE_OVERRIDES.get(slug)
            if fee_amount is None:
                if bedrooms >= 5:
                    fee_amount = Decimal('250.00')
                elif bedrooms >= 4:
                    fee_amount = Decimal('200.00')
                else:
                    fee_amount = Decimal('150.00')
                print(f'  {slug}: no override, using bedrooms heuristic ${fee_amount}')

            fee_name = f'Cleaning Fee - {slug}'
            cur.execute(
                "SELECT f.id FROM property_fees pf JOIN fees f ON f.id = pf.fee_id "
                "WHERE pf.property_id = %s AND f.name = %s LIMIT 1",
                (prop_id, fee_name),
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    "UPDATE fees SET flat_amount = %s, updated_at = now() WHERE id = %s",
                    (fee_amount, existing[0]),
                )
                updated += 1
            else:
                fee_id = str(uuid4())
                cur.execute(
                    "INSERT INTO fees (id, name, flat_amount, fee_type, is_pet_fee, is_optional, is_active, created_at, updated_at) "
                    "VALUES (%s, %s, %s, 'flat', false, false, true, now(), now())",
                    (fee_id, fee_name, fee_amount),
                )
                cur.execute(
                    "INSERT INTO property_fees (id, property_id, fee_id, is_active, created_at, updated_at) "
                    "VALUES (%s, %s, %s, true, now(), now()) "
                    "ON CONFLICT (property_id, fee_id) DO NOTHING",
                    (str(uuid4()), prop_id, fee_id),
                )
                inserted += 1
            print(f'  {slug}: ${fee_amount}')

        print(f'Cleaning fees — inserted: {inserted}, updated: {updated}')

        # ── Global fees (ADW, DOT Tax, Processing Fee, Check-In/Out) ──────────
        for fee_uuid, (fee_name, fee_amount, fee_type, pct_rate, is_opt) in GLOBAL_FEES.items():
            cur.execute("SELECT id FROM fees WHERE id = %s::uuid LIMIT 1", (fee_uuid,))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO fees (id, name, flat_amount, fee_type, percentage_rate, is_pet_fee, is_optional, is_active, created_at, updated_at) "
                    "VALUES (%s::uuid, %s, %s, %s, %s, false, %s, true, now(), now())",
                    (fee_uuid, fee_name, fee_amount, fee_type, pct_rate, is_opt),
                )
            else:
                cur.execute(
                    "UPDATE fees SET name = %s, flat_amount = %s, fee_type = %s, percentage_rate = %s, "
                    "is_optional = %s, is_active = true, updated_at = now() WHERE id = %s::uuid",
                    (fee_name, fee_amount, fee_type, pct_rate, is_opt, fee_uuid),
                )

            for prop_id, _slug, _beds in properties:
                cur.execute(
                    "INSERT INTO property_fees (id, property_id, fee_id, is_active, created_at, updated_at) "
                    "VALUES (%s::uuid, %s, %s::uuid, true, now(), now()) "
                    "ON CONFLICT (property_id, fee_id) DO UPDATE SET is_active = true, updated_at = now()",
                    (str(uuid4()), prop_id, fee_uuid),
                )

            label = f'{pct_rate}% of taxable base' if fee_type == 'percentage' else f'${fee_amount}'
            print(f'Global fee: {fee_name} = {label} → {len(properties)} properties')

        # ── County Tax + State Tax ─────────────────────────────────────────────
        # Replaces old single "Fannin County Lodging Tax" at 12%.
        # Deactivate old combined tax row to avoid double-counting.
        cur.execute(
            "UPDATE taxes SET is_active = false, updated_at = now() "
            "WHERE name NOT IN %s AND id::text NOT IN %s",
            (
                tuple(name for name, _ in GLOBAL_TAXES.values()),
                tuple(GLOBAL_TAXES.keys()),
            ),
        )

        for tax_uuid, (tax_name, pct_rate) in GLOBAL_TAXES.items():
            cur.execute("SELECT id FROM taxes WHERE id = %s::uuid LIMIT 1", (tax_uuid,))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO taxes (id, name, percentage_rate, is_active, created_at, updated_at) "
                    "VALUES (%s::uuid, %s, %s, true, now(), now())",
                    (tax_uuid, tax_name, pct_rate),
                )
            else:
                cur.execute(
                    "UPDATE taxes SET name = %s, percentage_rate = %s, is_active = true, updated_at = now() "
                    "WHERE id = %s::uuid",
                    (tax_name, pct_rate, tax_uuid),
                )

            for prop_id, _slug, _beds in properties:
                cur.execute(
                    "INSERT INTO property_taxes (id, property_id, tax_id, is_active, created_at, updated_at) "
                    "VALUES (%s::uuid, %s, %s::uuid, true, now(), now()) "
                    "ON CONFLICT (property_id, tax_id) DO UPDATE SET is_active = true, updated_at = now()",
                    (str(uuid4()), prop_id, tax_uuid),
                )
            print(f'Tax: {tax_name} = {pct_rate}% → {len(properties)} properties')

        conn.commit()
        print('Done.')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
