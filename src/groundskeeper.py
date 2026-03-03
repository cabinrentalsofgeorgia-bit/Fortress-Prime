"""
DIVISION 3: THE GROUNDSKEEPER
==============================
Operational Commander for Cabin Rentals of Georgia.

Wakes up. Checks who is leaving. Checks who is arriving.
Issues orders to the ops_tasks table.

Usage:
    python src/groundskeeper.py --ingest-props /path/to/properties.csv
    python src/groundskeeper.py --ingest-res /path/to/reservations.csv
    python src/groundskeeper.py --run --report

Modules: CF-01 Guardian Ops (Division 3 — Operations Kernel)
"""

import os
import sys
import csv
import json
import argparse
import psycopg2
from datetime import datetime, timedelta
from psycopg2.extras import DictCursor

# --- Use Fortress config pattern (env vars → config.py defaults) ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", ""))


class Groundskeeper:
    """
    The Groundskeeper Agent — converts reservations into operational tasks.

    Data flow:
        CSV/API → ops_properties → ops_turnovers → ops_tasks → ops_log
    """

    ACTOR = "Groundskeeper"

    def __init__(self):
        try:
            self.conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
            )
            self.conn.autocommit = True
            self.cursor = self.conn.cursor(cursor_factory=DictCursor)
            print(f"  Groundskeeper: Connected to {DB_NAME}@{DB_HOST}")
        except Exception as e:
            print(f"  DB Connection Failed: {e}")
            sys.exit(1)

    def close(self):
        if self.conn and not self.conn.closed:
            self.conn.close()

    # =========================================================================
    # AUDIT LOG
    # =========================================================================

    def log(self, action, entity_type=None, entity_id=None, metadata=None):
        """Writes to the ops_log audit trail."""
        sql = """
            INSERT INTO ops_log (actor, action, entity_type, entity_id, metadata)
            VALUES (%s, %s, %s, %s, %s)
        """
        self.cursor.execute(sql, (
            self.ACTOR, action, entity_type, entity_id,
            json.dumps(metadata or {})
        ))

    # =========================================================================
    # INGEST: PROPERTIES
    # =========================================================================

    def ingest_properties_csv(self, csv_path):
        """
        Seed ops_properties from a CSV export.
        Expected columns: 'Unit ID' (or 'property_id'), 'Unit Name' (or 'name')
        Optional: 'address', 'trash_pickup_day'
        Uses UPSERT — safe to run repeatedly.
        """
        print(f"  Seeding Properties from {csv_path}...")

        if not os.path.exists(csv_path):
            print(f"  File not found: {csv_path}")
            return

        count = 0
        skipped = 0
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid = (row.get("Unit ID") or row.get("property_id") or "").strip()
                name = (row.get("Unit Name") or row.get("name") or "").strip()
                address = (row.get("address") or row.get("Address") or "").strip()
                trash = (row.get("trash_pickup_day") or "Tuesday").strip()

                if not pid or not name:
                    skipped += 1
                    continue

                sql = """
                    INSERT INTO ops_properties (property_id, internal_name, address, trash_pickup_day)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (property_id) DO UPDATE
                    SET internal_name = EXCLUDED.internal_name,
                        address = COALESCE(NULLIF(EXCLUDED.address, ''), ops_properties.address),
                        updated_at = CURRENT_TIMESTAMP;
                """
                self.cursor.execute(sql, (pid, name, address or None, trash))
                count += 1

        print(f"  Synced {count} properties. Skipped {skipped} invalid rows.")
        self.log("INGEST_PROPERTIES", "property", metadata={
            "count": count, "skipped": skipped, "source": csv_path
        })

    # =========================================================================
    # INGEST: RESERVATIONS → TURNOVERS
    # =========================================================================

    def ingest_reservations_csv(self, csv_path):
        """
        Import check-in/check-out data to create turnovers.
        Expected columns:
            'Unit ID' / 'property_id'
            'Reservation ID' / 'res_id'
            'Departure Date' / 'end_date'    (format: MM/DD/YYYY or YYYY-MM-DD)
            'Arrival Date' / 'start_date'    (optional — defaults to same day 4pm)
        """
        print(f"  Ingesting Reservations from {csv_path}...")

        if not os.path.exists(csv_path):
            print(f"  File not found: {csv_path}")
            return

        count = 0
        skipped = 0

        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                res_id = (row.get("Reservation ID") or row.get("res_id") or "").strip()
                prop_id = (row.get("Unit ID") or row.get("property_id") or "").strip()

                if not res_id or not prop_id:
                    skipped += 1
                    continue

                # Parse departure (checkout) date
                depart_str = (row.get("Departure Date") or row.get("end_date") or "").strip()
                depart_dt = self._parse_date(depart_str)
                if not depart_dt:
                    print(f"    Skipping {res_id}: bad departure date '{depart_str}'")
                    skipped += 1
                    continue

                # Default checkout at 11:00 AM
                checkout_time = depart_dt.replace(hour=11, minute=0)

                # Parse arrival (checkin) date — default to same day 4:00 PM
                arrive_str = (row.get("Arrival Date") or row.get("start_date") or "").strip()
                arrive_dt = self._parse_date(arrive_str) if arrive_str else None
                if arrive_dt:
                    checkin_time = arrive_dt.replace(hour=16, minute=0)
                else:
                    # Same-day turnover assumed: next guest arrives at 4 PM
                    checkin_time = depart_dt.replace(hour=16, minute=0)

                # Calculate window
                window_hours = (checkin_time - checkout_time).total_seconds() / 3600

                # Verify property exists
                self.cursor.execute(
                    "SELECT property_id FROM ops_properties WHERE property_id = %s",
                    (prop_id,)
                )
                if not self.cursor.fetchone():
                    print(f"    Skipping {res_id}: property '{prop_id}' not in ops_properties")
                    skipped += 1
                    continue

                # UPSERT turnover (keyed on reservation_id_out + property_id)
                sql = """
                    INSERT INTO ops_turnovers
                        (property_id, reservation_id_out, checkout_time, checkin_time,
                         window_hours, status)
                    VALUES (%s, %s, %s, %s, %s, 'PENDING')
                    ON CONFLICT DO NOTHING;
                """
                self.cursor.execute(sql, (
                    prop_id, res_id, checkout_time, checkin_time, round(window_hours, 2)
                ))
                count += 1

        print(f"  Synced {count} turnovers. Skipped {skipped} rows.")
        self.log("INGEST_RESERVATIONS", "turnover", metadata={
            "count": count, "skipped": skipped, "source": csv_path
        })

    # =========================================================================
    # TASK GENERATION ENGINE
    # =========================================================================

    def generate_tasks(self):
        """
        The Brain: converts PENDING turnovers into actionable tasks.

        For each turnover:
          1. CLEANING task — starts 1h after checkout, 4h SLA
          2. INSPECTION task — due 1h after cleaning deadline
        """
        print("  Analyzing turnovers to generate tasks...")

        self.cursor.execute(
            "SELECT * FROM ops_turnovers WHERE status = 'PENDING' ORDER BY checkout_time"
        )
        turnovers = self.cursor.fetchall()

        if not turnovers:
            print("  No pending turnovers found.")
            return

        tasks_created = 0

        for t in turnovers:
            t_id = t["id"]
            prop_id = t["property_id"]
            checkout = t["checkout_time"]
            checkin = t["checkin_time"]
            window = t["window_hours"]

            # Fetch property SLA (if set)
            self.cursor.execute(
                "SELECT cleaning_sla_minutes FROM ops_properties WHERE property_id = %s",
                (prop_id,)
            )
            prop = self.cursor.fetchone()
            sla_minutes = prop["cleaning_sla_minutes"] if prop and prop["cleaning_sla_minutes"] else 240

            # Cleaning starts 1 hour after checkout
            clean_start = checkout + timedelta(hours=1)
            clean_deadline = clean_start + timedelta(minutes=sla_minutes)

            # Determine priority based on window tightness
            if window and float(window) < 4.0:
                priority = "URGENT"
            elif window and float(window) < 6.0:
                priority = "NORMAL"
            else:
                priority = "LOW"

            # Check for duplicate tasks (idempotent)
            self.cursor.execute(
                "SELECT id FROM ops_tasks WHERE turnover_id = %s AND type = 'CLEANING'",
                (t_id,)
            )
            if self.cursor.fetchone():
                # Tasks already generated for this turnover
                continue

            # --- TASK 1: CLEANING ---
            self.cursor.execute("""
                INSERT INTO ops_tasks
                    (type, priority, property_id, turnover_id, description, deadline, status)
                VALUES ('CLEANING', %s, %s, %s, %s, %s, 'OPEN')
            """, (
                priority, prop_id, t_id,
                f"Standard Turnover Clean — {sla_minutes // 60}h SLA",
                clean_deadline,
            ))

            # --- TASK 2: INSPECTION (post-clean QC) ---
            inspect_deadline = clean_deadline + timedelta(hours=1)
            self.cursor.execute("""
                INSERT INTO ops_tasks
                    (type, priority, property_id, turnover_id, description, deadline, status)
                VALUES ('INSPECTION', 'URGENT', %s, %s, %s, %s, 'OPEN')
            """, (
                prop_id, t_id,
                "Post-Clean QC Inspection (CF-01 Vision)",
                inspect_deadline,
            ))

            # --- TASK 3: HOT TUB CHECK (if property has one) ---
            self.cursor.execute(
                "SELECT hot_tub_gallons FROM ops_properties WHERE property_id = %s",
                (prop_id,)
            )
            prop_ht = self.cursor.fetchone()
            if prop_ht and prop_ht["hot_tub_gallons"]:
                self.cursor.execute("""
                    INSERT INTO ops_tasks
                        (type, priority, property_id, turnover_id, description, deadline, status)
                    VALUES ('HOT_TUB', 'NORMAL', %s, %s, %s, %s, 'OPEN')
                """, (
                    prop_id, t_id,
                    "Hot Tub Chemical Balance + Cover Check",
                    clean_deadline,  # Due by same time as cleaning
                ))
                tasks_created += 1

            # Update turnover status
            self.cursor.execute(
                "UPDATE ops_turnovers SET status = 'IN_PROGRESS', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (t_id,)
            )
            tasks_created += 2  # CLEANING + INSPECTION always

            # Log it
            self.log("TASK_GENERATED", "turnover", t_id, {
                "property": prop_id,
                "tasks": ["CLEANING", "INSPECTION"],
                "priority": priority,
                "window_hours": float(window) if window else None,
                "clean_deadline": clean_deadline.isoformat(),
            })

        print(f"  Generated {tasks_created} new tasks from {len(turnovers)} turnovers.")
        self.log("GENERATE_TASKS_COMPLETE", metadata={
            "tasks_created": tasks_created,
            "turnovers_processed": len(turnovers),
        })

    # =========================================================================
    # STATUS REPORT
    # =========================================================================

    def status_report(self):
        """Prints a dashboard-style operational summary."""
        print("\n" + "=" * 50)
        print("   FORTRESS OPERATIONS STATUS")
        print("=" * 50)

        self.cursor.execute("SELECT count(*) FROM ops_properties")
        print(f"  Properties:        {self.cursor.fetchone()[0]}")

        self.cursor.execute("SELECT count(*) FROM ops_crew WHERE status = 'ACTIVE'")
        print(f"  Active Crew:       {self.cursor.fetchone()[0]}")

        self.cursor.execute("SELECT count(*) FROM ops_turnovers WHERE status = 'PENDING'")
        print(f"  Pending Turnovers: {self.cursor.fetchone()[0]}")

        self.cursor.execute("SELECT count(*) FROM ops_turnovers WHERE status = 'IN_PROGRESS'")
        print(f"  Active Turnovers:  {self.cursor.fetchone()[0]}")

        self.cursor.execute("SELECT count(*) FROM ops_tasks WHERE status = 'OPEN'")
        open_tasks = self.cursor.fetchone()[0]
        print(f"  Open Tasks:        {open_tasks}")

        self.cursor.execute("SELECT count(*) FROM ops_tasks WHERE status = 'DONE'")
        print(f"  Completed Tasks:   {self.cursor.fetchone()[0]}")

        # Task breakdown by type
        self.cursor.execute("""
            SELECT type, count(*) as cnt
            FROM ops_tasks WHERE status IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS')
            GROUP BY type ORDER BY cnt DESC
        """)
        rows = self.cursor.fetchall()
        if rows:
            print("\n  Active Tasks by Type:")
            for r in rows:
                print(f"    {r['type']:15s} {r['cnt']}")

        # Upcoming turnovers (next 7 days)
        self.cursor.execute("""
            SELECT t.checkout_time, p.internal_name, t.window_hours, t.status
            FROM ops_turnovers t
            JOIN ops_properties p ON p.property_id = t.property_id
            WHERE t.checkout_time >= CURRENT_TIMESTAMP
              AND t.checkout_time < CURRENT_TIMESTAMP + INTERVAL '7 days'
            ORDER BY t.checkout_time
            LIMIT 10
        """)
        upcoming = self.cursor.fetchall()
        if upcoming:
            print("\n  Upcoming Turnovers (7-day window):")
            for u in upcoming:
                dt = u["checkout_time"].strftime("%m/%d %I:%M%p")
                win = f"{u['window_hours']}h" if u["window_hours"] else "N/A"
                print(f"    {dt}  {u['internal_name']:25s}  Window: {win}  [{u['status']}]")

        # Audit log recent
        self.cursor.execute("""
            SELECT timestamp, action FROM ops_log
            ORDER BY timestamp DESC LIMIT 5
        """)
        logs = self.cursor.fetchall()
        if logs:
            print("\n  Recent Audit Log:")
            for l in logs:
                ts = l["timestamp"].strftime("%m/%d %H:%M")
                print(f"    [{ts}] {l['action']}")

        print("\n" + "=" * 50)

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _parse_date(date_str):
        """Try common date formats."""
        if not date_str:
            return None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        return None


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Groundskeeper — Division 3 Operational Commander"
    )
    parser.add_argument("--ingest-props", metavar="CSV",
                        help="Seed ops_properties from a CSV file")
    parser.add_argument("--ingest-res", metavar="CSV",
                        help="Import reservations to create ops_turnovers")
    parser.add_argument("--run", action="store_true",
                        help="Generate ops_tasks from pending turnovers")
    parser.add_argument("--report", action="store_true",
                        help="Print operational status dashboard")

    args = parser.parse_args()

    # If no args, show help
    if not any([args.ingest_props, args.ingest_res, args.run, args.report]):
        parser.print_help()
        sys.exit(0)

    gk = Groundskeeper()

    try:
        if args.ingest_props:
            gk.ingest_properties_csv(args.ingest_props)

        if args.ingest_res:
            gk.ingest_reservations_csv(args.ingest_res)

        if args.run:
            gk.generate_tasks()

        if args.report:
            gk.status_report()
    finally:
        gk.close()
