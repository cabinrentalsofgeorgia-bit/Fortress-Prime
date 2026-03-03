"""
Division Engineering — PostgreSQL Schema
==========================================
The Drawing Board's database backbone.

Tables (in the 'engineering' schema):
    1. projects          — Construction project lifecycle tracker
    2. drawings          — Engineering document registry (all disciplines)
    3. permits           — Permit applications and approvals
    4. inspections       — Inspection scheduling and results
    5. mep_systems       — MEP system inventory per property
    6. compliance_log    — Code compliance issue tracker
    7. change_orders     — Construction change order registry
    8. rfis              — Requests for Information
    9. submittals        — Submittal tracking
   10. punch_items       — Punch list item tracking
   11. cost_estimates    — Project cost estimation history

Usage:
    python division_engineering/schema.py              # Create schema
    python division_engineering/schema.py --drop       # Drop and recreate
    python division_engineering/schema.py --stats      # Show table stats
"""

import os
import sys
import psycopg2
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("division_engineering.schema")

# Postgres config (same as all Fortress divisions)
PG_HOST = os.environ.get("DB_HOST", "localhost")
PG_DB = os.environ.get("DB_NAME", "fortress_db")
PG_USER = os.environ.get("DB_USER", "miner_bot")
PG_PASS = os.environ.get("DB_PASSWORD", os.environ.get("DB_PASS", ""))
PG_PORT = os.environ.get("DB_PORT", "5432")


# =============================================================================
# SCHEMA DDL
# =============================================================================

