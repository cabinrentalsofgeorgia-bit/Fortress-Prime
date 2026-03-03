"""
Fortress Prime — Seed Active Projects
========================================
Creates project entries for known active/planned work across the portfolio.

These represent:
    1. Compliance remediation (from audit findings)
    2. Seasonal maintenance cycles
    3. Capital improvements
    4. Ongoing renovations

Usage:
    python division_engineering/seed_projects.py
"""

import os
import sys
import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from division_engineering.project_tracker import ProjectTracker

PG_HOST = os.environ.get("DB_HOST", "localhost")
PG_DB = os.environ.get("DB_NAME", "fortress_db")
PG_USER = os.environ.get("DB_USER", "miner_bot")
PG_PASS = os.environ.get("DB_PASSWORD", os.environ.get("DB_PASS", ""))
PG_PORT = os.environ.get("DB_PORT", "5432")


# =============================================================================
# PROJECT DEFINITIONS
# =============================================================================

PROJECTS = [
    # ── COMPLIANCE REMEDIATION (from audit) ───────────────────
    {
        "project_code": "PRJ-2026-001",
        "name": "Portfolio Hot Tub GFCI Verification",
        "property_name": None,  # Portfolio-wide
        "project_type": "maintenance",
        "disciplines": ["electrical"],
        "estimated_cost": 15000.0,
        "target_completion": "2026-03-15",
        "description": (
            "Audit finding NEC 680.44: All 26 properties have hot tubs with "
            "unverified GFCI protection. Send electrician to each property to "
            "verify/install GFCI breakers on hot tub circuits. Critical safety item."
        ),
    },
    {
        "project_code": "PRJ-2026-002",
        "name": "Portfolio Deck Railing Inspection",
        "property_name": None,  # Portfolio-wide
        "project_type": "maintenance",
        "disciplines": ["structural"],
        "estimated_cost": 5000.0,
        "target_completion": "2026-04-01",
        "description": (
            "Audit finding IRC R312.1: All 26 properties have decks with "
            "unverified railing compliance. Inspect each property for: "
            "42\" railing height, 4\" max baluster spacing, ledger board condition, "
            "footing integrity. Prioritize high-traffic decks."
        ),
    },
    {
        "project_code": "PRJ-2026-003",
        "name": "Portfolio Smoke/CO Detector Refresh",
        "property_name": None,  # Portfolio-wide
        "project_type": "maintenance",
        "disciplines": ["fire_protection"],
        "estimated_cost": 8000.0,
        "target_completion": "2026-03-01",
        "description": (
            "Replace all smoke and CO detectors older than 7 years. "
            "Verify IRC R314.3 (every bedroom + hallway + level) and "
            "IRC R315.1 (CO near sleeping areas for propane cabins). "
            "Install hardwired with battery backup where possible."
        ),
    },

    # ── SEASONAL MAINTENANCE ──────────────────────────────────
    {
        "project_code": "PRJ-2026-004",
        "name": "Spring HVAC Maintenance Cycle",
        "property_name": None,  # Portfolio-wide
        "project_type": "maintenance",
        "disciplines": ["mechanical"],
        "estimated_cost": 12000.0,
        "target_completion": "2026-04-30",
        "description": (
            "Annual spring HVAC service for all 26 properties. "
            "AC condenser cleaning, refrigerant check, filter replacement, "
            "thermostat calibration. Prepare for summer rental season peak."
        ),
    },
    {
        "project_code": "PRJ-2026-005",
        "name": "Septic System Pump-Out Schedule",
        "property_name": None,  # Portfolio-wide
        "project_type": "maintenance",
        "disciplines": ["civil"],
        "estimated_cost": 20000.0,
        "target_completion": "2026-05-15",
        "description": (
            "Biannual septic pump-out for rental cabins with high occupancy. "
            "Fannin County Health Dept compliance. Prioritize by last pump date "
            "and occupancy rate. All 26 properties have 1000-gallon systems."
        ),
    },

    # ── CAPITAL IMPROVEMENTS ──────────────────────────────────
    {
        "project_code": "PRJ-2026-010",
        "name": "Cadence Ridge Deck Expansion",
        "property_name": "Cadence Ridge",
        "project_type": "renovation",
        "disciplines": ["architectural", "structural"],
        "estimated_cost": 35000.0,
        "target_completion": "2026-06-01",
        "description": (
            "Expand rear deck to accommodate larger hot tub and seating area. "
            "Engineer footings for slope > 15%. Permit required per Fannin County. "
            "Must meet IRC R312.1 railing requirements and IBC Ch.23 wood specs."
        ),
    },
    {
        "project_code": "PRJ-2026-011",
        "name": "Melancholy Moose Kitchen Renovation",
        "property_name": "Melancholy Moose",
        "project_type": "renovation",
        "disciplines": ["architectural", "mechanical", "electrical"],
        "estimated_cost": 55000.0,
        "target_completion": "2026-07-15",
        "description": (
            "Full kitchen remodel: new cabinets, countertops, appliances. "
            "Upgrade electrical to handle convection oven + dishwasher circuit. "
            "Install commercial-grade range hood. Propane gas line relocation. "
            "Must maintain rental operations — schedule between guest stays."
        ),
    },
    {
        "project_code": "PRJ-2026-012",
        "name": "Riverview Lodge Bathroom Addition",
        "property_name": "Riverview Lodge",
        "project_type": "renovation",
        "disciplines": ["architectural", "plumbing", "electrical"],
        "estimated_cost": 45000.0,
        "target_completion": "2026-08-01",
        "description": (
            "Add half-bath on main level to improve guest convenience. "
            "Plumbing tie-in to existing stack. Septic capacity verification required. "
            "ADA-accessible layout per Georgia DCA requirements."
        ),
    },
    {
        "project_code": "PRJ-2026-013",
        "name": "Buckhorn Lodge Generator Install",
        "property_name": "Buckhorn Lodge",
        "project_type": "new_installation",
        "disciplines": ["electrical"],
        "estimated_cost": 15000.0,
        "target_completion": "2026-04-15",
        "description": (
            "Install 22kW propane standby generator with automatic transfer switch. "
            "Dedicated 200A sub-panel. Propane line from existing tank. "
            "Mountain location prone to winter outages — protect guest experience."
        ),
    },
    {
        "project_code": "PRJ-2026-014",
        "name": "Crooked Creek Hot Tub Replacement",
        "property_name": "Crooked Creek",
        "project_type": "renovation",
        "disciplines": ["mechanical", "electrical"],
        "estimated_cost": 12000.0,
        "target_completion": "2026-03-30",
        "description": (
            "Replace aging 8-year-old hot tub with new 6-person model. "
            "Upgrade circuit to dedicated 240V 60A GFCI (NEC 680.44). "
            "Replace decking around tub pad. Critical rental amenity."
        ),
    },

    # ── PROPERTY DEVELOPMENT ──────────────────────────────────
    {
        "project_code": "PRJ-2026-020",
        "name": "Toccoa Heights Infrastructure Assessment",
        "property_name": "Toccoa Heights",
        "project_type": "assessment",
        "disciplines": ["civil", "structural"],
        "estimated_cost": 8000.0,
        "target_completion": "2026-05-01",
        "description": (
            "Full infrastructure assessment of Toccoa Heights S/D. "
            "Review: shared well system, road conditions, stormwater drainage, "
            "lot buildability per DXF plat analysis. "
            "Railroad crossing implications per CSX requirements."
        ),
    },
    {
        "project_code": "PRJ-2026-021",
        "name": "Five Peaks MEP Lifecycle Planning",
        "property_name": "Five Peaks",
        "project_type": "assessment",
        "disciplines": ["mechanical", "electrical", "plumbing"],
        "estimated_cost": 3000.0,
        "target_completion": "2026-04-01",
        "description": (
            "Systems lifecycle review for Five Peaks property. "
            "Document actual manufacturer, model, serial number, install dates "
            "for all MEP systems. Calculate remaining useful life. "
            "Build 5-year replacement capital plan."
        ),
    },
]


