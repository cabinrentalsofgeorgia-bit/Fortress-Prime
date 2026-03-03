"""
QBO Mapper Training — Teach the Strangler Fig Your History
================================================================
Parses QuickBooks Online P&L Detail CSV exports and trains the
accounting mapper with vendor → account mappings.

After training, Plaid transactions from known vendors get instant
DB lookups instead of slow LLM calls.

Supports:
    1. P&L Detail CSV (primary — most common QBO export)
    2. Transaction Detail by Account CSV (richer, if available)

Usage:
    # Train from P&L Detail
    python -m accounting.train_mapper --csv qbo_pnl_detail.csv --schema division_b

    # Dry run (show what would be learned, don't write)
    python -m accounting.train_mapper --csv qbo_pnl_detail.csv --dry-run

    # Report current mapper coverage
    python -m accounting.train_mapper --report --schema division_b

Module: Operation Strangler Fig — Brain Transplant Phase
"""

import argparse
import csv
import logging
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

logger = logging.getLogger("accounting.train_mapper")

# Confidence assigned to QBO-trained rules (higher than LLM-derived)
QBO_IMPORT_CONFIDENCE = 0.95
QBO_IMPORT_SOURCE = "qbo_import"

# Default credit account for expense payments (bank operating)
DEFAULT_CREDIT_ACCOUNT = "1000"


# =============================================================================
# DATABASE HELPERS
# =============================================================================

def _connect():
    import psycopg2
    import psycopg2.extras
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def _get_coa(schema: str = "division_b") -> List[Dict[str, str]]:
    """Fetch all Chart of Accounts entries."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT code, name, account_type, qbo_name, normal_balance
            FROM {schema}.chart_of_accounts
            WHERE is_active = TRUE
            ORDER BY code
        """)
        return cur.fetchall()
    finally:
        conn.close()


# =============================================================================
# 1. QBO P&L DETAIL CSV PARSER
# =============================================================================

def parse_qbo_pnl_detail(csv_path: str) -> List[Dict[str, Any]]:
    """
    Parse a QBO P&L Detail CSV export.

    Expected format (with variations):
        Date, Transaction Type, Num, Name, Memo/Description, Split, Amount, Balance

    The 'Split' column contains the QBO account name (e.g., "Utilities:Electricity").
    The 'Name' column contains the vendor name.

    Returns a list of dicts:
        {"vendor": str, "qbo_account": str, "amount": float, "date": str,
         "description": str, "txn_type": str}
    """
    transactions = []
    path = Path(csv_path)
    if not path.exists():
        logger.error(f"CSV file not found: {csv_path}")
        return []

    with open(path, "r", encoding="utf-8-sig") as f:
        # QBO P&L Detail CSVs often have header rows before the actual data.
        # Try to find the real header row by looking for known column names.
        lines = f.readlines()

    header_idx = _find_header_row(lines)
    if header_idx is None:
        logger.error(
            "Could not find a valid header row in the CSV. "
            "Expected columns like: Date, Name, Split, Amount"
        )
        return []

    # Re-parse from the header row
    reader = csv.DictReader(lines[header_idx:])
    col_map = _build_column_map(reader.fieldnames or [])

    if not col_map.get("name") or not col_map.get("amount"):
        logger.error(
            f"Missing required columns. Found: {list(col_map.keys())}. "
            f"Need at least: name, amount"
        )
        return []

    for row in reader:
        vendor = row.get(col_map.get("name", ""), "").strip()
        amount_str = row.get(col_map.get("amount", ""), "").strip()
        qbo_account = row.get(col_map.get("split", ""), "").strip()
        txn_date = row.get(col_map.get("date", ""), "").strip()
        description = row.get(col_map.get("memo", ""), "").strip()
        txn_type = row.get(col_map.get("txn_type", ""), "").strip()

        # Skip empty rows, subtotal/total rows
        if not vendor or not amount_str:
            continue
        if any(kw in vendor.lower() for kw in ("total", "subtotal", "net income")):
            continue

        # Parse amount (QBO uses commas and sometimes parentheses for negatives)
        amount = _parse_amount(amount_str)
        if amount is None:
            continue

        # The 'Split' column is the account name in QBO P&L Detail
        # If missing, try the parent section heading
        if not qbo_account or qbo_account in ("-Split-", "Split"):
            qbo_account = ""

        transactions.append({
            "vendor": vendor,
            "qbo_account": qbo_account,
            "amount": amount,
            "date": txn_date,
            "description": description,
            "txn_type": txn_type,
        })

    logger.info(f"Parsed {len(transactions)} transactions from {csv_path}")
    return transactions


