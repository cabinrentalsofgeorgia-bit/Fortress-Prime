"""create tenants table

Revision ID: a1b2c3d4e5f7
Revises: f1b2c3d4e5f6
Create Date: 2026-03-30 21:35:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "f1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(255) NOT NULL,
                slug VARCHAR(100) NOT NULL,
                domain VARCHAR(255),
                logo_url TEXT,
                primary_color VARCHAR(32) NOT NULL DEFAULT '#111827',
                timezone VARCHAR(64) NOT NULL DEFAULT 'America/New_York',
                plan VARCHAR(32) NOT NULL DEFAULT 'starter',
                max_properties INTEGER NOT NULL DEFAULT 25,
                max_staff_users INTEGER NOT NULL DEFAULT 5,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                streamline_api_url TEXT,
                streamline_api_key TEXT,
                streamline_api_secret TEXT,
                twilio_account_sid TEXT,
                twilio_auth_token TEXT,
                twilio_phone_number VARCHAR(32),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_tenants_slug UNIQUE (slug),
                CONSTRAINT uq_tenants_domain UNIQUE (domain)
            )
            """
        )
    )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_tenants_is_active ON tenants (is_active)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_tenants_name ON tenants (name)"))

    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON tenants TO fortress_api"))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_tenants_name"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_tenants_is_active"))
    op.execute(sa.text("DROP TABLE IF EXISTS tenants"))
