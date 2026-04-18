"""add capture_labels table + QC views

Revision ID: c255801e28a0
Revises: 1a0d5cfa13e5
Create Date: 2026-04-18

Phase 4e.1 — Labeling infrastructure. capture_labels holds Godhead judgments
and Gary QC decisions for every labeled capture. Two DB views expose the QC
queue and daily budget stats for psql-based QC workflow.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c255801e28a0"
down_revision = "1a0d5cfa13e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capture_labels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),

        # Source capture reference (no FK — captures live in two tables)
        sa.Column("capture_id",    postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capture_table", sa.String(32),  nullable=False),
        sa.Column("task_type",     sa.String(64),  nullable=False),

        # Godhead judgment
        sa.Column("godhead_model",     sa.String(128)),
        sa.Column("godhead_decision",  sa.String(16)),    # confident|uncertain|escalate|skip
        sa.Column("godhead_reasoning", sa.Text()),
        sa.Column("godhead_called_at", sa.DateTime(timezone=True)),
        sa.Column("godhead_cost_usd",  sa.Numeric(8, 4)),

        # QC sampling and Gary decision
        sa.Column("qc_sampled",     sa.Boolean, nullable=False, server_default="false"),
        sa.Column("qc_decision",    sa.String(16)),   # confirm|override_confident|…
        sa.Column("qc_note",        sa.Text()),
        sa.Column("qc_reviewed_at", sa.DateTime(timezone=True)),

        # Final resolved label
        sa.Column("final_decision", sa.String(16)),   # godhead or gary's override
        sa.Column("label_source",   sa.String(16)),   # godhead|gary_qc

        sa.UniqueConstraint("capture_id", "capture_table", name="uq_capture_labels_capture"),
    )

    op.create_index("idx_cl_capture_id",     "capture_labels", ["capture_id"])
    op.create_index("idx_cl_task_type",      "capture_labels", ["task_type"])
    op.create_index("idx_cl_created_at",     "capture_labels", ["created_at"])
    op.create_index("idx_cl_godhead_decision","capture_labels", ["godhead_decision"])
    # Partial index for QC queue — only sampled-but-not-reviewed rows
    op.execute("""
        CREATE INDEX idx_cl_qc_queue
        ON capture_labels (created_at DESC)
        WHERE qc_sampled = TRUE AND qc_reviewed_at IS NULL
    """)

    # View: QC queue
    op.execute("""
        CREATE VIEW v_qc_queue AS
        SELECT
            cl.id,
            cl.created_at,
            cl.task_type,
            cl.capture_table,
            cl.godhead_model,
            cl.godhead_decision,
            cl.godhead_reasoning,
            cl.godhead_cost_usd,
            COALESCE(
                (SELECT tc.user_prompt  FROM llm_training_captures tc WHERE tc.id = cl.capture_id),
                (SELECT rc.prompt       FROM restricted_captures   rc WHERE rc.id = cl.capture_id)
            ) AS user_prompt,
            COALESCE(
                (SELECT tc.assistant_resp FROM llm_training_captures tc WHERE tc.id = cl.capture_id),
                (SELECT rc.response       FROM restricted_captures   rc WHERE rc.id = cl.capture_id)
            ) AS assistant_resp,
            COALESCE(
                (SELECT tc.source_module FROM llm_training_captures tc WHERE tc.id = cl.capture_id),
                (SELECT rc.source_module FROM restricted_captures   rc WHERE rc.id = cl.capture_id)
            ) AS source_module
        FROM capture_labels cl
        WHERE cl.qc_sampled = TRUE AND cl.qc_reviewed_at IS NULL
        ORDER BY cl.created_at DESC
    """)

    # View: daily labeling stats
    op.execute("""
        CREATE VIEW v_labeling_stats AS
        SELECT
            DATE(created_at AT TIME ZONE 'America/New_York') AS label_date,
            task_type,
            COUNT(*)                                          AS total_labeled,
            COUNT(*) FILTER (WHERE godhead_decision='confident')  AS confident_count,
            COUNT(*) FILTER (WHERE godhead_decision='uncertain')  AS uncertain_count,
            COUNT(*) FILTER (WHERE godhead_decision='escalate')   AS escalate_count,
            COUNT(*) FILTER (WHERE godhead_decision='skip')       AS skip_count,
            COALESCE(SUM(godhead_cost_usd), 0)                AS total_cost_usd,
            COUNT(*) FILTER (WHERE qc_sampled = TRUE)         AS qc_sampled_count,
            COUNT(*) FILTER (WHERE qc_reviewed_at IS NOT NULL)AS qc_reviewed_count
        FROM capture_labels
        GROUP BY 1, 2
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_labeling_stats")
    op.execute("DROP VIEW IF EXISTS v_qc_queue")
    op.drop_index("idx_cl_qc_queue",       table_name="capture_labels")
    op.drop_index("idx_cl_godhead_decision",table_name="capture_labels")
    op.drop_index("idx_cl_created_at",     table_name="capture_labels")
    op.drop_index("idx_cl_task_type",      table_name="capture_labels")
    op.drop_index("idx_cl_capture_id",     table_name="capture_labels")
    op.drop_table("capture_labels")
