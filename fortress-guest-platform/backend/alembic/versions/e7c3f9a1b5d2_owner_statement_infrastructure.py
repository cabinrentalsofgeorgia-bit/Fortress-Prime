"""owner_statement_infrastructure

Combined migration for Area 2 gap-remediation Phase 1 + Phase 1.5 schema.

Changes in this revision:
  1. owner_payout_accounts — new columns
       commission_rate    NUMERIC(5,4) NOT NULL  (fraction, e.g. 0.3000 = 30%)
       streamline_owner_id INTEGER NULL           (Streamline integer owner ID)
     Before adding NOT NULL commission_rate, all existing test rows are deleted.
     Deleted rows (test data only, no real owner data):
       id=1  test-accept-...@example.com  acct_test123
       id=10 test-e2e-...@example.com     acct_1TM5m0Gs6a7mwDLz

  2. owner_statement_sends — new audit table
     Permanent record of every statement email generated, with Crog vs
     Streamline comparison and send status.

Revision ID: e7c3f9a1b5d2
Revises: b2c4d6e8f0a1
Create Date: 2026-04-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7c3f9a1b5d2"
down_revision: Union[str, Sequence[str], None] = "b2c4d6e8f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Part 1: owner_payout_accounts new columns ─────────────────────────

    # Delete all existing test rows so we can add the NOT NULL column cleanly.
    # As of this migration there are no real owner rows — only test data from
    # the unit/integration test runs.
    op.execute(sa.text("DELETE FROM owner_payout_accounts"))

    op.execute(sa.text("""
        ALTER TABLE owner_payout_accounts
            ADD COLUMN commission_rate  NUMERIC(5,4) NOT NULL,
            ADD COLUMN streamline_owner_id INTEGER NULL
    """))

    op.execute(sa.text("""
        ALTER TABLE owner_payout_accounts
            ADD CONSTRAINT chk_opa_commission_rate
            CHECK (commission_rate >= 0 AND commission_rate <= 0.5000)
    """))

    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_opa_streamline_owner_id "
        "ON owner_payout_accounts (streamline_owner_id)"
    ))

    # ── Part 2: owner_statement_sends audit table ─────────────────────────

    op.execute(sa.text("""
        CREATE TABLE owner_statement_sends (
            id                          BIGSERIAL    PRIMARY KEY,

            -- which payout account this statement was generated for
            owner_payout_account_id     BIGINT       NOT NULL
                REFERENCES owner_payout_accounts(id) ON DELETE RESTRICT,

            -- the property this statement covers (denormalised from the
            -- owner_payout_accounts row for fast queries without a join)
            property_id                 UUID         NOT NULL
                REFERENCES properties(id) ON DELETE RESTRICT,

            -- the statement period
            statement_period_start      DATE         NOT NULL,
            statement_period_end        DATE         NOT NULL,

            -- send status
            sent_at                     TIMESTAMPTZ,
            sent_to_email               VARCHAR(255),

            -- financial figures
            crog_total_amount           NUMERIC(12,2),
            streamline_total_amount     NUMERIC(12,2),

            -- which number was actually sent to the owner
            source_used                 VARCHAR(20)
                CHECK (source_used IN ('crog', 'streamline', 'failed')),

            -- comparison results
            comparison_status           VARCHAR(30)
                CHECK (comparison_status IN (
                    'match', 'mismatch',
                    'streamline_unavailable', 'not_compared'
                )),
            comparison_diff_cents       INTEGER,

            -- tracing / debugging
            email_message_id            VARCHAR(255),
            error_message               TEXT,

            -- marks rows written by the manual test endpoint
            is_test                     BOOLEAN      NOT NULL DEFAULT false,

            created_at                  TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """))

    op.execute(sa.text(
        "CREATE INDEX ix_oss_owner_payout_account_id "
        "ON owner_statement_sends (owner_payout_account_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_oss_property_id "
        "ON owner_statement_sends (property_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_oss_period "
        "ON owner_statement_sends (statement_period_start, statement_period_end)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_oss_sent_at ON owner_statement_sends (sent_at)"
    ))

    op.execute(sa.text(
        "GRANT SELECT, INSERT, UPDATE ON owner_statement_sends TO fortress_api"
    ))
    op.execute(sa.text(
        "GRANT USAGE, SELECT ON SEQUENCE owner_statement_sends_id_seq TO fortress_api"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS owner_statement_sends"))
    op.execute(sa.text("""
        ALTER TABLE owner_payout_accounts
            DROP CONSTRAINT IF EXISTS chk_opa_commission_rate,
            DROP COLUMN IF EXISTS commission_rate,
            DROP COLUMN IF EXISTS streamline_owner_id
    """))
