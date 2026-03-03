"""
Fortress Prime — MEP Systems Population
==========================================
Registers mechanical, electrical, and plumbing systems for all properties
in the CROG rental portfolio.

Every mountain cabin has a baseline set of systems that need lifecycle tracking:
    - HVAC (furnace + AC or heat pump)
    - Water heater
    - Electrical panel (200A typical)
    - Septic system
    - Well pump (if applicable)
    - Hot tub (most rental cabins)
    - Fireplace / gas logs
    - Smoke detectors, CO detectors
    - Fire extinguishers

This script creates baseline entries for all 26 properties. Actual equipment
details (manufacturer, model, serial, install date) should be updated as
the data is discovered through document ingestion or property inspections.

Usage:
    python division_engineering/populate_mep.py              # Populate all
    python division_engineering/populate_mep.py --stats      # Show current MEP stats
"""

import os
import sys
import psycopg2
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PG_HOST = os.environ.get("DB_HOST", "localhost")
PG_DB = os.environ.get("DB_NAME", "fortress_db")
PG_USER = os.environ.get("DB_USER", "miner_bot")
PG_PASS = os.environ.get("DB_PASSWORD", os.environ.get("DB_PASS", ""))
PG_PORT = os.environ.get("DB_PORT", "5432")


def get_conn():
    return psycopg2.connect(
        host=PG_HOST, database=PG_DB, user=PG_USER,
        password=PG_PASS, port=PG_PORT,
    )


# =============================================================================
# BASELINE MEP SYSTEMS (per-property templates)
# =============================================================================

# Each cabin gets these baseline systems registered.
# The data is populated with reasonable defaults for Blue Ridge, GA mountain cabins.
# Actual install dates, manufacturers, and conditions will be updated
# as documents are ingested or inspections occur.

