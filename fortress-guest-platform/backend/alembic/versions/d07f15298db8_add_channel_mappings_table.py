"""add_channel_mappings_table

Maps each Fortress property to its external listing ID on each OTA channel
(Airbnb, VRBO, Booking.com, iCal, etc.).

For Channex-managed channels, the external_listing_id is the Channex
property UUID.  Direct OTA IDs can be stored here once partner credentials
are provisioned.

Revision ID: d07f15298db8
Revises: 0de35771a5b6
Create Date: 2026-04-13 18:54:50.493056

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'd07f15298db8'
down_revision: Union[str, Sequence[str], None] = '0de35771a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS channel_mappings (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            property_id         UUID        NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
            channel             VARCHAR(50) NOT NULL,   -- 'channex', 'airbnb', 'vrbo', 'booking_com', 'ical'
            external_listing_id VARCHAR(255) NOT NULL,  -- UUID for Channex; numeric for direct OTA
            sync_status         VARCHAR(30) NOT NULL DEFAULT 'active',
                                                        -- 'active', 'paused', 'error', 'pending'
            last_synced_at      TIMESTAMPTZ,
            sync_error          TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_channel_mappings_property_channel
                UNIQUE (property_id, channel)
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_channel_mappings_property_id "
        "ON channel_mappings (property_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_channel_mappings_channel "
        "ON channel_mappings (channel)"
    ))
    op.execute(sa.text(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON channel_mappings TO fortress_api"
    ))

    # Back-fill Channex mappings from existing ota_metadata JSONB on properties
    op.execute(sa.text("""
        INSERT INTO channel_mappings (property_id, channel, external_listing_id, sync_status)
        SELECT
            id,
            'channex',
            ota_metadata->>'channex_listing_id',
            'active'
        FROM properties
        WHERE is_active = true
          AND ota_metadata->>'channex_listing_id' IS NOT NULL
          AND ota_metadata->>'channex_listing_id' != ''
        ON CONFLICT (property_id, channel) DO NOTHING
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS channel_mappings"))
