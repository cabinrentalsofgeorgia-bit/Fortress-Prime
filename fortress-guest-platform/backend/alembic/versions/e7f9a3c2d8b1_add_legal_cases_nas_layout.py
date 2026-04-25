"""Add nas_layout JSONB column to legal.cases.

Revision ID: e7f9a3c2d8b1
Revises: d4e5f6a7b8c9
Create Date: 2026-04-25

Per-case override of the canonical NAS folder layout used by the
/cases/{slug}/files and /cases/{slug}/download/{filename} endpoints.

NULL (default) preserves existing behaviour: walk
/mnt/fortress_nas/sectors/legal/{slug} with the canonical
six-subdir tree (certified_mail, correspondence, evidence, receipts,
filings/incoming, filings/outgoing).

When populated, the JSON has shape:

    {
      "root": "/absolute/nas/path",
      "subdirs": {
        "filings_incoming": "relative/path/to/pleadings",
        "filings_outgoing": "relative/path/to/outgoing",
        "correspondence":   "relative/path/to/correspondence",
        "evidence":         "relative/path/to/evidence",
        "certified_mail":   "relative/path/to/certmail",
        "receipts":         "relative/path/to/receipts"
      },
      "recursive": false
    }

Idempotent — uses ADD COLUMN IF NOT EXISTS so applying via raw psql
to a sibling database does not break a later `alembic upgrade head`.
"""
from __future__ import annotations

from alembic import op


revision = "e7f9a3c2d8b1"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


_COLUMN_COMMENT = (
    "Per-case NAS folder layout override. NULL = use default "
    "/mnt/fortress_nas/sectors/legal/{slug}/{6-subdir} convention. "
    "JSON shape: {root, subdirs:{filings_incoming, filings_outgoing, "
    "correspondence, evidence, certified_mail, receipts}, "
    "recursive: bool}."
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE legal.cases "
        "ADD COLUMN IF NOT EXISTS nas_layout JSONB DEFAULT NULL"
    )
    op.execute(
        f"COMMENT ON COLUMN legal.cases.nas_layout IS $${_COLUMN_COMMENT}$$"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE legal.cases DROP COLUMN IF EXISTS nas_layout")
