"""add_sanctions_tripwire

Revision ID: 043cd38e19c8
Revises: a48313599051
Create Date: 2026-03-15 12:49:58.666847
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "043cd38e19c8"
down_revision: Union[str, Sequence[str], None] = "a48313599051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_exists = inspector.has_table("sanctions_alerts_v2", schema="legal")

    if not table_exists:
        op.create_table(
            "sanctions_alerts_v2",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("case_slug", sa.String(length=255), nullable=False),
            sa.Column("alert_type", sa.String(length=32), nullable=False),
            sa.Column("contradiction_summary", sa.Text(), nullable=False),
            sa.Column("confidence_score", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
            sa.PrimaryKeyConstraint("id"),
            schema="legal",
        )
    else:
        existing_columns = {col["name"] for col in inspector.get_columns("sanctions_alerts_v2", schema="legal")}
        if "confidence_score" not in existing_columns:
            op.add_column(
                "sanctions_alerts_v2",
                sa.Column("confidence_score", sa.Integer(), nullable=False, server_default="50"),
                schema="legal",
            )
        if "status" in existing_columns:
            op.execute("UPDATE legal.sanctions_alerts_v2 SET status = 'DRAFT' WHERE status IS NULL")

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("sanctions_alerts_v2", schema="legal")}
    if op.f("ix_legal_sanctions_alerts_v2_alert_type") not in existing_indexes:
        op.create_index(op.f("ix_legal_sanctions_alerts_v2_alert_type"), "sanctions_alerts_v2", ["alert_type"], unique=False, schema="legal")
    if op.f("ix_legal_sanctions_alerts_v2_case_slug") not in existing_indexes:
        op.create_index(op.f("ix_legal_sanctions_alerts_v2_case_slug"), "sanctions_alerts_v2", ["case_slug"], unique=False, schema="legal")
    if op.f("ix_legal_sanctions_alerts_v2_confidence_score") not in existing_indexes:
        op.create_index(op.f("ix_legal_sanctions_alerts_v2_confidence_score"), "sanctions_alerts_v2", ["confidence_score"], unique=False, schema="legal")
    if op.f("ix_legal_sanctions_alerts_v2_status") not in existing_indexes:
        op.create_index(op.f("ix_legal_sanctions_alerts_v2_status"), "sanctions_alerts_v2", ["status"], unique=False, schema="legal")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("sanctions_alerts_v2", schema="legal"):
        return
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("sanctions_alerts_v2", schema="legal")}
    if op.f("ix_legal_sanctions_alerts_v2_status") in existing_indexes:
        op.drop_index(op.f("ix_legal_sanctions_alerts_v2_status"), table_name="sanctions_alerts_v2", schema="legal")
    if op.f("ix_legal_sanctions_alerts_v2_confidence_score") in existing_indexes:
        op.drop_index(op.f("ix_legal_sanctions_alerts_v2_confidence_score"), table_name="sanctions_alerts_v2", schema="legal")
    if op.f("ix_legal_sanctions_alerts_v2_case_slug") in existing_indexes:
        op.drop_index(op.f("ix_legal_sanctions_alerts_v2_case_slug"), table_name="sanctions_alerts_v2", schema="legal")
    if op.f("ix_legal_sanctions_alerts_v2_alert_type") in existing_indexes:
        op.drop_index(op.f("ix_legal_sanctions_alerts_v2_alert_type"), table_name="sanctions_alerts_v2", schema="legal")
    op.drop_table("sanctions_alerts_v2", schema="legal")
