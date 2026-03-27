"""reconcile legacy properties table to UUID swarm contract

Revision ID: 1d9f2e7a6c41
Revises: 0eecc0b42908
Create Date: 2026-03-21 22:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "1d9f2e7a6c41"
down_revision: Union[str, None] = "0eecc0b42908"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names(bind: sa.Connection) -> set[str]:
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _column_names(bind: sa.Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _constraint_names(bind: sa.Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    names: set[str] = set()
    pk_constraint = inspector.get_pk_constraint(table_name)
    if pk_constraint.get("name"):
        names.add(pk_constraint["name"])
    names.update(
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table_name)
        if constraint.get("name")
    )
    names.update(
        constraint["name"]
        for constraint in inspector.get_foreign_keys(table_name)
        if constraint.get("name")
    )
    return names


def _index_names(bind: sa.Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name) if index.get("name")}


def _property_fk_refs(bind: sa.Connection) -> list[tuple[str, str, str]]:
    rows = bind.execute(
        sa.text(
            """
            SELECT tc.table_schema, tc.table_name, tc.constraint_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.constraint_schema = tc.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND ccu.table_schema = 'public'
              AND ccu.table_name = 'properties'
              AND ccu.column_name = 'id'
            ORDER BY tc.table_schema, tc.table_name, tc.constraint_name
            """
        )
    ).fetchall()
    return [(str(row[0]), str(row[1]), str(row[2])) for row in rows]


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)
    if "properties" not in tables:
        return

    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    property_columns = _column_names(bind, "properties")
    if "legacy_vrs_id" not in property_columns and "id" in property_columns:
        for table_schema, table_name, constraint_name in _property_fk_refs(bind):
            op.drop_constraint(
                constraint_name,
                table_name,
                type_="foreignkey",
                schema=table_schema,
            )

        op.alter_column(
            "properties",
            "id",
            existing_type=sa.Integer(),
            existing_nullable=False,
            new_column_name="legacy_vrs_id",
        )
        property_columns = _column_names(bind, "properties")

    if "id" not in property_columns:
        op.add_column("properties", sa.Column("id", postgresql.UUID(as_uuid=True), nullable=True))
        property_columns = _column_names(bind, "properties")

    bind.execute(sa.text("UPDATE properties SET id = gen_random_uuid() WHERE id IS NULL"))
    op.alter_column(
        "properties",
        "id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )

    if "properties_pkey" in _constraint_names(bind, "properties"):
        op.drop_constraint("properties_pkey", "properties", type_="primary")
    op.create_primary_key("properties_pkey", "properties", ["id"])

    if "legacy_vrs_id" in _column_names(bind, "properties") and "ux_properties_legacy_vrs_id" not in _constraint_names(bind, "properties"):
        op.create_unique_constraint("ux_properties_legacy_vrs_id", "properties", ["legacy_vrs_id"])

    property_columns = _column_names(bind, "properties")

    if "slug" not in property_columns:
        op.add_column("properties", sa.Column("slug", sa.String(length=255), nullable=True))
        bind.execute(
            sa.text(
                """
                WITH base AS (
                    SELECT
                        legacy_vrs_id,
                        COALESCE(
                            NULLIF(
                                trim(BOTH '-' FROM regexp_replace(lower(name), '[^a-z0-9]+', '-', 'g')),
                                ''
                            ),
                            'property-' || legacy_vrs_id::text
                        ) AS base_slug
                    FROM properties
                ),
                numbered AS (
                    SELECT
                        legacy_vrs_id,
                        base_slug,
                        row_number() OVER (PARTITION BY base_slug ORDER BY legacy_vrs_id) AS rn
                    FROM base
                )
                UPDATE properties AS p
                SET slug = CASE
                    WHEN numbered.rn = 1 THEN numbered.base_slug
                    ELSE numbered.base_slug || '-' || numbered.rn::text
                END
                FROM numbered
                WHERE p.legacy_vrs_id = numbered.legacy_vrs_id
                  AND p.slug IS NULL
                """
            )
        )
        op.alter_column("properties", "slug", existing_type=sa.String(length=255), nullable=False)
        op.create_index("ix_properties_slug", "properties", ["slug"], unique=True)

    if "property_type" not in property_columns:
        op.add_column(
            "properties",
            sa.Column("property_type", sa.String(length=50), nullable=False, server_default="cabin"),
        )

    if "bedrooms" not in property_columns:
        op.add_column(
            "properties",
            sa.Column("bedrooms", sa.Integer(), nullable=False, server_default="1"),
        )

    if "bathrooms" not in property_columns:
        op.add_column(
            "properties",
            sa.Column("bathrooms", sa.Numeric(3, 1), nullable=False, server_default="1.0"),
        )

    if "max_guests" not in property_columns:
        op.add_column(
            "properties",
            sa.Column("max_guests", sa.Integer(), nullable=False, server_default="4"),
        )

    if "latitude" not in property_columns:
        op.add_column("properties", sa.Column("latitude", sa.Numeric(10, 8), nullable=True))

    if "longitude" not in property_columns:
        op.add_column("properties", sa.Column("longitude", sa.Numeric(11, 8), nullable=True))

    if "wifi_ssid" not in property_columns:
        op.add_column("properties", sa.Column("wifi_ssid", sa.String(length=255), nullable=True))

    if "wifi_password" not in property_columns:
        op.add_column("properties", sa.Column("wifi_password", sa.String(length=255), nullable=True))

    if "access_code_type" not in property_columns:
        op.add_column("properties", sa.Column("access_code_type", sa.String(length=50), nullable=True))

    if "access_code_location" not in property_columns:
        op.add_column("properties", sa.Column("access_code_location", sa.Text(), nullable=True))

    if "parking_instructions" not in property_columns:
        op.add_column("properties", sa.Column("parking_instructions", sa.Text(), nullable=True))

    if "rate_card" not in property_columns:
        op.add_column("properties", sa.Column("rate_card", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    if "default_housekeeper_id" not in property_columns:
        op.add_column("properties", sa.Column("default_housekeeper_id", postgresql.UUID(as_uuid=True), nullable=True))

    if "default_clean_minutes" not in property_columns:
        op.add_column("properties", sa.Column("default_clean_minutes", sa.Integer(), nullable=True))

    if "streamline_checklist_id" not in property_columns:
        op.add_column("properties", sa.Column("streamline_checklist_id", sa.String(length=100), nullable=True))

    if "amenities" not in property_columns:
        op.add_column(
            "properties",
            sa.Column(
                "amenities",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )

    if "qdrant_point_id" not in property_columns:
        op.add_column("properties", sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True), nullable=True))

    if "streamline_property_id" not in property_columns:
        op.add_column("properties", sa.Column("streamline_property_id", sa.String(length=100), nullable=True))
        bind.execute(
            sa.text(
                "UPDATE properties SET streamline_property_id = streamline_id::text "
                "WHERE streamline_property_id IS NULL AND streamline_id IS NOT NULL"
            )
        )

    if "owner_id" not in property_columns:
        op.add_column("properties", sa.Column("owner_id", sa.String(length=100), nullable=True))

    if "owner_name" not in property_columns:
        op.add_column("properties", sa.Column("owner_name", sa.String(length=255), nullable=True))

    if "owner_balance" not in property_columns:
        op.add_column("properties", sa.Column("owner_balance", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    if "is_active" not in property_columns:
        op.add_column(
            "properties",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )
        bind.execute(
            sa.text(
                """
                UPDATE properties
                SET is_active = CASE
                    WHEN lower(COALESCE(management_status, '')) = 'active' THEN true
                    ELSE false
                END
                """
            )
        )

    if "ix_properties_streamline_property_id" not in _index_names(bind, "properties") and "streamline_property_id" in _column_names(bind, "properties"):
        op.create_index(
            "ix_properties_streamline_property_id",
            "properties",
            ["streamline_property_id"],
            unique=False,
        )


def downgrade() -> None:
    raise RuntimeError("Downgrade not supported for legacy property UUID reconciliation.")
