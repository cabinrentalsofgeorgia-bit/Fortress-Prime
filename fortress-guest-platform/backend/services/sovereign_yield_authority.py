"""
Strike 18 — Sovereign Yield Authority: blackouts and stay-shape rules (local ledger).

Validates booking feasibility using ``property_stay_restrictions`` before quotes complete.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import and_, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.property_stay_restriction import PropertyStayRestriction

logger = structlog.get_logger()


def _missing_runtime_table(exc: ProgrammingError) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return "does not exist" in message or "undefinedtable" in message


class SovereignYieldAuthority:
    """Local authority for yield saturation: blackouts and check-in/out weekday rules."""

    @staticmethod
    async def validate_stay_constraints(
        db_session: AsyncSession,
        property_id: UUID,
        check_in: date,
        check_out: date,
    ) -> list[str]:
        """
        Validate check-in/out weekdays and blackout windows overlapping the stay.

        Stay occupies ``[check_in, check_out)`` (checkout morning exclusive of last night).
        Overlap with a restriction window uses the same rule as ``blocked_days``:
        ``restriction.start_date < check_out AND restriction.end_date > check_in``.

        Returns violation strings; empty means clear to proceed on this axis.
        """
        violations: list[str] = []
        stmt = (
            select(PropertyStayRestriction)
            .where(
                and_(
                    PropertyStayRestriction.property_id == property_id,
                    PropertyStayRestriction.start_date < check_out,
                    PropertyStayRestriction.end_date > check_in,
                )
            )
            .order_by(PropertyStayRestriction.start_date.asc())
        )
        try:
            result = await db_session.execute(stmt)
            restrictions: list[Any] = list(result.scalars().all())
        except ProgrammingError as exc:
            if not _missing_runtime_table(exc):
                raise
            logger.warning("sovereign_yield_restrictions_table_missing")
            await db_session.rollback()
            return []

        for res in restrictions:
            if res.is_blackout:
                violations.append("Selected dates overlap with a blackout period.")

            if res.must_check_in_on_day is not None:
                required = int(res.must_check_in_on_day)
                if check_in.weekday() != required:
                    name = res.must_check_in_day_name or f"weekday {required}"
                    violations.append(f"Check-in must be on a {name}.")

            if res.must_check_out_on_day is not None:
                required = int(res.must_check_out_on_day)
                if check_out.weekday() != required:
                    name = res.must_check_out_day_name or f"weekday {required}"
                    violations.append(f"Check-out must be on a {name}.")

        return list(dict.fromkeys(violations))
