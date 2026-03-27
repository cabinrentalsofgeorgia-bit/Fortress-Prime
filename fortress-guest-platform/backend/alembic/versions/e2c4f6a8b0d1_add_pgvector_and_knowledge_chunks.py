"""add pgvector and knowledge chunks

Revision ID: e2c4f6a8b0d1
Revises: c9d1e4f7a2b5
Create Date: 2026-03-22 13:05:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2c4f6a8b0d1"
down_revision: Union[str, None] = "c9d1e4f7a2b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VECTOR_DIMENSION = 768
TABLE_NAME = "property_knowledge_chunks"


def _table_names(bind: sa.Connection) -> set[str]:
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)

    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    if TABLE_NAME not in tables:
        bind.execute(
            sa.text(
                f"""
                CREATE TABLE {TABLE_NAME} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    embedding vector({VECTOR_DIMENSION}) NOT NULL,
                    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
                )
                """
            )
        )

    bind.execute(
        sa.text(
            f"CREATE INDEX IF NOT EXISTS ix_{TABLE_NAME}_property_id ON {TABLE_NAME} (property_id)"
        )
    )
    bind.execute(
        sa.text(
            f"""
            CREATE INDEX IF NOT EXISTS ix_{TABLE_NAME}_embedding_cosine
            ON {TABLE_NAME}
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
            """
        )
    )
    bind.execute(
        sa.text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {TABLE_NAME} TO fortress_api"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)
    if TABLE_NAME not in tables:
        return

    bind.execute(sa.text(f"DROP TABLE IF EXISTS {TABLE_NAME}"))
