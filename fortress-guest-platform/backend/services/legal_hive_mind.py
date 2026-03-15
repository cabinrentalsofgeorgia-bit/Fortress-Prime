"""
Legal Hive Mind — approved exemplar retrieval and prompt injection
for discovery draft quality improvement.

Queries previously-approved discovery items as style exemplars so the
Swarm mirrors proven phrasing and specificity patterns.
"""
from __future__ import annotations

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.legal_discovery import DiscoveryDraftItem, DiscoveryDraftPack

logger = structlog.get_logger()

MAX_EXEMPLARS = 5


async def get_approved_exemplars(
    db: AsyncSession,
    pack_type: str,
    max_items: int = MAX_EXEMPLARS,
) -> list[str]:
    """Return top-N approved discovery items of the given pack_type,
    ordered by relevance_score descending, for use as style exemplars."""
    result = await db.execute(
        select(DiscoveryDraftItem.content)
        .join(DiscoveryDraftPack, DiscoveryDraftPack.id == DiscoveryDraftItem.pack_id)
        .where(
            and_(
                DiscoveryDraftPack.pack_type == pack_type,
                DiscoveryDraftPack.status.in_(["approved", "counsel_review"]),
            )
        )
        .order_by(DiscoveryDraftItem.relevance_score.desc())
        .limit(max_items)
    )
    rows = result.scalars().all()
    logger.info(
        "hive_mind_exemplars_fetched",
        pack_type=pack_type,
        count=len(rows),
    )
    return list(rows)


def inject_exemplars_into_prompt(
    exemplars: list[str],
    base_prompt: str,
) -> str:
    """Prepend approved exemplars as style precedents to the system prompt."""
    if not exemplars:
        return base_prompt

    block = "\n".join(f"  {i+1}. {ex}" for i, ex in enumerate(exemplars))
    return (
        f"{base_prompt}\n\n"
        f"APPROVED PRECEDENT STYLE (mirror this specificity and structure):\n"
        f"{block}\n\n"
        f"Generate new items that match the quality and format above."
    )
