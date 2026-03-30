"""expand guest ledger compatibility fields

Revision ID: 5e7c1a9d4b2f
Revises: a9d4c2f7b1e8
Create Date: 2026-03-26 21:20:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "5e7c1a9d4b2f"
down_revision: Union[str, Sequence[str], None] = "a9d4c2f7b1e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    if column.name not in existing:
        op.add_column(table_name, column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    if column_name in existing:
        op.drop_column(table_name, column_name)


def _create_index_if_missing(name: str, table_name: str, columns: list[str], **kwargs) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns, **kwargs)


def _drop_index_if_exists(name: str, table_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if name in existing:
        op.drop_index(name, table_name=table_name)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "guests" not in inspector.get_table_names():
        return

    _add_column_if_missing("guests", sa.Column("phone_number_secondary", sa.String(length=20), nullable=True))
    _add_column_if_missing("guests", sa.Column("email_secondary", sa.String(length=255), nullable=True))
    _add_column_if_missing("guests", sa.Column("address_line1", sa.String(length=255), nullable=True))
    _add_column_if_missing("guests", sa.Column("address_line2", sa.String(length=255), nullable=True))
    _add_column_if_missing("guests", sa.Column("city", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("state", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("postal_code", sa.String(length=20), nullable=True))
    _add_column_if_missing("guests", sa.Column("country", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("date_of_birth", sa.Date(), nullable=True))
    _add_column_if_missing("guests", sa.Column("language_preference", sa.String(length=16), nullable=True))
    _add_column_if_missing("guests", sa.Column("preferred_contact_method", sa.String(length=32), nullable=True))
    _add_column_if_missing("guests", sa.Column("opt_in_marketing", sa.Boolean(), nullable=True))
    _add_column_if_missing("guests", sa.Column("opt_in_sms", sa.Boolean(), nullable=True))
    _add_column_if_missing("guests", sa.Column("opt_in_email", sa.Boolean(), nullable=True))
    _add_column_if_missing("guests", sa.Column("quiet_hours_start", sa.String(length=16), nullable=True))
    _add_column_if_missing("guests", sa.Column("quiet_hours_end", sa.String(length=16), nullable=True))
    _add_column_if_missing("guests", sa.Column("timezone", sa.String(length=64), nullable=True))
    _add_column_if_missing("guests", sa.Column("emergency_contact_name", sa.String(length=255), nullable=True))
    _add_column_if_missing("guests", sa.Column("emergency_contact_phone", sa.String(length=20), nullable=True))
    _add_column_if_missing("guests", sa.Column("emergency_contact_relationship", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("vehicle_make", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("vehicle_model", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("vehicle_color", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("vehicle_plate", sa.String(length=32), nullable=True))
    _add_column_if_missing("guests", sa.Column("vehicle_state", sa.String(length=32), nullable=True))
    _add_column_if_missing("guests", sa.Column("special_requests", sa.Text(), nullable=True))
    _add_column_if_missing("guests", sa.Column("internal_notes", sa.Text(), nullable=True))
    _add_column_if_missing("guests", sa.Column("staff_notes", sa.Text(), nullable=True))
    _add_column_if_missing("guests", sa.Column("preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    _add_column_if_missing("guests", sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=True))
    _add_column_if_missing("guests", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing("guests", sa.Column("verification_method", sa.String(length=64), nullable=True))
    _add_column_if_missing(
        "guests",
        sa.Column("loyalty_points", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    _add_column_if_missing("guests", sa.Column("loyalty_enrolled_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(
        "guests",
        sa.Column("lifetime_stays", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    _add_column_if_missing(
        "guests",
        sa.Column("total_stays", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    _add_column_if_missing(
        "guests",
        sa.Column("lifetime_nights", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    _add_column_if_missing(
        "guests",
        sa.Column("lifetime_revenue", sa.Numeric(precision=12, scale=2), nullable=False, server_default=sa.text("0")),
    )
    _add_column_if_missing("guests", sa.Column("average_rating", sa.Numeric(precision=4, scale=2), nullable=True))
    _add_column_if_missing("guests", sa.Column("last_stay_date", sa.Date(), nullable=True))
    _add_column_if_missing("guests", sa.Column("value_score", sa.Integer(), nullable=True))
    _add_column_if_missing("guests", sa.Column("risk_score", sa.Integer(), nullable=True))
    _add_column_if_missing("guests", sa.Column("satisfaction_score", sa.Integer(), nullable=True))
    _add_column_if_missing(
        "guests",
        sa.Column("is_vip", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    _add_column_if_missing(
        "guests",
        sa.Column("is_blacklisted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    _add_column_if_missing("guests", sa.Column("blacklist_reason", sa.Text(), nullable=True))
    _add_column_if_missing("guests", sa.Column("blacklisted_by", sa.String(length=255), nullable=True))
    _add_column_if_missing("guests", sa.Column("blacklisted_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(
        "guests",
        sa.Column("requires_supervision", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    _add_column_if_missing(
        "guests",
        sa.Column("is_do_not_contact", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    _add_column_if_missing("guests", sa.Column("guest_source", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("first_booking_source", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("referral_source", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("acquisition_campaign", sa.String(length=255), nullable=True))
    _add_column_if_missing("guests", sa.Column("streamline_guest_id", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("airbnb_guest_id", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("vrbo_guest_id", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("booking_com_guest_id", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("stripe_customer_id", sa.String(length=100), nullable=True))
    _add_column_if_missing("guests", sa.Column("notes", sa.Text(), nullable=True))

    _create_index_if_missing("ix_guests_city", "guests", ["city"], unique=False)
    _create_index_if_missing("ix_guests_state", "guests", ["state"], unique=False)
    _create_index_if_missing("ix_guests_last_stay_date", "guests", ["last_stay_date"], unique=False)
    _create_index_if_missing("ix_guests_value_score", "guests", ["value_score"], unique=False)
    _create_index_if_missing("ix_guests_risk_score", "guests", ["risk_score"], unique=False)
    _create_index_if_missing("ix_guests_is_vip", "guests", ["is_vip"], unique=False)
    _create_index_if_missing("ix_guests_is_blacklisted", "guests", ["is_blacklisted"], unique=False)
    _create_index_if_missing("ix_guests_guest_source", "guests", ["guest_source"], unique=False)
    _create_index_if_missing("ix_guests_streamline_guest_id", "guests", ["streamline_guest_id"], unique=False)
    _create_index_if_missing("ix_guests_tags_gin", "guests", ["tags"], unique=False, postgresql_using="gin")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "guests" not in inspector.get_table_names():
        return

    _drop_index_if_exists("ix_guests_tags_gin", "guests")
    _drop_index_if_exists("ix_guests_streamline_guest_id", "guests")
    _drop_index_if_exists("ix_guests_guest_source", "guests")
    _drop_index_if_exists("ix_guests_is_blacklisted", "guests")
    _drop_index_if_exists("ix_guests_is_vip", "guests")
    _drop_index_if_exists("ix_guests_risk_score", "guests")
    _drop_index_if_exists("ix_guests_value_score", "guests")
    _drop_index_if_exists("ix_guests_last_stay_date", "guests")
    _drop_index_if_exists("ix_guests_state", "guests")
    _drop_index_if_exists("ix_guests_city", "guests")

    for column_name in [
        "notes",
        "stripe_customer_id",
        "booking_com_guest_id",
        "vrbo_guest_id",
        "airbnb_guest_id",
        "streamline_guest_id",
        "acquisition_campaign",
        "referral_source",
        "first_booking_source",
        "guest_source",
        "is_do_not_contact",
        "requires_supervision",
        "blacklisted_at",
        "blacklisted_by",
        "blacklist_reason",
        "is_blacklisted",
        "is_vip",
        "satisfaction_score",
        "risk_score",
        "value_score",
        "last_stay_date",
        "average_rating",
        "lifetime_revenue",
        "lifetime_nights",
        "total_stays",
        "lifetime_stays",
        "loyalty_enrolled_at",
        "loyalty_points",
        "verification_method",
        "verified_at",
        "tags",
        "preferences",
        "staff_notes",
        "internal_notes",
        "special_requests",
        "vehicle_state",
        "vehicle_plate",
        "vehicle_color",
        "vehicle_model",
        "vehicle_make",
        "emergency_contact_relationship",
        "emergency_contact_phone",
        "emergency_contact_name",
        "timezone",
        "quiet_hours_end",
        "quiet_hours_start",
        "opt_in_email",
        "opt_in_sms",
        "opt_in_marketing",
        "preferred_contact_method",
        "language_preference",
        "date_of_birth",
        "country",
        "postal_code",
        "state",
        "city",
        "address_line2",
        "address_line1",
        "email_secondary",
        "phone_number_secondary",
    ]:
        _drop_column_if_exists("guests", column_name)
