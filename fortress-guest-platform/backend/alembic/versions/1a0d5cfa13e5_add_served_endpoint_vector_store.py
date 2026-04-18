"""add v5 tagging schema to capture tables

Revision ID: 1a0d5cfa13e5
Revises: 633f8f8bc383
Create Date: 2026-04-18

Phase 3 retag (Iron Dome v5). Full tagging schema for the Godhead/Sovereign/Judge
architecture. All columns nullable so existing rows are unaffected. NULL in any field
means "captured before this schema existed" — intentional, distinguishes pre-retag
from post-retag captures (R6 mitigation).

Schema (9 columns on each table):
  served_by_endpoint  — actual inference endpoint that produced the response
  served_vector_store — vector store queried (Phase 5a RAG)
  escalated_from      — sovereign endpoint if this was an escalated (Godhead) capture
  sovereign_attempt   — sovereign model's response text before escalation
  teacher_endpoint    — Godhead endpoint URL
  teacher_model       — Godhead model name (e.g. deepseek-r1:70b, claude-sonnet)
  task_type           — task classification (legal, reasoning, vrs, concierge, etc.)
  judge_decision      — external judge verdict: confident | uncertain | escalate
  judge_reasoning     — judge's reasoning for the escalation decision

Indexes added for analytics queries: task_type, teacher_model, judge_decision.
"""
from alembic import op
import sqlalchemy as sa

revision = "1a0d5cfa13e5"
down_revision = "633f8f8bc383"
branch_labels = None
depends_on = None

_NEW_COLS = [
    ("served_by_endpoint",  sa.String(256)),
    ("served_vector_store", sa.String(64)),
    ("escalated_from",      sa.String(256)),
    ("sovereign_attempt",   sa.Text()),
    ("teacher_endpoint",    sa.String(256)),
    ("teacher_model",       sa.String(128)),
    ("task_type",           sa.String(64)),
    ("judge_decision",      sa.String(16)),
    ("judge_reasoning",     sa.Text()),
]

_INDEXED_COLS = ["served_by_endpoint", "task_type", "teacher_model", "judge_decision"]


def upgrade() -> None:
    for table in ("llm_training_captures", "restricted_captures"):
        prefix = "llm_tc" if table == "llm_training_captures" else "rc"
        for col_name, col_type in _NEW_COLS:
            op.add_column(table, sa.Column(col_name, col_type, nullable=True))
        for col_name in _INDEXED_COLS:
            op.create_index(f"idx_{prefix}_{col_name}", table, [col_name])


def downgrade() -> None:
    for table in ("llm_training_captures", "restricted_captures"):
        prefix = "llm_tc" if table == "llm_training_captures" else "rc"
        for col_name in reversed(_INDEXED_COLS):
            op.drop_index(f"idx_{prefix}_{col_name}", table_name=table)
        for col_name, _ in reversed(_NEW_COLS):
            op.drop_column(table, col_name)
