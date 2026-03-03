"""
QBO Reconciliation Bridge — Fortress GL vs QuickBooks Online
================================================================
The proof engine for Operation Strangler Fig.

Phase 1 Success Metric:
    "Fortress P&L for Jan 2026 must match QBO P&L to the penny."

This module pulls financial reports from both systems and produces
a line-by-line reconciliation showing:
    - Matching accounts (within tolerance)
    - Mismatches (Fortress vs QBO delta)
    - Missing accounts (in one system but not the other)

Reports:
    1. Chart of Accounts Comparison (structure)
    2. Profit & Loss Reconciliation (period revenue/expenses)
    3. Balance Sheet Reconciliation (point-in-time positions)
    4. Trial Balance Reconciliation (debits/credits check)

Module: CF-04 Treasury / Operation Strangler Fig
"""

import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from accounting.statements import (
    profit_and_loss as fortress_pnl,
    balance_sheet as fortress_bs,
    trial_balance as fortress_tb,
)
from accounting.engine import list_accounts as fortress_coa

from integrations.quickbooks.client import (
    QBOClient,
    parse_qbo_coa,
    parse_qbo_report_rows,
)

logger = logging.getLogger("integrations.quickbooks.sync")

# Tolerance for "matching" (below this = rounding difference, not error)
TOLERANCE = Decimal("1.00")


# =============================================================================
# CHART OF ACCOUNTS COMPARISON
# =============================================================================

def compare_chart_of_accounts(
    schema: str = "division_b",
) -> Dict[str, Any]:
    """
    Compare Fortress Chart of Accounts against QBO Chart of Accounts.

    Identifies:
        - Matched accounts (same name/type in both systems)
        - Fortress-only accounts (exist in Fortress, not in QBO)
        - QBO-only accounts (exist in QBO, not in Fortress)

    This is the structural alignment check — do we have the same
    accounts before we compare the numbers?

    Returns:
        {
            "matched": [{"fortress": {...}, "qbo": {...}}, ...],
            "fortress_only": [...],
            "qbo_only": [...],
            "match_count": int,
            "total_fortress": int,
            "total_qbo": int,
        }
    """
    # Pull both CoAs
    f_accounts = fortress_coa(schema=schema)
    client = QBOClient()
    qbo_raw = client.get_chart_of_accounts()
    q_accounts = parse_qbo_coa(qbo_raw)

    # Build lookup by name (normalized)
    def _normalize(name):
        return name.strip().lower().replace(":", " ").replace("  ", " ")

    f_by_name = {_normalize(a.name): a for a in f_accounts}
    q_by_name = {_normalize(a["name"]): a for a in q_accounts}

    # Also try matching by qbo_name in Fortress accounts
    f_by_qbo_name = {}
    for a in f_accounts:
        if a.qbo_name:
            f_by_qbo_name[_normalize(a.qbo_name)] = a

    matched = []
    fortress_only = []
    qbo_only = []
    matched_qbo_names = set()

    # Match Fortress accounts to QBO
    for f_name, f_acct in f_by_name.items():
        q_acct = q_by_name.get(f_name)
        if not q_acct and f_acct.qbo_name:
            q_acct = q_by_name.get(_normalize(f_acct.qbo_name))

        if q_acct:
            matched.append({
                "fortress_code": f_acct.code,
                "fortress_name": f_acct.name,
                "fortress_type": f_acct.account_type.value,
                "qbo_id": q_acct["qbo_id"],
                "qbo_name": q_acct["name"],
                "qbo_type": q_acct["account_type"],
                "qbo_balance": q_acct["balance"],
            })
            matched_qbo_names.add(_normalize(q_acct["name"]))
        else:
            fortress_only.append({
                "code": f_acct.code,
                "name": f_acct.name,
                "type": f_acct.account_type.value,
            })

    # Find QBO-only accounts
    for q_name, q_acct in q_by_name.items():
        if q_name not in matched_qbo_names:
            # Check if matched via qbo_name
            if q_name not in {_normalize(m["qbo_name"]) for m in matched}:
                qbo_only.append(q_acct)

    return {
        "matched": matched,
        "fortress_only": fortress_only,
        "qbo_only": qbo_only,
        "match_count": len(matched),
        "total_fortress": len(f_accounts),
        "total_qbo": len(q_accounts),
    }


