"""reconcile schema privileges and legal evidence

Revision ID: f3d6a1b8c9e2
Revises: e1a4c9d7b2f3
Create Date: 2026-03-22 01:50:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f3d6a1b8c9e2"
down_revision: Union[str, None] = "e1a4c9d7b2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RUNTIME_ROLE = "fortress_api"
ADMIN_ROLE = "fortress_admin"
SCHEMAS = ("legal", "iot_schema", "verses_schema")


def _grant_schema_privileges(bind: sa.engine.Connection) -> None:
    for schema_name in SCHEMAS:
        bind.execute(sa.text(f'GRANT USAGE ON SCHEMA "{schema_name}" TO {RUNTIME_ROLE}'))
        bind.execute(
            sa.text(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema_name}" TO {RUNTIME_ROLE}'
            )
        )
        bind.execute(
            sa.text(
                f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{schema_name}" TO {RUNTIME_ROLE}'
            )
        )
        bind.execute(
            sa.text(
                f'ALTER DEFAULT PRIVILEGES FOR ROLE {ADMIN_ROLE} IN SCHEMA "{schema_name}" '
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {RUNTIME_ROLE}'
            )
        )
        bind.execute(
            sa.text(
                f'ALTER DEFAULT PRIVILEGES FOR ROLE {ADMIN_ROLE} IN SCHEMA "{schema_name}" '
                f'GRANT USAGE, SELECT ON SEQUENCES TO {RUNTIME_ROLE}'
            )
        )


def _reconcile_legal_case_evidence() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("case_evidence", schema="legal"):
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("case_evidence", schema="legal")
    }

    additions: list[tuple[str, sa.Column]] = [
        ("case_slug", sa.Column("case_slug", sa.String(length=255), nullable=True)),
        ("entity_id", sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True)),
        ("file_name", sa.Column("file_name", sa.String(length=500), nullable=True)),
        ("nas_path", sa.Column("nas_path", sa.Text(), nullable=True)),
        ("qdrant_point_id", sa.Column("qdrant_point_id", sa.String(length=255), nullable=True)),
        ("sha256_hash", sa.Column("sha256_hash", sa.String(length=128), nullable=True)),
        ("uploaded_at", sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True)),
    ]

    for column_name, column in additions:
        if column_name not in existing_columns:
            op.add_column("case_evidence", column, schema="legal")

    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_legal_case_evidence_case_slug "
            "ON legal.case_evidence (case_slug)"
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_legal_case_evidence_entity_id "
            "ON legal.case_evidence (entity_id)"
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_legal_case_evidence_qdrant_point_id "
            "ON legal.case_evidence (qdrant_point_id)"
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_legal_case_evidence_sha256_hash "
            "ON legal.case_evidence (sha256_hash)"
        )
    )


def upgrade() -> None:
    _reconcile_legal_case_evidence()
    _grant_schema_privileges(op.get_bind())


def downgrade() -> None:
    pass
