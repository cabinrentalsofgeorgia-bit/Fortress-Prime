"""create CROG acquisition foundation

Revision ID: b6f0a2c4d8e1
Revises: f4c2b7d9e1a0
Create Date: 2026-03-30 17:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType


revision: str = "b6f0a2c4d8e1"
down_revision: Union[str, Sequence[str], None] = "f4c2b7d9e1a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "crog_acquisition"


class GeometryPolygon(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **_kw: object) -> str:
        return "GEOMETRY(POLYGON,4326)"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
    bind.execute(sa.text('CREATE EXTENSION IF NOT EXISTS "postgis"'))
    bind.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))

    market_state = postgresql.ENUM(
        "UNMANAGED",
        "CROG_MANAGED",
        "COMPETITOR_MANAGED",
        "FOR_SALE",
        name="market_state",
        schema=SCHEMA,
        create_type=False,
    )
    funnel_stage = postgresql.ENUM(
        "RADAR",
        "TARGET_LOCKED",
        "DEPLOYED",
        "ENGAGED",
        "ACQUIRED",
        "REJECTED",
        name="funnel_stage",
        schema=SCHEMA,
        create_type=False,
    )
    market_state.create(bind, checkfirst=True)
    funnel_stage.create(bind, checkfirst=True)

    op.create_table(
        "parcels",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("county_name", sa.String(length=100), nullable=False, server_default=sa.text("'Fannin'")),
        sa.Column("parcel_id", sa.String(length=100), nullable=False),
        sa.Column("geom", GeometryPolygon(), nullable=True),
        sa.Column("assessed_value", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("zoning_code", sa.String(length=50), nullable=True),
        sa.Column("is_waterfront", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_ridgeline", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("parcel_id", name="uq_acquisition_parcels_parcel_id"),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_acquisition_parcels_geom",
        "parcels",
        ["geom"],
        unique=False,
        schema=SCHEMA,
        postgresql_using="gist",
    )
    op.create_index(
        "idx_acquisition_parcels_assessed",
        "parcels",
        ["assessed_value"],
        unique=False,
        schema=SCHEMA,
    )

    op.create_table(
        "owners",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("tax_mailing_address", sa.Text(), nullable=False),
        sa.Column("primary_residence_state", sa.String(length=2), nullable=True),
        sa.Column("psychological_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_acquisition_owners_legal_name",
        "owners",
        ["legal_name"],
        unique=False,
        schema=SCHEMA,
    )

    op.create_table(
        "owner_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_type", sa.String(length=50), nullable=True),
        sa.Column("contact_value", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("confidence_score", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("is_dnc", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.CheckConstraint(
            "contact_type IN ('CELL', 'LANDLINE', 'EMAIL')",
            name="ck_acquisition_owner_contacts_contact_type",
        ),
        sa.CheckConstraint(
            "confidence_score >= 0.00 AND confidence_score <= 1.00",
            name="ck_acquisition_owner_contacts_confidence_score",
        ),
        sa.ForeignKeyConstraint(["owner_id"], [f"{SCHEMA}.owners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "contact_value", name="uq_acquisition_owner_contacts_owner_value"),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_acquisition_owner_contacts_owner",
        "owner_contacts",
        ["owner_id"],
        unique=False,
        schema=SCHEMA,
    )

    op.create_table(
        "properties",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("parcel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fannin_str_cert_id", sa.String(length=100), nullable=True),
        sa.Column("blue_ridge_str_permit", sa.String(length=100), nullable=True),
        sa.Column("zillow_zpid", sa.String(length=100), nullable=True),
        sa.Column("google_place_id", sa.String(length=255), nullable=True),
        sa.Column("airbnb_listing_id", sa.String(length=100), nullable=True),
        sa.Column("vrbo_listing_id", sa.String(length=100), nullable=True),
        sa.Column(
            "status",
            market_state,
            nullable=False,
            server_default=sa.text(f"'UNMANAGED'::{SCHEMA}.market_state"),
        ),
        sa.Column("management_company", sa.String(length=255), nullable=True),
        sa.Column("bedrooms", sa.Integer(), nullable=True),
        sa.Column("bathrooms", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("projected_adr", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("projected_annual_revenue", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["parcel_id"], [f"{SCHEMA}.parcels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], [f"{SCHEMA}.owners.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fannin_str_cert_id"),
        sa.UniqueConstraint("blue_ridge_str_permit"),
        sa.UniqueConstraint("zillow_zpid"),
        sa.UniqueConstraint("google_place_id"),
        sa.UniqueConstraint("airbnb_listing_id"),
        sa.UniqueConstraint("vrbo_listing_id"),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_acquisition_properties_status",
        "properties",
        ["status"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "idx_acquisition_properties_mgmt",
        "properties",
        ["management_company"],
        unique=False,
        schema=SCHEMA,
    )

    op.create_table(
        "acquisition_pipeline",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "stage",
            funnel_stage,
            nullable=False,
            server_default=sa.text(f"'RADAR'::{SCHEMA}.funnel_stage"),
        ),
        sa.Column("llm_viability_score", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("lob_mail_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("instantly_campaign_id", sa.String(length=255), nullable=True),
        sa.Column("vapi_call_status", sa.String(length=100), nullable=True),
        sa.Column("next_action_date", sa.Date(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["property_id"], [f"{SCHEMA}.properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("property_id", name="uq_acquisition_pipeline_property_id"),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_acquisition_pipeline_stage",
        "acquisition_pipeline",
        ["stage"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "idx_acquisition_pipeline_next_action_date",
        "acquisition_pipeline",
        ["next_action_date"],
        unique=False,
        schema=SCHEMA,
    )

    op.create_table(
        "intel_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_description", sa.Text(), nullable=False),
        sa.Column("raw_source_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["property_id"], [f"{SCHEMA}.properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_acquisition_intel_property_time",
        "intel_events",
        ["property_id", "detected_at"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "idx_acquisition_intel_event_type",
        "intel_events",
        ["event_type"],
        unique=False,
        schema=SCHEMA,
    )
    bind.execute(sa.text(f"GRANT USAGE ON SCHEMA {SCHEMA} TO fortress_api"))
    bind.execute(sa.text(f"GRANT USAGE ON TYPE {SCHEMA}.market_state TO fortress_api"))
    bind.execute(sa.text(f"GRANT USAGE ON TYPE {SCHEMA}.funnel_stage TO fortress_api"))
    bind.execute(
        sa.text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO fortress_api"
        )
    )
    bind.execute(
        sa.text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fortress_api"
        )
    )


def downgrade() -> None:
    op.drop_index("idx_acquisition_intel_event_type", table_name="intel_events", schema=SCHEMA)
    op.drop_index("idx_acquisition_intel_property_time", table_name="intel_events", schema=SCHEMA)
    op.drop_table("intel_events", schema=SCHEMA)

    op.drop_index("idx_acquisition_pipeline_next_action_date", table_name="acquisition_pipeline", schema=SCHEMA)
    op.drop_index("idx_acquisition_pipeline_stage", table_name="acquisition_pipeline", schema=SCHEMA)
    op.drop_table("acquisition_pipeline", schema=SCHEMA)

    op.drop_index("idx_acquisition_properties_mgmt", table_name="properties", schema=SCHEMA)
    op.drop_index("idx_acquisition_properties_status", table_name="properties", schema=SCHEMA)
    op.drop_table("properties", schema=SCHEMA)

    op.drop_index("idx_acquisition_owner_contacts_owner", table_name="owner_contacts", schema=SCHEMA)
    op.drop_table("owner_contacts", schema=SCHEMA)

    op.drop_index("idx_acquisition_owners_legal_name", table_name="owners", schema=SCHEMA)
    op.drop_table("owners", schema=SCHEMA)

    op.drop_index("idx_acquisition_parcels_assessed", table_name="parcels", schema=SCHEMA)
    op.drop_index("idx_acquisition_parcels_geom", table_name="parcels", schema=SCHEMA)
    op.drop_table("parcels", schema=SCHEMA)

    funnel_stage = postgresql.ENUM(name="funnel_stage", schema=SCHEMA)
    market_state = postgresql.ENUM(name="market_state", schema=SCHEMA)
    funnel_stage.drop(op.get_bind(), checkfirst=True)
    market_state.drop(op.get_bind(), checkfirst=True)
    op.execute(sa.text(f"DROP SCHEMA IF EXISTS {SCHEMA}"))