BASELINE_SYSTEMS = [
    # ── HVAC ──────────────────────────────────────────────────
    {
        "system_type": "furnace",
        "discipline": "mechanical",
        "capacity": "80,000 BTU",
        "fuel_type": "propane",
        "expected_life_years": 20,
        "location": "basement/crawl space",
        "notes": "Mountain cabins at 2,500-3,500ft elevation. Altitude derate ~4%. "
                 "Most use propane forced-air. Service annually before winter season.",
    },
    {
        "system_type": "ac_condenser",
        "discipline": "mechanical",
        "capacity": "3-ton",
        "fuel_type": "electric",
        "expected_life_years": 15,
        "location": "exterior",
        "notes": "Split system AC. Summer peaks in Blue Ridge rarely exceed 90F, "
                 "but rental occupancy drives heavy usage Jun-Aug. "
                 "Check refrigerant annually.",
    },
    # ── WATER HEATER ──────────────────────────────────────────
    {
        "system_type": "water_heater",
        "discipline": "plumbing",
        "capacity": "50-gallon",
        "fuel_type": "propane",
        "expected_life_years": 12,
        "location": "utility closet",
        "notes": "High-occupancy rental demand. Consider tankless upgrade for "
                 "cabins with 4+ BR. Inspect anode rod annually. "
                 "Freeze protection critical — heat tape on exposed pipes.",
    },
    # ── ELECTRICAL ────────────────────────────────────────────
    {
        "system_type": "electrical_panel",
        "discipline": "electrical",
        "capacity": "200-amp",
        "fuel_type": "electric",
        "expected_life_years": 40,
        "location": "utility room/garage",
        "notes": "200A service standard for rental cabins. Must support hot tub "
                 "(40-60A dedicated circuit), HVAC, and peak guest load. "
                 "GFCI required on all outdoor, kitchen, bathroom circuits (NEC).",
    },
    # ── SEPTIC ────────────────────────────────────────────────
    {
        "system_type": "septic",
        "discipline": "civil",
        "capacity": "1,000-gallon",
        "fuel_type": "none",
        "expected_life_years": 30,
        "location": "yard/drain field",
        "notes": "Fannin County Health Dept regulates. Rental cabins with "
                 "high occupancy MUST pump every 1-2 years (vs 3-5 for residential). "
                 "Peak season (summer + fall) stresses system. "
                 "Monitor for backup indicators.",
    },
    # ── HOT TUB ───────────────────────────────────────────────
    {
        "system_type": "hot_tub",
        "discipline": "mechanical",
        "capacity": "6-person / 400-gallon",
        "fuel_type": "electric",
        "expected_life_years": 8,
        "location": "deck/patio",
        "notes": "Rental-critical amenity. Requires dedicated 220V/240V GFCI circuit "
                 "(NEC 680.44). Test water chemistry 2x/week in season. "
                 "Replace cover every 3-4 years. Inspect heater element annually. "
                 "Freeze protection required Nov-Mar.",
    },
    # ── FIREPLACE ─────────────────────────────────────────────
    {
        "system_type": "fireplace",
        "discipline": "mechanical",
        "capacity": "N/A",
        "fuel_type": "wood",
        "expected_life_years": 50,
        "location": "great room",
        "notes": "Wood-burning or gas logs. NFPA 211 requires chimney inspection "
                 "annually. Cap and screen required. Creosote cleaning before "
                 "each winter season. CO detector required within 15ft (GA DCA).",
    },
    # ── SAFETY: SMOKE DETECTORS ───────────────────────────────
    {
        "system_type": "smoke_detector",
        "discipline": "fire_protection",
        "capacity": "N/A",
        "fuel_type": "battery/hardwired",
        "expected_life_years": 10,
        "location": "every bedroom + hallway + each level",
        "notes": "IRC R314 — required in every sleeping room, outside each sleeping "
                 "area, and on each level. Hardwired with battery backup preferred. "
                 "Replace units every 10 years. Test monthly during turnover.",
    },
    # ── SAFETY: CO DETECTORS ─────────────────────────────────
    {
        "system_type": "co_detector",
        "discipline": "fire_protection",
        "capacity": "N/A",
        "fuel_type": "battery/hardwired",
        "expected_life_years": 7,
        "location": "near bedrooms + near gas appliances",
        "notes": "Georgia DCA requires CO detectors near sleeping areas in all "
                 "dwellings with fuel-burning appliances or attached garages. "
                 "Replace every 5-7 years. Critical for propane cabins.",
    },
    # ── SAFETY: FIRE EXTINGUISHER ─────────────────────────────
    {
        "system_type": "fire_extinguisher",
        "discipline": "fire_protection",
        "capacity": "5-lb ABC",
        "fuel_type": "N/A",
        "expected_life_years": 12,
        "location": "kitchen + each level + hot tub area",
        "notes": "Minimum one per level. Kitchen should have ABC type. "
                 "Inspect monthly (visual), annual professional inspection. "
                 "Replace or recharge every 6-12 years.",
    },
    # ── DECK STRUCTURE ────────────────────────────────────────
    {
        "system_type": "deck_structure",
        "discipline": "structural",
        "capacity": "N/A",
        "fuel_type": "N/A",
        "expected_life_years": 25,
        "location": "exterior deck(s)",
        "notes": "Mountain cabin decks take extreme weather. IRC R312.1 — "
                 "guards required on open sides >30in above grade. Min 36in height "
                 "(42in for rental). Balusters max 4in apart. "
                 "Inspect ledger board, footings, and railing connections annually. "
                 "Treat/stain every 2-3 years.",
    },
]

# Property-specific overrides and additions
PROPERTY_OVERRIDES = {
    "Buckhorn Lodge": {
        "add": [
            {"system_type": "well_pump", "discipline": "plumbing", "capacity": "1-HP submersible",
             "fuel_type": "electric", "expected_life_years": 15, "location": "well casing",
             "notes": "Private well. Test water quality annually. UV purification recommended for rentals."},
        ],
    },
    "Crooked Creek": {
        "add": [
            {"system_type": "well_pump", "discipline": "plumbing", "capacity": "1-HP submersible",
             "fuel_type": "electric", "expected_life_years": 15, "location": "well casing",
             "notes": "Private well on creek property. Seasonal turbidity may increase."},
        ],
    },
    "Riverview Lodge": {
        "add": [
            {"system_type": "generator", "discipline": "electrical", "capacity": "22kW standby",
             "fuel_type": "propane", "expected_life_years": 20, "location": "exterior pad",
             "notes": "Automatic transfer switch. Exercise weekly. Change oil every 200 hours."},
        ],
    },
    "Majestic Lake": {
        "add": [
            {"system_type": "dock_structure", "discipline": "structural", "capacity": "N/A",
             "fuel_type": "N/A", "expected_life_years": 20, "location": "lakefront",
             "notes": "Floating dock. Inspect flotation, decking, and anchoring annually."},
        ],
    },
    "Toccoa Heights": {
        "add": [
            {"system_type": "well_pump", "discipline": "plumbing", "capacity": "1-HP submersible",
             "fuel_type": "electric", "expected_life_years": 15, "location": "well casing",
             "notes": "Community well system for Toccoa Heights S/D."},
        ],
    },
}


