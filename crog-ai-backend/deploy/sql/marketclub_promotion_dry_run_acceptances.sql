CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS hedge_fund.signal_promotion_dry_run_acceptances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_record_id UUID NOT NULL
        REFERENCES hedge_fund.signal_shadow_review_decisions(id)
        ON DELETE RESTRICT,
    candidate_parameter_set VARCHAR(100) NOT NULL,
    baseline_parameter_set VARCHAR(100) NOT NULL,
    accepted_by VARCHAR(120) NOT NULL,
    acceptance_rationale TEXT NOT NULL,
    rollback_criteria TEXT NOT NULL,
    dry_run_generated_at TIMESTAMPTZ NOT NULL,
    dry_run_candidate_signal_count INTEGER NOT NULL,
    dry_run_proposed_insert_count INTEGER NOT NULL,
    dry_run_bullish_count INTEGER NOT NULL,
    dry_run_risk_count INTEGER NOT NULL,
    dry_run_skipped_neutral_count INTEGER NOT NULL,
    min_abs_score INTEGER NOT NULL,
    target_table TEXT NOT NULL,
    target_columns TEXT[] NOT NULL,
    dry_run_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_promotion_dry_run_acceptances_candidate_created
ON hedge_fund.signal_promotion_dry_run_acceptances (
    candidate_parameter_set,
    created_at DESC
);

CREATE INDEX IF NOT EXISTS ix_promotion_dry_run_acceptances_decision
ON hedge_fund.signal_promotion_dry_run_acceptances (decision_record_id);

GRANT SELECT, INSERT ON TABLE
    hedge_fund.signal_promotion_dry_run_acceptances
TO crog_ai_app;
