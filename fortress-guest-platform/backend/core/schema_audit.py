"""
Pre-Flight Schema Audit — Validates that the database schema matches
the SQLAlchemy model contract at startup.

If a mapped column is missing from the physical table, the API logs a
CRITICAL error and raises, preventing a half-broken site from serving
requests that would crash on the first ORM query.
"""

from __future__ import annotations

import structlog
from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger()

CRITICAL_TABLES = {
    "properties": [
        "id", "name", "slug", "county", "city_limits", "is_active",
        "streamline_property_id", "rate_card", "bedrooms", "bathrooms",
    ],
    "reservations": [
        "id", "confirmation_code", "property_id", "guest_id",
        "check_in_date", "check_out_date", "status", "total_amount",
    ],
}


async def run_schema_audit(engine: AsyncEngine) -> None:
    """Compare physical DB columns against expected model columns.

    Raises RuntimeError if critical columns are missing, preventing
    the API from starting in a broken state.
    """
    missing: list[str] = []

    async with engine.connect() as conn:
        for table, expected_cols in CRITICAL_TABLES.items():
            result = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = :tbl"
                ),
                {"tbl": table},
            )
            actual_cols = {row[0] for row in result.fetchall()}

            if not actual_cols:
                logger.warning("schema_audit_table_missing", table=table)
                continue

            for col in expected_cols:
                if col not in actual_cols:
                    missing.append(f"{table}.{col}")
                    logger.critical(
                        "schema_audit_column_missing",
                        table=table,
                        column=col,
                        hint="Run the Alembic migration or manually ALTER TABLE",
                    )

    if missing:
        msg = (
            f"SCHEMA AUDIT FAILED — {len(missing)} column(s) missing from the "
            f"database: {', '.join(missing)}. Run `alembic upgrade head` or apply "
            f"the migration manually before starting the API."
        )
        logger.critical("schema_audit_fatal", missing=missing)
        raise RuntimeError(msg)

    logger.info("schema_audit_passed", tables_checked=len(CRITICAL_TABLES))
