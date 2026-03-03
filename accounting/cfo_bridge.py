"""
CFO Bridge — CFO Extractor CSV → General Ledger
====================================================
Bridges the gap between the CFO Extractor's PDF analysis output (CSV)
and the double-entry general ledger. This is the missing link that
turns 9,899 extracted invoices into real accounting entries.

Pattern:
    1. Read the CFO Extractor CSV (financial_audit.csv)
    2. Filter to successfully extracted rows (status=EXTRACTED, amount > 0)
    3. Map each row to a balanced journal entry using:
       a. Vendor-specific learned rules (from account_mappings — instant)
       b. Category-based defaults (CFO Extractor AI classification)
    4. Post through the accounting engine (atomic, balanced)
    5. Deduplicate: same source file never posts twice

Deduplication:
    Entry IDs are deterministic: CFO-{sha256(source_path)[:12]}
    Re-running the import is safe — duplicates are silently skipped
    via ON CONFLICT (entry_id) DO NOTHING in the engine.

Integration:
    - Source data: CFO Extractor v3.0 (src/cfo_extractor.py)
    - Target: division_b.general_ledger (or division_a)
    - Complements: revenue_bridge.py (forecasts) and mapper.py (Plaid)

Module: CF-04 Treasury / Operation Strangler Fig
"""

import csv
import hashlib
import logging
import os
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

from accounting.models import AccountingError, JournalEntry, LedgerLine
from accounting.engine import post_journal_entry
from accounting.mapper import get_learned_mapping, get_account_info

logger = logging.getLogger("accounting.cfo_bridge")

# Default CSV path (CFO Extractor output)
DEFAULT_CSV = (
    "/mnt/fortress_nas/fortress_data/ai_brain/logs/"
    "cfo_extractor/financial_audit.csv"
)

SOURCE_TYPE = "cfo_extractor"
SCHEMA = "division_b"

# =============================================================================
# CATEGORY → CHART OF ACCOUNTS MAPPING
# =============================================================================
# These map the CFO Extractor's AI-classified categories to the default
# property management Chart of Accounts (division_b).
#
# For expenses: Dr Expense / Cr Bank (money went out to pay this)
# For income:   Dr Bank / Cr Revenue (money came in)
#
# The credit side for expenses defaults to "1000" (Bank:Operating).
# Override per-vendor using account_mappings (self-learning mapper).

CATEGORY_MAP: Dict[str, Dict[str, str]] = {
    "materials": {
        "debit_code": "6010",
        "debit_name": "COGS:Cabin Supplies",
        "credit_code": "1000",
        "credit_name": "Bank:Operating",
    },
    "labor": {
        "debit_code": "5600",
        "debit_name": "Payroll:Wages",
        "credit_code": "1000",
        "credit_name": "Bank:Operating",
    },
    "legal": {
        "debit_code": "5800",
        "debit_name": "Professional Services:Legal",
        "credit_code": "1000",
        "credit_name": "Bank:Operating",
    },
    "insurance": {
        "debit_code": "5300",
        "debit_name": "Insurance:Property",
        "credit_code": "1000",
        "credit_name": "Bank:Operating",
    },
    "utilities": {
        "debit_code": "5000",
        "debit_name": "Utilities:Electric",
        "credit_code": "1000",
        "credit_name": "Bank:Operating",
    },
    "taxes": {
        "debit_code": "5400",
        "debit_name": "Taxes:Property Tax",
        "credit_code": "1000",
        "credit_name": "Bank:Operating",
    },
    "rental_income": {
        "debit_code": "1000",
        "debit_name": "Bank:Operating",
        "credit_code": "4000",
        "credit_name": "Rental Income:Management Fees",
    },
    "maintenance": {
        "debit_code": "5100",
        "debit_name": "Maintenance:Repairs",
        "credit_code": "1000",
        "credit_name": "Bank:Operating",
    },
    "travel": {
        "debit_code": "5900",
        "debit_name": "Vehicle:Fuel",
        "credit_code": "1000",
        "credit_name": "Bank:Operating",
    },
    "office": {
        "debit_code": "5700",
        "debit_name": "Office:Supplies",
        "credit_code": "1000",
        "credit_name": "Bank:Operating",
    },
    "uncategorized": {
        "debit_code": "5950",
        "debit_name": "Miscellaneous Expense",
        "credit_code": "1000",
        "credit_name": "Bank:Operating",
    },
}


