"""
DIVISION 2: THE RAINMAKER — SHADOW REVENUE ESTIMATOR
=====================================================
Reconstructs booking revenue from the Shadow Calendar turnover data.

Strategy:
    1. Extract booking periods from ops_turnovers (checkout → next checkin = gap,
       consecutive checkins = stay duration)
    2. Estimate nightly rates from bedroom tier (calibrated from real rate data)
    3. Calculate gross revenue, taxes, management fees, owner payouts
    4. Populate fin_reservations + fin_owner_balances + fin_revenue_snapshots

Rate Calibration (from QuantRevenue engine — Rolling River 3BR = $275 base):
    2 BR: $175/night    3 BR: $225/night    4 BR: $300/night
    5 BR: $375/night    7 BR: $500/night

Tax Rate: 13% (Georgia state + Fannin County lodging tax estimate)
Management Fee: 25% of gross rent (CROG standard)

Usage:
    python3 src/bridges/shadow_revenue.py

Module: CF-02 QuantRevenue — Division 2 Finance
"""

import os
import sys
from datetime import datetime, date, timedelta
from collections import defaultdict
from pathlib import Path

import psycopg2
import psycopg2.extras

try:
    from dotenv import load_dotenv
    load_dotenv("/home/admin/Fortress-Prime/.env")
except ImportError:
    pass

# =============================================================================
# CONFIG
# =============================================================================

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("DB_PASSWORD", "")

# Rate tiers — loaded from cabins/_base_rates.yaml (Single Source of Truth, CF-02)
_RATE_TIERS_CACHE = None

def _load_rate_tiers():
    """Load bedroom→rate mapping from _base_rates.yaml. Falls back to defaults."""
    global _RATE_TIERS_CACHE
    if _RATE_TIERS_CACHE is not None:
        return _RATE_TIERS_CACHE
    try:
        import yaml
        rates_file = Path(__file__).resolve().parent.parent.parent / "cabins" / "_base_rates.yaml"
        with open(rates_file) as f:
            data = yaml.safe_load(f)
        by_br = {}
        for pid, cfg in data.get("properties", {}).items():
            br = cfg.get("bedrooms", 2)
            rate = float(cfg.get("base_rate", 200))
            if br not in by_br:
                by_br[br] = []
            by_br[br].append(rate)
        _RATE_TIERS_CACHE = {br: round(sum(rates) / len(rates), 2) for br, rates in by_br.items()}
        # Fill in missing bedroom counts with reasonable interpolation
        if 1 not in _RATE_TIERS_CACHE:
            _RATE_TIERS_CACHE[1] = round(_RATE_TIERS_CACHE.get(2, 175) * 0.70, 2)
        if 6 not in _RATE_TIERS_CACHE:
            _RATE_TIERS_CACHE[6] = round(
                (_RATE_TIERS_CACHE.get(5, 375) + _RATE_TIERS_CACHE.get(7, 550)) / 2, 2)
    except Exception:
        _RATE_TIERS_CACHE = {
            1: 125.00, 2: 175.00, 3: 250.00, 4: 312.00,
            5: 394.00, 6: 475.00, 7: 550.00,
        }
    return _RATE_TIERS_CACHE

TAX_RATE = 0.13         # GA state + county lodging tax
MGMT_FEE_PCT = 0.25     # CROG management fee
CLEANING_FEE = 150.00   # Flat cleaning fee per stay


def get_db():
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def get_rate_for_bedrooms(bedrooms):
    """Get estimated nightly rate based on bedroom count from _base_rates.yaml."""
    br = int(bedrooms) if bedrooms else 3
    tiers = _load_rate_tiers()
    return tiers.get(br, tiers.get(3, 250.00))


# =============================================================================
# STEP 1: Load property catalog
# =============================================================================

def load_properties(cur):
    """Load property details from ops_properties."""
    cur.execute("""
        SELECT property_id, internal_name, name, bedrooms, max_occupants, streamline_id
        FROM ops_properties
        WHERE property_id NOT LIKE 'CSV-%'
          AND property_id != '70224'
    """)
    props = {}
    for row in cur.fetchall():
        pid = row["property_id"]
        props[pid] = {
            "property_id": pid,
            "name": row["internal_name"] or row["name"] or pid,
            "bedrooms": int(row["bedrooms"]) if row["bedrooms"] else 3,
            "max_occupants": row["max_occupants"] or 6,
            "streamline_id": row["streamline_id"],
        }
    return props


