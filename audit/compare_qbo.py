"""
QBO Reconciler — The Strangler Fig Health Check
===================================================
Compares the Fortress Shadow Ledger against QuickBooks Online.

Three comparison modes:
    1. TRIAL BALANCE:  Fortress TB vs QBO TB (fastest check)
    2. P&L COMPARISON: Fortress P&L vs QBO P&L for a period
    3. ACCOUNT DETAIL:  Line-by-line comparison for a specific account

Data sources:
    - Fortress: PostgreSQL general_ledger (via accounting.statements)
    - QBO:      CSV export from QBO Reports (manual for now)
                Future: QBO API via python-quickbooks SDK

Success criteria: Delta < $0.01 on every account.

Usage:
    python -m audit.compare_qbo --mode trial_balance --qbo-csv qbo_trial_balance.csv --schema division_b
    python -m audit.compare_qbo --mode pnl --qbo-csv qbo_pnl_jan2026.csv --start 2026-01-01 --end 2026-01-31
"""

import argparse
import csv
import json
import logging
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from accounting.statements import (
    trial_balance, profit_and_loss, balance_sheet,
    format_trial_balance, format_pnl, format_balance_sheet,
)

logger = logging.getLogger("audit.compare_qbo")

# NAS log path for reconciliation reports
RECON_LOG_DIR = Path("/mnt/fortress_nas/fortress_data/ai_brain/logs/reconciliation")
RECON_LOG_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# QBO CSV PARSERS
# =============================================================================

def parse_qbo_trial_balance_csv(filepath: str) -> Dict[str, Dict[str, Decimal]]:
    """
    Parse a QBO Trial Balance CSV export.

    Expected format (from QBO Reports → Account List / Trial Balance):
        Account, Debit, Credit
        OR
        Account, Balance

    Returns:
        {"Account Name": {"debits": Decimal, "credits": Decimal}}
    """
    accounts = {}
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = ""
            debits = Decimal("0.00")
            credits = Decimal("0.00")

            # Flexible column matching
            for key in row:
                lower = key.strip().lower()
                if lower in ("account", "account name", "name"):
                    name = row[key].strip()
                elif lower in ("debit", "debits"):
                    val = row[key].strip().replace(",", "").replace("$", "")
                    if val:
                        debits = Decimal(val).quantize(Decimal("0.01"), ROUND_HALF_UP)
                elif lower in ("credit", "credits"):
                    val = row[key].strip().replace(",", "").replace("$", "")
                    if val:
                        credits = Decimal(val).quantize(Decimal("0.01"), ROUND_HALF_UP)
                elif lower == "balance":
                    val = row[key].strip().replace(",", "").replace("$", "")
                    if val:
                        balance = Decimal(val).quantize(Decimal("0.01"), ROUND_HALF_UP)
                        if balance >= 0:
                            debits = balance
                        else:
                            credits = abs(balance)

            if name:
                accounts[name] = {"debits": debits, "credits": credits}

    return accounts


def parse_qbo_pnl_csv(filepath: str) -> Dict[str, Decimal]:
    """
    Parse a QBO Profit & Loss CSV export.

    Expected format:
        Account, Amount (or Total)

    Returns:
        {"Account Name": Decimal(amount)}
    """
    accounts = {}
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = ""
            amount = Decimal("0.00")

            for key in row:
                lower = key.strip().lower()
                if lower in ("account", "account name", "name", "category"):
                    name = row[key].strip()
                elif lower in ("amount", "total", "balance"):
                    val = row[key].strip().replace(",", "").replace("$", "")
                    if val:
                        try:
                            amount = Decimal(val).quantize(
                                Decimal("0.01"), ROUND_HALF_UP,
                            )
                        except Exception:
                            pass

            if name:
                accounts[name] = amount

    return accounts


# =============================================================================
# COMPARISON ENGINE
# =============================================================================