def populate_mep(conn):
    """Insert baseline MEP systems for all properties."""
    cur = conn.cursor()

    # Get all properties
    cur.execute("SELECT id, name FROM properties ORDER BY name")
    properties = cur.fetchall()

    if not properties:
        print("  No properties found in database!")
        return

    print(f"\n{'='*70}")
    print(f"  THE ARCHITECT — MEP SYSTEMS POPULATION")
    print(f"  Registering baseline systems for {len(properties)} properties")
    print(f"{'='*70}\n")

    total_inserted = 0
    total_skipped = 0

    for prop_id, prop_name in properties:
        systems_to_add = list(BASELINE_SYSTEMS)

        # Add property-specific overrides
        override = PROPERTY_OVERRIDES.get(prop_name, {})
        if override.get("add"):
            systems_to_add.extend(override["add"])

        inserted = 0
        skipped = 0
        for sys_template in systems_to_add:
            # Check if already exists
            cur.execute("""
                SELECT id FROM engineering.mep_systems
                WHERE property_id = %s AND system_type = %s
            """, (prop_id, sys_template["system_type"]))

            if cur.fetchone():
                skipped += 1
                continue

            cur.execute("""
                INSERT INTO engineering.mep_systems
                (property_id, property_name, system_type, discipline,
                 capacity, fuel_type, expected_life_years, location,
                 condition, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                prop_id, prop_name,
                sys_template["system_type"],
                sys_template.get("discipline"),
                sys_template.get("capacity"),
                sys_template.get("fuel_type"),
                sys_template.get("expected_life_years"),
                sys_template.get("location"),
                "unknown",  # Condition unknown until inspected
                sys_template.get("notes"),
            ))
            inserted += 1

        total_inserted += inserted
        total_skipped += skipped

        status = f"+{inserted}" if inserted > 0 else "exists"
        print(f"  {prop_name:<30} {status:>8} systems")

    conn.commit()

    print(f"\n  TOTAL: {total_inserted} systems registered, {total_skipped} already existed")
    return total_inserted


def show_stats(conn):
    """Show MEP system statistics."""
    cur = conn.cursor()

    print(f"\n{'='*70}")
    print(f"  MEP SYSTEM REGISTRY — STATUS REPORT")
    print(f"{'='*70}")

    cur.execute("SELECT COUNT(*) FROM engineering.mep_systems")
    total = cur.fetchone()[0]
    print(f"\n  Total systems registered: {total}")

    cur.execute("""
        SELECT system_type, COUNT(*) FROM engineering.mep_systems
        GROUP BY system_type ORDER BY COUNT(*) DESC
    """)
    print(f"\n  {'SYSTEM TYPE':<25} {'COUNT':>6}")
    print(f"  {'-'*33}")
    for stype, cnt in cur.fetchall():
        print(f"  {stype:<25} {cnt:>6}")

    cur.execute("""
        SELECT condition, COUNT(*) FROM engineering.mep_systems
        GROUP BY condition ORDER BY COUNT(*) DESC
    """)
    print(f"\n  {'CONDITION':<20} {'COUNT':>6}")
    print(f"  {'-'*28}")
    for cond, cnt in cur.fetchall():
        print(f"  {cond:<20} {cnt:>6}")

    cur.execute("""
        SELECT property_name, COUNT(*) FROM engineering.mep_systems
        GROUP BY property_name ORDER BY property_name
    """)
    print(f"\n  {'PROPERTY':<30} {'SYSTEMS':>8}")
    print(f"  {'-'*40}")
    for pname, cnt in cur.fetchall():
        print(f"  {pname:<30} {cnt:>8}")

    # Systems needing attention (unknown condition)
    cur.execute("""
        SELECT COUNT(*) FROM engineering.mep_systems
        WHERE condition = 'unknown'
    """)
    unknown = cur.fetchone()[0]
    if unknown > 0:
        print(f"\n  WARNING: {unknown} systems with UNKNOWN condition — need inspection")

    # Systems past expected lifespan
    cur.execute("""
        SELECT COUNT(*) FROM engineering.mep_systems
        WHERE install_date IS NOT NULL AND expected_life_years IS NOT NULL
              AND install_date + (expected_life_years || ' years')::INTERVAL < CURRENT_DATE
    """)
    past_life = cur.fetchone()[0]
    if past_life > 0:
        print(f"  ALERT: {past_life} systems PAST expected lifespan")

    print(f"\n{'='*70}\n")


def main():
    conn = get_conn()

    if "--stats" in sys.argv:
        show_stats(conn)
        conn.close()
        return

    populate_mep(conn)
    show_stats(conn)
    conn.close()


if __name__ == "__main__":
    main()
