"""add legal_vault_documents table

Revision ID: d4c5e6f7a8b9
Revises: c3b4d5e6f7a8
Create Date: 2026-03-14 06:50:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d4c5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "c3b4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names(schema="legal"))

    if "vault_documents" not in tables:
        op.execute("SET search_path TO legal, public")
        op.create_table(
            "vault_documents",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("case_slug", sa.String(255), nullable=False),
            sa.Column("file_name", sa.String(500), nullable=False),
            sa.Column("nfs_path", sa.Text(), nullable=False),
            sa.Column("mime_type", sa.String(100), nullable=False),
            sa.Column("file_hash", sa.String(128), nullable=False),
            sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("processing_status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("error_detail", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("case_slug", "file_hash", name="uq_vault_case_file_hash"),
            schema="legal",
        )
        op.create_index("ix_vault_documents_case_slug", "vault_documents", ["case_slug"], schema="legal")
        op.create_index("ix_vault_documents_status", "vault_documents", ["processing_status"], schema="legal")


def downgrade() -> None:
    op.drop_index("ix_vault_documents_status", table_name="vault_documents", schema="legal")
    op.drop_index("ix_vault_documents_case_slug", table_name="vault_documents", schema="legal")
    op.drop_table("vault_documents", schema="legal")