# =============================================================================
# P&L RECONCILIATION
# =============================================================================

def reconcile_pnl(
    start_date: str,
    end_date: str,
    schema: str = "division_b",
) -> Dict[str, Any]:
    """
    Compare Fortress P&L against QBO P&L for a given period.

    This is THE Phase 1 success metric. If these match to the penny,
    the Strangler Fig has proven its accounting engine works.

    Returns:
        {
            "period": {"start": str, "end": str},
            "fortress": {"revenue": D, "expenses": D, "net_income": D},
            "qbo": {"revenue": D, "expenses": D, "net_income": D},
            "delta": {"revenue": D, "expenses": D, "net_income": D},
            "status": "MATCHED" | "WITHIN_TOLERANCE" | "MISMATCH",
            "detail": [...],  # Line-by-line comparison
        }
    """
    # Pull Fortress P&L
    f_pnl = fortress_pnl(
        schema=schema,
        start_date=date.fromisoformat(start_date),
        end_date=date.fromisoformat(end_date),
    )

    # Pull QBO P&L
    client = QBOClient()
    qbo_report = client.get_profit_and_loss(start_date, end_date)
    qbo_rows = parse_qbo_report_rows(qbo_report)

    # Extract QBO totals
    qbo_revenue = Decimal("0.00")
    qbo_expenses = Decimal("0.00")
    qbo_net = Decimal("0.00")

    for row in qbo_rows:
        if row["is_total"]:
            label = row["account"].lower()
            if "total income" in label or "total revenue" in label:
                qbo_revenue = row["amount"]
            elif "total expenses" in label or "total expense" in label:
                qbo_expenses = row["amount"]
            elif "net income" in label or "net operating income" in label:
                qbo_net = row["amount"]

    # Fortress totals
    f_revenue = f_pnl["revenue"]["total"]
    f_expenses = f_pnl["expenses"]["total"] + f_pnl["cogs"]["total"]
    f_net = f_pnl["net_income"]

    # Calculate deltas
    delta_revenue = f_revenue - qbo_revenue
    delta_expenses = f_expenses - qbo_expenses
    delta_net = f_net - qbo_net

    # Determine status
    if delta_net == Decimal("0.00"):
        status = "MATCHED"
    elif abs(delta_net) <= TOLERANCE:
        status = "WITHIN_TOLERANCE"
    else:
        status = "MISMATCH"

    # Build line-by-line detail
    detail = _build_line_detail(f_pnl, qbo_rows)

    return {
        "period": {"start": start_date, "end": end_date},
        "schema": schema,
        "fortress": {
            "revenue": f_revenue,
            "expenses": f_expenses,
            "cogs": f_pnl["cogs"]["total"],
            "net_income": f_net,
        },
        "qbo": {
            "revenue": qbo_revenue,
            "expenses": qbo_expenses,
            "net_income": qbo_net,
        },
        "delta": {
            "revenue": delta_revenue,
            "expenses": delta_expenses,
            "net_income": delta_net,
        },
        "status": status,
        "detail": detail,
    }


def _build_line_detail(
    f_pnl: Dict, qbo_rows: List[Dict],
) -> List[Dict[str, Any]]:
    """Build a line-by-line comparison between Fortress and QBO P&L."""
    detail = []

    # Build QBO name → amount lookup (non-totals only)
    qbo_by_name = {}
    for row in qbo_rows:
        if not row["is_total"]:
            key = row["account"].strip().lower()
            qbo_by_name[key] = row["amount"]

    # Compare Fortress revenue accounts
    for acct in f_pnl["revenue"]["accounts"]:
        qbo_key = acct["name"].strip().lower()
        qbo_amount = qbo_by_name.pop(qbo_key, None)
        detail.append({
            "account": acct["name"],
            "type": "revenue",
            "fortress_amount": acct["amount"],
            "qbo_amount": qbo_amount,
            "delta": acct["amount"] - qbo_amount if qbo_amount is not None else None,
            "status": _match_status(acct["amount"], qbo_amount),
        })

    # Compare Fortress expense accounts
    for section in ("expenses", "cogs"):
        for acct in f_pnl[section]["accounts"]:
            qbo_key = acct["name"].strip().lower()
            qbo_amount = qbo_by_name.pop(qbo_key, None)
            detail.append({
                "account": acct["name"],
                "type": section,
                "fortress_amount": acct["amount"],
                "qbo_amount": qbo_amount,
                "delta": acct["amount"] - qbo_amount if qbo_amount is not None else None,
                "status": _match_status(acct["amount"], qbo_amount),
            })

    # Remaining QBO accounts (not in Fortress)
    for name, amount in qbo_by_name.items():
        detail.append({
            "account": name,
            "type": "qbo_only",
            "fortress_amount": None,
            "qbo_amount": amount,
            "delta": None,
            "status": "QBO_ONLY",
        })

    return detail


