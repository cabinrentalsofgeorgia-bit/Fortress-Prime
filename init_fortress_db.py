#!/usr/bin/env python3
"""
Fortress Prime — Level 5 Database Initialization
====================================================
Creates all schemas and tables needed for the recursive financial stack.

What this initializes:
    1. Division A schema (division_a.*) — Holding company ledger
    2. Division B schema (division_b.*) — Property management + trust accounting
    3. Accounting tables (both divisions) — chart_of_accounts, journal_entries,
       general_ledger, account_mappings + views (trial_balance, balance_check)
    4. Chart of Accounts seed — default CoA for both divisions
    5. Recursive Core reflection logs — NAS/local JSONL directories

Run:
    python3 init_fortress_db.py

Prerequisites:
    - PostgreSQL running on Captain Node (localhost:5432)
    - Database 'fortress_db' exists
    - User 'miner_bot' has CREATE SCHEMA privileges
    - .env file with DB credentials
"""

import sys
import os

# Load environment before any imports that read config
from dotenv import load_dotenv
load_dotenv()

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD


def check_db_connection() -> bool:
    """Verify PostgreSQL is reachable before attempting schema creation."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
            connect_timeout=5,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
        conn.close()
        print(f"  PostgreSQL: {version.split(',')[0]}")
        print(f"  Host: {DB_HOST}:{DB_PORT}/{DB_NAME}")
        print(f"  User: {DB_USER}")
        return True
    except Exception as e:
        print(f"  FAILED: Cannot connect to PostgreSQL: {e}")
        print(f"  Check: DB_HOST={DB_HOST} DB_PORT={DB_PORT} DB_NAME={DB_NAME} DB_USER={DB_USER}")
        return False


def init_division_a() -> bool:
    """Initialize Division A (Holding Company) schema."""
    from division_a_holding.ledger import init_schema
    return init_schema()


def init_division_b() -> bool:
    """Initialize Division B (Property Management + Trust Accounting) schema."""
    from division_b_property.trust_accounting import init_schema
    return init_schema()


def init_accounting_tables() -> dict:
    """
    Initialize the double-entry accounting tables in both division schemas.

    Creates: chart_of_accounts, journal_entries, general_ledger,
             account_mappings, trial_balance view, balance_check view.

    These tables sit ON TOP of the division schemas created in steps 1-2.
    The accounting engine (accounting/engine.py) requires these to exist
    before it can post any journal entries.
    """
    from accounting.schema import init_all
    return init_all()


def seed_chart_of_accounts() -> dict:
    """
    Seed the Chart of Accounts for both divisions with sensible defaults.

    Division A (CROG LLC): 30 accounts — investment, compute assets, VC
    Division B (Cabin Rentals): 65 accounts — trust, utilities, revenue, COGS

    These are required by:
        - accounting.engine.post_journal_entry()  (validates account codes exist)
        - accounting.mapper.map_transaction()      (maps vendors to accounts)
        - accounting.revenue_bridge                (forecast accrual accounts)
        - accounting.cfo_bridge                    (category → account mapping)
        - division_b_property.handlers.revenue_realizer  (1000, 4000, 6020)

    Safe to re-run: uses ON CONFLICT (code) DO UPDATE.
    """
    from accounting.import_qbo_coa import (
        get_default_holding_coa,
        get_default_property_coa,
        insert_accounts,
    )

    results = {}

    # Division A: Holding Company CoA
    holding_accounts = get_default_holding_coa()
    stats_a = insert_accounts(holding_accounts, schema="division_a")
    results["division_a"] = stats_a

    # Division B: Property Management CoA
    property_accounts = get_default_property_coa()
    stats_b = insert_accounts(property_accounts, schema="division_b")
    results["division_b"] = stats_b

    return results


def init_reflection_logs() -> dict:
    """Initialize recursive core reflection log storage."""
    from recursive_core.reflection_log import init_log_storage
    return init_log_storage()


def main():
    print()
    print("=" * 64)
    print("  FORTRESS PRIME — Level 5 Database Initialization")
    print("  Operation Strangler Fig: Double-Entry Ledger Enabled")
    print("=" * 64)
    print()

    # --- Step 0: Verify connection ---
    print("[0/5] Verifying PostgreSQL connection...")
    if not check_db_connection():
        print()
        print("ABORT: Cannot proceed without database connection.")
        print("  Ensure PostgreSQL is running and .env has correct credentials.")
        sys.exit(1)
    print("  OK")
    print()

    results = {}

    # --- Step 1: Division A ---
    print("[1/5] Division A: CROG, LLC (Holding Company)...")
    print("  Creating schema: division_a")
    print("  Tables: transactions, predictions, audit_log")
    try:
        ok = init_division_a()
        results["division_a"] = "OK" if ok else "FAILED"
        print(f"  {'OK — Division A schema ready.' if ok else 'FAILED'}")
    except Exception as e:
        results["division_a"] = f"ERROR: {e}"
        print(f"  ERROR: {e}")
    print()

    # --- Step 2: Division B ---
    print("[2/5] Division B: Cabin Rentals of Georgia (Property Management)...")
    print("  Creating schema: division_b")
    print("  Tables: escrow, vendor_payouts, trust_ledger, transactions, predictions")
    try:
        ok = init_division_b()
        results["division_b"] = "OK" if ok else "FAILED"
        print(f"  {'OK — Division B schema ready.' if ok else 'FAILED'}")
    except Exception as e:
        results["division_b"] = f"ERROR: {e}"
        print(f"  ERROR: {e}")
    print()

    # --- Step 3: Accounting Tables (Operation Strangler Fig) ---
    print("[3/5] Accounting Engine: Double-Entry Ledger Tables...")
    print("  Creating in both schemas: chart_of_accounts, journal_entries,")
    print("    general_ledger, account_mappings, trial_balance, balance_check")
    try:
        acct_results = init_accounting_tables()
        all_acct_ok = all(acct_results.values())
        results["accounting_tables"] = "OK" if all_acct_ok else "PARTIAL"
        for schema_name, ok in acct_results.items():
            status = "OK" if ok else "FAILED"
            print(f"    {schema_name}: {status}")
        if all_acct_ok:
            print("  OK — Accounting tables ready in both divisions.")
        else:
            print("  WARNING: Some accounting tables failed to initialize.")
    except Exception as e:
        results["accounting_tables"] = f"ERROR: {e}"
        print(f"  ERROR: {e}")
    print()

    # --- Step 4: Chart of Accounts Seed ---
    print("[4/5] Chart of Accounts: Seeding Default Accounts...")
    try:
        coa_results = seed_chart_of_accounts()
        total_inserted = 0
        total_updated = 0
        total_errors = 0

        for schema_name, stats in coa_results.items():
            inserted = stats.get("inserted", 0)
            updated = stats.get("updated", 0)
            errors = stats.get("errors", 0)
            total_inserted += inserted
            total_updated += updated
            total_errors += errors
            total = inserted + updated
            print(f"    {schema_name}: {total} accounts ({inserted} new, {updated} updated)")

        results["chart_of_accounts"] = "OK" if total_errors == 0 else f"ERRORS: {total_errors}"
        if total_errors == 0:
            print(f"  OK — {total_inserted + total_updated} accounts seeded across both divisions.")
        else:
            print(f"  WARNING: {total_errors} account(s) failed to insert.")
    except Exception as e:
        results["chart_of_accounts"] = f"ERROR: {e}"
        print(f"  ERROR: {e}")
    print()

    # --- Step 5: Reflection Logs ---
    print("[5/5] Recursive Core: Reflection Log Storage...")
    try:
        log_status = init_reflection_logs()
        writable = log_status.get("writable", False)
        log_dir = log_status.get("log_dir", "unknown")
        results["reflection_logs"] = "OK" if writable else "NOT WRITABLE"
        print(f"  Path: {log_dir}")
        print(f"  Writable: {writable}")
        if writable:
            print(f"  OK — NAS log path verified.")
            cats = log_status.get("categories", {})
            for cat_name in cats:
                print(f"    {cat_name}")
        else:
            print(f"  WARNING: Log directory is not writable!")
            print(f"  Check NAS mount or permissions.")
    except Exception as e:
        results["reflection_logs"] = f"ERROR: {e}"
        print(f"  ERROR: {e}")
    print()

    # --- Summary ---
    print("=" * 64)
    print("  INITIALIZATION SUMMARY")
    print("=" * 64)
    all_ok = True
    for component, status in results.items():
        is_ok = status == "OK"
        icon = "OK" if is_ok else "!!"
        print(f"  [{icon}] {component:.<40} {status}")
        if not is_ok:
            all_ok = False

    print()
    if all_ok:
        print("  FORTRESS IS READY FOR THE FIRST OODA CYCLE.")
        print("  The Strangler Fig's roots are in place.")
        print()
        print("  What was initialized:")
        print("    - Division A & B schemas (transactions, trust, escrow)")
        print("    - Double-entry ledger (chart_of_accounts, journal_entries, GL)")
        print("    - Chart of Accounts seeded (both divisions)")
        print("    - Accounting views (trial_balance, balance_check)")
        print("    - Recursive core reflection logs")
        print()
        print("  Next steps:")
        print("    1. Start the webhook server:  python3 webhook_server.py")
        print("    2. Run a test transaction:    python3 tests/test_mock_transaction.py")
        print("    3. Check health:              curl http://localhost:8006/health")
        print("    4. Import QBO CoA (optional): python3 -m accounting.import_qbo_coa --csv <path> --schema division_b")
        print("    5. Import CFO extracts:       python3 -m accounting.cfo_bridge --dry-run")
        print("    6. Run revenue bridge:        python3 -m accounting.revenue_bridge --reconcile")
    else:
        print("  SOME COMPONENTS FAILED. Review the errors above.")
        print("  The system can still run in degraded mode for passing components.")

    print()
    print("=" * 64)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
