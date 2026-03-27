"""create media ledger

Revision ID: a4f9c2d7e6b1
Revises: e2c4f6a8b0d1
Create Date: 2026-03-22 15:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a4f9c2d7e6b1"
down_revision: Union[str, None] = "e2c4f6a8b0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "property_images" not in tables:
        op.create_table(
            "property_images",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("legacy_url", sa.String(length=2048), nullable=False),
            sa.Column("sovereign_url", sa.String(length=2048), nullable=True),
            sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("alt_text", sa.String(length=512), nullable=False, server_default=sa.text("''")),
            sa.Column("is_hero", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.CheckConstraint(
                "status IN ('pending', 'ingested', 'failed')",
                name="ck_property_images_status",
            ),
            sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("property_id", "legacy_url", name="uq_property_images_property_legacy_url"),
        )

    indexes = {index["name"] for index in inspector.get_indexes("property_images")}
    if "ix_property_images_property_id" not in indexes:
        op.create_index("ix_property_images_property_id", "property_images", ["property_id"], unique=False)
    if "ix_property_images_status" not in indexes:
        op.create_index("ix_property_images_status", "property_images", ["status"], unique=False)
    if "ix_property_images_property_status_order" not in indexes:
        op.create_index(
            "ix_property_images_property_status_order",
            "property_images",
            ["property_id", "status", "display_order"],
            unique=False,
        )

    bind.execute(
        sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE property_images TO fortress_api")
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "property_images" not in tables:
        return

    op.drop_index("ix_property_images_property_status_order", table_name="property_images")
    op.drop_index("ix_property_images_status", table_name="property_images")
    op.drop_index("ix_property_images_property_id", table_name="property_images")
    op.drop_table("property_images")