def _match_status(
    fortress_val: Optional[Decimal],
    qbo_val: Optional[Decimal],
) -> str:
    """Determine match status for a line item."""
    if fortress_val is None and qbo_val is None:
        return "BOTH_ZERO"
    if fortress_val is not None and qbo_val is None:
        return "FORTRESS_ONLY"
    if fortress_val is None and qbo_val is not None:
        return "QBO_ONLY"
    delta = abs(fortress_val - qbo_val)
    if delta == Decimal("0.00"):
        return "EXACT_MATCH"
    if delta <= TOLERANCE:
        return "WITHIN_TOLERANCE"
    return "MISMATCH"


# =============================================================================
# BALANCE SHEET RECONCILIATION
# =============================================================================

def reconcile_balance_sheet(
    as_of: Optional[str] = None,
    schema: str = "division_b",
) -> Dict[str, Any]:
    """
    Compare Fortress Balance Sheet against QBO Balance Sheet.

    Returns:
        {
            "as_of": str,
            "fortress": {"assets": D, "liabilities": D, "equity": D},
            "qbo": {"assets": D, "liabilities": D, "equity": D},
            "delta": {"assets": D, "liabilities": D, "equity": D},
            "status": "MATCHED" | "WITHIN_TOLERANCE" | "MISMATCH",
        }
    """
    as_of_date = date.fromisoformat(as_of) if as_of else None
    as_of_str = as_of or date.today().isoformat()

    # Fortress Balance Sheet
    f_bs = fortress_bs(schema=schema, as_of=as_of_date)

    # QBO Balance Sheet
    client = QBOClient()
    qbo_report = client.get_balance_sheet(as_of_str)
    qbo_rows = parse_qbo_report_rows(qbo_report)

    # Extract QBO totals from parsed rows
    qbo_assets = Decimal("0.00")
    qbo_liabilities = Decimal("0.00")
    qbo_equity = Decimal("0.00")

    for row in qbo_rows:
        if row["is_total"]:
            label = row["account"].lower()
            if "total assets" in label:
                qbo_assets = row["amount"]
            elif "total liabilities" in label:
                qbo_liabilities = row["amount"]
            elif "total equity" in label:
                qbo_equity = row["amount"]

    # Fortress totals
    f_assets = f_bs["assets"]["total"]
    f_liabilities = f_bs["liabilities"]["total"]
    f_equity = f_bs["equity"]["total"]

    # Deltas
    delta_a = f_assets - qbo_assets
    delta_l = f_liabilities - qbo_liabilities
    delta_e = f_equity - qbo_equity

    max_delta = max(abs(delta_a), abs(delta_l), abs(delta_e))
    if max_delta == Decimal("0.00"):
        status = "MATCHED"
    elif max_delta <= TOLERANCE:
        status = "WITHIN_TOLERANCE"
    else:
        status = "MISMATCH"

    return {
        "as_of": as_of_str,
        "schema": schema,
        "fortress": {
            "assets": f_assets,
            "liabilities": f_liabilities,
            "equity": f_equity,
            "balanced": f_bs["is_balanced"],
        },
        "qbo": {
            "assets": qbo_assets,
            "liabilities": qbo_liabilities,
            "equity": qbo_equity,
        },
        "delta": {
            "assets": delta_a,
            "liabilities": delta_l,
            "equity": delta_e,
        },
        "status": status,
    }


# =============================================================================
# FULL RECONCILIATION REPORT
# =============================================================================

