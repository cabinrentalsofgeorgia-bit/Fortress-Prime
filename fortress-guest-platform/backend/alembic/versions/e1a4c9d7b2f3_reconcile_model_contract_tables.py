"""reconcile model contract tables

Revision ID: e1a4c9d7b2f3
Revises: c2b7d9e4a1f0
Create Date: 2026-03-22 01:35:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.schema import CheckConstraint, PrimaryKeyConstraint, UniqueConstraint

from backend.core.database import Base
import backend.models  # noqa: F401


# revision identifiers, used by Alembic.
revision: str = "e1a4c9d7b2f3"
down_revision: Union[str, None] = "c2b7d9e4a1f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ensure_schemas(bind: sa.engine.Connection) -> None:
    schemas = sorted({table.schema for table in Base.metadata.sorted_tables if table.schema})
    for schema_name in schemas:
        bind.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))


def _clone_column(column: sa.Column) -> sa.Column:
    server_default = None
    if column.server_default is not None:
        server_default = column.server_default.arg

    return sa.Column(
        column.name,
        column.type,
        primary_key=column.primary_key,
        nullable=column.nullable,
        server_default=server_default,
    )


def _create_table_without_foreign_keys(
    bind: sa.engine.Connection,
    source_table: sa.Table,
) -> None:
    metadata = sa.MetaData()
    cloned_columns = [_clone_column(column) for column in source_table.columns]
    cloned_table = sa.Table(source_table.name, metadata, *cloned_columns, schema=source_table.schema)

    for constraint in source_table.constraints:
        if isinstance(constraint, PrimaryKeyConstraint):
            continue
        if isinstance(constraint, UniqueConstraint):
            cloned_table.append_constraint(
                UniqueConstraint(
                    *[cloned_table.c[column.name] for column in constraint.columns],
                    name=constraint.name,
                )
            )
        elif isinstance(constraint, CheckConstraint):
            cloned_table.append_constraint(
                CheckConstraint(str(constraint.sqltext), name=constraint.name)
            )

    cloned_table.create(bind=bind, checkfirst=True)

    for index in source_table.indexes:
        cloned_index = sa.Index(
            index.name,
            *[cloned_table.c[column.name] for column in index.columns],
            unique=index.unique,
        )
        cloned_index.create(bind=bind, checkfirst=True)


def _reconcile_missing_tables(bind: sa.engine.Connection) -> None:
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    existing_schema_tables = {
        f"{schema}.{name}"
        for schema in inspector.get_schema_names()
        if schema not in {"information_schema", "pg_catalog"}
        for name in inspector.get_table_names(schema=schema)
    }

    for table in Base.metadata.sorted_tables:
        qualified_name = f"{table.schema}.{table.name}" if table.schema else table.name
        if qualified_name in existing_tables or qualified_name in existing_schema_tables:
            continue
        _create_table_without_foreign_keys(bind, table)


def _column(name: str) -> sa.Column:
    table = Base.metadata.tables["agent_response_queue"]
    source = table.c[name]
    server_default = source.server_default.arg if source.server_default is not None else None
    return sa.Column(
        source.name,
        source.type,
        nullable=True,
        server_default=server_default,
    )


def _reconcile_agent_response_queue(bind: sa.engine.Connection) -> None:
    inspector = sa.inspect(bind)
    if "agent_response_queue" not in set(inspector.get_table_names()):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("agent_response_queue")}
    for column_name in [
        "message_id",
        "guest_id",
        "sentiment_label",
        "sentiment_score",
        "proposed_response",
        "confidence",
        "action",
        "final_response",
        "sent_message_id",
        "decision_metadata",
    ]:
        if column_name not in existing_columns:
            op.add_column("agent_response_queue", _column(column_name))

    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_agent_response_queue_message_id "
            "ON agent_response_queue (message_id)"
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_agent_response_queue_guest_id "
            "ON agent_response_queue (guest_id)"
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    _ensure_schemas(bind)
    _reconcile_missing_tables(bind)
    _reconcile_agent_response_queue(bind)


def downgrade() -> None:
    pass
