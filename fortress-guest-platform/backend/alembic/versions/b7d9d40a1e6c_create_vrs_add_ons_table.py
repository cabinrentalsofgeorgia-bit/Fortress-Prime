"""create vrs add ons table

Revision ID: b7d9d40a1e6c
Revises: 26118e0ba71f
Create Date: 2026-03-20 18:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b7d9d40a1e6c"
down_revision: Union[str, None] = "26118e0ba71f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "vrs_add_ons" not in tables:
        op.create_table(
            "vrs_add_ons",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
            sa.Column("price", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")),
            sa.Column("pricing_model", sa.String(length=32), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("scope", sa.String(length=32), nullable=False),
            sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=False),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=False),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint("price >= 0", name="ck_vrs_add_ons_price_nonnegative"),
            sa.CheckConstraint(
                "pricing_model IN ('flat_fee', 'per_night', 'per_guest')",
                name="vrs_add_on_pricing_model",
            ),
            sa.CheckConstraint(
                "scope IN ('global', 'property_specific')",
                name="vrs_add_on_scope",
            ),
            sa.CheckConstraint(
                "(scope = 'global' AND property_id IS NULL) OR "
                "(scope = 'property_specific' AND property_id IS NOT NULL)",
                name="ck_vrs_add_ons_scope_property_consistency",
            ),
            sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        check_constraints = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("vrs_add_ons")
            if constraint.get("name")
        }
        for constraint_name in (
            "vrs_add_on_pricing_model",
            "vrs_add_on_scope",
            "ck_vrs_add_ons_scope_property_consistency",
        ):
            if constraint_name in check_constraints:
                op.drop_constraint(constraint_name, "vrs_add_ons", type_="check")

        bind.execute(sa.text("UPDATE vrs_add_ons SET pricing_model = lower(pricing_model)"))
        bind.execute(sa.text("UPDATE vrs_add_ons SET scope = lower(scope)"))
        bind.execute(sa.text("ALTER TABLE vrs_add_ons ALTER COLUMN description SET DEFAULT ''"))
        bind.execute(sa.text("ALTER TABLE vrs_add_ons ALTER COLUMN price SET DEFAULT 0.00"))
        bind.execute(sa.text("ALTER TABLE vrs_add_ons ALTER COLUMN is_active SET DEFAULT true"))
        bind.execute(sa.text("ALTER TABLE vrs_add_ons ALTER COLUMN created_at SET DEFAULT now()"))
        bind.execute(sa.text("ALTER TABLE vrs_add_ons ALTER COLUMN updated_at SET DEFAULT now()"))

        op.create_check_constraint(
            "vrs_add_on_pricing_model",
            "vrs_add_ons",
            "pricing_model IN ('flat_fee', 'per_night', 'per_guest')",
        )
        op.create_check_constraint(
            "vrs_add_on_scope",
            "vrs_add_ons",
            "scope IN ('global', 'property_specific')",
        )
        op.create_check_constraint(
            "ck_vrs_add_ons_scope_property_consistency",
            "vrs_add_ons",
            "(scope = 'global' AND property_id IS NULL) OR "
            "(scope = 'property_specific' AND property_id IS NOT NULL)",
        )

    indexes = {index["name"] for index in inspector.get_indexes("vrs_add_ons")}
    if "ix_vrs_add_ons_is_active" not in indexes:
        op.create_index("ix_vrs_add_ons_is_active", "vrs_add_ons", ["is_active"], unique=False)
    if "ix_vrs_add_ons_scope" not in indexes:
        op.create_index("ix_vrs_add_ons_scope", "vrs_add_ons", ["scope"], unique=False)
    if "ix_vrs_add_ons_property_id" not in indexes:
        op.create_index("ix_vrs_add_ons_property_id", "vrs_add_ons", ["property_id"], unique=False)
    if "ix_vrs_add_ons_active_scope_property" not in indexes:
        op.create_index(
            "ix_vrs_add_ons_active_scope_property",
            "vrs_add_ons",
            ["is_active", "scope", "property_id"],
            unique=False,
        )
    if "ix_vrs_add_ons_active_global" not in indexes:
        op.create_index(
            "ix_vrs_add_ons_active_global",
            "vrs_add_ons",
            ["name"],
            unique=False,
            postgresql_where=sa.text("is_active = true AND scope = 'global'"),
        )
    if "ix_vrs_add_ons_active_property_specific" not in indexes:
        op.create_index(
            "ix_vrs_add_ons_active_property_specific",
            "vrs_add_ons",
            ["property_id", "name"],
            unique=False,
            postgresql_where=sa.text("is_active = true AND scope = 'property_specific'"),
        )


def downgrade() -> None:
    op.drop_index("ix_vrs_add_ons_active_property_specific", table_name="vrs_add_ons")
    op.drop_index("ix_vrs_add_ons_active_global", table_name="vrs_add_ons")
    op.drop_index("ix_vrs_add_ons_active_scope_property", table_name="vrs_add_ons")
    op.drop_index("ix_vrs_add_ons_property_id", table_name="vrs_add_ons")
    op.drop_index("ix_vrs_add_ons_scope", table_name="vrs_add_ons")
    op.drop_index("ix_vrs_add_ons_is_active", table_name="vrs_add_ons")
    op.drop_table("vrs_add_ons")
