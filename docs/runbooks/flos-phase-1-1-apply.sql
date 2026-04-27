-- FLOS Phase 1-1 — state store + dispatcher schema apply
-- Migration ID: r3c4d5e6f7g8 (revises q2b3c4d5e6f7 / Phase 0a-1)
-- Date: 2026-04-27
-- Per: docs/architecture/cross-division/FLOS-phase-1-state-store-design-v1.1.md
--
-- Atomic apply: BEGIN..COMMIT wraps schema + seed + alembic_version touch.
-- Per Issue #204 chain divergence pattern, applied via raw psql on each DB
-- in the bilateral pair (fortress_db + fortress_prod) plus the smaller-blast
-- preflight on fortress_shadow_test. fortress_shadow is skipped (not in scope).
--
-- Prerequisite: legal.event_log must exist (Phase 0a-1 / migration q2b3c4d5e6f7).
-- The CREATE TABLE statements below carry FK references to legal.event_log(id);
-- they will fail loudly if Phase 0a-1 has not been applied to this DB.

\set ON_ERROR_STOP on

BEGIN;

-- Pre-flight: confirm Phase 0a-1 prerequisite exists. RAISE if not.
DO $$
BEGIN
    IF to_regclass('legal.event_log') IS NULL THEN
        RAISE EXCEPTION
            'PRECONDITION FAILED: legal.event_log does not exist. '
            'Phase 0a-1 (q2b3c4d5e6f7) must be applied before Phase 1-1. '
            'Aborting Phase 1-1 apply.';
    END IF;
END
$$;

-- ── 1. legal.case_posture ──────────────────────────────────────────────
-- Per FLOS Phase 1 design v1.1 §3 (LOCKED). 18 fields. Phase 1 populates
-- a minimal subset; Phase 2+ work writes the remaining 10 fields.
CREATE TABLE IF NOT EXISTS legal.case_posture (
    case_slug TEXT PRIMARY KEY,
    procedural_phase TEXT NOT NULL DEFAULT 'pre-suit',
    next_deadline_date DATE,
    next_deadline_action TEXT,
    theory_of_defense_state TEXT NOT NULL DEFAULT 'drafting',
    top_defense_arguments JSONB NOT NULL DEFAULT '[]'::jsonb,
    top_risk_factors JSONB NOT NULL DEFAULT '{}'::jsonb,
    exposure_low NUMERIC(12, 2),
    exposure_mid NUMERIC(12, 2),
    exposure_high NUMERIC(12, 2),
    leverage_score NUMERIC(4, 2),
    opposing_counsel_profile JSONB,
    last_council_consensus JSONB,
    last_council_at TIMESTAMPTZ,
    posture_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_event BIGINT REFERENCES legal.event_log(id),
    updated_by_event BIGINT REFERENCES legal.event_log(id),
    CONSTRAINT chk_case_posture_procedural_phase
        CHECK (procedural_phase IN (
            'pre-suit', 'answer-due', 'discovery', 'motion',
            'trial-prep', 'settlement', 'post-trial', 'closed'
        )),
    CONSTRAINT chk_case_posture_theory_of_defense_state
        CHECK (theory_of_defense_state IN (
            'drafting', 'validated', 'locked'
        )),
    CONSTRAINT chk_case_posture_leverage_score
        CHECK (leverage_score IS NULL
               OR (leverage_score >= -1.00 AND leverage_score <= 1.00))
);

CREATE INDEX IF NOT EXISTS idx_case_posture_next_deadline
    ON legal.case_posture (next_deadline_date)
    WHERE next_deadline_date IS NOT NULL;

-- ── 2. legal.dispatcher_routes ─────────────────────────────────────────
-- Per design v1.1 §4 (LOCKED). No `priority` column (v1.1 sharpening Q5 lineage).
CREATE TABLE IF NOT EXISTS legal.dispatcher_routes (
    event_type TEXT PRIMARY KEY,
    handler_module TEXT NOT NULL,
    handler_function TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    max_retries INTEGER NOT NULL DEFAULT 5,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_dispatcher_routes_max_retries_nonnegative
        CHECK (max_retries >= 0)
);

-- ── 3. legal.dispatcher_event_attempts ─────────────────────────────────
-- Single retry/metrics table per Principle 7 (LOCKED v1.1).
CREATE TABLE IF NOT EXISTS legal.dispatcher_event_attempts (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES legal.event_log(id),
    attempt_number INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    error_message TEXT,
    duration_ms INTEGER,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_dispatcher_event_attempts_outcome
        CHECK (outcome IN ('success', 'error', 'dead_letter')),
    CONSTRAINT chk_dispatcher_event_attempts_attempt_positive
        CHECK (attempt_number >= 1)
);

CREATE INDEX IF NOT EXISTS idx_dispatcher_event_attempts_event_id
    ON legal.dispatcher_event_attempts (event_id);

CREATE INDEX IF NOT EXISTS idx_dispatcher_event_attempts_attempted_at
    ON legal.dispatcher_event_attempts (attempted_at DESC);