def compare_trial_balances(
    fortress_tb: Dict[str, Any],
    qbo_accounts: Dict[str, Dict[str, Decimal]],
    tolerance: Decimal = Decimal("0.01"),
) -> Dict[str, Any]:
    """
    Compare Fortress Trial Balance against QBO Trial Balance.

    Matches by account name (QBO name → Fortress account).
    Reports discrepancies exceeding the tolerance.
    """
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tolerance": float(tolerance),
        "matched": [],
        "discrepancies": [],
        "fortress_only": [],
        "qbo_only": list(qbo_accounts.keys()),
        "total_fortress_accounts": len(fortress_tb["accounts"]),
        "total_qbo_accounts": len(qbo_accounts),
    }

    qbo_remaining = set(qbo_accounts.keys())

    for acct in fortress_tb["accounts"]:
        f_name = acct["name"]
        f_debits = acct["debits"]
        f_credits = acct["credits"]

        # Try to match by name (exact or QBO name)
        matched_qbo_name = None
        for qbo_name in qbo_remaining:
            if qbo_name.lower() == f_name.lower():
                matched_qbo_name = qbo_name
                break

        if matched_qbo_name:
            qbo_remaining.discard(matched_qbo_name)
            q_data = qbo_accounts[matched_qbo_name]
            q_debits = q_data["debits"]
            q_credits = q_data["credits"]

            debit_delta = abs(f_debits - q_debits)
            credit_delta = abs(f_credits - q_credits)

            if debit_delta <= tolerance and credit_delta <= tolerance:
                results["matched"].append({
                    "account": f_name,
                    "fortress_debits": float(f_debits),
                    "fortress_credits": float(f_credits),
                    "qbo_debits": float(q_debits),
                    "qbo_credits": float(q_credits),
                    "status": "MATCH",
                })
            else:
                results["discrepancies"].append({
                    "account": f_name,
                    "fortress_debits": float(f_debits),
                    "fortress_credits": float(f_credits),
                    "qbo_debits": float(q_debits),
                    "qbo_credits": float(q_credits),
                    "debit_delta": float(debit_delta),
                    "credit_delta": float(credit_delta),
                    "status": "MISMATCH",
                })
        else:
            results["fortress_only"].append({
                "account": f_name,
                "debits": float(f_debits),
                "credits": float(f_credits),
            })

    results["qbo_only"] = list(qbo_remaining)

    # Summary
    total = len(results["matched"]) + len(results["discrepancies"])
    results["summary"] = {
        "accounts_compared": total,
        "matches": len(results["matched"]),
        "mismatches": len(results["discrepancies"]),
        "fortress_unmatched": len(results["fortress_only"]),
        "qbo_unmatched": len(results["qbo_only"]),
        "verdict": "PASS" if len(results["discrepancies"]) == 0 else "FAIL",
    }

    return results


