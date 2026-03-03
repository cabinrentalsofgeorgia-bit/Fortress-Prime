"""add_message_queue_and_template_approval

Revision ID: 1b9f9997297d
Revises: a19206a9919e
Create Date: 2026-02-24 13:09:02.207666

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import inspect as sa_inspect

revision: str = '1b9f9997297d'
down_revision: Union[str, Sequence[str], None] = 'a19206a9919e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)

    existing_tables = inspector.get_table_names()
    existing_cols = {
        c["name"]
        for c in inspector.get_columns("email_templates")
    } if "email_templates" in existing_tables else set()

    if "requires_human_approval" not in existing_cols:
        op.add_column(
            "email_templates",
            sa.Column(
                "requires_human_approval",
                sa.Boolean(),
                nullable=False,
                server_default="true",
            ),
        )

    if "message_queue" not in existing_tables:
        op.create_table(
            "message_queue",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("quote_id", UUID(as_uuid=True), sa.ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("email_templates.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="drafted", index=True),
            sa.Column("rendered_subject", sa.String(1000), nullable=False, server_default=""),
            sa.Column("rendered_body", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()")),
            sa.UniqueConstraint("quote_id", "template_id", name="uq_message_queue_quote_template"),
        )


def downgrade() -> None:
    op.drop_table("message_queue")
    op.drop_column("email_templates", "requires_human_approval")