SCHEMA_SQL = """
-- ================================================================
-- DIVISION ENGINEERING: THE DRAWING BOARD (CF-10)
-- Full A/E Database Schema
-- ================================================================

-- Create dedicated schema
CREATE SCHEMA IF NOT EXISTS engineering;

-- ----------------------------------------------------------------
-- 1. PROJECTS — Construction Project Lifecycle
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS engineering.projects (
    id                  SERIAL PRIMARY KEY,
    project_code        VARCHAR(20) UNIQUE NOT NULL,   -- e.g., "PRJ-2026-001"
    name                VARCHAR(200) NOT NULL,
    description         TEXT,
    property_id         INTEGER REFERENCES properties(id),
    property_name       VARCHAR(100),

    -- Lifecycle
    phase               VARCHAR(30) NOT NULL DEFAULT 'concept',
        -- concept, schematic, dd, cd, permitting, bidding,
        -- construction, punch_list, inspection, co, closeout,
        -- on_hold, cancelled
    status              VARCHAR(20) NOT NULL DEFAULT 'active',
        -- active, on_hold, completed, cancelled

    -- Scope
    project_type        VARCHAR(50),
        -- new_construction, renovation, addition, repair,
        -- site_work, mep_upgrade, demolition
    disciplines         TEXT[],
        -- Array of involved disciplines: {architectural, civil, structural,
        -- mechanical, electrical, plumbing, fire_protection}

    -- Schedule
    start_date          DATE,
    target_completion   DATE,
    actual_completion   DATE,

    -- Budget
    estimated_cost      NUMERIC(12,2),
    actual_cost         NUMERIC(12,2),
    contingency_pct     NUMERIC(5,2) DEFAULT 10.00,

    -- Team
    architect_of_record VARCHAR(150),
    engineer_of_record  VARCHAR(150),
    general_contractor  VARCHAR(150),
    project_manager     VARCHAR(150),

    -- Jurisdiction
    jurisdiction        VARCHAR(100) DEFAULT 'Fannin County',
    permit_number       VARCHAR(50),

    -- Metadata
    notes               TEXT,
    ai_json             JSONB,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eng_proj_property ON engineering.projects(property_id);
CREATE INDEX IF NOT EXISTS idx_eng_proj_phase ON engineering.projects(phase);
CREATE INDEX IF NOT EXISTS idx_eng_proj_status ON engineering.projects(status);

-- ----------------------------------------------------------------
-- 2. DRAWINGS — Engineering Document Registry (All Disciplines)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS engineering.drawings (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id),
    project_id          INTEGER REFERENCES engineering.projects(id),

    -- Classification
    discipline          VARCHAR(30) NOT NULL DEFAULT 'general',
        -- architectural, civil, structural, mechanical,
        -- electrical, plumbing, fire_protection, general
    doc_type            VARCHAR(50) NOT NULL DEFAULT 'Unknown',

    -- File info
    file_path           TEXT UNIQUE,
    filename            TEXT,
    extension           VARCHAR(10),
    file_size           BIGINT,

    -- Drawing metadata
    sheet_number        VARCHAR(20),       -- e.g., "A-101", "C-201", "M-301"
    title               VARCHAR(200),
    revision            VARCHAR(10),
    revision_date       DATE,
    scale               VARCHAR(30),

    -- AI extraction
    ocr_text            TEXT,
    confidence          VARCHAR(20),
    ai_json             JSONB,
    phase               INTEGER DEFAULT 1, -- 1=path, 2=AI, 3=vision

    -- Metadata
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eng_draw_property ON engineering.drawings(property_id);
CREATE INDEX IF NOT EXISTS idx_eng_draw_project ON engineering.drawings(project_id);
CREATE INDEX IF NOT EXISTS idx_eng_draw_discipline ON engineering.drawings(discipline);
CREATE INDEX IF NOT EXISTS idx_eng_draw_doc_type ON engineering.drawings(doc_type);

-- ----------------------------------------------------------------
-- 3. PERMITS — Permit Application & Approval Tracking
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS engineering.permits (
    id                  SERIAL PRIMARY KEY,
    project_id          INTEGER REFERENCES engineering.projects(id),
    property_id         INTEGER REFERENCES properties(id),

    -- Permit details
    permit_type         VARCHAR(50) NOT NULL,
        -- building, mechanical, electrical, plumbing,
        -- septic, grading, demolition, fire, variance
    permit_number       VARCHAR(50) UNIQUE,
    jurisdiction        VARCHAR(100) DEFAULT 'Fannin County',
    issuing_authority   VARCHAR(150),

    -- Lifecycle
    status              VARCHAR(30) NOT NULL DEFAULT 'draft',
        -- draft, submitted, under_review, approved,
        -- denied, expired, revoked, closed
    application_date    DATE,
    approval_date       DATE,
    expiration_date     DATE,
    renewal_date        DATE,

    -- Fees
    application_fee     NUMERIC(10,2),
    impact_fee          NUMERIC(10,2),

    -- Conditions
    conditions          TEXT,
    special_inspections TEXT[],

    -- Documents
    application_doc     TEXT,     -- file path
    approval_doc        TEXT,     -- file path

    -- Metadata
    notes               TEXT,
    ai_json             JSONB,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eng_perm_project ON engineering.permits(project_id);
CREATE INDEX IF NOT EXISTS idx_eng_perm_status ON engineering.permits(status);
CREATE INDEX IF NOT EXISTS idx_eng_perm_expiration ON engineering.permits(expiration_date);

-- ----------------------------------------------------------------
-- 4. INSPECTIONS — Inspection Scheduling & Results
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS engineering.inspections (
    id                  SERIAL PRIMARY KEY,
    project_id          INTEGER REFERENCES engineering.projects(id),
    permit_id           INTEGER REFERENCES engineering.permits(id),
    property_id         INTEGER REFERENCES properties(id),

    -- Inspection details
    inspection_type     VARCHAR(50) NOT NULL,
        -- foundation, framing, rough_plumbing, rough_electrical,
        -- rough_mechanical, insulation, drywall, final_building,
        -- final_mechanical, final_electrical, final_plumbing,
        -- septic, grading, fire, stormwater, erosion_control
    discipline          VARCHAR(30),

    -- Schedule
    scheduled_date      DATE,
    actual_date         DATE,
    inspector_name      VARCHAR(150),

    -- Result
    result              VARCHAR(20),
        -- passed, failed, partial, cancelled, rescheduled
    deficiencies        TEXT,
    corrections_required TEXT,
    re_inspection_date  DATE,

    -- Documents
    report_path         TEXT,

    -- Metadata
    notes               TEXT,
    ai_json             JSONB,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eng_insp_project ON engineering.inspections(project_id);
CREATE INDEX IF NOT EXISTS idx_eng_insp_result ON engineering.inspections(result);
CREATE INDEX IF NOT EXISTS idx_eng_insp_scheduled ON engineering.inspections(scheduled_date);

-- ----------------------------------------------------------------
-- 5. MEP_SYSTEMS — MEP System Inventory Per Property
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS engineering.mep_systems (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) NOT NULL,
    property_name       VARCHAR(100),

    -- System identification
    system_type         VARCHAR(50) NOT NULL,
        -- hvac, furnace, heat_pump, ac_condenser, water_heater,
        -- well_pump, septic, electrical_panel, generator,
        -- hot_tub, fireplace, gas_logs, range_hood,
        -- fire_extinguisher, smoke_detector, co_detector
    discipline          VARCHAR(30),

    -- Equipment details
    manufacturer        VARCHAR(100),
    model_number        VARCHAR(100),
    serial_number       VARCHAR(100),
    capacity            VARCHAR(50),       -- e.g., "3-ton", "50-gallon", "200-amp"
    fuel_type           VARCHAR(30),       -- electric, gas, propane, wood, solar

    -- Lifecycle
    install_date        DATE,
    warranty_expiry     DATE,
    expected_life_years INTEGER,
    condition           VARCHAR(20) DEFAULT 'good',
        -- excellent, good, fair, poor, critical, replaced
    last_service_date   DATE,
    next_service_due    DATE,

    -- Location within property
    location            VARCHAR(100),      -- e.g., "basement", "attic", "exterior north"

    -- Cost
    install_cost        NUMERIC(10,2),
    replacement_cost    NUMERIC(10,2),

    -- Metadata
    notes               TEXT,
    ai_json             JSONB,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eng_mep_property ON engineering.mep_systems(property_id);
CREATE INDEX IF NOT EXISTS idx_eng_mep_type ON engineering.mep_systems(system_type);
CREATE INDEX IF NOT EXISTS idx_eng_mep_condition ON engineering.mep_systems(condition);

-- ----------------------------------------------------------------
-- 6. COMPLIANCE_LOG — Code Compliance Issue Tracker
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS engineering.compliance_log (
    id                  SERIAL PRIMARY KEY,
    project_id          INTEGER REFERENCES engineering.projects(id),
    property_id         INTEGER REFERENCES properties(id),
    drawing_id          INTEGER REFERENCES engineering.drawings(id),

    -- Issue details
    issue_type          VARCHAR(50) NOT NULL,
        -- code_violation, pe_stamp_required, fire_marshal_review,
        -- septic_review, ada_violation, setback_violation,
        -- egress_violation, structural_concern, permit_expired,
        -- inspection_failure
    severity            VARCHAR(20) NOT NULL DEFAULT 'HIGH',
        -- CRITICAL, HIGH, MEDIUM, LOW, INFORMATIONAL
    discipline          VARCHAR(30),

    -- Description
    code_reference      VARCHAR(100),      -- e.g., "IBC 2018 Section 1006.2"
    description         TEXT NOT NULL,
    recommended_action  TEXT,

    -- Resolution
    status              VARCHAR(20) NOT NULL DEFAULT 'open',
        -- open, in_progress, resolved, waived, escalated
    resolved_date       DATE,
    resolution_notes    TEXT,
    resolved_by         VARCHAR(100),

    -- Metadata
    detected_by         VARCHAR(50) DEFAULT 'architect_agent',
    ai_json             JSONB,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eng_comp_severity ON engineering.compliance_log(severity);
CREATE INDEX IF NOT EXISTS idx_eng_comp_status ON engineering.compliance_log(status);
CREATE INDEX IF NOT EXISTS idx_eng_comp_project ON engineering.compliance_log(project_id);

-- ----------------------------------------------------------------
-- 7. CHANGE_ORDERS — Construction Change Orders
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS engineering.change_orders (
    id                  SERIAL PRIMARY KEY,
    project_id          INTEGER REFERENCES engineering.projects(id) NOT NULL,
    co_number           VARCHAR(20) NOT NULL,          -- e.g., "CO-001"

    -- Details
    description         TEXT NOT NULL,
    reason              VARCHAR(50),
        -- owner_request, field_condition, design_error,
        -- code_requirement, value_engineering, unforeseen
    discipline          VARCHAR(30),

    -- Cost impact
    cost_impact         NUMERIC(12,2),     -- positive = increase
    schedule_impact_days INTEGER,           -- positive = delay

    -- Lifecycle
    status              VARCHAR(20) NOT NULL DEFAULT 'proposed',
        -- proposed, under_review, approved, rejected, voided
    submitted_date      DATE,
    approved_date       DATE,
    approved_by         VARCHAR(100),

    -- Documents
    document_path       TEXT,

    -- Metadata
    notes               TEXT,
    ai_json             JSONB,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eng_co_project ON engineering.change_orders(project_id);
CREATE INDEX IF NOT EXISTS idx_eng_co_status ON engineering.change_orders(status);

-- ----------------------------------------------------------------
-- 8. RFIs — Requests for Information
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS engineering.rfis (
    id                  SERIAL PRIMARY KEY,
    project_id          INTEGER REFERENCES engineering.projects(id) NOT NULL,
    rfi_number          VARCHAR(20) NOT NULL,           -- e.g., "RFI-001"

    -- Details
    subject             VARCHAR(200) NOT NULL,
    question            TEXT NOT NULL,
    discipline          VARCHAR(30),
    drawing_reference   VARCHAR(50),        -- e.g., "A-201, Detail 3"

    -- Response
    response            TEXT,
    responded_by        VARCHAR(100),
    response_date       DATE,

    -- Impact
    cost_impact         NUMERIC(12,2),
    schedule_impact_days INTEGER,

    -- Lifecycle
    status              VARCHAR(20) NOT NULL DEFAULT 'open',
        -- open, answered, closed, void
    submitted_date      DATE,
    due_date            DATE,
    submitted_by        VARCHAR(100),

    -- Metadata
    notes               TEXT,
    ai_json             JSONB,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eng_rfi_project ON engineering.rfis(project_id);
CREATE INDEX IF NOT EXISTS idx_eng_rfi_status ON engineering.rfis(status);

-- ----------------------------------------------------------------
-- 9. SUBMITTALS — Submittal Tracking
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS engineering.submittals (
    id                  SERIAL PRIMARY KEY,
    project_id          INTEGER REFERENCES engineering.projects(id) NOT NULL,
    submittal_number    VARCHAR(20) NOT NULL,            -- e.g., "SUB-001"

    -- Details
    description         VARCHAR(200) NOT NULL,
    discipline          VARCHAR(30),
    spec_section        VARCHAR(20),        -- e.g., "23 05 00" (HVAC)

    -- Review
    status              VARCHAR(30) NOT NULL DEFAULT 'pending',
        -- pending, under_review, approved, approved_as_noted,
        -- revise_resubmit, rejected
    submitted_date      DATE,
    review_date         DATE,
    reviewed_by         VARCHAR(100),
    review_comments     TEXT,

    -- Documents
    document_path       TEXT,

    -- Metadata
    notes               TEXT,
    ai_json             JSONB,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eng_sub_project ON engineering.submittals(project_id);
CREATE INDEX IF NOT EXISTS idx_eng_sub_status ON engineering.submittals(status);

-- ----------------------------------------------------------------
-- 10. PUNCH_ITEMS — Punch List Tracking
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS engineering.punch_items (
    id                  SERIAL PRIMARY KEY,
    project_id          INTEGER REFERENCES engineering.projects(id) NOT NULL,
    inspection_id       INTEGER REFERENCES engineering.inspections(id),

    -- Details
    item_number         INTEGER NOT NULL,
    description         TEXT NOT NULL,
    discipline          VARCHAR(30),
    location            VARCHAR(100),       -- e.g., "Master bedroom, north wall"
    priority            VARCHAR(20) DEFAULT 'normal',
        -- critical, high, normal, low, cosmetic

    -- Assignment
    assigned_to         VARCHAR(100),       -- contractor/trade
    due_date            DATE,

    -- Resolution
    status              VARCHAR(20) NOT NULL DEFAULT 'open',
        -- open, in_progress, completed, verified, waived
    completed_date      DATE,
    verified_by         VARCHAR(100),

    -- Photos
    photo_before        TEXT,               -- file path
    photo_after         TEXT,               -- file path

    -- Metadata
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eng_punch_project ON engineering.punch_items(project_id);
CREATE INDEX IF NOT EXISTS idx_eng_punch_status ON engineering.punch_items(status);

-- ----------------------------------------------------------------
-- 11. COST_ESTIMATES — Project Cost Estimation History
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS engineering.cost_estimates (
    id                  SERIAL PRIMARY KEY,
    project_id          INTEGER REFERENCES engineering.projects(id) NOT NULL,

    -- Estimate details
    estimate_type       VARCHAR(30) NOT NULL,
        -- conceptual, schematic, dd, cd, bid, final
    version             INTEGER DEFAULT 1,

    -- Cost breakdown
    architectural_cost  NUMERIC(12,2) DEFAULT 0,
    civil_cost          NUMERIC(12,2) DEFAULT 0,
    structural_cost     NUMERIC(12,2) DEFAULT 0,
    mechanical_cost     NUMERIC(12,2) DEFAULT 0,
    electrical_cost     NUMERIC(12,2) DEFAULT 0,
    plumbing_cost       NUMERIC(12,2) DEFAULT 0,
    fire_protection_cost NUMERIC(12,2) DEFAULT 0,
    general_conditions  NUMERIC(12,2) DEFAULT 0,
    contingency         NUMERIC(12,2) DEFAULT 0,
    total_estimate      NUMERIC(12,2) NOT NULL,

    -- Per unit
    cost_per_sqft       NUMERIC(8,2),
    total_sqft          NUMERIC(10,2),

    -- Source
    prepared_by         VARCHAR(100),
    estimate_date       DATE,

    -- Documents
    document_path       TEXT,

    -- Metadata
    notes               TEXT,
    ai_json             JSONB,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eng_cost_project ON engineering.cost_estimates(project_id);
CREATE INDEX IF NOT EXISTS idx_eng_cost_type ON engineering.cost_estimates(estimate_type);
""";


