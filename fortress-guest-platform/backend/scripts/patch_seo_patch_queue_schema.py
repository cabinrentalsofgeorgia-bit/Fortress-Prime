"""
Idempotent schema patch and backfill for seo_patch_queue polymorphic targets.
"""
from __future__ import annotations

import os
from typing import Iterable

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


def sync_url_candidates(db_url: str) -> Iterable[str]:
    if not db_url:
        return []
    urls = [db_url]
    if "postgresql+asyncpg://" in db_url:
        urls.append(db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1))
        urls.append(db_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if "postgres://" in db_url:
        urls.append(db_url.replace("postgres://", "postgresql://", 1))

    deduped = []
    seen = set()
    for url in urls:
        if url and url not in seen:
            deduped.append(url)
            seen.add(url)
    return deduped


def build_sync_engine():
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        raise RuntimeError("DATABASE_URL is missing. Set it in .env.")

    last_error = None
    for candidate in sync_url_candidates(db_url):
        try:
            engine = create_engine(candidate, future=True)
            with engine.connect():
                pass
            print(f"[db] connected via: {candidate}")
            return engine
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    raise RuntimeError(f"Unable to connect to Postgres. Last error: {last_error}")


def main() -> int:
    load_dotenv(dotenv_path=".env")
    engine = build_sync_engine()

    statements = [
        "ALTER TABLE seo_patch_queue ADD COLUMN IF NOT EXISTS target_type VARCHAR(32);",
        "ALTER TABLE seo_patch_queue ADD COLUMN IF NOT EXISTS target_slug VARCHAR(255);",
        "ALTER TABLE seo_patch_queue ALTER COLUMN property_id DROP NOT NULL;",
        """
        UPDATE seo_patch_queue AS patch
        SET
            target_type = 'property',
            target_slug = prop.slug
        FROM properties AS prop
        WHERE patch.property_id = prop.id
          AND (
              patch.target_type IS DISTINCT FROM 'property'
              OR patch.target_slug IS DISTINCT FROM prop.slug
          );
        """,
        """
        UPDATE seo_patch_queue
        SET target_type = 'property'
        WHERE target_type IS NULL AND property_id IS NOT NULL;
        """,
        """
        UPDATE seo_patch_queue
        SET target_slug = COALESCE(
            NULLIF(TRIM(fact_snapshot->>'property_slug'), ''),
            NULLIF(TRIM(approved_payload->>'property_slug'), ''),
            NULLIF(TRIM(fact_snapshot->>'slug'), ''),
            NULLIF(TRIM(approved_payload->>'slug'), '')
        )
        WHERE target_slug IS NULL;
        """,
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM seo_patch_queue
                WHERE target_type IS NULL OR target_slug IS NULL
            ) THEN
                RAISE EXCEPTION 'seo_patch_queue has rows with unresolved target_type/target_slug after backfill';
            END IF;
        END $$;
        """,
        "ALTER TABLE seo_patch_queue ALTER COLUMN target_type SET NOT NULL;",
        "ALTER TABLE seo_patch_queue ALTER COLUMN target_slug SET NOT NULL;",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_seo_patch_queue_target_type'
            ) THEN
                ALTER TABLE seo_patch_queue
                ADD CONSTRAINT ck_seo_patch_queue_target_type
                CHECK (target_type IN ('property', 'archive_review'));
            END IF;
        END $$;
        """,
        """
        ALTER TABLE seo_patch_queue
        DROP CONSTRAINT IF EXISTS uq_seo_patch_queue_property_campaign_source;
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_seo_patch_queue_target_campaign_source'
            ) THEN
                ALTER TABLE seo_patch_queue
                ADD CONSTRAINT uq_seo_patch_queue_target_campaign_source
                UNIQUE (target_type, target_slug, campaign, source_hash);
            END IF;
        END $$;
        """,
        "CREATE INDEX IF NOT EXISTS ix_seo_patch_queue_target_type ON seo_patch_queue (target_type);",
        "CREATE INDEX IF NOT EXISTS ix_seo_patch_queue_target_slug ON seo_patch_queue (target_slug);",
        """
        CREATE INDEX IF NOT EXISTS ix_seo_patch_queue_target_approved
        ON seo_patch_queue (target_type, target_slug, approved_at);
        """,
    ]

    with engine.begin() as conn:
        for stmt in statements:
            preview = " ".join(stmt.split())
            print(f"[sql] {preview}")
            conn.execute(text(stmt))

        counts = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total_rows,
                    COUNT(*) FILTER (WHERE target_type = 'property') AS property_rows,
                    COUNT(*) FILTER (WHERE target_type = 'archive_review') AS archive_rows
                FROM seo_patch_queue
                """
            )
        ).mappings().one()

    print(
        "[ok] seo_patch_queue schema patched:"
        f" total={counts['total_rows']}"
        f" property={counts['property_rows']}"
        f" archive={counts['archive_rows']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
