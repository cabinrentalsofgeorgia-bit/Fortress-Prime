"""
Discovery Probe — Streamline VRS Schema Reconnaissance

Calls the three API methods we need for Vector 1 Entity Roster extraction
(GetOwnerList, GetUnitOwnerBalance, GetMonthEndStatement) and dumps the raw
JSON responses so we can see the exact field names before building the
production extractor.

Usage:
    cd fortress-guest-platform && python -m tools.discovery_probe
"""

import asyncio
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from backend.integrations.streamline_vrs import StreamlineVRS


TARGET_UNIT_ID = 235641  # Aska Escape Lodge


def dump(label: str, data):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(json.dumps(data, indent=2, default=str))


async def run_probe():
    sl = StreamlineVRS()

    if not sl.is_configured:
        print("FATAL: Streamline credentials not loaded. Check .env file.")
        return

    print(f"Streamline endpoint: {sl.api_url}")
    print(f"Token key prefix:    {sl.token_key[:8]}...")

    # ------------------------------------------------------------------
    # Probe 1: GetOwnerList
    # ------------------------------------------------------------------
    print("\n[1/3] Calling fetch_owners() -> GetOwnerList ...")
    try:
        owners = await sl.fetch_owners()
        print(f"  Returned {len(owners)} owner(s)")
        if owners:
            dump("OWNER SAMPLE (first record)", owners[0])
            dump("ALL OWNERS (id + name)", [
                {"owner_id": o.get("owner_id"), "name": f"{o.get('first_name','')} {o.get('last_name','')}".strip()}
                for o in owners
            ])
            sample_owner_id = owners[0].get("owner_id")
        else:
            print("  No owners returned — cannot proceed to statement probe.")
            return
    except Exception as e:
        print(f"  FAILED: {e}")
        return

    # ------------------------------------------------------------------
    # Probe 2: GetUnitOwnerBalance
    # ------------------------------------------------------------------
    print(f"\n[2/3] Calling fetch_unit_owner_balance({TARGET_UNIT_ID}) ...")
    try:
        balance = await sl.fetch_unit_owner_balance(TARGET_UNIT_ID)
        dump(f"BALANCE for unit {TARGET_UNIT_ID}", balance)
    except Exception as e:
        print(f"  FAILED: {e}")

    # ------------------------------------------------------------------
    # Probe 3: GetMonthEndStatement (previous month)
    # ------------------------------------------------------------------
    today = date.today()
    first_this_month = today.replace(day=1)
    last_prev_month = first_this_month - timedelta(days=1)
    first_prev_month = last_prev_month.replace(day=1)

    print(f"\n[3/3] Calling fetch_owner_statement("
          f"owner_id={sample_owner_id}, unit_id={TARGET_UNIT_ID}, "
          f"{first_prev_month} to {last_prev_month}) ...")
    try:
        statement = await sl.fetch_owner_statement(
            owner_id=int(sample_owner_id),
            unit_id=TARGET_UNIT_ID,
            start_date=first_prev_month,
            end_date=last_prev_month,
        )
        dump(f"STATEMENT for owner {sample_owner_id} / unit {TARGET_UNIT_ID} "
             f"({first_prev_month} to {last_prev_month})", statement)
    except Exception as e:
        print(f"  FAILED: {e}")

    # ------------------------------------------------------------------
    # Probe 3b: Try 2 months back if prev month was empty
    # ------------------------------------------------------------------
    if not statement or statement == {}:
        two_back_end = first_prev_month - timedelta(days=1)
        two_back_start = two_back_end.replace(day=1)
        print(f"\n[3b] Previous month empty. Trying {two_back_start} to {two_back_end} ...")
        try:
            statement2 = await sl.fetch_owner_statement(
                owner_id=int(sample_owner_id),
                unit_id=TARGET_UNIT_ID,
                start_date=two_back_start,
                end_date=two_back_end,
            )
            dump(f"STATEMENT (2 months back)", statement2)
        except Exception as e:
            print(f"  FAILED: {e}")

    print("\n[DISCOVERY PROBE COMPLETE]")


if __name__ == "__main__":
    asyncio.run(run_probe())