# =============================================================================
# STEP 2: Reconstruct bookings from turnovers
# =============================================================================

def reconstruct_bookings(cur, properties):
    """
    Reconstruct Shadow Reservations from turnover data.

    Logic:
    - Each turnover row = a guest checking OUT (checkout_time) and the next
      guest checking IN (checkin_time)
    - For a given property, sort turnovers by checkout_time
    - The stay that ended at checkout_time STARTED at the previous turnover's
      checkin_time (or is unknown if it's the first record)
    - A booking exists between a checkin and the next checkout for the same property
    """
    cur.execute("""
        SELECT property_id, checkout_time::date as checkout_date,
               checkin_time::date as checkin_date,
               reservation_id_out
        FROM ops_turnovers
        WHERE property_id NOT LIKE 'CSV-%'
          AND property_id != '70224'
        ORDER BY property_id, checkout_time
    """)

    # Group turnovers by property
    by_property = defaultdict(list)
    for row in cur.fetchall():
        by_property[row["property_id"]].append(dict(row))

    bookings = []
    today = date.today()

    for pid, turnovers in by_property.items():
        prop = properties.get(pid)
        if not prop:
            continue

        bedrooms = prop["bedrooms"]
        nightly_rate = get_rate_for_bedrooms(bedrooms)

        # Sort by checkout date
        turnovers.sort(key=lambda x: x["checkout_date"])

        for i, t in enumerate(turnovers):
            checkout = t["checkout_date"]
            checkin = t["checkin_date"]

            # The NEXT booking starts at checkin_date of this turnover
            # and ends at checkout_date of the NEXT turnover
            if i + 1 < len(turnovers):
                next_checkout = turnovers[i + 1]["checkout_date"]
                stay_start = checkin
                stay_end = next_checkout
                nights = (stay_end - stay_start).days

                if nights > 0 and nights <= 30:  # Sanity: max 30 night stays
                    base_rent = round(nightly_rate * nights, 2)
                    taxes = round(base_rent * TAX_RATE, 2)
                    total = round(base_rent + taxes + CLEANING_FEE, 2)

                    res_id = f"SHADOW-{stay_start.isoformat()}-{pid[:20]}"

                    bookings.append({
                        "res_id": res_id,
                        "property_id": pid,
                        "property_name": prop["name"],
                        "check_in": stay_start,
                        "check_out": stay_end,
                        "nights": nights,
                        "nightly_rate": nightly_rate,
                        "base_rent": base_rent,
                        "taxes": taxes,
                        "fees": CLEANING_FEE,
                        "total_revenue": total,
                        "status": "Shadow-Booked",
                        "source": "shadow_calendar",
                        "is_estimation": True,
                        "confidence": "high" if nights <= 7 else "medium",
                        "notes": f"Reconstructed from turnover data. {bedrooms}BR @ ${nightly_rate}/night.",
                    })

            # Also capture the FIRST booking (the one ending at the first checkout)
            # We don't know when it started, but if it's after today, estimate 3-night minimum
            if i == 0 and checkout > today:
                est_start = checkout - timedelta(days=3)
                if est_start < today:
                    est_start = today
                nights = (checkout - est_start).days
                if nights > 0:
                    base_rent = round(nightly_rate * nights, 2)
                    taxes = round(base_rent * TAX_RATE, 2)
                    total = round(base_rent + taxes + CLEANING_FEE, 2)

                    res_id = f"SHADOW-{est_start.isoformat()}-{pid[:20]}-first"

                    bookings.append({
                        "res_id": res_id,
                        "property_id": pid,
                        "property_name": prop["name"],
                        "check_in": est_start,
                        "check_out": checkout,
                        "nights": nights,
                        "nightly_rate": nightly_rate,
                        "base_rent": base_rent,
                        "taxes": taxes,
                        "fees": CLEANING_FEE,
                        "total_revenue": total,
                        "status": "Shadow-Booked",
                        "source": "shadow_calendar",
                        "is_estimation": True,
                        "confidence": "low",
                        "notes": f"Estimated first booking (unknown start). {bedrooms}BR @ ${nightly_rate}/night.",
                    })

    return bookings


