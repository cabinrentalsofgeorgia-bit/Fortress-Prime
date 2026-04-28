"""flos phase 0a-7 — add last_seen_uid watermark to mail_ingester_state.

Revision ID: s4d5e6f7g8h9
Revises: r3c4d5e6f7g8
Create Date: 2026-04-28

INC-2026-04-28-flos-silent-intake — root cause fix.

Adds last_seen_uid column to legal.mail_ingester_state so the ingester
can shift IMAP SEARCH from UNSEEN SINCE <date> (which silently misses
messages read by webmail/Captain/operator before patrol) to
UID <last+1>:* SINCE <date>.

The UNSEEN-based design assumed the legal mailbox would be ingester-
exclusive. In production, anything that reads marks \\Seen, hiding the
message from the ingester forever. Result: 38-day silent intake gap
(2026-03-21 -> 2026-04-28) and zero rows in legal.event_log.

Companion code change in legal_mail_ingester.py replaces UNSEEN with
UID-watermark logic.

Apply via raw psql per Issue #204:
  psql -d fortress_db   -c "ALTER TABLE legal.mail_ingester_state ADD COLUMN IF NOT EXISTS last_seen_uid TEXT NULL;"
  psql -d fortress_prod -c "ALTER TABLE legal.mail_ingester_state ADD COLUMN IF NOT EXISTS last_seen_uid TEXT NULL;"

Bilateral mirror discipline (ADR-001): both DBs receive this migration.
"""

from __future__ import annotations

from alembic import op


revision = "s4d5e6f7g8h9"
down_revision = "r3c4d5e6f7g8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE legal.mail_ingester_state
        ADD COLUMN IF NOT EXISTS last_seen_uid TEXT NULL;
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN legal.mail_ingester_state.last_seen_uid IS
        'Highest IMAP UID ingested per mailbox. NULL = no watermark (bootstrap on next patrol). Drives SEARCH UID <last+1>:* without relying on \\Seen flag.';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE legal.mail_ingester_state
        DROP COLUMN IF EXISTS last_seen_uid;
        """
    )
