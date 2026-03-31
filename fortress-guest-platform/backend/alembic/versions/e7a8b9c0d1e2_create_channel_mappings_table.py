"""create channel mappings table

Revision ID: e7a8b9c0d1e2
Revises: d6e7f8a9b0c1
Create Date: 2026-03-30 21:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS channel_mappings (
                id BIGSERIAL PRIMARY KEY,
                property_id TEXT NOT NULL,
                channel VARCHAR(64) NOT NULL,
                listing_id VARCHAR(255) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_channel_mappings_property_channel UNIQUE (property_id, channel)
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_channel_mappings_property_id
            ON channel_mappings (property_id)
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_channel_mappings_channel
            ON channel_mappings (channel)
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_channel_mappings_active
            ON channel_mappings (is_active)
            """
        )
    )
    op.execute(
        sa.text(
            """
            GRANT SELECT, INSERT, UPDATE, DELETE ON channel_mappings TO fortress_api
            """
        )
    )
    op.execute(
        sa.text(
            """
            GRANT USAGE, SELECT ON SEQUENCE channel_mappings_id_seq TO fortress_api
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_channel_mappings_active"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_channel_mappings_channel"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_channel_mappings_property_id"))
    op.execute(sa.text("DROP TABLE IF EXISTS channel_mappings"))
