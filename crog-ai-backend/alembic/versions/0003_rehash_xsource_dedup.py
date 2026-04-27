"""rehash market_club_observations for cross-source dedup

Revision ID: 0003_rehash_xsource_dedup
Revises: 0002_crog_ai_core_schema
Create Date: 2026-04-26

Context: Phase 1 (NAS loader) used observation_hash that INCLUDED
source_external_id. That preserves the same alert from NAS + IMAP as
two distinct rows (NAS has meta.id, IMAP has Message-Id — different
external IDs).

Phase 3 (IMAP harvester) needs cross-source dedup so the historical
~16k daily NAS rows don't duplicate when the IMAP harvester pulls the
same alerts from Gmail. We change the hash to exclude source_external_id
and rely on the signal-identity tuple alone.

This migration:
  1. Drops the UNIQUE constraint on observation_hash temporarily
  2. Recomputes observation_hash for every row using the new formula:
       SHA256(ticker | alert_timestamp_utc_iso | triangle_color | timeframe | score)
  3. Removes any duplicates that emerge (shouldn't be any from Phase 1
     since NAS sourced from one corpus, but defensive)
  4. Re-adds the UNIQUE constraint

After this migration: Phase 3 harvester can compute the same hash for
an IMAP-sourced alert that's already in the table from NAS, hit the
ON CONFLICT (observation_hash) DO NOTHING branch, and not insert a
duplicate row.

Idempotent: re-running computes the same hashes, finds them already
correct, no-op.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0003_rehash_xsource_dedup"
down_revision: str | None = "0002_crog_ai_core_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Drop UNIQUE constraint temporarily (Postgres handles this via
    #    the index name auto-generated when we added UNIQUE in migration 0002)
    op.execute(
        """
        ALTER TABLE hedge_fund.market_club_observations
        DROP CONSTRAINT IF EXISTS market_club_observations_observation_hash_key
        """
    )

    # 2. Recompute observation_hash using the new formula.
    #    Postgres encode(digest(...), 'hex') gives us SHA-256 hex.
    #    We need pgcrypto for digest(); migration 0002 already loaded it.
    #
    #    The Python-side formula is:
    #      SHA256("|".join([ticker, ts_iso, color, timeframe, score, ext_id_or_empty]))
    #    But we now drop ext_id_or_empty:
    #      SHA256("|".join([ticker, ts_iso, color, timeframe, score]))
    #
    #    For SQL parity with Python's `dt.isoformat()`, we use to_char with
    #    Postgres's ISO-8601-with-T format and explicit UTC suffix.
    op.execute(
        """
        UPDATE hedge_fund.market_club_observations
        SET observation_hash = encode(
            digest(
                ticker
                || '|' ||
                to_char(alert_timestamp_utc AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS')
                || '+00:00'
                || '|' || triangle_color
                || '|' || timeframe
                || '|' || score::text,
                'sha256'
            ),
            'hex'
        )
        """
    )

    # 3. Defensive de-dup: if any rows now share the same hash (theoretically
    #    impossible given Phase 1 was single-source, but the constraint is
    #    cheap insurance), keep the lowest id and delete the rest.
    op.execute(
        """
        DELETE FROM hedge_fund.market_club_observations a
        USING hedge_fund.market_club_observations b
        WHERE a.observation_hash = b.observation_hash
          AND a.id > b.id
        """
    )

    # 4. Re-add UNIQUE constraint
    op.execute(
        """
        ALTER TABLE hedge_fund.market_club_observations
        ADD CONSTRAINT market_club_observations_observation_hash_key
        UNIQUE (observation_hash)
        """
    )


def downgrade() -> None:
    # Reverse direction: recompute hashes WITH source_external_id appended.
    # Re-running Phase 1 against the same NAS files would re-fix idempotently.
    op.execute(
        """
        ALTER TABLE hedge_fund.market_club_observations
        DROP CONSTRAINT IF EXISTS market_club_observations_observation_hash_key
        """
    )
    op.execute(
        """
        UPDATE hedge_fund.market_club_observations
        SET observation_hash = encode(
            digest(
                ticker
                || '|' ||
                to_char(alert_timestamp_utc AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS')
                || '+00:00'
                || '|' || triangle_color
                || '|' || timeframe
                || '|' || score::text
                || '|' || COALESCE(source_external_id, ''),
                'sha256'
            ),
            'hex'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE hedge_fund.market_club_observations
        ADD CONSTRAINT market_club_observations_observation_hash_key
        UNIQUE (observation_hash)
        """
    )
