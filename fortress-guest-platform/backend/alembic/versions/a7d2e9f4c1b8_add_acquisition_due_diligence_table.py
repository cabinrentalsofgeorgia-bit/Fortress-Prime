"""add_acquisition_due_diligence_table

Revision ID: a7d2e9f4c1b8
Revises: f3a91b8c2e47
Create Date: 2026-04-13 19:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d2e9f4c1b8'
down_revision: Union[str, Sequence[str], None] = 'f3a91b8c2e47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Default checklist items (seeded for every new pipeline entry)
# item_key, label, display_order
# ---------------------------------------------------------------------------
DEFAULT_CHECKLIST = [
    ("title_search",                 "Title Search & Lien Check",               1),
    ("property_inspection",          "Physical Property Inspection",             2),
    ("revenue_history",              "Revenue History Review (2+ Years)",        3),
    ("hoa_review",                   "HOA Documents Review",                     4),
    ("tax_records",                  "Tax Records & Assessment Verification",    5),
    ("zoning",                       "Zoning & Land-Use Compliance",             6),
    ("competitor_rates",             "Competitive Rate & Occupancy Analysis",    7),
    ("owner_motivation",             "Owner Motivation Interview",               8),
    ("str_license_verification",     "STR License Verification (Fannin/Gilmer)", 9),
    ("hoa_str_policy_review",        "HOA STR Policy Review",                   10),
    ("comparable_revenue_streamline","Comparable Revenue from Streamline",      11),
]


def upgrade() -> None:
    # 1. Create due_diligence table in crog_acquisition schema
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS crog_acquisition.due_diligence (
            id              UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
            pipeline_id     UUID         NOT NULL
                REFERENCES crog_acquisition.acquisition_pipeline(id) ON DELETE CASCADE,
            item_key        VARCHAR(80)  NOT NULL,
            label           VARCHAR(255) NOT NULL,
            display_order   INTEGER      NOT NULL DEFAULT 0,
            status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
            notes           TEXT,
            completed_at    TIMESTAMPTZ,
            completed_by    VARCHAR(255),
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT uq_dd_pipeline_item UNIQUE (pipeline_id, item_key),
            CONSTRAINT chk_dd_status CHECK (status IN ('pending','passed','failed','waived'))
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_dd_pipeline_id "
        "ON crog_acquisition.due_diligence (pipeline_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_dd_status "
        "ON crog_acquisition.due_diligence (status)"
    ))
    op.execute(sa.text(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON crog_acquisition.due_diligence TO fortress_api"
    ))

    # 2. Seed default checklist items for any existing pipeline entries
    for item_key, label, order in DEFAULT_CHECKLIST:
        op.execute(sa.text(f"""
            INSERT INTO crog_acquisition.due_diligence
                (pipeline_id, item_key, label, display_order, status)
            SELECT id, '{item_key}', '{label}', {order}, 'pending'
            FROM crog_acquisition.acquisition_pipeline
            ON CONFLICT (pipeline_id, item_key) DO NOTHING
        """))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS crog_acquisition.due_diligence"))