CREATE INDEX IF NOT EXISTS idx_dispatcher_event_attempts_outcome_recent
    ON legal.dispatcher_event_attempts (attempted_at DESC)
    WHERE outcome IN ('error', 'dead_letter');

-- ── 4. legal.dispatcher_dead_letter ────────────────────────────────────
-- Long-term retained log. Operator-triggered purge only (Q3 LOCKED).
CREATE TABLE IF NOT EXISTS legal.dispatcher_dead_letter (
    id BIGSERIAL PRIMARY KEY,
    original_event_id BIGINT NOT NULL REFERENCES legal.event_log(id),
    event_type TEXT NOT NULL,
    case_slug TEXT,
    final_error TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    dead_lettered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_dispatcher_dead_letter_attempts_positive
        CHECK (attempts >= 1)
);

CREATE INDEX IF NOT EXISTS idx_dispatcher_dead_letter_dead_lettered_at
    ON legal.dispatcher_dead_letter (dead_lettered_at DESC);

CREATE INDEX IF NOT EXISTS idx_dispatcher_dead_letter_event_type
    ON legal.dispatcher_dead_letter (event_type, dead_lettered_at DESC);

-- ── 5. legal.dispatcher_pause ──────────────────────────────────────────
-- Single-row table — at most one pause record at a time for v1.
CREATE TABLE IF NOT EXISTS legal.dispatcher_pause (
    singleton_id INTEGER PRIMARY KEY DEFAULT 1,
    paused_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paused_by TEXT NOT NULL,
    reason TEXT,
    CONSTRAINT chk_dispatcher_pause_singleton
        CHECK (singleton_id = 1)
);

-- ── 6. Seed rows for legal.dispatcher_routes ───────────────────────────
-- 4 enabled=TRUE (live in Phase 1-3) + 2 enabled=FALSE (placeholders for
-- future producers; flipped to TRUE in Phase 2+ when those producers ship).
INSERT INTO legal.dispatcher_routes
    (event_type, handler_module, handler_function, enabled, max_retries, description)
VALUES
    (
        'email.received',
        'backend.services.legal_dispatcher',
        'handle_email_received',
        TRUE,
        5,
        'Phase 1-3 LIVE — load case_posture, emit watchdog.matched events, refresh audit timestamps'
    ),
    (
        'watchdog.matched',
        'backend.services.legal_dispatcher',
        'handle_watchdog_matched',
        TRUE,
        5,
        'Phase 1-3 LIVE — aggregate watchdog matches into case_posture.top_risk_factors keyed by rule_id'
    ),
    (
        'operator.input',
        'backend.services.legal_dispatcher',
        'handle_operator_input',
        TRUE,
        5,
        'Phase 1-3 LIVE — operator-driven case_posture mutations; route wired now, full CLI in Phase 2+'
    ),
    (
        'dispatcher.dead_letter',
        'backend.services.legal_dispatcher',
        'handle_dead_letter',
        TRUE,
        1,
        'Phase 1-3 LIVE — observability sink; appends to legal.dispatcher_dead_letter and emits no further events'
    ),
    (
        'vault.document_ingested',
        'backend.services.legal_dispatcher',
        'handle_vault_document_ingested',
        FALSE,
        5,
        'PLACEHOLDER — Vault ingester does not yet emit; flip to TRUE in Phase 2+ when producer ships'
    ),
    (
        'council.deliberation_complete',
        'backend.services.legal_dispatcher',
        'handle_council_deliberation_complete',
        FALSE,
        5,
        'PLACEHOLDER — Council audit migration to event_log is Phase 2+ work'
    )
ON CONFLICT (event_type) DO NOTHING;

-- ── 7. alembic_version touch ───────────────────────────────────────────
-- Per Issue #204 chain divergence pattern: alembic_version is updated by
-- raw SQL after the schema apply. The migration revision id matches the
-- file in backend/alembic/versions/.
--
-- For first-time apply on this DB: INSERT (Step 1 fortress_shadow_test).
-- For subsequent apply on a DB that already has the row: UPDATE
-- (Step 2 fortress_db, Step 3 fortress_prod) — Step 2 and 3 SQL replaces
-- the INSERT below with: UPDATE alembic_version SET version_num = 'r3c4d5e6f7g8'.
--
-- The Step 1 form is below; operator runs Step 2/Step 3 with the UPDATE form
-- via the runbook (or per-step inline-edit before psql invocation).
INSERT INTO alembic_version (version_num)
VALUES ('r3c4d5e6f7g8')
ON CONFLICT (version_num) DO NOTHING;

COMMIT;

-- Post-apply verification queries (run separately after COMMIT):
--
-- SELECT to_regclass('legal.case_posture'),
--        to_regclass('legal.dispatcher_routes'),
--        to_regclass('legal.dispatcher_event_attempts'),
--        to_regclass('legal.dispatcher_dead_letter'),
--        to_regclass('legal.dispatcher_pause');
--
-- SELECT event_type, enabled FROM legal.dispatcher_routes ORDER BY event_type;
--
-- Expected: 6 rows, 4 with enabled=TRUE, 2 with enabled=FALSE.
