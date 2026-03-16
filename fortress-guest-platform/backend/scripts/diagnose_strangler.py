#!/usr/bin/env python3
"""
STRANGLER FIG DIAGNOSTIC PROBE
================================
Verifies the full Streamline -> PostgreSQL -> Qdrant -> AI Retrieval pipeline.

Layer 1: Hard Ledger     — PostgreSQL record counts and sync evidence
Layer 2: Vector Brain    — Qdrant fgp_knowledge breakdown by source_table
Layer 3: AI Neural Link  — Live semantic search proving the AI can read the data

Run:
  cd ~/Fortress-Prime/fortress-guest-platform
  ./venv/bin/python -m backend.scripts.diagnose_strangler
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
from sqlalchemy import select, func
from backend.core.config import settings
from backend.core.database import AsyncSessionLocal

BOLD = "\033[1m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
RESET = "\033[0m"


def banner():
    print(f"""
{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════════╗
║        STRANGLER FIG DIAGNOSTIC PROBE                           ║
║        Streamline → PostgreSQL → Qdrant → AI Retrieval          ║
╚══════════════════════════════════════════════════════════════════╝{RESET}
""")


def section(name: str):
    print(f"\n{BOLD}{'─' * 64}")
    print(f"  {name}")
    print(f"{'─' * 64}{RESET}")


def row(label: str, value, highlight: bool = False):
    color = GREEN if highlight else ""
    reset = RESET if highlight else ""
    print(f"    {label:<45} {color}{value}{reset}")


async def layer_1_postgres():
    """Layer 1: Hard Ledger — PostgreSQL record counts."""
    section("LAYER 1: Hard Ledger (PostgreSQL)")

    from backend.models.property import Property
    from backend.models.reservation import Reservation
    from backend.models.workorder import WorkOrder
    from backend.models.damage_claim import DamageClaim

    async with AsyncSessionLocal() as db:
        # Total counts
        prop_count = (await db.execute(select(func.count(Property.id)))).scalar()
        res_count = (await db.execute(select(func.count(Reservation.id)))).scalar()
        wo_count = (await db.execute(select(func.count(WorkOrder.id)))).scalar()
        dc_count = (await db.execute(select(func.count(DamageClaim.id)))).scalar()

        print(f"\n  {BOLD}Record Counts:{RESET}")
        row("properties", prop_count, prop_count > 0)
        row("reservations", res_count, res_count > 0)
        row("work_orders", wo_count, wo_count > 0)
        row("damage_claims", dc_count, dc_count > 0)

        # Sync evidence — Streamline IDs populated
        prop_synced = (await db.execute(
            select(func.count(Property.id)).where(Property.streamline_property_id.isnot(None))
        )).scalar()
        res_synced = (await db.execute(
            select(func.count(Reservation.id)).where(Reservation.streamline_reservation_id.isnot(None))
        )).scalar()

        print(f"\n  {BOLD}Streamline Sync Evidence:{RESET}")
        row("properties with streamline_property_id", f"{prop_synced}/{prop_count}", prop_synced > 0)
        row("reservations with streamline_reservation_id", f"{res_synced}/{res_count}", res_synced > 0)

        pct_prop = (prop_synced / prop_count * 100) if prop_count else 0
        pct_res = (res_synced / res_count * 100) if res_count else 0
        print(f"\n    {DIM}Sync coverage: properties={pct_prop:.0f}%, reservations={pct_res:.0f}%{RESET}")

        # Qdrant point IDs — vectorization evidence
        prop_vec = (await db.execute(
            select(func.count(Property.id)).where(Property.qdrant_point_id.isnot(None))
        )).scalar()
        res_vec = (await db.execute(
            select(func.count(Reservation.id)).where(Reservation.qdrant_point_id.isnot(None))
        )).scalar()
        wo_vec = (await db.execute(
            select(func.count(WorkOrder.id)).where(WorkOrder.qdrant_point_id.isnot(None))
        )).scalar()

        print(f"\n  {BOLD}Vectorization Evidence (qdrant_point_id set):{RESET}")
        row("properties vectorized", f"{prop_vec}/{prop_count}", prop_vec > 0)
        row("reservations vectorized", f"{res_vec}/{res_count}", res_vec > 0)
        row("work_orders vectorized", f"{wo_vec}/{wo_count}", wo_vec > 0)


async def layer_2_qdrant():
    """Layer 2: Vector Brain — Qdrant collection breakdown."""
    section("LAYER 2: Vector Brain (Qdrant)")

    qdrant_url = settings.qdrant_url.rstrip("/")
    collection = settings.qdrant_collection_name
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}

    async with httpx.AsyncClient(timeout=15) as client:
        # Collection info
        try:
            resp = await client.get(f"{qdrant_url}/collections/{collection}", headers=headers)
            if resp.status_code != 200:
                print(f"  {RED}Qdrant collection '{collection}' not found (HTTP {resp.status_code}){RESET}")
                return
            info = resp.json().get("result", {})
            total_pts = info.get("points_count", 0)
            status = info.get("status", "unknown")
            dim = info.get("config", {}).get("params", {}).get("vectors", {}).get("size", "?")

            print(f"\n  {BOLD}Collection: {collection}{RESET}")
            row("Total vectors", total_pts, total_pts > 0)
            row("Status", status, status == "green")
            row("Vector dimension", dim)
        except Exception as e:
            print(f"  {RED}Qdrant unreachable: {e}{RESET}")
            return

        # Breakdown by source_table
        source_tables = ["properties", "reservations", "work_orders"]
        print(f"\n  {BOLD}Vectors by source_table:{RESET}")

        for table in source_tables:
            try:
                resp = await client.post(
                    f"{qdrant_url}/collections/{collection}/points/count",
                    json={
                        "filter": {
                            "must": [{"key": "source_table", "match": {"value": table}}]
                        }
                    },
                    headers=headers,
                )
                if resp.status_code == 200:
                    count = resp.json().get("result", {}).get("count", 0)
                    row(table, count, count > 0)
                else:
                    row(table, f"query failed (HTTP {resp.status_code})")
            except Exception as e:
                row(table, f"error: {str(e)[:60]}")

        # Check for any other source_tables we might have missed
        try:
            resp = await client.post(
                f"{qdrant_url}/collections/{collection}/points/scroll",
                json={
                    "limit": 5,
                    "with_payload": {"include": ["source_table", "name", "text"]},
                    "with_vector": False,
                },
                headers=headers,
            )
            if resp.status_code == 200:
                sample_pts = resp.json().get("result", {}).get("points", [])
                if sample_pts:
                    print(f"\n  {BOLD}Sample payloads (first 5 points):{RESET}")
                    for pt in sample_pts:
                        p = pt.get("payload", {})
                        src = p.get("source_table", "?")
                        name = p.get("name", "")[:40]
                        text_preview = (p.get("text", "")[:60] + "...") if p.get("text") else ""
                        print(f"    [{src}] {name}")
                        if text_preview:
                            print(f"      {DIM}{text_preview}{RESET}")
        except Exception:
            pass


async def layer_3_neural_link():
    """Layer 3: AI Neural Link — Live semantic retrieval test."""
    section("LAYER 3: AI Neural Link (Semantic Retrieval)")

    from backend.services.knowledge_retriever import semantic_search

    test_query = "Show me the most recent damage claims, broken items, or maintenance work orders."

    print(f"\n  {BOLD}Test query:{RESET}")
    print(f"    {CYAN}\"{test_query}\"{RESET}")

    async with AsyncSessionLocal() as db:
        try:
            hits = await semantic_search(
                question=test_query,
                db=db,
                property_id=None,
                top_k=3,
            )

            if not hits:
                print(f"\n  {YELLOW}No results returned. The vector brain has no matching knowledge.{RESET}")
                print(f"  {DIM}This may mean the vectorizer hasn't run, or no damage/work order data exists.{RESET}")
                return

            print(f"\n  {GREEN}{BOLD}Top {len(hits)} results:{RESET}\n")

            for i, hit in enumerate(hits, 1):
                score = hit.get("score", 0)
                source = hit.get("source_table", "unknown")
                name = hit.get("name", "")
                text = hit.get("text", "")

                score_color = GREEN if score > 0.7 else (YELLOW if score > 0.4 else RED)

                print(f"  {BOLD}Result #{i}{RESET}  "
                      f"[{source}]  "
                      f"score={score_color}{score:.4f}{RESET}")
                if name:
                    print(f"    Name: {name}")
                print(f"    ──────────────────────────────────────────")
                for line in text[:500].split("\n"):
                    print(f"    {line}")
                if len(text) > 500:
                    print(f"    {DIM}... ({len(text)} chars total){RESET}")
                print()

        except Exception as e:
            print(f"  {RED}Semantic search failed: {e}{RESET}")
            import traceback
            traceback.print_exc()


async def main():
    banner()
    await layer_1_postgres()
    await layer_2_qdrant()
    await layer_3_neural_link()

    section("DIAGNOSIS COMPLETE")
    print(f"  {DIM}Strangler Fig pipeline: Streamline → PostgreSQL → Qdrant → AI Retrieval{RESET}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