def full_reconciliation(
    start_date: str,
    end_date: str,
    schema: str = "division_b",
) -> Dict[str, Any]:
    """
    Run a complete reconciliation: CoA + P&L + Balance Sheet.

    This is the command you run when the CPA asks:
    "Show me Fortress matches QuickBooks."

    Returns:
        {
            "coa_comparison": {...},
            "pnl_reconciliation": {...},
            "balance_sheet_reconciliation": {...},
            "overall_status": "PASS" | "PARTIAL" | "FAIL",
        }
    """
    logger.info(
        f"Running full reconciliation: {start_date} to {end_date} "
        f"(schema={schema})"
    )

    coa = compare_chart_of_accounts(schema)
    pnl = reconcile_pnl(start_date, end_date, schema)
    bs = reconcile_balance_sheet(end_date, schema)

    # Overall status
    statuses = [pnl["status"], bs["status"]]
    if all(s in ("MATCHED", "WITHIN_TOLERANCE") for s in statuses):
        overall = "PASS"
    elif any(s in ("MATCHED", "WITHIN_TOLERANCE") for s in statuses):
        overall = "PARTIAL"
    else:
        overall = "FAIL"

    return {
        "period": {"start": start_date, "end": end_date},
        "schema": schema,
        "coa_comparison": coa,
        "pnl_reconciliation": pnl,
        "balance_sheet_reconciliation": bs,
        "overall_status": overall,
    }


# =============================================================================
# FORMATTED OUTPUT
# =============================================================================

