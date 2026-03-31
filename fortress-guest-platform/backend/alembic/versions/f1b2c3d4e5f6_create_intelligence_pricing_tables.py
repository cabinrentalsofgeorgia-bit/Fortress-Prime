"""create intelligence pricing tables

Revision ID: f1b2c3d4e5f6
Revises: e7a8b9c0d1e2
Create Date: 2026-03-30 21:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "e7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS channels (
                id UUID PRIMARY KEY,
                code VARCHAR(64) NOT NULL,
                display_name VARCHAR(255) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_channels_code UNIQUE (code)
            )
            """
        )
    )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_channels_code ON channels (code)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_channels_is_active ON channels (is_active)"))

    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS property_base_rates (
                id UUID PRIMARY KEY,
                property_id UUID NOT NULL,
                date_start DATE NOT NULL,
                date_end DATE NOT NULL,
                rate_plan VARCHAR(64) NOT NULL DEFAULT 'BAR',
                base_nightly_rate NUMERIC(12, 2) NOT NULL,
                priority INTEGER NOT NULL DEFAULT 100,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_property_base_rates_window UNIQUE (property_id, date_start, date_end, rate_plan),
                CONSTRAINT fk_property_base_rates_property FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_property_base_rates_property_dates
            ON property_base_rates (property_id, date_start, date_end)
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_property_base_rates_active
            ON property_base_rates (is_active)
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS property_channel_rate_adjustments (
                id UUID PRIMARY KEY,
                property_id UUID NOT NULL,
                channel_id UUID NOT NULL,
                date_start DATE NOT NULL,
                date_end DATE NOT NULL,
                adjustment_type VARCHAR(32) NOT NULL,
                adjustment_value NUMERIC(12, 4) NOT NULL,
                applies_to VARCHAR(32) NOT NULL,
                rule_name VARCHAR(120),
                priority INTEGER NOT NULL DEFAULT 100,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_property_channel_rate_adjustments_window UNIQUE (
                    property_id, channel_id, date_start, date_end, adjustment_type, applies_to
                ),
                CONSTRAINT fk_property_channel_rate_adjustments_property FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE,
                CONSTRAINT fk_property_channel_rate_adjustments_channel FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_property_channel_rate_adjustments_property_channel_dates
            ON property_channel_rate_adjustments (property_id, channel_id, date_start, date_end)
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_property_channel_rate_adjustments_active
            ON property_channel_rate_adjustments (is_active)
            """
        )
    )

    op.execute(
        sa.text(
            """
            GRANT SELECT, INSERT, UPDATE, DELETE
            ON channels, property_base_rates, property_channel_rate_adjustments
            TO fortress_api
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_property_channel_rate_adjustments_active"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_property_channel_rate_adjustments_property_channel_dates"))
    op.execute(sa.text("DROP TABLE IF EXISTS property_channel_rate_adjustments"))

    op.execute(sa.text("DROP INDEX IF EXISTS ix_property_base_rates_active"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_property_base_rates_property_dates"))
    op.execute(sa.text("DROP TABLE IF EXISTS property_base_rates"))

    op.execute(sa.text("DROP INDEX IF EXISTS ix_channels_is_active"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_channels_code"))
    op.execute(sa.text("DROP TABLE IF EXISTS channels"))