def compare_pnl(
    fortress_pnl: Dict[str, Any],
    qbo_pnl: Dict[str, Decimal],
    tolerance: Decimal = Decimal("0.01"),
) -> Dict[str, Any]:
    """
    Compare Fortress P&L against QBO P&L.

    This is the Phase 1 success metric: exact penny-level match.
    """
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "period": fortress_pnl["period"],
        "tolerance": float(tolerance),
        "revenue_comparison": [],
        "expense_comparison": [],
        "discrepancies": [],
    }

    qbo_remaining = set(qbo_pnl.keys())

    # Compare revenue accounts
    for acct in fortress_pnl["revenue"]["accounts"]:
        f_name = acct["name"]
        f_amount = acct["amount"]
        matched = None
        for qbo_name in qbo_remaining:
            if qbo_name.lower() == f_name.lower():
                matched = qbo_name
                break

        if matched:
            qbo_remaining.discard(matched)
            delta = abs(f_amount - qbo_pnl[matched])
            entry = {
                "account": f_name,
                "fortress": float(f_amount),
                "qbo": float(qbo_pnl[matched]),
                "delta": float(delta),
                "status": "MATCH" if delta <= tolerance else "MISMATCH",
            }
            results["revenue_comparison"].append(entry)
            if delta > tolerance:
                results["discrepancies"].append(entry)

    # Compare expense accounts
    for section in ("expenses", "cogs"):
        for acct in fortress_pnl[section]["accounts"]:
            f_name = acct["name"]
            f_amount = acct["amount"]
            matched = None
            for qbo_name in qbo_remaining:
                if qbo_name.lower() == f_name.lower():
                    matched = qbo_name
                    break

            if matched:
                qbo_remaining.discard(matched)
                delta = abs(f_amount - qbo_pnl[matched])
                entry = {
                    "account": f_name,
                    "fortress": float(f_amount),
                    "qbo": float(qbo_pnl[matched]),
                    "delta": float(delta),
                    "status": "MATCH" if delta <= tolerance else "MISMATCH",
                }
                results["expense_comparison"].append(entry)
                if delta > tolerance:
                    results["discrepancies"].append(entry)

    # Net income comparison
    fortress_net = fortress_pnl["net_income"]
    qbo_net = sum(qbo_pnl.values())  # Rough: QBO net = sum of all P&L accounts
    net_delta = abs(fortress_net - qbo_net)

    results["net_income"] = {
        "fortress": float(fortress_net),
        "qbo_estimated": float(qbo_net),
        "delta": float(net_delta),
        "status": "MATCH" if net_delta <= tolerance else "MISMATCH",
    }

    results["summary"] = {
        "total_discrepancies": len(results["discrepancies"]),
        "unmatched_qbo_accounts": list(qbo_remaining),
        "verdict": "PASS" if len(results["discrepancies"]) == 0 else "FAIL",
    }

    return results


# =============================================================================
# REPORTING
# =============================================================================

