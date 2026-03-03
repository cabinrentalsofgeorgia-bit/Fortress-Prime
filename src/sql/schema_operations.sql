-- =============================================================================
-- DIVISION 3: OPERATIONS KERNEL
-- "The Nervous System"
-- =============================================================================
-- Deployed by: Fortress-Prime Phase 1
-- Target DB:   fortress_db (Captain Node — 192.168.0.100)
-- =============================================================================

-- 1. THE CREW (Who does the work?)
CREATE TABLE IF NOT EXISTS ops_crew (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    role VARCHAR(50) NOT NULL,           -- 'Cleaner', 'Maintenance', 'Inspector', 'Manager'
    phone VARCHAR(20),
    email VARCHAR(100),
    status VARCHAR(20) DEFAULT 'ACTIVE', -- 'ACTIVE', 'OFF_DUTY', 'TERMINATED'
    current_location VARCHAR(100),       -- 'Blue Ridge', 'Morganton', etc.
    skills JSONB DEFAULT '{}',           -- e.g. {"hvac": true, "plumbing": false}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. THE ASSETS (The Cabins — linking to Streamline IDs)
CREATE TABLE IF NOT EXISTS ops_properties (
    property_id VARCHAR(50) PRIMARY KEY, -- Streamline ID
    internal_name VARCHAR(100),
    address TEXT,
    access_code_wifi VARCHAR(50),
    access_code_door VARCHAR(50),
    trash_pickup_day VARCHAR(20),
    cleaning_sla_minutes INT DEFAULT 240,  -- Standard 4-hour clean
    hvac_filter_size VARCHAR(20),
    hot_tub_gallons INT,
    config_yaml TEXT,                      -- Path to cabins/*.yaml
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. THE TURNOVERS (The Trigger)
-- Links a Checkout (Departure) to a Check-in (Arrival)
CREATE TABLE IF NOT EXISTS ops_turnovers (
    id SERIAL PRIMARY KEY,
    property_id VARCHAR(50) REFERENCES ops_properties(property_id),
    reservation_id_out VARCHAR(50),       -- Who is leaving?
    reservation_id_in VARCHAR(50),        -- Who is arriving?
    checkout_time TIMESTAMP NOT NULL,
    checkin_time TIMESTAMP NOT NULL,
    window_hours DECIMAL(5,2),            -- How tight is the squeeze? (e.g. 4.0)
    status VARCHAR(50) DEFAULT 'PENDING', -- 'PENDING', 'IN_PROGRESS', 'READY', 'LATE'
    cleanliness_score INT,                -- From Vision Inspection (CF-01)
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. THE TASK QUEUE (The Work)
CREATE TABLE IF NOT EXISTS ops_tasks (
    id SERIAL PRIMARY KEY,
    type VARCHAR(50) NOT NULL,            -- 'CLEANING', 'INSPECTION', 'REPAIR', 'HOT_TUB'
    priority VARCHAR(20) DEFAULT 'NORMAL',-- 'LOW', 'NORMAL', 'URGENT', 'EMERGENCY'
    property_id VARCHAR(50) REFERENCES ops_properties(property_id),
    assigned_to INT REFERENCES ops_crew(id),
    turnover_id INT REFERENCES ops_turnovers(id),
    description TEXT,
    deadline TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR(50) DEFAULT 'OPEN',    -- 'OPEN', 'ASSIGNED', 'IN_PROGRESS', 'BLOCKED', 'DONE'
    evidence_photos JSONB,                -- URLs to proof-of-work images
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. THE AUDIT LOG (History — every action the Groundskeeper takes)
CREATE TABLE IF NOT EXISTS ops_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actor VARCHAR(100),                   -- 'Groundskeeper Agent', crew name, or system
    action TEXT NOT NULL,
    entity_type VARCHAR(50),              -- 'task', 'turnover', 'crew', 'property'
    entity_id INT,                        -- FK to the relevant record
    metadata JSONB
);

-- =============================================================================
-- INDEXES FOR SPEED
-- =============================================================================

-- Crew
CREATE INDEX IF NOT EXISTS idx_ops_crew_status ON ops_crew(status);
CREATE INDEX IF NOT EXISTS idx_ops_crew_role ON ops_crew(role);

-- Properties
CREATE INDEX IF NOT EXISTS idx_ops_props_name ON ops_properties(internal_name);

-- Turnovers
CREATE INDEX IF NOT EXISTS idx_ops_turn_status ON ops_turnovers(status);
CREATE INDEX IF NOT EXISTS idx_ops_turn_checkout ON ops_turnovers(checkout_time);
CREATE INDEX IF NOT EXISTS idx_ops_turn_property ON ops_turnovers(property_id);

-- Tasks
CREATE INDEX IF NOT EXISTS idx_ops_tasks_status ON ops_tasks(status);
CREATE INDEX IF NOT EXISTS idx_ops_tasks_assignee ON ops_tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_ops_tasks_type ON ops_tasks(type);
CREATE INDEX IF NOT EXISTS idx_ops_tasks_priority ON ops_tasks(priority);
CREATE INDEX IF NOT EXISTS idx_ops_tasks_deadline ON ops_tasks(deadline);
CREATE INDEX IF NOT EXISTS idx_ops_tasks_property ON ops_tasks(property_id);
CREATE INDEX IF NOT EXISTS idx_ops_tasks_turnover ON ops_tasks(turnover_id);

-- Audit Log
CREATE INDEX IF NOT EXISTS idx_ops_log_actor ON ops_log(actor);
CREATE INDEX IF NOT EXISTS idx_ops_log_entity ON ops_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_ops_log_time ON ops_log(timestamp);
