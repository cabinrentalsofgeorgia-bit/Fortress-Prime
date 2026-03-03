"""add_vrs_rule_engine_and_automation_events

Revision ID: 342e9a59b9cf
Create Date: 2026-02-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "342e9a59b9cf"
down_revision = "1b9f9997297d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "vrs_automations" not in existing_tables:
        op.create_table(
            "vrs_automations",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False, index=True),
            sa.Column("target_entity", sa.String(50), nullable=False, index=True),
            sa.Column("trigger_event", sa.String(50), nullable=False, index=True),
            sa.Column("conditions", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("action_type", sa.String(50), nullable=False),
            sa.Column("action_payload", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
            sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        )

    if "vrs_automation_events" not in existing_tables:
        op.create_table(
            "vrs_automation_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "rule_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("vrs_automations.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("entity_type", sa.String(50), nullable=False, index=True),
            sa.Column("entity_id", sa.String(100), nullable=False, index=True),
            sa.Column("event_type", sa.String(50), nullable=False, index=True),
            sa.Column("previous_state", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("current_state", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("action_result", sa.String(20), nullable=True),
            sa.Column("error_detail", sa.Text(), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("vrs_automation_events")
    op.drop_table("vrs_automations")