# =============================================================================
# DATABASE HELPERS
# =============================================================================

def _connect():
    import psycopg2
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )


def _entry_id_for_path(source_path: str) -> str:
    """
    Generate a deterministic entry_id from the source file path.
    Same file → same ID → natural deduplication via ON CONFLICT.
    """
    path_hash = hashlib.sha256(source_path.encode()).hexdigest()[:12]
    return f"CFO-{path_hash}"


def _is_already_posted(entry_id: str, schema: str = SCHEMA) -> bool:
    """Check if this entry_id already exists in journal_entries."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT 1 FROM {schema}.journal_entries "
                f"WHERE entry_id = %s LIMIT 1",
                (entry_id,),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


# =============================================================================
# CSV READER
# =============================================================================

def read_cfo_csv(csv_path: str = DEFAULT_CSV) -> List[Dict[str, Any]]:
    """
    Read the CFO Extractor output CSV and return extracted rows.

    Filters:
        - status == "EXTRACTED" (successfully processed by AI)
        - total_amount > 0 (has a real dollar value)

    Returns:
        List of dicts with keys matching CSV_HEADER from cfo_extractor.py
    """
    if not os.path.exists(csv_path):
        logger.error(f"[CFO BRIDGE] CSV not found: {csv_path}")
        return []

    rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            status = (row.get("status") or "").strip()
            if status != "EXTRACTED":
                continue

            # Parse and validate amount
            try:
                amount = float(row.get("total_amount", 0) or 0)
            except (ValueError, TypeError):
                continue

            if amount <= 0:
                continue

            rows.append(row)

    logger.info(f"[CFO BRIDGE] Read {len(rows)} extractable rows from {csv_path}")
    return rows


# =============================================================================
# ROW → JOURNAL ENTRY MAPPER
# =============================================================================

def _resolve_accounts(
    vendor: str,
    category: str,
    schema: str = SCHEMA,
) -> Dict[str, str]:
    """
    Determine the debit and credit accounts for a CFO Extractor row.

    Priority:
        1. Vendor-specific learned mapping (from account_mappings table)
        2. Category-based default mapping (from CATEGORY_MAP)
        3. Uncategorized fallback (5950 → 1000)

    Returns:
        {"debit_code": "...", "debit_name": "...",
         "credit_code": "...", "credit_name": "..."}
    """
    # === Priority 1: Check vendor-specific learned rules ===
    if vendor and vendor.strip().lower() != "unknown":
        learned = get_learned_mapping(vendor, schema)
        if learned:
            debit_code = learned["debit_account"]
            credit_code = learned["credit_account"]

            # Resolve names from CoA
            debit_info = get_account_info(debit_code, schema)
            credit_info = get_account_info(credit_code, schema)

            source = learned.get("source", "learned")
            tag = "QBO" if source == "qbo_import" else (
                "manual" if source == "manual" else "LLM"
            )
            logger.debug(
                f"[CFO BRIDGE] Vendor rule [{tag}] for '{vendor}': "
                f"Dr {debit_code} / Cr {credit_code}"
            )
            return {
                "debit_code": debit_code,
                "debit_name": debit_info["name"] if debit_info else f"Account {debit_code}",
                "credit_code": credit_code,
                "credit_name": credit_info["name"] if credit_info else f"Account {credit_code}",
                "source": f"vendor_rule:{tag}",
            }

    # === Priority 2: Category-based mapping ===
    cat_key = (category or "uncategorized").strip().lower()
    mapping = CATEGORY_MAP.get(cat_key, CATEGORY_MAP["uncategorized"])

    return {
        "debit_code": mapping["debit_code"],
        "debit_name": mapping["debit_name"],
        "credit_code": mapping["credit_code"],
        "credit_name": mapping["credit_name"],
        "source": f"category:{cat_key}",
    }


def map_cfo_row(
    row: Dict[str, Any],
    schema: str = SCHEMA,
) -> Optional[JournalEntry]:
    """
    Convert a single CFO Extractor CSV row into a JournalEntry.

    The entry is deterministically identified by the source file path,
    making re-runs safe (duplicates are skipped by the engine).

    Args:
        row: Dict from CSV DictReader (keys: filename, date, vendor_name,
             total_amount, tax_deductible, category, summary, source_path, etc.)
        schema: Target division schema

    Returns:
        A validated JournalEntry, or None if the row can't be mapped.
    """
    source_path = (row.get("source_path") or row.get("filename") or "").strip()
    if not source_path:
        logger.warning("[CFO BRIDGE] Row has no source_path or filename, skipping")
        return None

    # Parse fields
    filename = (row.get("filename") or "").strip()
    vendor = (row.get("vendor_name") or "Unknown").strip()
    category = (row.get("category") or "Uncategorized").strip()
    summary = (row.get("summary") or "").strip()[:200]
    tax_deductible = str(row.get("tax_deductible", "")).strip().lower() in (
        "true", "1", "yes",
    )

    # Parse amount
    try:
        amount = Decimal(str(row.get("total_amount", "0"))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, ValueError):
        logger.warning(f"[CFO BRIDGE] Invalid amount for {filename}, skipping")
        return None

    if amount <= 0:
        return None

    # Parse date
    raw_date = (row.get("date") or "").strip()
    try:
        if raw_date and raw_date != "null":
            entry_date = date.fromisoformat(raw_date)
        else:
            # No date extracted — use today as a holding date
            entry_date = date.today()
    except ValueError:
        # Try common date formats
        for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d", "%d-%m-%Y"):
            try:
                entry_date = datetime.strptime(raw_date, fmt).date()
                break
            except ValueError:
                continue
        else:
            entry_date = date.today()

    # Generate deterministic entry ID
    entry_id = _entry_id_for_path(source_path)

    # Resolve accounts
    accounts = _resolve_accounts(vendor, category, schema)

    # Build description
    desc_parts = [vendor]
    if filename and filename != vendor:
        desc_parts.append(f"({filename})")
    description = " ".join(desc_parts)
    if len(description) > 120:
        description = description[:117] + "..."

    # Build memo
    memo_parts = []
    if summary:
        memo_parts.append(summary)
    if tax_deductible:
        memo_parts.append("[TAX DEDUCTIBLE]")
    memo_parts.append(f"cat:{category}")
    memo_parts.append(f"mapped_by:{accounts.get('source', 'unknown')}")
    memo = " | ".join(memo_parts)

    entry = JournalEntry(
        entry_id=entry_id,
        date=entry_date,
        description=description,
        lines=[
            LedgerLine(
                account_code=accounts["debit_code"],
                account_name=accounts["debit_name"],
                debit=amount,
                credit=Decimal("0.00"),
                memo=f"CFO Extract: {filename}",
            ),
            LedgerLine(
                account_code=accounts["credit_code"],
                account_name=accounts["credit_name"],
                debit=Decimal("0.00"),
                credit=amount,
                memo=f"CFO Extract: {filename}",
            ),
        ],
        source_type=SOURCE_TYPE,
        source_ref=source_path,
        division=schema,
        created_by="cfo_bridge",
        memo=memo,
    )

    # Validate before returning
    try:
        entry.validate()
    except AccountingError as e:
        logger.error(f"[CFO BRIDGE] Validation failed for {filename}: {e}")
        return None

    return entry


# =============================================================================
# BATCH IMPORT
# =============================================================================

def import_cfo_csv(
    csv_path: str = DEFAULT_CSV,
    schema: str = SCHEMA,
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Import CFO Extractor CSV into the double-entry general ledger.

    This is the main entry point. Safe to re-run — duplicates are
    automatically skipped via deterministic entry IDs.

    Args:
        csv_path: Path to the CFO Extractor CSV
        schema: Target division schema (division_a or division_b)
        dry_run: If True, map entries but don't write to DB
        limit: Max rows to process (for testing)

    Returns:
        {
            "csv_rows": int,         # Total extractable rows in CSV
            "already_posted": int,   # Skipped (already in ledger)
            "posted": int,           # Successfully posted this run
            "skipped": int,          # Failed validation or mapping
            "total_amount": Decimal, # Sum of all posted amounts
            "by_category": dict,     # Breakdown by CFO category
            "errors": list,          # Error details
        }
    """
    result = {
        "csv_rows": 0,
        "already_posted": 0,
        "posted": 0,
        "skipped": 0,
        "total_amount": Decimal("0.00"),
        "by_category": {},
        "errors": [],
    }

    # Read CSV
    rows = read_cfo_csv(csv_path)
    result["csv_rows"] = len(rows)

    if not rows:
        logger.info("[CFO BRIDGE] No rows to import")
        return result

    if limit:
        rows = rows[:limit]
        logger.info(f"[CFO BRIDGE] Limited to {limit} rows")

    # Process each row
    for idx, row in enumerate(rows, 1):
        source_path = (row.get("source_path") or row.get("filename") or "").strip()
        filename = (row.get("filename") or "").strip()
        category = (row.get("category") or "Uncategorized").strip()

        # Check if already posted
        entry_id = _entry_id_for_path(source_path)
        if not dry_run and _is_already_posted(entry_id, schema):
            result["already_posted"] += 1
            continue

        # Map to journal entry
        entry = map_cfo_row(row, schema)
        if not entry:
            result["skipped"] += 1
            result["errors"].append(f"SKIP: {filename} (mapping failed)")
            continue

        amount = entry.total_debits

        # Post or record
        if dry_run:
            result["posted"] += 1
            result["total_amount"] += amount
            cat_key = category.lower()
            result["by_category"][cat_key] = (
                result["by_category"].get(cat_key, Decimal("0.00")) + amount
            )
            if idx <= 10:
                logger.info(
                    f"  [DRY RUN] {filename[:40]:<40} "
                    f"${amount:>10,.2f}  {category:<15} "
                    f"Dr {entry.lines[0].account_code} / "
                    f"Cr {entry.lines[1].account_code}"
                )
        else:
            try:
                post_journal_entry(entry, schema)
                result["posted"] += 1
                result["total_amount"] += amount
                cat_key = category.lower()
                result["by_category"][cat_key] = (
                    result["by_category"].get(cat_key, Decimal("0.00")) + amount
                )
                if idx <= 20 or idx % 100 == 0:
                    logger.info(
                        f"  POSTED [{idx}/{len(rows)}] {filename[:40]:<40} "
                        f"${amount:>10,.2f}  {category}"
                    )
            except AccountingError as e:
                result["skipped"] += 1
                result["errors"].append(f"ACCT_ERR: {filename}: {e}")
                logger.warning(f"[CFO BRIDGE] Accounting error: {e}")
            except Exception as e:
                err_str = str(e).lower()
                if "duplicate" in err_str or "unique" in err_str:
                    result["already_posted"] += 1
                else:
                    result["skipped"] += 1
                    result["errors"].append(f"DB_ERR: {filename}: {e}")
                    logger.warning(f"[CFO BRIDGE] DB error: {e}")

        # Progress log every 500 rows
        if idx % 500 == 0:
            logger.info(
                f"  --- Progress: {idx}/{len(rows)} | "
                f"Posted: {result['posted']} | "
                f"Skipped: {result['skipped']} | "
                f"Dupes: {result['already_posted']} | "
                f"${result['total_amount']:,.2f} ---"
            )

    return result