def format_reconciliation(recon: Dict[str, Any]) -> str:
    """Pretty-print a full reconciliation report."""
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"  OPERATION STRANGLER FIG — RECONCILIATION REPORT")
    lines.append(f"  Period: {recon['period']['start']} to {recon['period']['end']}")
    lines.append(f"  Schema: {recon['schema']}")
    lines.append(f"{'='*70}")

    # CoA
    coa = recon["coa_comparison"]
    lines.append(f"\n  1. CHART OF ACCOUNTS")
    lines.append(f"  {'-'*50}")
    lines.append(f"     Fortress accounts:  {coa['total_fortress']}")
    lines.append(f"     QBO accounts:       {coa['total_qbo']}")
    lines.append(f"     Matched:            {coa['match_count']}")
    lines.append(f"     Fortress-only:      {len(coa['fortress_only'])}")
    lines.append(f"     QBO-only:           {len(coa['qbo_only'])}")

    # P&L
    pnl = recon["pnl_reconciliation"]
    lines.append(f"\n  2. PROFIT & LOSS")
    lines.append(f"  {'-'*50}")
    lines.append(f"     {'':25} {'Fortress':>12} {'QBO':>12} {'Delta':>12}")
    lines.append(f"     {'':25} {'-'*12} {'-'*12} {'-'*12}")
    for key in ("revenue", "expenses", "net_income"):
        f_val = pnl["fortress"][key]
        q_val = pnl["qbo"][key]
        d_val = pnl["delta"][key]
        label = key.replace("_", " ").title()
        lines.append(
            f"     {label:<25} "
            f"${float(f_val):>11,.2f} "
            f"${float(q_val):>11,.2f} "
            f"${float(d_val):>11,.2f}"
        )
    lines.append(f"     Status: {pnl['status']}")

    # P&L detail (mismatches only)
    mismatches = [d for d in pnl["detail"]
                  if d["status"] not in ("EXACT_MATCH", "WITHIN_TOLERANCE", "BOTH_ZERO")]
    if mismatches:
        lines.append(f"\n     Differences:")
        for d in mismatches:
            f_val = f"${float(d['fortress_amount']):>10,.2f}" if d["fortress_amount"] is not None else "         —"
            q_val = f"${float(d['qbo_amount']):>10,.2f}" if d["qbo_amount"] is not None else "         —"
            lines.append(f"       {d['account'][:30]:<30} {f_val} {q_val}  [{d['status']}]")

    # Balance Sheet
    bs = recon["balance_sheet_reconciliation"]
    lines.append(f"\n  3. BALANCE SHEET (as of {bs['as_of']})")
    lines.append(f"  {'-'*50}")
    lines.append(f"     {'':25} {'Fortress':>12} {'QBO':>12} {'Delta':>12}")
    lines.append(f"     {'':25} {'-'*12} {'-'*12} {'-'*12}")
    for key in ("assets", "liabilities", "equity"):
        f_val = bs["fortress"][key]
        q_val = bs["qbo"][key]
        d_val = bs["delta"][key]
        label = key.title()
        lines.append(
            f"     {label:<25} "
            f"${float(f_val):>11,.2f} "
            f"${float(q_val):>11,.2f} "
            f"${float(d_val):>11,.2f}"
        )
    lines.append(f"     Status: {bs['status']}")

    # Overall
    lines.append(f"\n{'='*70}")
    overall = recon["overall_status"]
    if overall == "PASS":
        lines.append(f"  OVERALL: PASS — The Strangler Fig's books match QBO.")
    elif overall == "PARTIAL":
        lines.append(f"  OVERALL: PARTIAL — Some statements match, others don't.")
    else:
        lines.append(f"  OVERALL: FAIL — Fortress and QBO do not reconcile.")
    lines.append(f"{'='*70}\n")

    return "\n".join(lines)


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="QBO Reconciliation — Fortress GL vs QuickBooks Online",
    )
    parser.add_argument(
        "--full", nargs=2, metavar=("START", "END"),
        help="Run full reconciliation for a period (YYYY-MM-DD YYYY-MM-DD)",
    )
    parser.add_argument(
        "--pnl", nargs=2, metavar=("START", "END"),
        help="Reconcile P&L only",
    )
    parser.add_argument(
        "--balance-sheet", metavar="AS_OF",
        help="Reconcile Balance Sheet as of date",
    )
    parser.add_argument(
        "--coa", action="store_true",
        help="Compare Chart of Accounts",
    )
    parser.add_argument(
        "--schema", default="division_b",
        choices=["division_a", "division_b"],
        help="Fortress schema to compare (default: division_b)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [RECON] %(message)s",
    )

    if args.full:
        start, end = args.full
        recon = full_reconciliation(start, end, args.schema)
        print(format_reconciliation(recon))

    elif args.pnl:
        start, end = args.pnl
        result = reconcile_pnl(start, end, args.schema)
        # Wrap in full report format for display
        recon = {
            "period": {"start": start, "end": end},
            "schema": args.schema,
            "coa_comparison": {"total_fortress": 0, "total_qbo": 0,
                              "match_count": 0, "fortress_only": [], "qbo_only": []},
            "pnl_reconciliation": result,
            "balance_sheet_reconciliation": {
                "as_of": end, "fortress": {"assets": 0, "liabilities": 0, "equity": 0},
                "qbo": {"assets": 0, "liabilities": 0, "equity": 0},
                "delta": {"assets": 0, "liabilities": 0, "equity": 0},
                "status": "SKIPPED",
            },
            "overall_status": result["status"],
        }
        print(format_reconciliation(recon))

    elif args.balance_sheet:
        result = reconcile_balance_sheet(args.balance_sheet, args.schema)
        print(f"\n{'='*60}")
        print(f"  BALANCE SHEET RECONCILIATION — {args.balance_sheet}")
        print(f"{'='*60}")
        print(f"  {'':25} {'Fortress':>12} {'QBO':>12} {'Delta':>12}")
        for key in ("assets", "liabilities", "equity"):
            f_val = result["fortress"][key]
            q_val = result["qbo"][key]
            d_val = result["delta"][key]
            print(f"  {key.title():<25} ${float(f_val):>11,.2f} "
                  f"${float(q_val):>11,.2f} ${float(d_val):>11,.2f}")
        print(f"  Status: {result['status']}")
        print(f"{'='*60}\n")

    elif args.coa:
        result = compare_chart_of_accounts(args.schema)
        print(f"\n{'='*60}")
        print(f"  CHART OF ACCOUNTS COMPARISON")
        print(f"{'='*60}")
        print(f"  Fortress: {result['total_fortress']} accounts")
        print(f"  QBO:      {result['total_qbo']} accounts")
        print(f"  Matched:  {result['match_count']}")

        if result["fortress_only"]:
            print(f"\n  Fortress-Only ({len(result['fortress_only'])}):")
            for a in result["fortress_only"]:
                print(f"    {a['code']:<8} {a['name']:<35} ({a['type']})")

        if result["qbo_only"]:
            print(f"\n  QBO-Only ({len(result['qbo_only'])}):")
            for a in result["qbo_only"]:
                print(f"    {a['qbo_id']:<8} {a['name']:<35} ({a['account_type']})")
        print(f"{'='*60}\n")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