# =============================================================================
# SCHEMA MANAGEMENT
# =============================================================================

def get_pg():
    """Connect to Postgres."""
    return psycopg2.connect(
        host=PG_HOST, database=PG_DB, user=PG_USER,
        password=PG_PASS, port=PG_PORT
    )


def init_schema(drop_first: bool = False):
    """Create the engineering schema and all tables."""
    print(f"\n[Engineering] Initializing schema in fortress_db...")
    conn = get_pg()
    cur = conn.cursor()

    if drop_first:
        print("[Engineering] WARNING: Dropping engineering schema...")
        cur.execute("DROP SCHEMA IF EXISTS engineering CASCADE")
        conn.commit()

    cur.execute(SCHEMA_SQL)
    conn.commit()

    # Count tables created
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'engineering'
        ORDER BY table_name
    """)
    tables = [row[0] for row in cur.fetchall()]
    print(f"[Engineering] Schema created with {len(tables)} tables:")
    for t in tables:
        print(f"  - engineering.{t}")

    conn.close()
    print("[Engineering] Schema initialization complete.\n")


def show_stats():
    """Display table row counts and key metrics."""
    conn = get_pg()
    cur = conn.cursor()

    print("\n" + "=" * 65)
    print("  ENGINEERING DIVISION — DATABASE STATUS")
    print("=" * 65)

    tables = [
        "projects", "drawings", "permits", "inspections",
        "mep_systems", "compliance_log", "change_orders",
        "rfis", "submittals", "punch_items", "cost_estimates",
    ]

    for table in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM engineering.{table}")
            count = cur.fetchone()[0]
            print(f"  engineering.{table:<20} {count:>8,} rows")
        except Exception:
            conn.rollback()
            print(f"  engineering.{table:<20}    (not found)")

    # Key metrics
    print(f"\n  KEY METRICS:")

    try:
        cur.execute("""
            SELECT phase, COUNT(*) FROM engineering.projects
            WHERE status = 'active' GROUP BY phase ORDER BY COUNT(*) DESC
        """)
        active = cur.fetchall()
        if active:
            print(f"  Active Projects by Phase:")
            for phase, count in active:
                print(f"    {phase:<20} {count:>5}")
    except Exception:
        conn.rollback()

    try:
        cur.execute("""
            SELECT status, COUNT(*) FROM engineering.permits
            WHERE expiration_date < CURRENT_DATE AND status NOT IN ('closed', 'revoked')
        """)
        row = cur.fetchone()
        if row and row[1] > 0:
            print(f"\n  WARNING: {row[1]} EXPIRED PERMITS detected!")
    except Exception:
        conn.rollback()

    try:
        cur.execute("""
            SELECT severity, COUNT(*) FROM engineering.compliance_log
            WHERE status = 'open' GROUP BY severity ORDER BY
            CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2
            WHEN 'MEDIUM' THEN 3 ELSE 4 END
        """)
        issues = cur.fetchall()
        if issues:
            print(f"\n  Open Compliance Issues:")
            for severity, count in issues:
                print(f"    {severity:<12} {count:>5}")
    except Exception:
        conn.rollback()

    try:
        cur.execute("""
            SELECT condition, COUNT(*) FROM engineering.mep_systems
            GROUP BY condition ORDER BY
            CASE condition WHEN 'critical' THEN 1 WHEN 'poor' THEN 2
            WHEN 'fair' THEN 3 WHEN 'good' THEN 4 ELSE 5 END
        """)
        conditions = cur.fetchall()
        if conditions:
            print(f"\n  MEP System Conditions:")
            for condition, count in conditions:
                print(f"    {condition:<12} {count:>5}")
    except Exception:
        conn.rollback()

    conn.close()
    print(f"\n{'='*65}\n")


# =============================================================================
# CLI
# =============================================================================

def main():
    print("=" * 65)
    print("  FORTRESS PRIME: DIVISION ENGINEERING — SCHEMA MANAGER")
    print("=" * 65)

    if "--drop" in sys.argv:
        confirm = input("  Type 'DROP' to confirm schema destruction: ")
        if confirm == "DROP":
            init_schema(drop_first=True)
        else:
            print("  Aborted.")
            return
    elif "--stats" in sys.argv:
        show_stats()
    else:
        init_schema()

    show_stats()


if __name__ == "__main__":
    main()
