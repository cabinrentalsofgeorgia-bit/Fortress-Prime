"""Create email pipeline tables: email_inquirers and email_messages.

Parallel email-channel tables that mirror the SMS guests/messages architecture.
Email inquirers may not yet have a phone-bearing Guest row; the existing SMS
tables are untouched.

Revision ID: l7e8f1a2b3c4
Revises: c255801e28a0, i23a1_add_payment_credit_codes
Create Date: 2026-04-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "l7e8f1a2b3c4"
down_revision = ("c255801e28a0", "i23a1_add_payment_credit_codes")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_inquirers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255)),
        sa.Column("first_name", sa.String(100)),
        sa.Column("last_name", sa.String(100)),
        sa.Column("guest_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("inferred_party_size", sa.Integer()),
        sa.Column("inferred_dates_text", sa.Text()),
        sa.Column(
            "opt_in_email",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "first_seen_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "inquiry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.UniqueConstraint("email", name="uq_email_inquirers_email"),
        sa.ForeignKeyConstraint(["guest_id"], ["guests.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_email_inquirers_guest_id", "email_inquirers", ["guest_id"])

    op.create_table(
        "email_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("inquirer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guest_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("in_reply_to_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("email_from", sa.String(255), nullable=False),
        sa.Column("email_to", sa.String(255), nullable=False),
        sa.Column("email_cc", sa.Text()),
        sa.Column("subject", sa.Text()),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_excerpt", sa.Text()),
        sa.Column("imap_uid", sa.BigInteger()),
        sa.Column("imap_message_id", sa.Text()),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("intent", sa.String(50)),
        sa.Column("sentiment", sa.String(20)),
        sa.Column("category", sa.String(50)),
        sa.Column("ai_draft", sa.Text()),
        sa.Column("ai_confidence", sa.Numeric(4, 3)),
        sa.Column("ai_meta", postgresql.JSONB()),
        sa.Column(
            "approval_status",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'pending_approval'"),
        ),
        sa.Column(
            "requires_human_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("human_reviewed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("human_reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("human_edited_body", sa.Text()),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("smtp_message_id", sa.Text()),
        sa.Column("error_code", sa.String(50)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("extra_data", postgresql.JSONB()),
        sa.CheckConstraint(
            "direction IN ('inbound', 'outbound')",
            name="ck_email_messages_direction",
        ),
        sa.CheckConstraint(
            "approval_status IN ('pending_approval', 'approved', 'rejected', "
            "'sent', 'send_failed', 'no_draft_needed')",
            name="ck_email_messages_approval_status",
        ),
        sa.ForeignKeyConstraint(
            ["inquirer_id"], ["email_inquirers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["guest_id"], ["guests.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["reservations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["human_reviewed_by"], ["staff_users.id"], ondelete="SET NULL"
        ),
    )
    # Self-referential FK must be added after table exists
    op.create_foreign_key(
        "fk_email_messages_reply_to",
        "email_messages",
        "email_messages",
        ["in_reply_to_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Partial unique on imap_uid (only when set)
    op.execute(sa.text(
        "CREATE UNIQUE INDEX idx_email_messages_imap_uid "
        "ON email_messages (imap_uid) WHERE imap_uid IS NOT NULL"
    ))
    op.execute(sa.text(
        "CREATE INDEX idx_email_messages_inquirer "
        "ON email_messages (inquirer_id, received_at DESC)"
    ))
    op.execute(sa.text(
        "CREATE INDEX idx_email_messages_status "
        "ON email_messages (approval_status, received_at DESC)"
    ))
    op.create_index(
        "idx_email_messages_thread", "email_messages", ["in_reply_to_message_id"]
    )

    # Grant runtime user access to new tables
    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE ON email_inquirers TO fortress_api"))
    op.execute(sa.text("GRANT SELECT, INSERT, UPDATE ON email_messages TO fortress_api"))


def downgrade() -> None:
    op.execute(sa.text("REVOKE ALL ON email_messages FROM fortress_api"))
    op.execute(sa.text("REVOKE ALL ON email_inquirers FROM fortress_api"))
    op.drop_table("email_messages")
    op.drop_table("email_inquirers")
