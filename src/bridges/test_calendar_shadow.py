"""
STREAMLINE — Shadow Calendar Probe
=====================================
Fortress Prime | Cabin Rentals of Georgia

Tests whether our token can see availability/booking status
WITHOUT needing the GetReservationList permission.

GetPropertyAvailability is a "travel agent" method — it tells us
which dates are booked vs. open. Combined with GetPropertyRates,
we can reconstruct the full calendar shadow.
"""

import os
import sys
import json
import requests
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
except ImportError:
    pass

TOKEN = os.getenv("STREAMLINE_TOKEN_KEY", "")
SECRET = os.getenv("STREAMLINE_TOKEN_SECRET", "")
URL = "https://web.streamlinevrs.com/api/json"


def call(method, extra=None):
    params = {"token_key": TOKEN, "token_secret": SECRET}
    if extra:
        params.update(extra)
    payload = {"methodName": method, "params": params}
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    r = requests.post(URL, json=payload, headers=headers, timeout=30)
    return r.json()


def probe_calendar():
    print("=" * 64)
    print("  STREAMLINE — SHADOW CALENDAR PROBE")
    print("=" * 64)

    today = datetime.now()
    start_date = today.strftime("%m/%d/%Y")
    end_date = (today + timedelta(days=30)).strftime("%m/%d/%Y")

    print(f"\n  Scan window: {start_date} -> {end_date}")

    # 1. Get all active properties
    result = call("GetPropertyList", {"status_id": 1})
    properties = result.get("data", {}).get("property", [])

    if not properties:
        print("  ERROR: No properties returned.")
        return

    print(f"  Properties: {len(properties)}")

    # 2. Probe availability for each cabin
    print(f"\n  --- AVAILABILITY PROBE (all cabins, next 30 days) ---\n")

    for prop in properties:
        pid = prop.get("id")
        name = prop.get("name", "?")

        # GetPropertyRates returns 'booked' field per date
        try:
            rates = call("GetPropertyRates", {
                "unit_id": pid,
                "startdate": start_date,
                "enddate": end_date,
            })

            rate_data = rates.get("data", [])
            if isinstance(rate_data, list) and rate_data:
                booked_dates = [d["date"] for d in rate_data if d.get("booked") == 1]
                open_dates = [d["date"] for d in rate_data if d.get("booked") == 0]
                total = len(rate_data)

                # Calculate occupancy rate
                occ_pct = (len(booked_dates) / total * 100) if total > 0 else 0

                status = "FULL" if len(open_dates) == 0 else f"{len(booked_dates)}/{total} nights booked"

                print(f"  {name:40s} | {status:25s} | Occ: {occ_pct:.0f}%")

                if booked_dates:
                    # Show booked blocks
                    blocks = _find_blocks(booked_dates)
                    for b in blocks:
                        if b[0] == b[1]:
                            print(f"    Booked: {b[0]}")
                        else:
                            print(f"    Booked: {b[0]} -> {b[1]}")
            else:
                # Check for error
                status_info = rates.get("status", {})
                if status_info.get("code"):
                    print(f"  {name:40s} | ERROR: {status_info.get('description', '?')[:50]}")
                else:
                    print(f"  {name:40s} | No rate data")

        except Exception as e:
            print(f"  {name:40s} | FAILED: {e}")

    # 3. Also try GetPropertyAvailability directly
    print(f"\n  --- DIRECT AVAILABILITY ENDPOINT ---\n")

    target = properties[0]
    target_id = target.get("id")
    target_name = target.get("name")

    for occupants in [2, 4]:
        try:
            avail = call("GetPropertyAvailability", {
                "property_id": target_id,
                "startdate": start_date,
                "enddate": end_date,
                "occupants": occupants,
            })

            status_info = avail.get("status", {})
            if status_info.get("code"):
                print(f"  GetPropertyAvailability (occ={occupants}): {status_info.get('code')} — {status_info.get('description', '?')[:80]}")
            elif "data" in avail:
                data = avail["data"]
                avail_props = data.get("available_properties", {}).get("property_id", [])
                print(f"  GetPropertyAvailability (occ={occupants}): {len(avail_props)} properties available")
                if avail_props:
                    # Map IDs to names
                    id_to_name = {p["id"]: p["name"] for p in properties}
                    for apid in avail_props[:10]:
                        print(f"    - {id_to_name.get(apid, f'ID:{apid}')}")
        except Exception as e:
            print(f"  GetPropertyAvailability (occ={occupants}): {e}")

    print(f"\n" + "=" * 64)
    print("  VERDICT")
    print("=" * 64)
    print("  If booked dates appeared above, the Shadow Calendar is LIVE.")
    print("  We can build the Groundskeeper schedule from rate/booked data.")
    print("=" * 64)


def _find_blocks(dates):
    """Group consecutive dates into booking blocks."""
    if not dates:
        return []

    from datetime import datetime as dt
    parsed = sorted([dt.strptime(d, "%Y-%m-%d").date() for d in dates])

    blocks = []
    block_start = parsed[0]
    block_end = parsed[0]

    for d in parsed[1:]:
        if (d - block_end).days <= 1:
            block_end = d
        else:
            blocks.append((str(block_start), str(block_end)))
            block_start = d
            block_end = d

    blocks.append((str(block_start), str(block_end)))
    return blocks


if __name__ == "__main__":
    probe_calendar()
