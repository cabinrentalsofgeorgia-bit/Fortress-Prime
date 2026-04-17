#!/usr/bin/env python3
"""
Shadow Ledger DB Initializer
Creates the shadow_discrepancies table if it doesn't already exist.
Safe to re-run — uses CREATE TABLE IF NOT EXISTS.
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from backend.core.database import get_async_engine
from backend.models.shadow_discrepancy import ShadowDiscrepancy  # noqa: F401


DDL = """
CREATE TABLE IF NOT EXISTS shadow_discrepancies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    "timestamp"     TIMESTAMP NOT NULL DEFAULT now(),
    property_id     UUID NOT NULL,
    legacy_total_cents  INTEGER NOT NULL,
    dgx_total_cents     INTEGER NOT NULL,
    delta_cents         INTEGER NOT NULL,
    legacy_payload  JSONB,
    dgx_payload     JSONB,
    hermes_diagnosis TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
);

CREATE INDEX IF NOT EXISTS ix_shadow_discrepancies_property_id
    ON shadow_discrepancies (property_id);
CREATE INDEX IF NOT EXISTS ix_shadow_discrepancies_status
    ON shadow_discrepancies (status);
"""


async def main() -> None:
    engine = get_async_engine()
    async with engine.begin() as conn:
        existing = await conn.execute(
            text(
                "SELECT to_regclass('public.shadow_discrepancies')"
            )
        )
        already_exists = existing.scalar() is not None

        await conn.execute(text(DDL))

        if already_exists:
            print("[Shadow Ledger] Table already existed — no-op.")
        else:
            print("[Shadow Ledger] Table created successfully.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
