"""
Deadline sweeper for Division 3.

Runs on the sovereign host, inspects legal.deadlines, and emits
`deadline_approaching` events into the live automation queue through the
internal FastAPI route.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

import httpx
from sqlalchemy import text

import run  # noqa: F401 - ensures env/bootstrap side effects
from backend.core.config import settings
from backend.core.database import AsyncSessionLocal

logger = logging.getLogger("deadline_sweeper")


async def sweep_and_emit(days_out: int = 3) -> int:
    target_date = date.today() + timedelta(days=days_out)
    emitted = 0
    api_base = str(settings.internal_api_base_url or "").strip().rstrip("/")
    api_url = f"{api_base}/api/rules/events/emit-deadline"
    token = settings.internal_api_bearer_token
    if not api_base:
        raise RuntimeError("INTERNAL_API_BASE_URL is not configured")
    if not token:
        raise RuntimeError("INTERNAL_API_TOKEN or SWARM_API_KEY is not configured")

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        c.case_number,
                        c.case_slug,
                        COALESCE(c.judge, 'Mary Beth Priest') AS presiding_judge,
                        d.due_date,
                        d.deadline_type,
                        d.description
                    FROM legal.deadlines d
                    JOIN legal.cases c ON c.id = d.case_id
                    WHERE d.due_date = :target_date
                      AND COALESCE(d.status, 'ACTIVE') = 'ACTIVE'
                    ORDER BY d.due_date ASC
                    """
                ),
                {"target_date": target_date},
            )
        ).mappings().all()

    if not rows:
        logger.info("deadline_sweeper_no_matches target_date=%s", target_date.isoformat())
        return 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        for row in rows:
            deadline_type = str(row.get("deadline_type") or row.get("description") or "Responsive Pleading").strip()
            payload = {
                "case_number": row["case_number"],
                "deadline_date": row["due_date"].isoformat(),
                "days_remaining": days_out,
                "deadline_type": deadline_type,
                "description": row.get("description") or deadline_type,
                "presiding_judge": row.get("presiding_judge") or "Mary Beth Priest",
                "jurisdiction": "Appalachian Judicial Circuit",
                "is_hard_stop": True,
            }
            response = await client.post(
                api_url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            emitted += 1
            logger.info(
                "deadline_sweeper_emitted case_number=%s case_slug=%s deadline_type=%s queue_status=%s",
                row["case_number"],
                row["case_slug"],
                deadline_type,
                response.json().get("status"),
            )

    return emitted


def main() -> int:
    count = asyncio.run(sweep_and_emit())
    print(f"emitted_deadline_events={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
