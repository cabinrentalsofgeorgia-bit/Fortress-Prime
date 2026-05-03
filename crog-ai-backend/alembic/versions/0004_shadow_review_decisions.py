"""add shadow review decision records

Revision ID: 0004_shadow_review_decisions
Revises: 0003_rehash_xsource_dedup
Create Date: 2026-05-03

Decision records are the supervised promotion/defer audit trail for Dochia
candidate reviews. They do not promote rows into hedge_fund.market_signals.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_shadow_review_decisions"
down_revision: str | None = "0003_rehash_xsource_dedup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
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
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_shadow_review_decisions_candidate_created
        ON hedge_fund.signal_shadow_review_decisions (
            candidate_parameter_set,
            created_at DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_shadow_review_decisions_decision_created
        ON hedge_fund.signal_shadow_review_decisions (
            decision,
            created_at DESC
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS hedge_fund.ix_shadow_review_decisions_decision_created")
    op.execute("DROP INDEX IF EXISTS hedge_fund.ix_shadow_review_decisions_candidate_created")
    op.execute("DROP TABLE IF EXISTS hedge_fund.signal_shadow_review_decisions")
