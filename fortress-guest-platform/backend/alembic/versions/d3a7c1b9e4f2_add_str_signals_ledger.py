"""add acquisition str signals ledger

Revision ID: d3a7c1b9e4f2
Revises: b6f0a2c4d8e1
Create Date: 2026-03-30 17:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d3a7c1b9e4f2"
down_revision: Union[str, Sequence[str], None] = "b6f0a2c4d8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "crog_acquisition"


def upgrade() -> None:
    bind = op.get_bind()
    signal_source = postgresql.ENUM(
        "foia_csv",
        "ota_firecrawl_heuristic",
        "aggregator_api",
        name="signal_source",
        schema=SCHEMA,
        create_type=False,
    )
    signal_source.create(bind, checkfirst=True)

    op.create_table(
        "str_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_source", signal_source, nullable=False),
        sa.Column("confidence_score", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint(
            "confidence_score >= 0.00 AND confidence_score <= 1.00",
            name="ck_acquisition_str_signals_confidence_score",
        ),
        sa.ForeignKeyConstraint(["property_id"], [f"{SCHEMA}.properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_acquisition_str_signals_property",
        "str_signals",
        ["property_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "idx_acquisition_str_signals_source",
        "str_signals",
        ["signal_source"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "idx_acquisition_str_signals_detected_at",
        "str_signals",
        ["detected_at"],
        unique=False,
        schema=SCHEMA,
    )
    bind.execute(sa.text(f"GRANT USAGE ON TYPE {SCHEMA}.signal_source TO fortress_api"))
    bind.execute(
        sa.text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {SCHEMA}.str_signals TO fortress_api"
        )
    )
    bind.execute(
        sa.text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fortress_api"
        )
    )


def downgrade() -> None:
    op.drop_index("idx_acquisition_str_signals_detected_at", table_name="str_signals", schema=SCHEMA)
    op.drop_index("idx_acquisition_str_signals_source", table_name="str_signals", schema=SCHEMA)
    op.drop_index("idx_acquisition_str_signals_property", table_name="str_signals", schema=SCHEMA)
    op.drop_table("str_signals", schema=SCHEMA)
    signal_source = postgresql.ENUM(name="signal_source", schema=SCHEMA)
    signal_source.drop(op.get_bind(), checkfirst=True)