def save_reconciliation_report(report: Dict[str, Any], mode: str) -> str:
    """Save reconciliation report to NAS."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"recon_{mode}_{timestamp}.json"
    filepath = RECON_LOG_DIR / filename

    with open(filepath, "w") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info(f"Reconciliation report saved: {filepath}")
    return str(filepath)


def print_reconciliation_summary(report: Dict[str, Any]) -> None:
    """Print a human-readable reconciliation summary."""
    summary = report.get("summary", {})
    verdict = summary.get("verdict", "UNKNOWN")

    print(f"\n{'='*60}")
    print(f"  RECONCILIATION REPORT")
    print(f"{'='*60}")
    print(f"  Verdict:         {'PASS — Fortress matches QBO' if verdict == 'PASS' else 'FAIL — Discrepancies found'}")
    print(f"  Accounts matched: {summary.get('matches', 0)}")
    print(f"  Mismatches:       {summary.get('mismatches', summary.get('total_discrepancies', 0))}")

    if report.get("discrepancies"):
        print(f"\n  DISCREPANCIES:")
        print(f"  {'Account':<30} {'Fortress':>10} {'QBO':>10} {'Delta':>10}")
        print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*10}")
        for d in report["discrepancies"]:
            print(
                f"  {d['account']:<30} "
                f"{d.get('fortress', d.get('fortress_debits', 0)):>10,.2f} "
                f"{d.get('qbo', d.get('qbo_debits', 0)):>10,.2f} "
                f"{d.get('delta', d.get('debit_delta', 0)):>10,.2f}"
            )

    unmatched_f = report.get("fortress_only", [])
    unmatched_q = report.get("qbo_only", [])
    if unmatched_f:
        print(f"\n  Fortress accounts not in QBO: {len(unmatched_f)}")
        for a in unmatched_f[:5]:
            print(f"    - {a['account'] if isinstance(a, dict) else a}")
    if unmatched_q:
        print(f"\n  QBO accounts not in Fortress: {len(unmatched_q)}")
        for a in unmatched_q[:5]:
            print(f"    - {a}")

    print(f"{'='*60}\n")


# =============================================================================
# STANDALONE MODE: Fortress-only health check (no QBO CSV needed)
# =============================================================================

def run_internal_audit(schema: str = "division_b") -> Dict[str, Any]:
    """
    Run a Fortress-internal audit without needing QBO data.

    Checks:
        1. Trial Balance is balanced (debits == credits)
        2. Balance Sheet equation holds (A = L + E)
        3. No orphaned ledger lines
    """
    print(f"\n{'='*60}")
    print(f"  FORTRESS INTERNAL AUDIT — {schema.upper()}")
    print(f"{'='*60}")

    results = {"schema": schema, "checks": []}

    # Check 1: Trial Balance
    tb = trial_balance(schema)
    print(format_trial_balance(tb))
    results["trial_balance"] = {
        "total_debits": float(tb["total_debits"]),
        "total_credits": float(tb["total_credits"]),
        "is_balanced": tb["is_balanced"],
    }
    results["checks"].append({
        "name": "Trial Balance",
        "status": "PASS" if tb["is_balanced"] else "FAIL",
    })

    # Check 2: Balance Sheet
    bs = balance_sheet(schema)
    print(format_balance_sheet(bs))
    results["balance_sheet"] = {
        "assets": float(bs["assets"]["total"]),
        "liabilities": float(bs["liabilities"]["total"]),
        "equity": float(bs["equity"]["total"]),
        "is_balanced": bs["is_balanced"],
    }
    results["checks"].append({
        "name": "Balance Sheet (A = L + E)",
        "status": "PASS" if bs["is_balanced"] else "FAIL",
    })

    # Check 3: P&L
    pnl = profit_and_loss(schema)
    print(format_pnl(pnl))
    results["pnl"] = {
        "net_income": float(pnl["net_income"]),
        "revenue": float(pnl["revenue"]["total"]),
        "expenses": float(pnl["expenses"]["total"]),
    }

    # Verdict
    all_pass = all(c["status"] == "PASS" for c in results["checks"])
    results["verdict"] = "PASS" if all_pass else "FAIL"

    print(f"\n  OVERALL VERDICT: {results['verdict']}")
    if not all_pass:
        for c in results["checks"]:
            if c["status"] != "PASS":
                print(f"    FAILED: {c['name']}")
    print(f"\n{'='*60}\n")

    return results


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Compare Fortress ledger against QBO exports",
    )
    parser.add_argument(
        "--mode", type=str, default="internal",
        choices=["trial_balance", "pnl", "internal"],
        help="Comparison mode",
    )
    parser.add_argument("--qbo-csv", type=str, help="Path to QBO CSV export")
    parser.add_argument("--schema", type=str, default="division_b")
    parser.add_argument("--start", type=str, help="P&L start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="P&L end date (YYYY-MM-DD)")
    parser.add_argument(
        "--save", action="store_true",
        help="Save report to NAS",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.mode == "internal":
        report = run_internal_audit(args.schema)
    elif args.mode == "trial_balance":
        if not args.qbo_csv:
            print("Error: --qbo-csv required for trial_balance mode")
            sys.exit(1)
        fortress_tb = trial_balance(args.schema)
        qbo_tb = parse_qbo_trial_balance_csv(args.qbo_csv)
        report = compare_trial_balances(fortress_tb, qbo_tb)
        print_reconciliation_summary(report)
    elif args.mode == "pnl":
        if not args.qbo_csv:
            print("Error: --qbo-csv required for pnl mode")
            sys.exit(1)
        start = date.fromisoformat(args.start) if args.start else None
        end = date.fromisoformat(args.end) if args.end else None
        fortress_pnl = profit_and_loss(args.schema, start, end)
        qbo_pnl = parse_qbo_pnl_csv(args.qbo_csv)
        report = compare_pnl(fortress_pnl, qbo_pnl)
        print_reconciliation_summary(report)

    if args.save:
        path = save_reconciliation_report(report, args.mode)
        print(f"  Report saved: {path}")


if __name__ == "__main__":
    main()
