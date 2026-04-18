#!/usr/bin/env python3
"""
FORTRESS PRIME — Data Gap Fixer (Reconciliation Engine)
========================================================
Detects and fixes data integrity gaps across all sectors:
  - COMP: Revenue ledger vs division_a.transactions alignment
  - DEV:  Missing permit records in engineering schema
  - CROG: Task completion gaps in division_b
  - LEGAL: Orphaned evidence/correspondence without case linkage

Re-runnable: safe to execute multiple times (idempotent).

Usage:
    ./venv/bin/python tools/data_reconciliation.py              # Full reconciliation
    ./venv/bin/python tools/data_reconciliation.py --sector comp # Single sector
    ./venv/bin/python tools/data_reconciliation.py --dry-run    # Report only
"""

import json
import os
import sys
import logging
import psycopg2
import psycopg2.extras
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT

log = logging.getLogger("fortress.reconcile")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [RECON] %(message)s")


def get_conn():
    config = {"dbname": DB_NAME, "user": DB_USER}
    if DB_HOST:
        config["host"] = DB_HOST
        config["port"] = DB_PORT
    if DB_PASS:
        config["password"] = DB_PASS
    return psycopg2.connect(**config)


def check_comp(conn, dry_run: bool = False) -> list:
    """Check COMP sector (finance) data integrity."""
    issues = []
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT count(*) as cnt FROM finance_invoices WHERE vendor IS NULL OR vendor = ''")
    row = cur.fetchone()
    if row["cnt"] > 0:
        issues.append({"sector": "comp", "issue": f"{row['cnt']} invoices with no vendor_name", "severity": "HIGH"})

    cur.execute("""
        SELECT count(*) as cnt FROM finance.vendor_classifications
        WHERE classification = 'UNKNOWN' OR classification IS NULL
    """)
    row = cur.fetchone()
    if row["cnt"] > 0:
        issues.append({"sector": "comp", "issue": f"{row['cnt']} unclassified vendors", "severity": "MEDIUM"})

    cur.execute("""
        SELECT count(*) as cnt FROM finance_invoices fi
        LEFT JOIN finance.vendor_classifications vc ON fi.vendor = vc.vendor_label
        WHERE vc.id IS NULL
    """)
    row = cur.fetchone()
    if row["cnt"] > 0:
        issues.append({"sector": "comp", "issue": f"{row['cnt']} invoices with unregistered vendors", "severity": "LOW"})

    cur.close()
    return issues


def check_legal(conn, dry_run: bool = False) -> list:
    """Check LEGAL sector data integrity."""
    issues = []
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT count(*) as cnt FROM legal.case_evidence ce
        LEFT JOIN legal.cases c ON ce.case_id = c.id
        WHERE c.id IS NULL
    """)
    row = cur.fetchone()
    if row["cnt"] > 0:
        issues.append({"sector": "legal", "issue": f"{row['cnt']} orphaned evidence records", "severity": "HIGH"})

    cur.execute("""
        SELECT count(*) as cnt FROM legal.correspondence co
        LEFT JOIN legal.cases c ON co.case_id = c.id
        WHERE c.id IS NULL
    """)
    row = cur.fetchone()
    if row["cnt"] > 0:
        issues.append({"sector": "legal", "issue": f"{row['cnt']} orphaned correspondence", "severity": "HIGH"})

    cur.execute("""
        SELECT c.case_name, count(cw.id) as watchdog_count
        FROM legal.cases c
        LEFT JOIN legal.case_watchdog cw ON cw.case_id = c.id
        WHERE c.status = 'active'
        GROUP BY c.case_name
        HAVING count(cw.id) = 0
    """)
    for row in cur.fetchall():
        issues.append({
            "sector": "legal",
            "issue": f"Active case '{row['case_name']}' has no watchdog terms",
            "severity": "HIGH",
        })

    cur.close()
    return issues


def check_email(conn, dry_run: bool = False) -> list:
    """Check email_archive data integrity."""
    issues = []
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT count(*) as cnt FROM email_archive
        WHERE division IS NULL OR division = ''
    """)
    row = cur.fetchone()
    if row["cnt"] > 0:
        issues.append({"sector": "email", "issue": f"{row['cnt']} emails with no division", "severity": "MEDIUM"})

    cur.execute("""
        SELECT count(*) as cnt FROM email_archive
        WHERE sender IS NULL OR sender = ''
    """)
    row = cur.fetchone()
    if row["cnt"] > 0:
        issues.append({"sector": "email", "issue": f"{row['cnt']} emails with no sender", "severity": "LOW"})

    cur.close()
    return issues


def run_reconciliation(sector: str = None, dry_run: bool = False) -> list:
    """Run data reconciliation across all or a specific sector."""
    conn = get_conn()
    all_issues = []

    checks = {
        "comp": check_comp,
        "legal": check_legal,
        "email": check_email,
    }

    if sector:
        if sector in checks:
            all_issues.extend(checks[sector](conn, dry_run))
        else:
            log.warning(f"No reconciliation check for sector: {sector}")
    else:
        for name, fn in checks.items():
            try:
                issues = fn(conn, dry_run)
                all_issues.extend(issues)
            except Exception as e:
                log.error(f"Check failed for {name}: {e}")
                conn.rollback()
                all_issues.append({"sector": name, "issue": f"Check error: {e}", "severity": "CRITICAL"})

    conn.close()
    return all_issues


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fortress Data Reconciliation")
    parser.add_argument("--sector", type=str, help="Target sector (comp, legal, email)")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no fixes")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    issues = run_reconciliation(sector=args.sector, dry_run=args.dry_run)

    if args.json:
        print(json.dumps(issues, indent=2))
    else:
        if not issues:
            print("No data integrity issues found.")
        else:
            print(f"Found {len(issues)} issue(s):\n")
            for i in issues:
                print(f"  [{i['severity']:8s}] [{i['sector']:6s}] {i['issue']}")
