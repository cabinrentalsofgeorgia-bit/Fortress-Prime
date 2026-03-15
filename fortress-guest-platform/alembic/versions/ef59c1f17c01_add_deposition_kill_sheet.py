"""add_deposition_kill_sheet

Revision ID: ef59c1f17c01
Revises: 043cd38e19c8
Create Date: 2026-03-15 13:00:11.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "ef59c1f17c01"
down_revision: Union[str, Sequence[str], None] = "043cd38e19c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("case_statements_v2", schema="legal"):
        op.create_table(
            "case_statements_v2",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("case_slug", sa.String(length=255), nullable=False),
            sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("quote_text", sa.Text(), nullable=False),
            sa.Column("source_ref", sa.Text(), nullable=True),
            sa.Column("doc_id", sa.String(length=255), nullable=True),
            sa.Column("stated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
            sa.PrimaryKeyConstraint("id"),
            schema="legal",
        )

    existing_stmt_indexes = {idx["name"] for idx in inspector.get_indexes("case_statements_v2", schema="legal")}
    if op.f("ix_legal_case_statements_v2_case_slug") not in existing_stmt_indexes:
        op.create_index(op.f("ix_legal_case_statements_v2_case_slug"), "case_statements_v2", ["case_slug"], unique=False, schema="legal")
    if op.f("ix_legal_case_statements_v2_doc_id") not in existing_stmt_indexes:
        op.create_index(op.f("ix_legal_case_statements_v2_doc_id"), "case_statements_v2", ["doc_id"], unique=False, schema="legal")
    if op.f("ix_legal_case_statements_v2_entity_id") not in existing_stmt_indexes:
        op.create_index(op.f("ix_legal_case_statements_v2_entity_id"), "case_statements_v2", ["entity_id"], unique=False, schema="legal")
    if op.f("ix_legal_case_statements_v2_stated_at") not in existing_stmt_indexes:
        op.create_index(op.f("ix_legal_case_statements_v2_stated_at"), "case_statements_v2", ["stated_at"], unique=False, schema="legal")

    if not inspector.has_table("deposition_kill_sheets_v2", schema="legal"):
        op.create_table(
            "deposition_kill_sheets_v2",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("case_slug", sa.String(length=255), nullable=False),
            sa.Column("deponent_entity", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("high_risk_topics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
            sa.Column("document_sequence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
            sa.Column("suggested_questions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
            sa.PrimaryKeyConstraint("id"),
            schema="legal",
        )

    existing_kill_indexes = {idx["name"] for idx in inspector.get_indexes("deposition_kill_sheets_v2", schema="legal")}
    if op.f("ix_legal_deposition_kill_sheets_v2_case_slug") not in existing_kill_indexes:
        op.create_index(op.f("ix_legal_deposition_kill_sheets_v2_case_slug"), "deposition_kill_sheets_v2", ["case_slug"], unique=False, schema="legal")
    if op.f("ix_legal_deposition_kill_sheets_v2_deponent_entity") not in existing_kill_indexes:
        op.create_index(op.f("ix_legal_deposition_kill_sheets_v2_deponent_entity"), "deposition_kill_sheets_v2", ["deponent_entity"], unique=False, schema="legal")
    if op.f("ix_legal_deposition_kill_sheets_v2_status") not in existing_kill_indexes:
        op.create_index(op.f("ix_legal_deposition_kill_sheets_v2_status"), "deposition_kill_sheets_v2", ["status"], unique=False, schema="legal")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("deposition_kill_sheets_v2", schema="legal"):
        existing_kill_indexes = {idx["name"] for idx in inspector.get_indexes("deposition_kill_sheets_v2", schema="legal")}
        if op.f("ix_legal_deposition_kill_sheets_v2_status") in existing_kill_indexes:
            op.drop_index(op.f("ix_legal_deposition_kill_sheets_v2_status"), table_name="deposition_kill_sheets_v2", schema="legal")
        if op.f("ix_legal_deposition_kill_sheets_v2_deponent_entity") in existing_kill_indexes:
            op.drop_index(op.f("ix_legal_deposition_kill_sheets_v2_deponent_entity"), table_name="deposition_kill_sheets_v2", schema="legal")
        if op.f("ix_legal_deposition_kill_sheets_v2_case_slug") in existing_kill_indexes:
            op.drop_index(op.f("ix_legal_deposition_kill_sheets_v2_case_slug"), table_name="deposition_kill_sheets_v2", schema="legal")
        op.drop_table("deposition_kill_sheets_v2", schema="legal")

    if inspector.has_table("case_statements_v2", schema="legal"):
        existing_stmt_indexes = {idx["name"] for idx in inspector.get_indexes("case_statements_v2", schema="legal")}
        if op.f("ix_legal_case_statements_v2_stated_at") in existing_stmt_indexes:
            op.drop_index(op.f("ix_legal_case_statements_v2_stated_at"), table_name="case_statements_v2", schema="legal")
        if op.f("ix_legal_case_statements_v2_entity_id") in existing_stmt_indexes:
            op.drop_index(op.f("ix_legal_case_statements_v2_entity_id"), table_name="case_statements_v2", schema="legal")
        if op.f("ix_legal_case_statements_v2_doc_id") in existing_stmt_indexes:
            op.drop_index(op.f("ix_legal_case_statements_v2_doc_id"), table_name="case_statements_v2", schema="legal")
        if op.f("ix_legal_case_statements_v2_case_slug") in existing_stmt_indexes:
            op.drop_index(op.f("ix_legal_case_statements_v2_case_slug"), table_name="case_statements_v2", schema="legal")
        op.drop_table("case_statements_v2", schema="legal")
