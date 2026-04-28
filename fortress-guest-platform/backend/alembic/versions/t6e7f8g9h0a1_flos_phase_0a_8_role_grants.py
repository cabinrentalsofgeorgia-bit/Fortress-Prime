"""flos phase 0a-8 — grant fortress_api privileges on legal mail intake tables.

Revision ID: t6e7f8g9h0a1
Revises: s4d5e6f7g8h9
Create Date: 2026-04-28

INC-2026-04-28-flos-silent-intake — bugs #4 + #5 durable fix.

The Phase 0a-1 migration created legal.* tables but did not grant write
privileges on them to fortress_api (the role LegacySession + ProdSession
actually use). It also did not extend grants on the pre-existing
public.email_archive table.

Production effect (incident 2026-04-28): even after the UID-watermark fix
landed (Phase 0a-7, PR #271), the ingester silently dropped every message
because fortress_api hit `permission denied for table email_archive` on
every INSERT.

Privileges were granted at runtime via raw psql on 2026-04-28 ~21:30 UTC.
This migration captures those grants in version control so a fresh DB
restore reapplies them automatically.

Apply via raw psql per Issue #204 chain divergence pattern:

    psql -d fortress_db   -f <this-file-as-sql>
    psql -d fortress_prod -f <this-file-as-sql>

Idempotent: GRANT statements re-issued against existing privilege sets
are no-ops in PostgreSQL.

Bilateral mirror discipline (ADR-001): both fortress_db AND fortress_prod
receive this migration.
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "t6e7f8g9h0a1"
down_revision = "s4d5e6f7g8h9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Grant fortress_api the privileges required for legal mail intake.

    Grants:
      - INSERT/UPDATE/DELETE on public.email_archive
        (SELECT was already present; the new grants close the write gap)
      - USAGE/SELECT/UPDATE on public.email_archive_id_seq
        (USAGE+SELECT for nextval()/RETURNING id, UPDATE for setval()
        which the bilateral mirror writer calls to align fortress_prod's
        sequence with the source row's id)
      - USAGE/SELECT/UPDATE on every sequence in schema legal
        (covers legal.event_log_id_seq, legal.mail_ingester_metrics_id_seq,
        and any future sequences added to the schema; UPDATE is required
        because the bilateral mirror writer calls setval() to keep
        fortress_prod's sequences aligned with fortress_db)
      - USAGE/SELECT/UPDATE default privileges on future sequences in legal
        (so subsequent migrations creating new tables with sequences in
        legal.* automatically grant fortress_api access — closes the
        same class of bug for any future Phase work)

    Why UPDATE on sequences: PostgreSQL setval() requires UPDATE
    privilege on the sequence object. Without it the bilateral mirror
    raises "permission denied for sequence ..." on every cycle and the
    INC-2026-04-28 silent-drop pattern returns. The runtime patch
    applied during incident response only granted USAGE+SELECT, which
    was discovered to be insufficient when the worker was restarted.

    Schema-level USAGE on the legal schema is assumed to already exist
    (granted by the Phase 0a-1 migration). If absent, this migration's
    GRANTs against legal.* sequences would fail; surfacing that error
    is preferable to silently re-granting.
    """
    op.execute(
        """
        GRANT INSERT, UPDATE, DELETE ON public.email_archive TO fortress_api;
        """
    )
    op.execute(
        """
        GRANT USAGE, SELECT, UPDATE ON SEQUENCE public.email_archive_id_seq TO fortress_api;
        """
    )
    op.execute(
        """
        GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA legal TO fortress_api;
        """
    )
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA legal
        GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO fortress_api;
        """
    )
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA legal
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fortress_api;
        """
    )


def downgrade() -> None:
    """Revoke the grants this migration adds.

    Note: revoking grants on email_archive will break legal mail intake
    immediately. Only run downgrade if the entire FLOS legal mail
    pipeline is being rolled back.
    """
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA legal
        REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM fortress_api;
        """
    )
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA legal
        REVOKE USAGE, SELECT, UPDATE ON SEQUENCES FROM fortress_api;
        """
    )
    op.execute(
        """
        REVOKE USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA legal FROM fortress_api;
        """
    )
    op.execute(
        """
        REVOKE USAGE, SELECT, UPDATE ON SEQUENCE public.email_archive_id_seq FROM fortress_api;
        """
    )
    op.execute(
        """
        REVOKE INSERT, UPDATE, DELETE ON public.email_archive FROM fortress_api;
        """
    )
