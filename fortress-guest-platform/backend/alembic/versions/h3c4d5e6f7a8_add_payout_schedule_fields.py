"""Bootstrap payout tables in fortress_shadow and add schedule configuration fields.

The owner_payout_accounts / payout_ledger / stripe_connect_events tables were
originally created against fortress_guest when the Alembic config pointed there.
This migration idempotently creates them in fortress_shadow (the live app DB)
and adds the payout schedule configuration columns in one pass.

Revision ID: h3c4d5e6f7a8
Revises: h2b3c4d5e6f7
Create Date: 2026-04-11
"""

from __future__ import annotations

revision = "h3c4d5e6f7a8"
down_revision = "h2b3c4d5e6f7"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # ── 1. Bootstrap tables (idempotent — safe if they already exist) ──────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS owner_payout_accounts (
            id BIGSERIAL PRIMARY KEY,
            property_id VARCHAR(100) NOT NULL,
            owner_name VARCHAR(255) NOT NULL,
            owner_email VARCHAR(255),
            stripe_account_id VARCHAR(255),
            account_status VARCHAR(64) NOT NULL DEFAULT 'onboarding',
            instant_payout BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_owner_payout_accounts_property_id UNIQUE (property_id),
            CONSTRAINT uq_owner_payout_accounts_stripe_account_id UNIQUE (stripe_account_id)
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_owner_payout_accounts_status "
        "ON owner_payout_accounts (account_status)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_owner_payout_accounts_owner_email "
        "ON owner_payout_accounts (owner_email)"
    ))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS payout_ledger (
            id BIGSERIAL PRIMARY KEY,
            property_id VARCHAR(100) NOT NULL,
            confirmation_code VARCHAR(100),
            gross_amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
            owner_amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
            stripe_transfer_id VARCHAR(255),
            stripe_payout_id VARCHAR(255),
            status VARCHAR(64) NOT NULL DEFAULT 'staged',
            initiated_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            failure_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    op.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_payout_ledger_stripe_transfer_id "
        "ON payout_ledger (stripe_transfer_id) WHERE stripe_transfer_id IS NOT NULL"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_payout_ledger_property_created "
        "ON payout_ledger (property_id, created_at DESC)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_payout_ledger_status_created "
        "ON payout_ledger (status, created_at DESC)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_payout_ledger_confirmation_code "
        "ON payout_ledger (confirmation_code)"
    ))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS stripe_connect_events (
            id BIGSERIAL PRIMARY KEY,
            stripe_event_id VARCHAR(255) NOT NULL,
            event_type VARCHAR(100) NOT NULL,
            account_id VARCHAR(255),
            transfer_id VARCHAR(255),
            payout_id VARCHAR(255),
            amount NUMERIC(12, 2),
            status VARCHAR(64),
            failure_code VARCHAR(100),
            failure_message TEXT,
            raw_payload JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_stripe_connect_events_event_id UNIQUE (stripe_event_id)
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_stripe_connect_events_event_type "
        "ON stripe_connect_events (event_type)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_stripe_connect_events_account_id "
        "ON stripe_connect_events (account_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_stripe_connect_events_transfer_id "
        "ON stripe_connect_events (transfer_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_stripe_connect_events_payout_id "
        "ON stripe_connect_events (payout_id)"
    ))

    # Grant permissions to runtime role
    op.execute(sa.text(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON owner_payout_accounts, payout_ledger, stripe_connect_events TO fortress_api"
    ))
    op.execute(sa.text(
        "GRANT USAGE, SELECT ON SEQUENCE owner_payout_accounts_id_seq TO fortress_api"
    ))
    op.execute(sa.text(
        "GRANT USAGE, SELECT ON SEQUENCE payout_ledger_id_seq TO fortress_api"
    ))
    op.execute(sa.text(
        "GRANT USAGE, SELECT ON SEQUENCE stripe_connect_events_id_seq TO fortress_api"
    ))

    # ── 2. Add payout schedule configuration columns ────────────────────────────
    # payout_schedule: 'manual' | 'weekly' | 'biweekly' | 'monthly'
    op.execute(sa.text(
        "ALTER TABLE owner_payout_accounts "
        "ADD COLUMN IF NOT EXISTS payout_schedule VARCHAR(20) NOT NULL DEFAULT 'manual'"
    ))
    op.execute(sa.text(
        "ALTER TABLE owner_payout_accounts "
        "ADD COLUMN IF NOT EXISTS payout_day_of_week INTEGER"
    ))
    op.execute(sa.text(
        "ALTER TABLE owner_payout_accounts "
        "ADD COLUMN IF NOT EXISTS payout_day_of_month INTEGER"
    ))
    op.execute(sa.text(
        "ALTER TABLE owner_payout_accounts "
        "ADD COLUMN IF NOT EXISTS last_payout_at TIMESTAMPTZ"
    ))
    op.execute(sa.text(
        "ALTER TABLE owner_payout_accounts "
        "ADD COLUMN IF NOT EXISTS next_scheduled_payout TIMESTAMPTZ"
    ))
    op.execute(sa.text(
        "ALTER TABLE owner_payout_accounts "
        "ADD COLUMN IF NOT EXISTS minimum_payout_threshold NUMERIC(10, 2) NOT NULL DEFAULT 100.00"
    ))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE owner_payout_accounts DROP COLUMN IF EXISTS minimum_payout_threshold"))
    op.execute(sa.text("ALTER TABLE owner_payout_accounts DROP COLUMN IF EXISTS next_scheduled_payout"))
    op.execute(sa.text("ALTER TABLE owner_payout_accounts DROP COLUMN IF EXISTS last_payout_at"))
    op.execute(sa.text("ALTER TABLE owner_payout_accounts DROP COLUMN IF EXISTS payout_day_of_month"))
    op.execute(sa.text("ALTER TABLE owner_payout_accounts DROP COLUMN IF EXISTS payout_day_of_week"))
    op.execute(sa.text("ALTER TABLE owner_payout_accounts DROP COLUMN IF EXISTS payout_schedule"))
    # Note: downgrade does NOT drop the base tables — they may contain production data.