# =============================================================================
# STEP 3: Write to Financial Vault
# =============================================================================

def write_reservations(cur, bookings):
    """Insert shadow reservations into fin_reservations."""
    cur.execute("DELETE FROM fin_reservations WHERE source = 'shadow_calendar'")

    for b in bookings:
        cur.execute("""
            INSERT INTO fin_reservations
                (res_id, property_id, property_name, check_in, check_out, nights,
                 nightly_rate, base_rent, taxes, fees, total_revenue,
                 status, source, is_estimation, confidence, notes)
            VALUES (%(res_id)s, %(property_id)s, %(property_name)s,
                    %(check_in)s, %(check_out)s, %(nights)s,
                    %(nightly_rate)s, %(base_rent)s, %(taxes)s, %(fees)s,
                    %(total_revenue)s, %(status)s, %(source)s,
                    %(is_estimation)s, %(confidence)s, %(notes)s)
            ON CONFLICT (res_id) DO UPDATE SET
                total_revenue = EXCLUDED.total_revenue,
                updated_at = CURRENT_TIMESTAMP
        """, b)


def write_owner_balances(cur, bookings, properties):
    """Aggregate revenue per property into fin_owner_balances."""
    cur.execute("DELETE FROM fin_owner_balances")

    # Aggregate by property
    by_prop = defaultdict(lambda: {"nights": 0, "gross": 0.0})
    for b in bookings:
        pid = b["property_id"]
        by_prop[pid]["nights"] += b["nights"]
        by_prop[pid]["gross"] += float(b["base_rent"])

    for pid, agg in by_prop.items():
        prop = properties.get(pid, {})
        name = prop.get("name", pid)
        bedrooms = prop.get("bedrooms", 3)
        rate = get_rate_for_bedrooms(bedrooms)
        mgmt_fee = round(agg["gross"] * MGMT_FEE_PCT, 2)
        owner_payout = round(agg["gross"] - mgmt_fee, 2)

        cur.execute("""
            INSERT INTO fin_owner_balances
                (property_id, property_name, bedrooms, estimated_rate,
                 total_booked_nights, gross_revenue, mgmt_fee_pct,
                 mgmt_fee_amount, owner_payout, last_calculated)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (property_id) DO UPDATE SET
                total_booked_nights = EXCLUDED.total_booked_nights,
                gross_revenue = EXCLUDED.gross_revenue,
                mgmt_fee_amount = EXCLUDED.mgmt_fee_amount,
                owner_payout = EXCLUDED.owner_payout,
                last_calculated = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
        """, (pid, name, bedrooms, rate, agg["nights"], agg["gross"],
              MGMT_FEE_PCT * 100, mgmt_fee, owner_payout))


def write_snapshot(cur, bookings):
    """Write a point-in-time revenue snapshot."""
    if not bookings:
        return

    all_checkins = [b["check_in"] for b in bookings]
    all_checkouts = [b["check_out"] for b in bookings]
    total_nights = sum(b["nights"] for b in bookings)
    gross = sum(float(b["base_rent"]) for b in bookings)
    taxes = sum(float(b["taxes"]) for b in bookings)
    total_props = len(set(b["property_id"] for b in bookings))
    mgmt_fees = round(gross * MGMT_FEE_PCT, 2)
    owner_payout = round(gross - mgmt_fees, 2)

    cur.execute("""
        INSERT INTO fin_revenue_snapshots
            (period_start, period_end, total_properties, total_nights,
             gross_revenue, est_taxes, est_mgmt_fees, est_owner_payout, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'shadow')
    """, (min(all_checkins), max(all_checkouts), total_props, total_nights,
          gross, taxes, mgmt_fees, owner_payout))


# =============================================================================
# MAIN
# =============================================================================

