CREATE TABLE IF NOT EXISTS hedge_fund.signal_shadow_review_decisions (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_parameter_set     TEXT NOT NULL,
    baseline_parameter_set      TEXT NOT NULL,
    decision                    TEXT NOT NULL,
    reviewer                    TEXT NOT NULL,
    rationale                   TEXT NOT NULL,
    rollback_criteria           TEXT NOT NULL,
    reviewed_tickers            TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    notes                       TEXT,
    shadow_review_generated_at  TIMESTAMPTZ NOT NULL,
    promotion_gate_status       TEXT NOT NULL,
    recommendation_status       TEXT NOT NULL,
    evidence_payload            JSONB NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (decision IN (
        'defer',
        'continue_shadow',
        'promote_to_market_signals'
    )),
    CHECK (promotion_gate_status IN ('hold', 'review', 'ready_for_shadow')),
    CHECK (recommendation_status IN (
        'ready_for_shadow_review',
        'needs_review',
        'hold'
    ))
);

CREATE INDEX IF NOT EXISTS ix_shadow_review_decisions_candidate_created
ON hedge_fund.signal_shadow_review_decisions (
    candidate_parameter_set,
    created_at DESC
);

CREATE INDEX IF NOT EXISTS ix_shadow_review_decisions_decision_created
ON hedge_fund.signal_shadow_review_decisions (
    decision,
    created_at DESC
);

GRANT SELECT, INSERT ON TABLE
    hedge_fund.signal_shadow_review_decisions
TO crog_ai_app;
