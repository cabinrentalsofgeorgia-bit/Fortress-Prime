"""FLOS Phase 1-1 — state store + dispatcher schema (5 tables + 6 seed rows)

Revision ID: r3c4d5e6f7g8
Revises: q2b3c4d5e6f7
Create Date: 2026-04-27

Implements the consumer side of FLOS per
docs/architecture/cross-division/FLOS-phase-1-state-store-design-v1.1.md
(LOCKED v1.1, all Q1-Q5 closed).

Tables created:
  legal.case_posture                  — per-case structured state (18 fields,
                                        Phase 1 populates a subset)
  legal.dispatcher_routes             — config-driven event_type → handler map
                                        (no priority column per Q5/v1.1)
  legal.dispatcher_event_attempts     — single retry/metrics table (Principle 7)
  legal.dispatcher_dead_letter        — long-term retained dead-letter log
                                        (operator-triggered purge per Q3)
  legal.dispatcher_pause              — single-row dispatcher pause control

Seed data (legal.dispatcher_routes):
  4 enabled=TRUE  (email.received, watchdog.matched, operator.input,
                   dispatcher.dead_letter)
  2 enabled=FALSE (vault.document_ingested, council.deliberation_complete)
                  pre-registered placeholders

FK dependencies:
  All four mutator tables reference legal.event_log(id) — Phase 0a-1 must be
  applied before this migration. The CREATE TABLE statements would fail with
  "relation legal.event_log does not exist" otherwise.

Per ADR-001: applied bilaterally to fortress_db (canonical) + fortress_prod
(mirror). fortress_shadow_test is the smallest-blast-radius preflight.

Per Issue #204 alembic chain divergence: applied via raw psql on each DB and
the alembic_version row is updated separately. The migration file remains in
the alembic tree as documentation of the schema state.

Application targets: fortress_shadow_test, fortress_db, fortress_prod.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "r3c4d5e6f7g8"
down_revision = "q2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. legal.case_posture ─────────────────────────────────────────
    # Single row per active case. Phase 1 populates a minimal subset
    # (case_slug, procedural_phase default, theory_of_defense_state default,
    # top_risk_factors, posture_hash, timestamps, event FKs); Phase 2+ work
    # writes the remaining 10 fields. Schema lands end-to-end so Phase 2
    # onboarding does not require an ALTER.
    op.execute("""
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
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_case_posture_next_deadline
            ON legal.case_posture (next_deadline_date)
            WHERE next_deadline_date IS NOT NULL
    """)

    # ── 2. legal.dispatcher_routes ────────────────────────────────────
    # Config-driven event_type → handler. v1.1 LOCKED: no priority column.
    # Polling stays ORDER BY emitted_at (chronological FIFO).
    op.execute("""
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
        )
    """)

    # ── 3. legal.dispatcher_event_attempts ────────────────────────────
    # Single retry/metrics table per Principle 7 (LOCKED v1.1). Drives
    # both the polling-exclusion sub-query (retry budget enforcement)
    # and aggregate metrics (processed_last_hour, failed_last_hour, etc.).
    op.execute("""
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
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dispatcher_event_attempts_event_id
            ON legal.dispatcher_event_attempts (event_id)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dispatcher_event_attempts_attempted_at
            ON legal.dispatcher_event_attempts (attempted_at DESC)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dispatcher_event_attempts_outcome_recent
            ON legal.dispatcher_event_attempts (attempted_at DESC)
            WHERE outcome IN ('error', 'dead_letter')
    """)

    # ── 4. legal.dispatcher_dead_letter ───────────────────────────────
    # Long-term retained log for events that exhausted retries.
    # Operator-triggered purge only (Q3 LOCKED). Denormalizes event_type
    # and case_slug for query convenience (no join required for list).
    op.execute("""
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
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dispatcher_dead_letter_dead_lettered_at
            ON legal.dispatcher_dead_letter (dead_lettered_at DESC)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dispatcher_dead_letter_event_type
            ON legal.dispatcher_dead_letter (event_type, dead_lettered_at DESC)
    """)

    # ── 5. legal.dispatcher_pause ─────────────────────────────────────
    # Single-row table — at most one pause record at a time for v1.
    # CHECK on a literal singleton-id column enforces the singleton.
    op.execute("""
        CREATE TABLE IF NOT EXISTS legal.dispatcher_pause (
            singleton_id INTEGER PRIMARY KEY DEFAULT 1,
            paused_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            paused_by TEXT NOT NULL,
            reason TEXT,
            CONSTRAINT chk_dispatcher_pause_singleton
                CHECK (singleton_id = 1)
        )
    """)

    # ── 6. Initial seed rows for legal.dispatcher_routes ──────────────
    # 4 enabled=TRUE (live handlers per Phase 1-3 scope)
    # 2 enabled=FALSE (placeholders for future producers — Phase 2+ flips)
    op.execute("""
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
        ON CONFLICT (event_type) DO NOTHING
    """)


def downgrade() -> None:
    """
    Forward-only schema policy per ADR-001. Downgrade kept for completeness
    only — never invoked in production. Drops in reverse dependency order.
    """
    op.execute("DROP TABLE IF EXISTS legal.dispatcher_pause")
    op.execute("DROP INDEX IF EXISTS legal.idx_dispatcher_dead_letter_event_type")
    op.execute("DROP INDEX IF EXISTS legal.idx_dispatcher_dead_letter_dead_lettered_at")
    op.execute("DROP TABLE IF EXISTS legal.dispatcher_dead_letter")
    op.execute("DROP INDEX IF EXISTS legal.idx_dispatcher_event_attempts_outcome_recent")
    op.execute("DROP INDEX IF EXISTS legal.idx_dispatcher_event_attempts_attempted_at")
    op.execute("DROP INDEX IF EXISTS legal.idx_dispatcher_event_attempts_event_id")
    op.execute("DROP TABLE IF EXISTS legal.dispatcher_event_attempts")
    op.execute("DROP TABLE IF EXISTS legal.dispatcher_routes")
    op.execute("DROP INDEX IF EXISTS legal.idx_case_posture_next_deadline")
    op.execute("DROP TABLE IF EXISTS legal.case_posture")
