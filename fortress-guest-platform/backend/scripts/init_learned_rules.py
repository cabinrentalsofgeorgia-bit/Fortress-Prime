#!/usr/bin/env python3
"""
Godhead Memory Ledger DB Initializer
Creates the learned_rules table if it doesn't already exist.
Safe to re-run — uses CREATE TABLE IF NOT EXISTS.
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from backend.core.database import get_async_engine
from backend.models.learned_rule import LearnedRule  # noqa: F401


DDL = """
CREATE TABLE IF NOT EXISTS learned_rules (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id         UUID,
    rule_name           VARCHAR(255) NOT NULL,
    trigger_condition   JSONB NOT NULL,
    adjustment_type     VARCHAR(20) NOT NULL,
    adjustment_value    DOUBLE PRECISION NOT NULL,
    confidence_score    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    status              VARCHAR(30) NOT NULL DEFAULT 'pending_approval',
    created_at          TIMESTAMP NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_learned_rules_property_id
    ON learned_rules (property_id);
CREATE INDEX IF NOT EXISTS ix_learned_rules_status
    ON learned_rules (status);
"""


async def main() -> None:
    engine = get_async_engine()
    async with engine.begin() as conn:
        existing = await conn.execute(
            text("SELECT to_regclass('public.learned_rules')")
        )
        already_exists = existing.scalar() is not None

        await conn.execute(text(DDL))

        if already_exists:
            print("[Godhead Memory Ledger] Table already existed — no-op.")
        else:
            print("[Godhead Memory Ledger] Table created successfully.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
