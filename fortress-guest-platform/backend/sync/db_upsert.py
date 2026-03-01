"""
SynapseDB — Database UPSERT engine for the Streamline Data Synapse.

Property and reservation upserts delegate to the production sync_all() engine
in backend.integrations.streamline_vrs (Phase 1 and Phase 2 respectively).

Calendar/blocked-day upserts use direct ON CONFLICT SQL against the
blocked_days table introduced in this ETL layer.
"""
from __future__ import annotations

from typing import Any, Dict, List
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(service="synapse_db")


class SynapseDB:
    """Idempotent UPSERT engine — all writes use ON CONFLICT DO UPDATE."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def upsert_blocked_day(
        self,
        property_id: UUID,
        start_date: Any,
        end_date: Any,
        block_type: str = "reservation",
        confirmation_code: str | None = None,
    ) -> bool:
        """
        Upsert a single calendar block into the blocked_days table.

        Uses ON CONFLICT (property_id, start_date, end_date, block_type) DO UPDATE
        to ensure idempotency.
        """
        try:
            await self._db.execute(
                text("""
                    INSERT INTO blocked_days
                        (id, property_id, start_date, end_date, block_type,
                         confirmation_code, source, created_at, updated_at)
                    VALUES
                        (gen_random_uuid(), :pid, :sd, :ed, :bt, :cc,
                         'streamline', NOW(), NOW())
                    ON CONFLICT (property_id, start_date, end_date, block_type)
                    DO UPDATE SET
                        confirmation_code = EXCLUDED.confirmation_code,
                        updated_at = NOW()
                """),
                {
                    "pid": str(property_id),
                    "sd": start_date,
                    "ed": end_date,
                    "bt": block_type[:50],
                    "cc": str(confirmation_code)[:50] if confirmation_code else None,
                },
            )
            return True
        except Exception as e:
            logger.error("upsert_blocked_day_failed", error=str(e))
            return False

    async def upsert_calendar(
        self,
        property_id: UUID,
        blocks: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        """Upsert a batch of calendar blocks for a single property."""
        inserted = 0
        errors = 0
        for b in blocks:
            if not b.get("start_date") or not b.get("end_date"):
                continue
            block_type = (b.get("type_name") or "reservation").lower().replace(" ", "_")
            ok = await self.upsert_blocked_day(
                property_id=property_id,
                start_date=b["start_date"],
                end_date=b["end_date"],
                block_type=block_type,
                confirmation_code=b.get("confirmation_id"),
            )
            if ok:
                inserted += 1
            else:
                errors += 1
        await self._db.commit()
        logger.info("calendar_upserted", property_id=str(property_id), inserted=inserted, errors=errors)
        return {"inserted": inserted, "errors": errors}

    async def upsert_properties(self, db_session: AsyncSession) -> Dict[str, Any]:
        """
        Delegate to the production sync engine (Phase 1).

        The real upsert logic lives in StreamlineVRS.sync_all() which handles
        SELECT-then-UPDATE/INSERT for all 14 properties with detail enrichment
        and rate card sync.
        """
        from backend.integrations.streamline_vrs import StreamlineVRS
        vrs = StreamlineVRS()
        summary = await vrs.sync_all(db_session)
        return summary.get("properties", {})

    async def upsert_reservations(self, db_session: AsyncSession) -> Dict[str, Any]:
        """
        Delegate to the production sync engine (Phase 2).

        The real upsert logic lives in StreamlineVRS.sync_all() which handles
        2,650+ reservations with guest extraction and batch commits.
        """
        from backend.integrations.streamline_vrs import StreamlineVRS
        vrs = StreamlineVRS()
        summary = await vrs.sync_all(db_session)
        return summary.get("reservations", {})
