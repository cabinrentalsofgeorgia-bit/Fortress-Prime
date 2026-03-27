"""reconcile reservation ledger columns

Revision ID: f6a8b0c2d4e5
Revises: e5f7a9c1d3b4
Create Date: 2026-03-22 01:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f6a8b0c2d4e5"
down_revision: Union[str, None] = "e5f7a9c1d3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "reservations" not in tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("reservations")}

    def add_column(name: str, column: sa.Column) -> None:
        if name not in existing_columns:
            op.add_column("reservations", column)
            existing_columns.add(name)

    add_column("special_requests", sa.Column("special_requests", sa.Text(), nullable=True))
    add_column("paid_amount", sa.Column("paid_amount", sa.DECIMAL(10, 2), nullable=True))
    add_column("balance_due", sa.Column("balance_due", sa.DECIMAL(10, 2), nullable=True))
    add_column("nightly_rate", sa.Column("nightly_rate", sa.DECIMAL(10, 2), nullable=True))
    add_column("cleaning_fee", sa.Column("cleaning_fee", sa.DECIMAL(10, 2), nullable=True))
    add_column("pet_fee", sa.Column("pet_fee", sa.DECIMAL(10, 2), nullable=True))
    add_column("damage_waiver_fee", sa.Column("damage_waiver_fee", sa.DECIMAL(10, 2), nullable=True))
    add_column("service_fee", sa.Column("service_fee", sa.DECIMAL(10, 2), nullable=True))
    add_column("tax_amount", sa.Column("tax_amount", sa.DECIMAL(10, 2), nullable=True))
    add_column("nights_count", sa.Column("nights_count", sa.Integer(), nullable=True))
    add_column(
        "digital_guide_sent",
        sa.Column("digital_guide_sent", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )
    add_column(
        "pre_arrival_sent",
        sa.Column("pre_arrival_sent", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )
    add_column(
        "access_info_sent",
        sa.Column("access_info_sent", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )
    add_column(
        "mid_stay_checkin_sent",
        sa.Column("mid_stay_checkin_sent", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )
    add_column(
        "checkout_reminder_sent",
        sa.Column("checkout_reminder_sent", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )
    add_column(
        "post_stay_followup_sent",
        sa.Column("post_stay_followup_sent", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )
    add_column("guest_rating", sa.Column("guest_rating", sa.Integer(), nullable=True))
    add_column("guest_feedback", sa.Column("guest_feedback", sa.Text(), nullable=True))
    add_column(
        "streamline_notes",
        sa.Column("streamline_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    add_column(
        "streamline_financial_detail",
        sa.Column("streamline_financial_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    add_column("qdrant_point_id", sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True), nullable=True))
    add_column(
        "security_deposit_required",
        sa.Column(
            "security_deposit_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    add_column(
        "security_deposit_amount",
        sa.Column(
            "security_deposit_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("500.00"),
        ),
    )
    add_column(
        "security_deposit_status",
        sa.Column(
            "security_deposit_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'none'"),
        ),
    )
    add_column(
        "security_deposit_stripe_pi",
        sa.Column("security_deposit_stripe_pi", sa.String(length=255), nullable=True),
    )
    add_column(
        "security_deposit_updated_at",
        sa.Column("security_deposit_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "reservations" not in tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("reservations")}
    for name in [
        "security_deposit_updated_at",
        "security_deposit_stripe_pi",
        "security_deposit_status",
        "security_deposit_amount",
        "security_deposit_required",
        "qdrant_point_id",
        "streamline_financial_detail",
        "streamline_notes",
        "guest_feedback",
        "guest_rating",
        "post_stay_followup_sent",
        "checkout_reminder_sent",
        "mid_stay_checkin_sent",
        "access_info_sent",
        "pre_arrival_sent",
        "digital_guide_sent",
        "nights_count",
        "tax_amount",
        "service_fee",
        "damage_waiver_fee",
        "pet_fee",
        "cleaning_fee",
        "nightly_rate",
        "balance_due",
        "paid_amount",
        "special_requests",
    ]:
        if name in existing_columns:
            op.drop_column("reservations", name)
