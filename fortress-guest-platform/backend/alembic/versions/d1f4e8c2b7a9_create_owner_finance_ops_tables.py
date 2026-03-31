"""Create canonical owner finance operations tables.

Revision ID: d1f4e8c2b7a9
Revises: f2a6b8c4d1e9
Create Date: 2026-03-29 18:10:00.000000

This revision codifies tables that are actively referenced by admin ops, owner
portal, contracts, auth, and payout flows but are not currently represented in
the sovereign Alembic branch.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d1f4e8c2b7a9"
down_revision: Union[str, Sequence[str], None] = "f2a6b8c4d1e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "owner_property_map",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("sl_owner_id", sa.String(length=50), nullable=False),
        sa.Column("unit_id", sa.String(length=100), nullable=False),
        sa.Column("owner_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("property_name", sa.String(length=255), nullable=True),
        sa.Column("live_balance", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("sl_owner_id", "unit_id", name="uq_owner_property_map_owner_unit"),
    )
    op.create_index("ix_owner_property_map_owner_id", "owner_property_map", ["sl_owner_id"], unique=False)
    op.create_index("ix_owner_property_map_email", "owner_property_map", ["email"], unique=False)
    op.create_index("ix_owner_property_map_unit_id", "owner_property_map", ["unit_id"], unique=False)

    op.create_table(
        "management_splits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("property_id", sa.String(length=100), nullable=False),
        sa.Column("owner_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("pm_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("property_id", name="uq_management_splits_property_id"),
    )
    op.create_index("ix_management_splits_property_id", "management_splits", ["property_id"], unique=False)

    op.create_table(
        "owner_markup_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("property_id", sa.String(length=100), nullable=False),
        sa.Column("expense_category", sa.String(length=64), nullable=False, server_default="ALL"),
        sa.Column("markup_percentage", sa.Numeric(6, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("property_id", "expense_category", name="uq_owner_markup_rules_property_category"),
    )
    op.create_index("ix_owner_markup_rules_property_id", "owner_markup_rules", ["property_id"], unique=False)

    op.create_table(
        "capex_staging",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("property_id", sa.String(length=100), nullable=False),
        sa.Column("vendor", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_owner_charge", sa.Numeric(12, 2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("journal_lines", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("audit_trail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("compliance_status", sa.String(length=64), nullable=False, server_default="PENDING_CAPEX_APPROVAL"),
        sa.Column("approved_by", sa.String(length=100), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.String(length=100), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_capex_staging_property_id", "capex_staging", ["property_id"], unique=False)
    op.create_index("ix_capex_staging_status_created", "capex_staging", ["compliance_status", "created_at"], unique=False)

    op.create_table(
        "marketing_attribution",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("property_id", sa.String(length=100), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("ad_spend", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("direct_bookings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gross_revenue", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("roas", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("campaign_notes", sa.Text(), nullable=True),
        sa.Column("entered_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("property_id", "period_start", "period_end", name="uq_marketing_attribution_property_period"),
    )
    op.create_index("ix_marketing_attribution_property_id", "marketing_attribution", ["property_id"], unique=False)
    op.create_index("ix_marketing_attribution_period_end", "marketing_attribution", ["period_end"], unique=False)

    op.create_table(
        "owner_marketing_preferences",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("property_id", sa.String(length=100), nullable=False),
        sa.Column("marketing_pct", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by", sa.String(length=100), nullable=True),
        sa.UniqueConstraint("property_id", name="uq_owner_marketing_preferences_property_id"),
    )
    op.create_index("ix_owner_marketing_preferences_property_id", "owner_marketing_preferences", ["property_id"], unique=False)

    op.create_table(
        "owner_magic_tokens",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("owner_email", sa.String(length=255), nullable=False),
        sa.Column("sl_owner_id", sa.String(length=50), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("token_hash", name="uq_owner_magic_tokens_token_hash"),
    )
    op.create_index("ix_owner_magic_tokens_owner_email", "owner_magic_tokens", ["owner_email"], unique=False)
    op.create_index("ix_owner_magic_tokens_owner_id", "owner_magic_tokens", ["sl_owner_id"], unique=False)
    op.create_index("ix_owner_magic_tokens_expires_at", "owner_magic_tokens", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_owner_magic_tokens_expires_at", table_name="owner_magic_tokens")
    op.drop_index("ix_owner_magic_tokens_owner_id", table_name="owner_magic_tokens")
    op.drop_index("ix_owner_magic_tokens_owner_email", table_name="owner_magic_tokens")
    op.drop_table("owner_magic_tokens")

    op.drop_index("ix_owner_marketing_preferences_property_id", table_name="owner_marketing_preferences")
    op.drop_table("owner_marketing_preferences")

    op.drop_index("ix_marketing_attribution_period_end", table_name="marketing_attribution")
    op.drop_index("ix_marketing_attribution_property_id", table_name="marketing_attribution")
    op.drop_table("marketing_attribution")

    op.drop_index("ix_capex_staging_status_created", table_name="capex_staging")
    op.drop_index("ix_capex_staging_property_id", table_name="capex_staging")
    op.drop_table("capex_staging")

    op.drop_index("ix_owner_markup_rules_property_id", table_name="owner_markup_rules")
    op.drop_table("owner_markup_rules")

    op.drop_index("ix_management_splits_property_id", table_name="management_splits")
    op.drop_table("management_splits")

    op.drop_index("ix_owner_property_map_unit_id", table_name="owner_property_map")
    op.drop_index("ix_owner_property_map_email", table_name="owner_property_map")
    op.drop_index("ix_owner_property_map_owner_id", table_name="owner_property_map")
    op.drop_table("owner_property_map")
