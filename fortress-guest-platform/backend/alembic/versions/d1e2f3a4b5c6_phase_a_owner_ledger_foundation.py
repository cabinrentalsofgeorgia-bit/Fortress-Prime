"""phase_a_owner_ledger_foundation

Phase A of the Crog-VRS Owner Statements build.

Changes:
  1. properties.renting_state  — new ENUM column distinguishing active from
     pre-launch / paused / offboarded properties. Existing rows default to
     'active'. Restoration Luxury is set to 'pre_launch'.

  2. owner_balance_periods — new table that persists one row per owner per
     calendar period, carrying opening/closing balances forward indefinitely.
     Enforces the ledger equation via a DB CHECK constraint so any discrepancy
     is caught at the database level.

Revision ID: d1e2f3a4b5c6
Revises: c1a8f3b7e2d4
Create Date: 2026-04-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c1a8f3b7e2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # ── Part 1: properties.renting_state ─────────────────────────────────────

    # Create the enum type in the public schema
    renting_state_enum = postgresql.ENUM(
        "active",
        "pre_launch",
        "paused",
        "offboarded",
        name="property_renting_state",
        create_type=False,
    )
    renting_state_enum.create(bind, checkfirst=True)

    op.execute(sa.text("""
        ALTER TABLE properties
            ADD COLUMN renting_state property_renting_state
                NOT NULL DEFAULT 'active'
    """))

    # Set Restoration Luxury to pre_launch (identified by name, not UUID,
    # so the migration is not fragile to id changes if data is ever seeded fresh)
    updated = bind.execute(sa.text("""
        UPDATE properties
        SET renting_state = 'pre_launch'
        WHERE name = 'Restoration Luxury'
        RETURNING id, name
    """))
    rows = updated.fetchall()
    if not rows:
        raise RuntimeError(
            "Migration d1e2f3a4b5c6: could not find 'Restoration Luxury' to set "
            "renting_state = pre_launch. Check the property name in the database."
        )

    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_properties_renting_state "
        "ON properties (renting_state)"
    ))

    # ── Part 2: statement_period_status enum ─────────────────────────────────

    statement_status_enum = postgresql.ENUM(
        "draft",
        "pending_approval",
        "approved",
        "paid",
        "emailed",
        "voided",
        name="statement_period_status",
        create_type=False,
    )
    statement_status_enum.create(bind, checkfirst=True)

    # ── Part 3: owner_balance_periods table ──────────────────────────────────

    op.execute(sa.text("""
        CREATE TABLE owner_balance_periods (
            id                      BIGSERIAL       PRIMARY KEY,

            owner_payout_account_id BIGINT          NOT NULL
                REFERENCES owner_payout_accounts(id) ON DELETE RESTRICT,

            period_start            DATE            NOT NULL,
            period_end              DATE            NOT NULL,

            opening_balance         NUMERIC(12,2)   NOT NULL,
            closing_balance         NUMERIC(12,2)   NOT NULL,

            -- Components of the period's activity
            total_revenue           NUMERIC(12,2)   NOT NULL DEFAULT 0,
            total_commission        NUMERIC(12,2)   NOT NULL DEFAULT 0,
            total_charges           NUMERIC(12,2)   NOT NULL DEFAULT 0,
            total_payments          NUMERIC(12,2)   NOT NULL DEFAULT 0,
            total_owner_income      NUMERIC(12,2)   NOT NULL DEFAULT 0,

            status                  statement_period_status NOT NULL DEFAULT 'draft',

            created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),

            -- Approval / payment / email tracking
            approved_at             TIMESTAMPTZ,
            approved_by             VARCHAR(255),
            paid_at                 TIMESTAMPTZ,
            emailed_at              TIMESTAMPTZ,

            notes                   TEXT,

            CONSTRAINT uq_obp_owner_period
                UNIQUE (owner_payout_account_id, period_start, period_end),

            CONSTRAINT chk_obp_period_order
                CHECK (period_end > period_start),

            -- The ledger must balance.
            -- closing = opening + revenue - commission - charges - payments + owner_income
            CONSTRAINT chk_obp_ledger_equation
                CHECK (
                    closing_balance = opening_balance
                        + total_revenue
                        - total_commission
                        - total_charges
                        - total_payments
                        + total_owner_income
                )
        )
    """))

    op.execute(sa.text(
        "CREATE INDEX ix_obp_owner_period "
        "ON owner_balance_periods (owner_payout_account_id, period_start)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_obp_status "
        "ON owner_balance_periods (status)"
    ))
    op.execute(sa.text(
        "GRANT SELECT, INSERT, UPDATE ON owner_balance_periods TO fortress_api"
    ))
    op.execute(sa.text(
        "GRANT USAGE, SELECT ON SEQUENCE owner_balance_periods_id_seq TO fortress_api"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS owner_balance_periods"))

    statement_status = postgresql.ENUM(name="statement_period_status")
    statement_status.drop(op.get_bind(), checkfirst=True)

    op.execute(sa.text(
        "ALTER TABLE properties DROP COLUMN IF EXISTS renting_state"
    ))
    renting_state = postgresql.ENUM(name="property_renting_state")
    renting_state.drop(op.get_bind(), checkfirst=True)
