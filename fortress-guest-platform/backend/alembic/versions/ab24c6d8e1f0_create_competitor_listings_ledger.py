"""create competitor listings ledger

Revision ID: ab24c6d8e1f0
Revises: f1a2b3c4d5e6
Create Date: 2026-03-24 21:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "ab24c6d8e1f0"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "competitor_listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "platform",
            sa.Enum(
                "airbnb",
                "vrbo",
                "booking_com",
                name="ota_provider",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("external_url", sa.String(length=500), nullable=True),
        sa.Column("external_id", sa.String(length=100), nullable=True),
        sa.Column("dedupe_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_nightly_rate", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("observed_total_before_tax", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("platform_fee", sa.Numeric(precision=12, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("cleaning_fee", sa.Numeric(precision=12, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("total_after_tax", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "snapshot_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_observed", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_hash", name="uq_competitor_listings_dedupe_hash"),
    )
    op.create_index(op.f("ix_competitor_listings_dedupe_hash"), "competitor_listings", ["dedupe_hash"], unique=False)
    op.create_index(op.f("ix_competitor_listings_last_observed"), "competitor_listings", ["last_observed"], unique=False)
    op.create_index(op.f("ix_competitor_listings_platform"), "competitor_listings", ["platform"], unique=False)
    op.create_index(op.f("ix_competitor_listings_property_id"), "competitor_listings", ["property_id"], unique=False)
    op.create_index(
        "ix_competitor_listings_property_platform_observed",
        "competitor_listings",
        ["property_id", "platform", "last_observed"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_competitor_listings_property_platform_observed", table_name="competitor_listings")
    op.drop_index(op.f("ix_competitor_listings_property_id"), table_name="competitor_listings")
    op.drop_index(op.f("ix_competitor_listings_platform"), table_name="competitor_listings")
    op.drop_index(op.f("ix_competitor_listings_last_observed"), table_name="competitor_listings")
    op.drop_index(op.f("ix_competitor_listings_dedupe_hash"), table_name="competitor_listings")
    op.drop_table("competitor_listings")
    op.execute("DROP TYPE IF EXISTS ota_provider")
