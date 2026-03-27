#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import logging
import sys

from sqlalchemy import func, select

from backend.core.database import AsyncSessionLocal, close_db
from backend.models.functional_node import FunctionalNode

MIRRORED_CONTENT_CATEGORIES = ("area_guide", "blog_article")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("DeconstructionAudit")


async def audit_finality() -> None:
    """
    STRIKE 14 FINALITY AUDIT
    Verifies the cutover state of the 415-node mirrored legacy corpus and
    surfaces any nodes still leaking to the Drupal origin.
    """

    async with AsyncSessionLocal() as db:
        distribution_stmt = (
            select(FunctionalNode.cutover_status, func.count(FunctionalNode.canonical_path))
            .where(FunctionalNode.content_category.in_(MIRRORED_CONTENT_CATEGORIES))
            .group_by(FunctionalNode.cutover_status)
            .order_by(FunctionalNode.cutover_status.asc())
        )
        results = (await db.execute(distribution_stmt)).all()

        total_nodes = sum(int(count) for _, count in results)

        print("\n--- SOVEREIGN DECONSTRUCTION: FINALITY REPORT ---")
        for status_value, count in results:
            status_str = str(status_value or "")
            icon = "✅" if status_str == "sovereign" else "🟡"
            print(f"{icon} Status: {status_str:15} | Count: {count}")

        print("-------------------------------------------------")
        print(f"Total Mirrored Corpus Nodes in Ledger: {total_nodes}")

        leak_stmt = (
            select(FunctionalNode.canonical_path)
            .where(
                FunctionalNode.content_category.in_(MIRRORED_CONTENT_CATEGORIES),
                FunctionalNode.cutover_status == "legacy",
            )
            .order_by(FunctionalNode.canonical_path.asc())
            .limit(15)
        )
        leaks = (await db.execute(leak_stmt)).scalars().all()

        if leaks:
            print(f"\n⚠️ WARNING: {len(leaks)} mirrored nodes are still in 'legacy' state.")
            print("These paths are bypassing the Sovereign Bridge and hitting Drupal.")
            for path in leaks:
                print(f"  - {path}")
        else:
            print("\n🏁 FINALITY ACHIEVED: 100% Edge Intercept Coverage.")
        print("-------------------------------------------------\n")


async def amain() -> int:
    try:
        await audit_finality()
        return 0
    finally:
        await close_db()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
