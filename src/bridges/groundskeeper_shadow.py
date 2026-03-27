"""
GROUNDSKEEPER SHADOW — Live Calendar → Turnover Detection
============================================================
Fortress Prime | Cabin Rentals of Georgia
Lead Architect: Gary M. Knight

Replaces CSV-based reservation imports. Pulls live booking data from
Streamline VRS via GetPropertyRates (the `booked` field), detects
checkout/checkin "edges," and creates turnovers in ops_turnovers.

Then triggers the Groundskeeper task engine to generate CLEANING
and INSPECTION tasks automatically.

How it works:
    1. Pulls nightly rate data for all cabins (next 30-60 days)
    2. The `booked` field (0 or 1) reveals which nights are occupied
    3. Edge detection: booked→open = CHECKOUT, open→booked = CHECKIN
    4. Creates turnover records with 11:00 AM checkout, 4:00 PM checkin
    5. Triggers groundskeeper.py --run to generate tasks

Usage:
    python3 src/bridges/groundskeeper_shadow.py              # full sync + task gen
    python3 src/bridges/groundskeeper_shadow.py --scan-only   # detect only, no DB writes
    python3 src/bridges/groundskeeper_shadow.py --days 60     # scan 60 days ahead

Cron (05:15 daily, after property sync at 05:00):
    15 5 * * * /usr/bin/python3 /home/admin/Fortress-Prime/src/bridges/groundskeeper_shadow.py
"""

import os
import sys
import json
import logging
import argparse
import requests
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
except ImportError:
    pass

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS

# ---------------------------------------------------------------------------
# Streamline API
# ---------------------------------------------------------------------------
TOKEN_KEY = os.getenv("STREAMLINE_TOKEN_KEY", "")
TOKEN_SECRET = os.getenv("STREAMLINE_TOKEN_SECRET", "")
API_URL = "https://web.streamlinevrs.com/api/json"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = "/mnt/fortress_nas/fortress_data/ai_brain/logs"
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("ShadowGroundskeeper")
logger.setLevel(logging.INFO)

_fh = logging.FileHandler(os.path.join(LOG_DIR, "groundskeeper_shadow.log"))
_fh.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(_ch)


# ---------------------------------------------------------------------------
# Streamline API Helper
# ---------------------------------------------------------------------------
def call_streamline(method: str, extra: dict = None) -> dict:
    params = {"token_key": TOKEN_KEY, "token_secret": TOKEN_SECRET}
    if extra:
        params.update(extra)
    payload = {"methodName": method, "params": params}
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    r = requests.post(API_URL, json=payload, headers=headers, timeout=30)
    return r.json()


# ===========================================================================
# SHADOW CALENDAR ENGINE
# ===========================================================================

