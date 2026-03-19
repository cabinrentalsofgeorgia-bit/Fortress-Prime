"""
Idempotent schema patch for guest_quotes.
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
    load_dotenv()
    engine = build_sync_engine()

    statements = [
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS property_id UUID;",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS status VARCHAR(24);",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS campaign VARCHAR(100);",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS target_keyword VARCHAR(255);",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS guest_name VARCHAR(255);",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS guest_email VARCHAR(255);",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS guest_phone VARCHAR(40);",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS check_in DATE;",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS check_out DATE;",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS nights INTEGER;",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS adults INTEGER;",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS children INTEGER;",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS pets INTEGER;",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS currency VARCHAR(10);",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS base_rent NUMERIC(12,2);",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS taxes NUMERIC(12,2);",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS fees NUMERIC(12,2);",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS total_amount NUMERIC(12,2);",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS quote_breakdown JSONB;",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS source_snapshot JSONB;",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS stripe_payment_link_url VARCHAR(1024);",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS stripe_payment_link_id VARCHAR(255);",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS note TEXT;",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMP;",
        "ALTER TABLE guest_quotes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;",
    ]

    with engine.begin() as conn:
        for stmt in statements:
            print(f"[sql] {stmt}")
            conn.execute(text(stmt))
    print("[ok] guest_quotes schema patched: GuestQuote columns ensured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