def run():
    print("=" * 65)
    print("  DIVISION 2: THE RAINMAKER — SHADOW REVENUE ESTIMATOR")
    print("=" * 65)
    print()

    conn = get_db()
    cur = conn.cursor()

    # Step 1: Load properties
    print("  Loading property catalog...", flush=True)
    properties = load_properties(cur)
    print(f"  Found {len(properties)} active properties", flush=True)
    print()

    # Show rate tier mapping
    print("  Rate Tiers (from QuantRevenue calibration):")
    for pid, prop in sorted(properties.items(), key=lambda x: x[1]["bedrooms"]):
        rate = get_rate_for_bedrooms(prop["bedrooms"])
        print(f"    {prop['name'][:35]:<36} {prop['bedrooms']}BR  ${rate:>7.2f}/night")
    print()

    # Step 2: Reconstruct bookings
    print("  Scanning Shadow Calendar for bookings...", flush=True)
    bookings = reconstruct_bookings(cur, properties)
    print(f"  Reconstructed {len(bookings)} Shadow Reservations", flush=True)
    print()

    if not bookings:
        print("  No bookings found. Vault remains empty.")
        conn.close()
        return

    # Step 3: Write to vault
    print("  Writing to Financial Vault...", flush=True)
    write_reservations(cur, bookings)
    write_owner_balances(cur, bookings, properties)
    write_snapshot(cur, bookings)
    conn.commit()
    print("  Vault populated.", flush=True)
    print()

    # === REPORT ===
    total_nights = sum(b["nights"] for b in bookings)
    gross_rent = sum(float(b["base_rent"]) for b in bookings)
    total_taxes = sum(float(b["taxes"]) for b in bookings)
    total_fees = sum(float(b["fees"]) for b in bookings)
    total_revenue = sum(float(b["total_revenue"]) for b in bookings)
    mgmt_fees = round(gross_rent * MGMT_FEE_PCT, 2)
    owner_payout = round(gross_rent - mgmt_fees, 2)
    active_props = len(set(b["property_id"] for b in bookings))

    # Date range
    earliest = min(b["check_in"] for b in bookings)
    latest = max(b["check_out"] for b in bookings)

    print("=" * 65)
    print("  SHADOW REVENUE REPORT")
    print(f"  Period: {earliest} to {latest}")
    print(f"  Source: Shadow Calendar (ops_turnovers)")
    print("=" * 65)
    print()
    print(f"  Properties with bookings:    {active_props}")
    print(f"  Shadow Reservations:         {len(bookings)}")
    print(f"  Total Booked Nights:         {total_nights}")
    print()
    print(f"  GROSS RENT (base):           ${gross_rent:>12,.2f}")
    print(f"  Estimated Taxes (13%):       ${total_taxes:>12,.2f}")
    print(f"  Cleaning Fees:               ${total_fees:>12,.2f}")
    print(f"  ─────────────────────────────────────────")
    print(f"  TOTAL ESTIMATED REVENUE:     ${total_revenue:>12,.2f}")
    print()
    print(f"  CROG Management Fee (25%):   ${mgmt_fees:>12,.2f}")
    print(f"  Est. Owner Payouts:          ${owner_payout:>12,.2f}")
    print()

    # Per-property breakdown
    print("  ─── PER-PROPERTY BREAKDOWN ───")
    by_prop = defaultdict(lambda: {"nights": 0, "rent": 0.0, "count": 0})
    for b in bookings:
        by_prop[b["property_id"]]["nights"] += b["nights"]
        by_prop[b["property_id"]]["rent"] += float(b["base_rent"])
        by_prop[b["property_id"]]["count"] += 1
        by_prop[b["property_id"]]["name"] = b["property_name"]

    for pid, agg in sorted(by_prop.items(), key=lambda x: x[1]["rent"], reverse=True):
        name = agg["name"][:30]
        print(f"    {name:<31} {agg['count']} stays  {agg['nights']:>3} nights  ${agg['rent']:>10,.2f}")
    print()

    # Confidence breakdown
    high = [b for b in bookings if b["confidence"] == "high"]
    med = [b for b in bookings if b["confidence"] == "medium"]
    low = [b for b in bookings if b["confidence"] == "low"]
    print(f"  Confidence: {len(high)} high / {len(med)} medium / {len(low)} low")
    print()
    print("=" * 65)
    print("  STATUS: SHADOW LEDGER OPERATIONAL")
    print("  The Rainmaker is awake.")
    print("=" * 65)

    conn.close()


if __name__ == "__main__":
    run()