def parse_qbo_transaction_detail(csv_path: str) -> List[Dict[str, Any]]:
    """
    Parse a QBO Transaction Detail by Account CSV.

    This format groups transactions by account and includes:
        Date, Transaction Type, Num, Name, Memo/Description, Amount, Balance

    The account name appears as a section header row before its transactions.

    Returns same format as parse_qbo_pnl_detail.
    """
    transactions = []
    path = Path(csv_path)
    if not path.exists():
        logger.error(f"CSV file not found: {csv_path}")
        return []

    with open(path, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()

    header_idx = _find_header_row(lines)
    if header_idx is None:
        logger.error("Could not find header row in Transaction Detail CSV")
        return []

    current_account = ""
    reader = csv.DictReader(lines[header_idx:])
    col_map = _build_column_map(reader.fieldnames or [])

    for row in reader:
        name_val = row.get(col_map.get("name", ""), "").strip()
        amount_str = row.get(col_map.get("amount", ""), "").strip()

        # Detect account section headers (rows where only the first column has text)
        non_empty = sum(1 for v in row.values() if v and v.strip())
        if non_empty <= 2 and name_val and not amount_str:
            # This is likely an account section header
            potential = row.get(col_map.get("date", ""), "").strip()
            if potential and not _parse_date(potential):
                current_account = potential
                continue

        vendor = name_val
        if not vendor or not amount_str:
            continue
        if any(kw in vendor.lower() for kw in ("total", "subtotal")):
            continue

        amount = _parse_amount(amount_str)
        if amount is None:
            continue

        txn_date = row.get(col_map.get("date", ""), "").strip()
        description = row.get(col_map.get("memo", ""), "").strip()
        txn_type = row.get(col_map.get("txn_type", ""), "").strip()

        transactions.append({
            "vendor": vendor,
            "qbo_account": current_account,
            "amount": amount,
            "date": txn_date,
            "description": description,
            "txn_type": txn_type,
        })

    logger.info(f"Parsed {len(transactions)} transactions from {csv_path}")
    return transactions


# =============================================================================
# 2. COA MATCHING
# =============================================================================

def match_qbo_to_coa(
    qbo_account_name: str,
    coa_entries: List[Dict[str, str]],
) -> Optional[str]:
    """
    Match a QBO account name (e.g., "Utilities:Electricity") to the closest
    Chart of Accounts code in Fortress.

    Strategy:
        1. Exact match on qbo_name field
        2. Exact match on name field
        3. Fuzzy match on name (>= 0.70 similarity)
        4. Prefix match (first segment matches)

    Returns the CoA code or None if no match.
    """
    if not qbo_account_name:
        return None

    normalized = qbo_account_name.strip().lower()

    # Pass 1: Exact match on qbo_name
    for entry in coa_entries:
        if entry.get("qbo_name") and entry["qbo_name"].strip().lower() == normalized:
            return entry["code"]

    # Pass 2: Exact match on name
    for entry in coa_entries:
        if entry["name"].strip().lower() == normalized:
            return entry["code"]

    # Pass 3: Fuzzy match on name
    best_score = 0.0
    best_code = None
    for entry in coa_entries:
        # Compare full names
        score = SequenceMatcher(
            None, normalized, entry["name"].strip().lower(),
        ).ratio()
        if score > best_score:
            best_score = score
            best_code = entry["code"]

        # Also try matching against qbo_name
        if entry.get("qbo_name"):
            qbo_score = SequenceMatcher(
                None, normalized, entry["qbo_name"].strip().lower(),
            ).ratio()
            if qbo_score > best_score:
                best_score = qbo_score
                best_code = entry["code"]

    if best_score >= 0.70:
        return best_code

    # Pass 4: Prefix match (e.g., "Utilities:Electricity" → "Utilities:Electric")
    prefix = normalized.split(":")[0] if ":" in normalized else normalized
    for entry in coa_entries:
        entry_prefix = entry["name"].strip().lower().split(":")[0]
        if prefix == entry_prefix:
            return entry["code"]

    return None


def _determine_debit_credit(
    qbo_account_code: Optional[str],
    amount: float,
    coa_entries: List[Dict[str, str]],
) -> Tuple[str, str]:
    """
    Determine the debit and credit accounts for a transaction.

    For expenses (outflows): Dr Expense, Cr Bank (1000)
    For income (inflows): Dr Bank (1000), Cr Revenue
    """
    if not qbo_account_code:
        # Unknown account — can't determine mapping
        return ("", "")

    # Find the account type
    acct_type = None
    for entry in coa_entries:
        if entry["code"] == qbo_account_code:
            acct_type = entry["account_type"]
            break

    if acct_type in ("expense", "cogs"):
        return (qbo_account_code, DEFAULT_CREDIT_ACCOUNT)
    elif acct_type == "revenue":
        return (DEFAULT_CREDIT_ACCOUNT, qbo_account_code)
    elif acct_type == "asset":
        # Asset purchase: Dr Asset, Cr Bank
        return (qbo_account_code, DEFAULT_CREDIT_ACCOUNT)
    elif acct_type == "liability":
        # Liability payment: Dr Liability, Cr Bank
        return (qbo_account_code, DEFAULT_CREDIT_ACCOUNT)
    else:
        # Default: use amount sign
        if amount > 0:
            return (qbo_account_code, DEFAULT_CREDIT_ACCOUNT)
        else:
            return (DEFAULT_CREDIT_ACCOUNT, qbo_account_code)


# =============================================================================
# 3. TRAINING ENGINE
# =============================================================================

def train_from_csv(
    csv_path: str,
    schema: str = "division_b",
    dry_run: bool = False,
    csv_type: str = "pnl_detail",
) -> Dict[str, Any]:
    """
    The main training function:
        1. Parse the QBO CSV
        2. For each vendor, find the most frequent account assignment
        3. Map QBO account names to Fortress CoA codes
        4. Upsert into account_mappings with confidence=0.95, source='qbo_import'

    Args:
        csv_path: Path to QBO CSV export
        schema: Target division schema
        dry_run: If True, show what would be learned without writing
        csv_type: "pnl_detail" or "transaction_detail"

    Returns:
        {"vendors_learned": N, "unmatched": M, "skipped": S, "details": [...]}
    """
    # Step 1: Parse CSV
    if csv_type == "transaction_detail":
        transactions = parse_qbo_transaction_detail(csv_path)
    else:
        transactions = parse_qbo_pnl_detail(csv_path)

    if not transactions:
        return {"vendors_learned": 0, "unmatched": 0, "skipped": 0, "details": []}

    # Step 2: Aggregate vendor → account frequencies
    vendor_accounts = defaultdict(lambda: Counter())
    vendor_totals = defaultdict(lambda: {"count": 0, "total": 0.0})

    for txn in transactions:
        vendor = txn["vendor"]
        qbo_acct = txn["qbo_account"]
        if qbo_acct:
            vendor_accounts[vendor][qbo_acct] += 1
        vendor_totals[vendor]["count"] += 1
        vendor_totals[vendor]["total"] += abs(txn["amount"])

    # Step 3: For each vendor, pick the most frequent account
    coa_entries = _get_coa(schema)
    results = {
        "vendors_learned": 0,
        "unmatched": 0,
        "skipped": 0,
        "total_transactions": len(transactions),
        "unique_vendors": len(vendor_totals),
        "details": [],
    }
    unmatched_accounts = set()

    conn = _connect() if not dry_run else None
    try:
        for vendor, acct_counter in sorted(
            vendor_accounts.items(), key=lambda x: sum(x[1].values()), reverse=True,
        ):
            most_common_qbo_acct, freq = acct_counter.most_common(1)[0]
            total_txns = vendor_totals[vendor]["count"]
            total_amount = vendor_totals[vendor]["total"]

            # Match QBO account → Fortress CoA code
            coa_code = match_qbo_to_coa(most_common_qbo_acct, coa_entries)

            if not coa_code:
                unmatched_accounts.add(most_common_qbo_acct)
                results["unmatched"] += 1
                results["details"].append({
                    "vendor": vendor,
                    "qbo_account": most_common_qbo_acct,
                    "status": "UNMATCHED",
                    "transactions": total_txns,
                    "total_amount": round(total_amount, 2),
                })
                continue

            # Determine debit/credit based on account type
            debit_acct, credit_acct = _determine_debit_credit(
                coa_code, -total_amount, coa_entries,  # Expenses are negative
            )

            if not debit_acct or not credit_acct:
                results["skipped"] += 1
                continue

            # Calculate confidence based on frequency consistency
            consistency = freq / total_txns if total_txns > 0 else 0
            confidence = min(
                QBO_IMPORT_CONFIDENCE,
                0.80 + (consistency * 0.15),  # 0.80 to 0.95
            )

            detail = {
                "vendor": vendor,
                "qbo_account": most_common_qbo_acct,
                "coa_code": coa_code,
                "debit": debit_acct,
                "credit": credit_acct,
                "confidence": round(confidence, 3),
                "transactions": total_txns,
                "total_amount": round(total_amount, 2),
                "status": "LEARNED",
            }
            results["details"].append(detail)

            if not dry_run and conn:
                cur = conn.cursor()
                reasoning = (
                    f"QBO import: {freq}/{total_txns} transactions mapped to "
                    f"'{most_common_qbo_acct}' (${total_amount:,.2f} total)"
                )
                cur.execute(f"""
                    INSERT INTO {schema}.account_mappings
                        (vendor_name, debit_account, credit_account,
                         confidence, reasoning, source, learned_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (vendor_name) DO UPDATE SET
                        debit_account = CASE
                            WHEN {schema}.account_mappings.source = 'qbo_import'
                                 OR {schema}.account_mappings.confidence < EXCLUDED.confidence
                            THEN EXCLUDED.debit_account
                            ELSE {schema}.account_mappings.debit_account
                        END,
                        credit_account = CASE
                            WHEN {schema}.account_mappings.source = 'qbo_import'
                                 OR {schema}.account_mappings.confidence < EXCLUDED.confidence
                            THEN EXCLUDED.credit_account
                            ELSE {schema}.account_mappings.credit_account
                        END,
                        confidence = GREATEST(
                            {schema}.account_mappings.confidence, EXCLUDED.confidence
                        ),
                        reasoning = EXCLUDED.reasoning,
                        source = EXCLUDED.source,
                        learned_at = NOW()
                """, (
                    vendor.strip(), debit_acct, credit_acct,
                    confidence, reasoning, QBO_IMPORT_SOURCE,
                ))

            results["vendors_learned"] += 1

        if conn:
            conn.commit()

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Training failed: {e}")
        raise
    finally:
        if conn:
            conn.close()

    if unmatched_accounts:
        logger.warning(
            f"Unmatched QBO accounts (need manual CoA mapping): "
            f"{sorted(unmatched_accounts)}"
        )

    return results


# =============================================================================
# 4. REPORT
# =============================================================================

def report(schema: str = "division_b") -> Dict[str, Any]:
    """
    Report current mapper coverage:
        - Total vendors with learned rules
        - Breakdown by source (llm, manual, qbo_import)
        - Average confidence
        - Vendors still unmapped (no rules at all)
    """
    conn = _connect()
    try:
        cur = conn.cursor()

        # Total learned mappings
        cur.execute(f"""
            SELECT
                source,
                COUNT(*) as count,
                AVG(confidence) as avg_confidence,
                MIN(confidence) as min_confidence,
                MAX(confidence) as max_confidence
            FROM {schema}.account_mappings
            GROUP BY source
            ORDER BY source
        """)
        by_source = cur.fetchall()

        # Total
        cur.execute(f"SELECT COUNT(*) FROM {schema}.account_mappings")
        total = cur.fetchone()["count"]

        # Top vendors by confidence
        cur.execute(f"""
            SELECT vendor_name, debit_account, credit_account,
                   confidence, source
            FROM {schema}.account_mappings
            ORDER BY confidence DESC, vendor_name
            LIMIT 20
        """)
        top_vendors = cur.fetchall()

        # Low-confidence mappings (might need review)
        cur.execute(f"""
            SELECT vendor_name, debit_account, credit_account,
                   confidence, source, reasoning
            FROM {schema}.account_mappings
            WHERE confidence < 0.60
            ORDER BY confidence ASC
            LIMIT 10
        """)
        low_conf = cur.fetchall()

        return {
            "total_mappings": total,
            "by_source": [dict(r) for r in by_source],
            "top_vendors": [dict(r) for r in top_vendors],
            "low_confidence": [dict(r) for r in low_conf],
        }
    finally:
        conn.close()


# =============================================================================
# UTILITY HELPERS
# =============================================================================

def _find_header_row(lines: List[str]) -> Optional[int]:
    """
    Find the index of the header row in a QBO CSV.
    QBO CSVs often have title/subtitle rows before the actual header.
    """
    header_keywords = {"date", "name", "amount", "transaction type", "memo", "split"}
    for i, line in enumerate(lines[:20]):  # Check first 20 lines
        lower = line.strip().lower()
        matches = sum(1 for kw in header_keywords if kw in lower)
        if matches >= 2:
            return i
    return None


def _build_column_map(fieldnames: List[str]) -> Dict[str, str]:
    """Map normalized column names to actual CSV column names."""
    col_map = {}
    for col in fieldnames:
        lower = col.strip().lower()
        if lower == "date":
            col_map["date"] = col
        elif lower in ("name", "payee", "vendor"):
            col_map["name"] = col
        elif lower in ("amount", "total"):
            col_map["amount"] = col
        elif lower in ("split", "account", "category"):
            col_map["split"] = col
        elif lower in ("memo", "memo/description", "description"):
            col_map["memo"] = col
        elif lower in ("transaction type", "type", "txn type"):
            col_map["txn_type"] = col
        elif lower in ("num", "number", "ref", "check #"):
            col_map["num"] = col
        elif lower == "balance":
            col_map["balance"] = col
    return col_map


def _parse_amount(amount_str: str) -> Optional[float]:
    """Parse a QBO amount string, handling commas, parens, dollar signs."""
    if not amount_str:
        return None
    cleaned = amount_str.strip()
    # Remove dollar signs and commas
    cleaned = cleaned.replace("$", "").replace(",", "")
    # Handle parentheses for negatives: (100.00) → -100.00
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(date_str: str) -> Optional[str]:
    """Try to parse a date string. Returns ISO format or None."""
    import re
    # MM/DD/YYYY
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", date_str)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    # YYYY-MM-DD
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_str)
    if m:
        return date_str
    return None


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="QBO Mapper Training — Operation Strangler Fig Brain Transplant",
    )
    parser.add_argument(
        "--csv", type=str,
        help="Path to QBO CSV export (P&L Detail or Transaction Detail)",
    )
    parser.add_argument(
        "--csv-type", type=str, default="pnl_detail",
        choices=["pnl_detail", "transaction_detail"],
        help="Type of QBO CSV (default: pnl_detail)",
    )
    parser.add_argument(
        "--schema", type=str, default="division_b",
        choices=["division_a", "division_b"],
        help="Target division schema (default: division_b)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be learned without writing to DB",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Show current mapper coverage report",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [MAPPER-TRAIN] %(message)s",
    )

    if args.report:
        print(f"\n{'='*60}")
        print(f"  OPERATION STRANGLER FIG — Mapper Coverage Report")
        print(f"  Schema: {args.schema}")
        print(f"{'='*60}\n")

        rpt = report(args.schema)
        print(f"  Total vendor mappings: {rpt['total_mappings']}\n")

        if rpt["by_source"]:
            print("  By Source:")
            for src in rpt["by_source"]:
                print(
                    f"    {src['source']:15s}  "
                    f"{src['count']:4d} vendors  "
                    f"avg conf: {float(src['avg_confidence']):.2f}  "
                    f"range: {float(src['min_confidence']):.2f}-{float(src['max_confidence']):.2f}"
                )
            print()

        if rpt["top_vendors"]:
            print("  Top Vendors (by confidence):")
            for v in rpt["top_vendors"][:10]:
                print(
                    f"    {v['vendor_name']:30s}  "
                    f"Dr {v['debit_account']:6s} / Cr {v['credit_account']:6s}  "
                    f"conf: {float(v['confidence']):.2f}  [{v['source']}]"
                )
            print()

        if rpt["low_confidence"]:
            print("  Low-Confidence Mappings (review recommended):")
            for v in rpt["low_confidence"]:
                print(
                    f"    {v['vendor_name']:30s}  "
                    f"Dr {v['debit_account']:6s} / Cr {v['credit_account']:6s}  "
                    f"conf: {float(v['confidence']):.2f}  [{v['source']}]"
                )
            print()

    elif args.csv:
        print(f"\n{'='*60}")
        print(f"  OPERATION STRANGLER FIG — Brain Transplant")
        print(f"  Source: {args.csv}")
        print(f"  Format: {args.csv_type}")
        print(f"  Target: {args.schema}")
        if args.dry_run:
            print(f"  Mode: DRY RUN (no writes)")
        print(f"{'='*60}\n")

        result = train_from_csv(
            csv_path=args.csv,
            schema=args.schema,
            dry_run=args.dry_run,
            csv_type=args.csv_type,
        )

        print(f"  Transactions parsed:  {result['total_transactions']}")
        print(f"  Unique vendors:       {result['unique_vendors']}")
        print(f"  Vendors learned:      {result['vendors_learned']}")
        print(f"  Unmatched accounts:   {result['unmatched']}")
        print(f"  Skipped:              {result['skipped']}")

        if args.dry_run:
            print(f"\n  --- DRY RUN DETAILS ---\n")
            for d in result["details"]:
                status = d["status"]
                if status == "LEARNED":
                    print(
                        f"    LEARN: {d['vendor']:30s} → "
                        f"Dr {d['debit']:6s} / Cr {d['credit']:6s}  "
                        f"conf: {d['confidence']:.2f}  "
                        f"({d['transactions']} txns, ${d['total_amount']:,.2f})"
                    )
                else:
                    print(
                        f"    SKIP:  {d['vendor']:30s} → "
                        f"QBO: '{d['qbo_account']}'  "
                        f"({d['transactions']} txns, ${d['total_amount']:,.2f})"
                    )
            print()

        print(f"\n  The Strangler Fig has learned {result['vendors_learned']} vendor patterns.")
        if result["unmatched"] > 0:
            print(
                f"  {result['unmatched']} QBO accounts had no match in the CoA. "
                f"Consider running: python -m accounting.import_qbo_coa --csv <coa.csv>"
            )
        print()

    else:
        print("Error: specify --csv <path> or --report")
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