def scan_shadow_calendar(days_ahead: int = 30, scan_only: bool = False):
    """
    Pull live booking data from Streamline and detect turnovers.

    For each property:
      1. GetPropertyRates returns {date, rate, booked, minStay, ...}
      2. booked=1 means occupied, booked=0 means available
      3. Edge detection finds checkout and checkin boundaries
      4. Creates PENDING turnovers in ops_turnovers
    """
    logger.info(f"[SHADOW] Starting scan (days={days_ahead}, scan_only={scan_only})")

    today = datetime.now()
    start_str = today.strftime("%m/%d/%Y")
    end_date = today + timedelta(days=days_ahead)
    end_str = end_date.strftime("%m/%d/%Y")

    # Get properties with Streamline IDs from our DB
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS,
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT property_id, streamline_id, name, internal_name
        FROM ops_properties
        WHERE streamline_id IS NOT NULL
        ORDER BY name
    """)
    properties = cur.fetchall()

    if not properties:
        logger.error("[SHADOW] No Streamline-synced properties found.")
        conn.close()
        return {"status": "FAILED", "reason": "No properties"}

    logger.info(f"[SHADOW] Scanning {len(properties)} properties, {start_str} -> {end_str}")

    turnovers_found = 0
    turnovers_created = 0
    all_turnovers = []

    for prop in properties:
        prop_id = prop["property_id"]
        sl_id = prop["streamline_id"]
        name = prop["name"] or prop["internal_name"] or prop_id

        try:
            result = call_streamline("GetPropertyRates", {
                "unit_id": sl_id,
                "startdate": start_str,
                "enddate": end_str,
            })

            rate_data = result.get("data", [])
            if not isinstance(rate_data, list) or not rate_data:
                # Check for API error
                status = result.get("status", {})
                if status.get("code"):
                    logger.warning(f"[SHADOW] {name}: API error {status.get('code')}")
                continue

            # Build date → booked map
            calendar = {}
            for entry in rate_data:
                d_str = entry.get("date", "")
                booked = entry.get("booked", 0)
                try:
                    d = datetime.strptime(d_str, "%Y-%m-%d").date()
                    calendar[d] = bool(booked)
                except ValueError:
                    continue

            if not calendar:
                continue

            # Sort dates
            sorted_dates = sorted(calendar.keys())

            # Edge detection: find checkout and checkin boundaries
            for i, d in enumerate(sorted_dates):
                is_booked = calendar[d]
                next_d = d + timedelta(days=1)
                next_booked = calendar.get(next_d)

                # CHECKOUT: booked today, NOT booked tomorrow
                if is_booked and next_booked is False:
                    checkout_date = next_d  # Guest leaves next morning

                    # Look ahead for the next CHECKIN on this same checkout day
                    # (same-day turnover: checkout 11 AM, next guest arrives 4 PM)
                    checkin_date = checkout_date  # Default: same day

                    # Scan forward to find next booking start
                    scan_d = next_d
                    next_booking_start = None
                    while scan_d <= sorted_dates[-1]:
                        if calendar.get(scan_d):
                            next_booking_start = scan_d
                            break
                        scan_d += timedelta(days=1)

                    if next_booking_start:
                        checkin_date = next_booking_start

                    # Build turnover record
                    checkout_dt = datetime.combine(checkout_date, datetime.strptime("11:00", "%H:%M").time())
                    checkin_dt = datetime.combine(checkin_date, datetime.strptime("16:00", "%H:%M").time())
                    window_hours = (checkin_dt - checkout_dt).total_seconds() / 3600

                    res_id = f"SHADOW-{checkout_date.isoformat()}-{sl_id}"

                    turnover = {
                        "property_id": prop_id,
                        "property_name": name,
                        "streamline_id": sl_id,
                        "reservation_id_out": res_id,
                        "checkout_date": checkout_date,
                        "checkout_time": checkout_dt,
                        "checkin_date": checkin_date,
                        "checkin_time": checkin_dt,
                        "window_hours": round(window_hours, 2),
                        "next_booking": next_booking_start,
                    }

                    all_turnovers.append(turnover)
                    turnovers_found += 1

                    logger.info(
                        f"[SHADOW] Checkout: {name} on {checkout_date} "
                        f"(next checkin: {checkin_date}, window: {window_hours:.1f}h)"
                    )

                    if not scan_only:
                        # Insert into ops_turnovers (skip duplicates)
                        try:
                            cur.execute("""
                                INSERT INTO ops_turnovers
                                    (property_id, reservation_id_out, checkout_time,
                                     checkin_time, window_hours, status)
                                VALUES (%s, %s, %s, %s, %s, 'PENDING')
                                ON CONFLICT DO NOTHING
                            """, (
                                prop_id, res_id, checkout_dt,
                                checkin_dt, round(window_hours, 2),
                            ))
                            if cur.rowcount > 0:
                                turnovers_created += 1
                        except psycopg2.Error as e:
                            logger.warning(f"[SHADOW] DB insert failed for {name}: {e}")
                            conn.rollback()

        except Exception as e:
            logger.error(f"[SHADOW] Error scanning {name}: {e}")

    if not scan_only:
        conn.commit()

    cur.close()
    conn.close()

    logger.info(
        f"[SHADOW] Scan complete. "
        f"Detected: {turnovers_found}, Created: {turnovers_created}"
    )

    return {
        "status": "SCAN_ONLY" if scan_only else "SYNCED",
        "properties_scanned": len(properties),
        "turnovers_detected": turnovers_found,
        "turnovers_created": turnovers_created,
        "turnovers": all_turnovers,
    }


# ===========================================================================
# CLI
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Shadow Groundskeeper — Live Calendar Turnover Detection"
    )
    parser.add_argument("--scan-only", action="store_true",
                        help="Detect turnovers but don't write to DB")
    parser.add_argument("--days", type=int, default=30,
                        help="Days ahead to scan (default: 30)")
    parser.add_argument("--no-tasks", action="store_true",
                        help="Skip task generation after sync")
    args = parser.parse_args()

    print("=" * 64)
    print("  SHADOW GROUNDSKEEPER — Live Calendar Turnover Detection")
    print("=" * 64)

    result = scan_shadow_calendar(
        days_ahead=args.days,
        scan_only=args.scan_only,
    )

    print(f"\n  Status:             {result['status']}")
    print(f"  Properties scanned: {result['properties_scanned']}")
    print(f"  Turnovers detected: {result['turnovers_detected']}")
    print(f"  Turnovers created:  {result['turnovers_created']}")

    if result["turnovers"]:
        print(f"\n  --- UPCOMING TURNOVERS ---\n")
        for t in sorted(result["turnovers"], key=lambda x: x["checkout_date"]):
            window = t["window_hours"]
            urgency = "URGENT" if window < 6 else "NORMAL" if window < 24 else "LOW"
            print(f"  {t['checkout_date']}  {t['property_name']:35s}  "
                  f"Window: {window:.0f}h  [{urgency}]")
            if t["next_booking"]:
                print(f"               Next guest arrives: {t['next_booking']}")

    # Trigger Groundskeeper task generation
    if not args.scan_only and not args.no_tasks and result["turnovers_created"] > 0:
        print(f"\n  Triggering Groundskeeper task engine...")
        candidate_engines = [
            "/home/admin/Fortress-Prime/src/groundskeeper.py",
            "/home/admin/Fortress-Prime/src/ops/groundskeeper.py",
            "/home/admin/Fortress-Prime/tools/groundskeeper.py",
        ]
        engine = next((path for path in candidate_engines if os.path.exists(path)), None)
        if engine:
            os.system(f"python3 {engine} --run --report")
        else:
            logger.warning(
                "[SHADOW] No groundskeeper task engine found. "
                "Turnovers are synced, but task generation handoff is skipped."
            )

    print("\n" + "=" * 64)


if __name__ == "__main__":
    main()
