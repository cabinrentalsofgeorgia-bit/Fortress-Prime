#!/usr/bin/env python3
"""Ensure Stripe Connect payout tables exist on the live Fortress schema."""

from __future__ import annotations

from sqlalchemy import create_engine, text

from backend.core.config import settings


DDL_STATEMENTS = [
    """
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
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_owner_payout_accounts_status
        ON owner_payout_accounts (account_status)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_owner_payout_accounts_owner_email
        ON owner_payout_accounts (owner_email)
    """,
    """
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
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_payout_ledger_stripe_transfer_id
        ON payout_ledger (stripe_transfer_id)
        WHERE stripe_transfer_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_payout_ledger_property_created
        ON payout_ledger (property_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_payout_ledger_status_created
        ON payout_ledger (status, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_payout_ledger_confirmation_code
        ON payout_ledger (confirmation_code)
    """,
    """
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
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_stripe_connect_events_event_type
        ON stripe_connect_events (event_type)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_stripe_connect_events_account_id
        ON stripe_connect_events (account_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_stripe_connect_events_transfer_id
        ON stripe_connect_events (transfer_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_stripe_connect_events_payout_id
        ON stripe_connect_events (payout_id)
    """,
]


def main() -> None:
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    with engine.begin() as conn:
        for statement in DDL_STATEMENTS:
            conn.execute(text(statement))

        rows = conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('owner_payout_accounts', 'payout_ledger', 'stripe_connect_events')
                ORDER BY table_name
                """
            )
        ).fetchall()
    print("\n".join(row.table_name for row in rows))


if __name__ == "__main__":
    main()
