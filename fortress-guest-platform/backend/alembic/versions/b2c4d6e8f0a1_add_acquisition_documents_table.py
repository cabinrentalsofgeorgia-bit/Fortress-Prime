"""add_acquisition_documents_table

Revision ID: b2c4d6e8f0a1
Revises: a7d2e9f4c1b8
Create Date: 2026-04-14 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c4d6e8f0a1'
down_revision: Union[str, Sequence[str], None] = 'a7d2e9f4c1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS crog_acquisition.acquisition_documents (
            id              UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
            pipeline_id     UUID         NOT NULL
                REFERENCES crog_acquisition.acquisition_pipeline(id) ON DELETE CASCADE,
            file_name       VARCHAR(255) NOT NULL,
            nfs_path        TEXT         NOT NULL,
            mime_type       VARCHAR(100) NOT NULL DEFAULT 'application/octet-stream',
            file_hash       VARCHAR(64),
            file_size_bytes INTEGER,
            doc_type        VARCHAR(50)  NOT NULL DEFAULT 'general',
            uploaded_by     VARCHAR(255),
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_acq_docs_pipeline_id "
        "ON crog_acquisition.acquisition_documents (pipeline_id)"
    ))
    op.execute(sa.text(
        "GRANT SELECT, INSERT, DELETE "
        "ON crog_acquisition.acquisition_documents TO fortress_api"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS crog_acquisition.acquisition_documents"))
