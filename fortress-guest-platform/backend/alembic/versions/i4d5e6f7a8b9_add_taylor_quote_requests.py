"""Add taylor_quote_requests table for multi-property availability-first quote flow.

Revision ID: i4d5e6f7a8b9
Revises: h3c4d5e6f7a8
Create Date: 2026-04-12
"""
from __future__ import annotations

revision = "i4d5e6f7a8b9"
down_revision = "h3c4d5e6f7a8"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS taylor_quote_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            guest_email VARCHAR(320) NOT NULL,
            check_in DATE NOT NULL,
            check_out DATE NOT NULL,
            nights INTEGER NOT NULL,
            adults INTEGER NOT NULL DEFAULT 2,
            children INTEGER NOT NULL DEFAULT 0,
            pets INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(30) NOT NULL DEFAULT 'pending_approval',
            property_options JSONB NOT NULL DEFAULT '[]'::jsonb,
            approved_by VARCHAR(320),
            sent_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_taylor_quote_requests_guest_email "
        "ON taylor_quote_requests (guest_email)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_taylor_quote_requests_status "
        "ON taylor_quote_requests (status)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_taylor_quote_requests_created_at "
        "ON taylor_quote_requests (created_at DESC)"
    ))
    op.execute(sa.text(
        "GRANT SELECT, INSERT, UPDATE ON taylor_quote_requests TO fortress_api"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS taylor_quote_requests"))
