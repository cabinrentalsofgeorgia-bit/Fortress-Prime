"""create seo patch tables

Revision ID: 26118e0ba71f
Revises: 1d9f2e7a6c41
Create Date: 2026-03-20 13:27:58.081580

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '26118e0ba71f'
down_revision: Union[str, None] = '1d9f2e7a6c41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('seo_rubrics',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('keyword_cluster', sa.String(), nullable=False),
        sa.Column('rubric_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('source_model', sa.String(), nullable=False),
        sa.Column('min_pass_score', sa.Float(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('seo_patches',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('property_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('rubric_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('page_path', sa.String(), nullable=False),
        sa.Column('patch_version', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=70), nullable=True),
        sa.Column('meta_description', sa.String(length=320), nullable=True),
        sa.Column('og_title', sa.String(length=95), nullable=True),
        sa.Column('og_description', sa.String(length=200), nullable=True),
        sa.Column('jsonld_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('canonical_url', sa.String(), nullable=True),
        sa.Column('h1_suggestion', sa.String(), nullable=True),
        sa.Column('alt_tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('godhead_score', sa.Float(), nullable=True),
        sa.Column('godhead_model', sa.String(), nullable=True),
        sa.Column('godhead_feedback', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('grade_attempts', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('reviewed_by', sa.String(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('final_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('deployed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('swarm_model', sa.String(), nullable=True),
        sa.Column('swarm_node', sa.String(), nullable=True),
        sa.Column('generation_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['rubric_id'], ['seo_rubrics.id'], ondelete='SET NULL'),
        # FK to properties.id intentionally deferred: this SEO branch runs before the
        # main migration chain creates `properties` on a fresh DB. The constraint is
        # already present on production (migration applied when properties existed).
        # A follow-up migration can add the FK once the branch ordering is resolved.
        sa.PrimaryKeyConstraint('id')
    )

    op.create_index('ix_seo_patches_deployed_at', 'seo_patches', ['deployed_at'], unique=False)
    op.create_index('ix_seo_patches_page_path', 'seo_patches', ['page_path'], unique=False)
    op.create_index('ix_seo_patches_property_id', 'seo_patches', ['property_id'], unique=False)
    op.create_index('ix_seo_patches_status', 'seo_patches', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_seo_patches_status', table_name='seo_patches')
    op.drop_index('ix_seo_patches_property_id', table_name='seo_patches')
    op.drop_index('ix_seo_patches_page_path', table_name='seo_patches')
    op.drop_index('ix_seo_patches_deployed_at', table_name='seo_patches')
    op.drop_table('seo_patches')
    op.drop_table('seo_rubrics')