def seed_projects():
    """Create all defined projects."""
    conn = psycopg2.connect(
        host=PG_HOST, database=PG_DB, user=PG_USER,
        password=PG_PASS, port=PG_PORT,
    )
    tracker = ProjectTracker()
    tracker._conn = conn  # Use our connection

    print(f"\n{'='*70}")
    print(f"  THE ARCHITECT — PROJECT SEEDING")
    print(f"  Creating {len(PROJECTS)} projects in the tracker")
    print(f"{'='*70}\n")

    created = 0
    skipped = 0

    for proj in PROJECTS:
        # Check if already exists
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM engineering.projects WHERE project_code = %s",
            (proj["project_code"],),
        )
        if cur.fetchone():
            print(f"  [{proj['project_code']}] {proj['name']:<50} exists")
            skipped += 1
            continue

        try:
            result = tracker.create_project(
                project_code=proj["project_code"],
                name=proj["name"],
                property_name=proj.get("property_name"),
                project_type=proj.get("project_type", "renovation"),
                disciplines=proj.get("disciplines"),
                estimated_cost=proj.get("estimated_cost"),
                target_completion=proj.get("target_completion"),
                description=proj.get("description"),
            )
            print(f"  [{proj['project_code']}] {proj['name']:<50} CREATED")
            created += 1
        except Exception as e:
            print(f"  [{proj['project_code']}] {proj['name']:<50} ERROR: {e}")
            conn.rollback()

    # Show summary
    cur = conn.cursor()
    cur.execute("""
        SELECT project_code, name, phase, status, project_type,
               estimated_cost, target_completion, property_name
        FROM engineering.projects ORDER BY project_code
    """)
    projects = cur.fetchall()

    print(f"\n  Created: {created}, Skipped: {skipped}")
    print(f"\n{'='*70}")
    print(f"  ACTIVE PROJECT REGISTER")
    print(f"{'='*70}")
    print(f"\n  {'CODE':<15} {'PROJECT':<45} {'PHASE':<12} {'BUDGET':>10}")
    print(f"  {'-'*85}")
    total_budget = 0
    for p in projects:
        budget = f"${p[5]:,.0f}" if p[5] else "TBD"
        prop = f" [{p[7]}]" if p[7] else " [Portfolio]"
        total_budget += p[5] or 0
        print(f"  {p[0]:<15} {p[1][:42]:<45} {p[2]:<12} {budget:>10}")
        print(f"  {'':>15} {prop}")

    print(f"  {'-'*85}")
    print(f"  {'TOTAL BUDGET':>60} ${total_budget:>10,.0f}")
    print(f"\n{'='*70}\n")

    conn.close()


if __name__ == "__main__":
    seed_projects()
