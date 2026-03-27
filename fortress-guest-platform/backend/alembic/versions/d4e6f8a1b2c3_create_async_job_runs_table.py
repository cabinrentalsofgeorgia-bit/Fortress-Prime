"""create async job runs table

Revision ID: d4e6f8a1b2c3
Revises: b1c3d5e7f9a1
Create Date: 2026-03-22 00:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d4e6f8a1b2c3"
down_revision: Union[str, None] = "b1c3d5e7f9a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "async_job_runs" in tables:
        return

    op.create_table(
        "async_job_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("job_name", sa.String(length=100), nullable=False),
        sa.Column(
            "queue_name",
            sa.String(length=100),
            nullable=False,
            server_default=sa.text("'fortress:arq'"),
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("arq_job_id", sa.String(length=100), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_async_job_runs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("arq_job_id", name="uq_async_job_runs_arq_job_id"),
    )
    op.create_index("ix_async_job_runs_job_name", "async_job_runs", ["job_name"], unique=False)
    op.create_index("ix_async_job_runs_queue_name", "async_job_runs", ["queue_name"], unique=False)
    op.create_index("ix_async_job_runs_status", "async_job_runs", ["status"], unique=False)
    op.create_index("ix_async_job_runs_requested_by", "async_job_runs", ["requested_by"], unique=False)
    op.create_index("ix_async_job_runs_tenant_id", "async_job_runs", ["tenant_id"], unique=False)
    op.create_index("ix_async_job_runs_request_id", "async_job_runs", ["request_id"], unique=False)
    op.create_index("ix_async_job_runs_arq_job_id", "async_job_runs", ["arq_job_id"], unique=False)
    op.create_index(
        "ix_async_job_runs_job_status_created",
        "async_job_runs",
        ["job_name", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_async_job_runs_status_created",
        "async_job_runs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_async_job_runs_requested_by_created",
        "async_job_runs",
        ["requested_by", "created_at"],
        unique=False,
    )
    bind.execute(
        sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE async_job_runs TO fortress_api")
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "async_job_runs" not in tables:
        return

    op.drop_index("ix_async_job_runs_requested_by_created", table_name="async_job_runs")
    op.drop_index("ix_async_job_runs_status_created", table_name="async_job_runs")
    op.drop_index("ix_async_job_runs_job_status_created", table_name="async_job_runs")
    op.drop_index("ix_async_job_runs_arq_job_id", table_name="async_job_runs")
    op.drop_index("ix_async_job_runs_request_id", table_name="async_job_runs")
    op.drop_index("ix_async_job_runs_tenant_id", table_name="async_job_runs")
    op.drop_index("ix_async_job_runs_requested_by", table_name="async_job_runs")
    op.drop_index("ix_async_job_runs_status", table_name="async_job_runs")
    op.drop_index("ix_async_job_runs_queue_name", table_name="async_job_runs")
    op.drop_index("ix_async_job_runs_job_name", table_name="async_job_runs")
    op.drop_table("async_job_runs")