# =============================================================================
# STATUS / REPORTING
# =============================================================================

def get_import_status(schema: str = SCHEMA) -> Dict[str, Any]:
    """
    Check how many CFO Extractor entries have been imported.

    Returns:
        {
            "total_entries": int,
            "total_amount": Decimal,
            "by_category": dict,
            "date_range": {"min": str, "max": str},
            "last_import": str,
        }
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # Count and sum
            cur.execute(f"""
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(gl.debit), 0) AS total_debits
                FROM {schema}.journal_entries je
                JOIN {schema}.general_ledger gl
                    ON gl.journal_entry_id = je.entry_id
                WHERE je.source_type = %s
                  AND gl.debit > 0
            """, (SOURCE_TYPE,))
            row = cur.fetchone()
            total = row[0] if row else 0
            total_amount = Decimal(str(row[1])) if row else Decimal("0.00")

            # Date range
            cur.execute(f"""
                SELECT MIN(entry_date), MAX(entry_date), MAX(created_at)
                FROM {schema}.journal_entries
                WHERE source_type = %s
            """, (SOURCE_TYPE,))
            date_row = cur.fetchone()
            min_date = str(date_row[0]) if date_row and date_row[0] else "N/A"
            max_date = str(date_row[1]) if date_row and date_row[1] else "N/A"
            last_import = str(date_row[2]) if date_row and date_row[2] else "N/A"

            # By category (from memo field)
            cur.execute(f"""
                SELECT je.memo, COUNT(*), SUM(gl.debit)
                FROM {schema}.journal_entries je
                JOIN {schema}.general_ledger gl
                    ON gl.journal_entry_id = je.entry_id
                WHERE je.source_type = %s AND gl.debit > 0
                GROUP BY je.memo
            """, (SOURCE_TYPE,))
            # Extract category from memo (format: "... | cat:Materials | ...")
            by_cat = {}
            for memo_row in cur.fetchall():
                memo = memo_row[0] or ""
                cat_match = re.search(r"cat:(\w+)", memo)
                cat = cat_match.group(1) if cat_match else "unknown"
                by_cat[cat] = by_cat.get(cat, Decimal("0.00")) + Decimal(str(memo_row[2]))

        return {
            "total_entries": total,
            "total_amount": total_amount,
            "by_category": by_cat,
            "date_range": {"min": min_date, "max": max_date},
            "last_import": last_import,
        }
    finally:
        conn.close()


# =============================================================================
# RECONCILIATION: CSV vs LEDGER
# =============================================================================

def reconcile(
    csv_path: str = DEFAULT_CSV,
    schema: str = SCHEMA,
) -> Dict[str, Any]:
    """
    Compare the CFO Extractor CSV against the general ledger to find
    gaps — rows that haven't been imported yet.

    Returns:
        {
            "csv_total_rows": int,
            "csv_total_amount": Decimal,
            "gl_total_entries": int,
            "gl_total_amount": Decimal,
            "unimported_count": int,
            "unimported_amount": Decimal,
            "status": "SYNCED" | "PENDING" | "NO_CSV"
        }
    """
    # Read CSV
    rows = read_cfo_csv(csv_path)
    if not rows:
        return {"status": "NO_CSV", "message": f"No data in {csv_path}"}

    csv_total = Decimal("0.00")
    unimported_count = 0
    unimported_amount = Decimal("0.00")

    for row in rows:
        try:
            amount = Decimal(str(row.get("total_amount", "0"))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP,
            )
        except (InvalidOperation, ValueError):
            continue

        if amount <= 0:
            continue

        csv_total += amount

        source_path = (row.get("source_path") or row.get("filename") or "").strip()
        entry_id = _entry_id_for_path(source_path)

        if not _is_already_posted(entry_id, schema):
            unimported_count += 1
            unimported_amount += amount

    # Get GL totals
    gl_status = get_import_status(schema)

    status = "SYNCED" if unimported_count == 0 else "PENDING"

    return {
        "csv_total_rows": len(rows),
        "csv_total_amount": csv_total,
        "gl_total_entries": gl_status["total_entries"],
        "gl_total_amount": gl_status["total_amount"],
        "unimported_count": unimported_count,
        "unimported_amount": unimported_amount,
        "status": status,
    }


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="CFO Bridge — CFO Extractor CSV → General Ledger",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview what would be imported)
  python -m accounting.cfo_bridge --dry-run

  # Import all extracted rows into division_b
  python -m accounting.cfo_bridge --import

  # Import first 50 rows (for testing)
  python -m accounting.cfo_bridge --import --limit 50

  # Check import status
  python -m accounting.cfo_bridge --status

  # Reconcile CSV vs GL
  python -m accounting.cfo_bridge --reconcile

  # Use a custom CSV path
  python -m accounting.cfo_bridge --import --csv /path/to/audit.csv
        """,
    )
    parser.add_argument(
        "--import", dest="do_import", action="store_true",
        help="Import CFO Extractor CSV into the general ledger",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview import without writing to database",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show current import status",
    )
    parser.add_argument(
        "--reconcile", action="store_true",
        help="Compare CSV against ledger (find gaps)",
    )
    parser.add_argument(
        "--csv", type=str, default=DEFAULT_CSV,
        help=f"Path to CFO Extractor CSV (default: {DEFAULT_CSV})",
    )
    parser.add_argument(
        "--schema", type=str, default=SCHEMA,
        choices=["division_a", "division_b"],
        help=f"Target division schema (default: {SCHEMA})",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max rows to process (for testing)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [CFO BRIDGE] %(message)s",
    )

    if args.do_import or args.dry_run:
        mode = "DRY RUN" if args.dry_run else "LIVE IMPORT"
        print(f"\n{'='*70}")
        print(f"  CFO BRIDGE — {mode}")
        print(f"  CSV:    {args.csv}")
        print(f"  Target: {args.schema}")
        if args.limit:
            print(f"  Limit:  {args.limit} rows")
        print(f"{'='*70}\n")

        result = import_cfo_csv(
            csv_path=args.csv,
            schema=args.schema,
            dry_run=args.dry_run,
            limit=args.limit,
        )

        print(f"\n{'='*70}")
        print(f"  CFO BRIDGE — IMPORT {'PREVIEW' if args.dry_run else 'COMPLETE'}")
        print(f"{'='*70}")
        print(f"  CSV Rows (extractable):  {result['csv_rows']}")
        print(f"  Already in ledger:       {result['already_posted']}")
        print(f"  {'Would post' if args.dry_run else 'Posted'}:    "
              f"            {result['posted']}")
        print(f"  Skipped (errors):        {result['skipped']}")
        print(f"  Total amount:            ${float(result['total_amount']):>12,.2f}")

        if result["by_category"]:
            print(f"\n  Category Breakdown:")
            print(f"  {'-'*50}")
            for cat, amt in sorted(
                result["by_category"].items(),
                key=lambda x: x[1], reverse=True,
            ):
                print(f"    {cat:<25} ${float(amt):>12,.2f}")

        if result["errors"]:
            print(f"\n  Errors ({len(result['errors'])}):")
            for err in result["errors"][:20]:
                print(f"    {err}")
            if len(result["errors"]) > 20:
                print(f"    ... and {len(result['errors']) - 20} more")

        if args.dry_run:
            print(f"\n  [DRY RUN] No changes written to database.")
            print(f"  Run with --import to write for real.")
        print(f"{'='*70}\n")

    elif args.status:
        print(f"\n{'='*60}")
        print(f"  CFO BRIDGE — Import Status")
        print(f"  Schema: {args.schema}")
        print(f"{'='*60}\n")

        status = get_import_status(args.schema)
        print(f"  Total entries in GL:     {status['total_entries']}")
        print(f"  Total amount:            ${float(status['total_amount']):>12,.2f}")
        print(f"  Date range:              {status['date_range']['min']} to "
              f"{status['date_range']['max']}")
        print(f"  Last import:             {status['last_import']}")

        if status["by_category"]:
            print(f"\n  Category Breakdown:")
            print(f"  {'-'*50}")
            for cat, amt in sorted(
                status["by_category"].items(),
                key=lambda x: x[1], reverse=True,
            ):
                print(f"    {cat:<25} ${float(amt):>12,.2f}")
        print(f"\n{'='*60}\n")

    elif args.reconcile:
        print(f"\n{'='*60}")
        print(f"  CFO BRIDGE — Reconciliation")
        print(f"  CSV:    {args.csv}")
        print(f"  Schema: {args.schema}")
        print(f"{'='*60}\n")

        result = reconcile(args.csv, args.schema)

        if result.get("status") == "NO_CSV":
            print(f"  {result.get('message', 'No CSV data')}")
        else:
            print(f"  CSV total rows:          {result['csv_total_rows']}")
            print(f"  CSV total amount:        ${float(result['csv_total_amount']):>12,.2f}")
            print(f"  GL total entries:        {result['gl_total_entries']}")
            print(f"  GL total amount:         ${float(result['gl_total_amount']):>12,.2f}")
            print(f"  Unimported rows:         {result['unimported_count']}")
            print(f"  Unimported amount:       ${float(result['unimported_amount']):>12,.2f}")
            print(f"  Status:                  {result['status']}")

        print(f"\n{'='*60}\n")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
