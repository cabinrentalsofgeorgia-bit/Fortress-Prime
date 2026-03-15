"""Add legal phase 2 — hive_mind_feedback_events table and
seed jurisdiction rules for Delaware and Fannin County.
Tables case_statements, sanctions_alerts, jurisdiction_rules
already exist (hand-created); this migration only adds what is missing.

Revision ID: g1a2b3c4d5e6
Revises: f1e2d3c4b5a6
Create Date: 2026-03-14
"""
from alembic import op
import sqlalchemy as sa

revision = "g1a2b3c4d5e6"
down_revision = "f1e2d3c4b5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS legal"))

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS legal.hive_mind_feedback_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pack_id UUID NOT NULL REFERENCES legal.discovery_draft_packs(id) ON DELETE CASCADE,
            feedback_type VARCHAR(32) NOT NULL,
            original_content TEXT,
            revised_content TEXT,
            quality_score FLOAT,
            metadata JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_hive_feedback_pack_id "
        "ON legal.hive_mind_feedback_events (pack_id)"
    ))

    # Ensure indexes exist on pre-existing tables
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_case_statements_case_slug "
        "ON legal.case_statements (case_slug)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_sanctions_alerts_case_slug "
        "ON legal.sanctions_alerts (case_slug)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_jurisdiction_rules_court_name "
        "ON legal.jurisdiction_rules (court_name)"
    ))

    # Seed jurisdiction rules (idempotent)
    existing = conn.execute(
        sa.text("SELECT count(*) FROM legal.jurisdiction_rules")
    ).scalar()

    if existing == 0:
        conn.execute(sa.text("""
            INSERT INTO legal.jurisdiction_rules
                (court_name, rule_type, limit_value, source_ref)
            VALUES
                ('USBC District of Delaware', 'interrogatory_cap', 25,
                 'Fed. R. Civ. P. 33(a)(1)'),
                ('USBC District of Delaware', 'rfp_cap', 30,
                 'Fed. R. Civ. P. 34 (no fixed cap; 30 is local convention)'),
                ('USBC District of Delaware', 'admission_cap', 25,
                 'Fed. R. Civ. P. 36 (no fixed cap; 25 proportionality default)'),
                ('Fannin County Superior Court, GA', 'interrogatory_cap', 50,
                 'O.C.G.A. 9-11-33 (50 including sub-parts)')
        """))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS legal.hive_mind_feedback_events")
    op.execute("DELETE FROM legal.jurisdiction_rules")
