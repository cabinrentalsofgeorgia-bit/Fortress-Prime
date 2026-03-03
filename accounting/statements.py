"""
Financial Statements — The Proof That Fortress Matches QBO
=============================================================
Generates the three core statements that your CPA needs:

    1. Trial Balance     — Debits == Credits? (sanity check)
    2. Profit & Loss     — Revenue minus Expenses for a period
    3. Balance Sheet     — Assets = Liabilities + Equity (at a point in time)

The Success Metric for Phase 1 of Operation Strangler Fig:
    Fortress P&L for Jan 2026 must match QBO P&L for Jan 2026, to the penny.
"""

import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

logger = logging.getLogger("accounting.statements")


# =============================================================================
# DATABASE
# =============================================================================

def _connect():
    import psycopg2
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )


# =============================================================================
# TRIAL BALANCE
# =============================================================================

def trial_balance(
    schema: str = "division_b",
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Generate a Trial Balance.

    The Trial Balance is the first checkpoint: sum(all debits) MUST equal
    sum(all credits). If they don't, something is broken in the engine.

    Returns:
        {
            "as_of": "2026-02-09",
            "accounts": [{"code", "name", "type", "debits", "credits", "balance"}],
            "total_debits": Decimal,
            "total_credits": Decimal,
            "is_balanced": bool,
            "imbalance": Decimal,
        }
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            date_filter = ""
            params = []
            if as_of:
                date_filter = "AND je.entry_date <= %s"
                params.append(as_of)

            cur.execute(f"""
                SELECT
                    coa.code,
                    coa.name,
                    coa.account_type,
                    coa.normal_balance,
                    COALESCE(SUM(gl.debit), 0) AS total_debits,
                    COALESCE(SUM(gl.credit), 0) AS total_credits
                FROM {schema}.chart_of_accounts coa
                LEFT JOIN {schema}.general_ledger gl
                    ON gl.account_code = coa.code
                LEFT JOIN {schema}.journal_entries je
                    ON gl.journal_entry_id = je.entry_id
                    {date_filter}
                WHERE coa.is_active = TRUE
                GROUP BY coa.code, coa.name, coa.account_type, coa.normal_balance
                HAVING COALESCE(SUM(gl.debit), 0) != 0
                    OR COALESCE(SUM(gl.credit), 0) != 0
                ORDER BY coa.code
            """, params)

            rows = cur.fetchall()

        accounts = []
        grand_debit = Decimal("0.00")
        grand_credit = Decimal("0.00")

        for row in rows:
            debits = Decimal(str(row[4])).quantize(Decimal("0.01"), ROUND_HALF_UP)
            credits = Decimal(str(row[5])).quantize(Decimal("0.01"), ROUND_HALF_UP)
            normal = row[3]

            # Account balance follows normal balance convention
            if normal == "debit":
                balance = debits - credits
            else:
                balance = credits - debits

            accounts.append({
                "code": row[0],
                "name": row[1],
                "account_type": row[2],
                "normal_balance": normal,
                "debits": debits,
                "credits": credits,
                "balance": balance,
            })
            grand_debit += debits
            grand_credit += credits

        imbalance = grand_debit - grand_credit
        return {
            "as_of": (as_of or date.today()).isoformat(),
            "schema": schema,
            "accounts": accounts,
            "total_debits": grand_debit,
            "total_credits": grand_credit,
            "is_balanced": imbalance == Decimal("0.00"),
            "imbalance": imbalance,
        }
    finally:
        conn.close()


# =============================================================================
# PROFIT & LOSS (Income Statement)
# =============================================================================

def profit_and_loss(
    schema: str = "division_b",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Generate a Profit & Loss (Income Statement) for a date range.

    P&L = Revenue - Expenses - COGS

    This is the statement you compare against QBO. If they match
    to the penny, Phase 1 of the Strangler Fig is complete.

    Returns:
        {
            "period": {"start": "2026-01-01", "end": "2026-01-31"},
            "revenue": {"total": Decimal, "accounts": [...]},
            "expenses": {"total": Decimal, "accounts": [...]},
            "cogs": {"total": Decimal, "accounts": [...]},
            "net_income": Decimal,
            "net_income_formatted": "$X,XXX.XX"
        }
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            date_clause = ""
            params = []
            if start_date:
                date_clause += " AND je.entry_date >= %s"
                params.append(start_date)
            if end_date:
                date_clause += " AND je.entry_date <= %s"
                params.append(end_date)

            cur.execute(f"""
                SELECT
                    coa.code,
                    coa.name,
                    coa.account_type,
                    coa.normal_balance,
                    COALESCE(SUM(gl.debit), 0) AS total_debits,
                    COALESCE(SUM(gl.credit), 0) AS total_credits
                FROM {schema}.chart_of_accounts coa
                JOIN {schema}.general_ledger gl ON gl.account_code = coa.code
                JOIN {schema}.journal_entries je ON gl.journal_entry_id = je.entry_id
                WHERE coa.account_type IN ('revenue', 'expense', 'cogs')
                    AND je.is_posted = TRUE
                    {date_clause}
                GROUP BY coa.code, coa.name, coa.account_type, coa.normal_balance
                ORDER BY coa.code
            """, params)
            rows = cur.fetchall()

        revenue_accounts = []
        expense_accounts = []
        cogs_accounts = []
        total_revenue = Decimal("0.00")
        total_expenses = Decimal("0.00")
        total_cogs = Decimal("0.00")

        for row in rows:
            code, name, acct_type, normal, debits_raw, credits_raw = row
            debits = Decimal(str(debits_raw)).quantize(Decimal("0.01"), ROUND_HALF_UP)
            credits = Decimal(str(credits_raw)).quantize(Decimal("0.01"), ROUND_HALF_UP)

            # Revenue: normal credit balance (credits - debits)
            # Expenses/COGS: normal debit balance (debits - credits)
            if acct_type == "revenue":
                balance = credits - debits
                total_revenue += balance
                revenue_accounts.append({
                    "code": code, "name": name, "amount": balance,
                })
            elif acct_type == "expense":
                balance = debits - credits
                total_expenses += balance
                expense_accounts.append({
                    "code": code, "name": name, "amount": balance,
                })
            elif acct_type == "cogs":
                balance = debits - credits
                total_cogs += balance
                cogs_accounts.append({
                    "code": code, "name": name, "amount": balance,
                })

        net_income = total_revenue - total_expenses - total_cogs

        return {
            "period": {
                "start": (start_date or date(2026, 1, 1)).isoformat(),
                "end": (end_date or date.today()).isoformat(),
            },
            "schema": schema,
            "revenue": {"total": total_revenue, "accounts": revenue_accounts},
            "expenses": {"total": total_expenses, "accounts": expense_accounts},
            "cogs": {"total": total_cogs, "accounts": cogs_accounts},
            "gross_profit": total_revenue - total_cogs,
            "net_income": net_income,
            "net_income_formatted": f"${net_income:,.2f}",
        }
    finally:
        conn.close()


# =============================================================================
# BALANCE SHEET
# =============================================================================

def balance_sheet(
    schema: str = "division_b",
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Generate a Balance Sheet as of a specific date.

    The Accounting Equation: Assets = Liabilities + Equity
    (With net income rolled into Equity as Retained Earnings)

    This is the ultimate proof: if Assets == Liabilities + Equity,
    the Strangler Fig's books are clean.

    Returns:
        {
            "as_of": "2026-02-09",
            "assets": {"total": Decimal, "accounts": [...]},
            "liabilities": {"total": Decimal, "accounts": [...]},
            "equity": {"total": Decimal, "accounts": [...]},
            "net_income": Decimal,   (rolled into equity)
            "total_equity_and_liabilities": Decimal,
            "is_balanced": bool,
        }
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            date_filter = ""
            params = []
            if as_of:
                date_filter = "AND je.entry_date <= %s"
                params.append(as_of)

            cur.execute(f"""
                SELECT
                    coa.code,
                    coa.name,
                    coa.account_type,
                    coa.normal_balance,
                    COALESCE(SUM(gl.debit), 0) AS total_debits,
                    COALESCE(SUM(gl.credit), 0) AS total_credits
                FROM {schema}.chart_of_accounts coa
                LEFT JOIN {schema}.general_ledger gl ON gl.account_code = coa.code
                LEFT JOIN {schema}.journal_entries je ON gl.journal_entry_id = je.entry_id
                    {date_filter}
                WHERE coa.is_active = TRUE
                GROUP BY coa.code, coa.name, coa.account_type, coa.normal_balance
                HAVING COALESCE(SUM(gl.debit), 0) != 0
                    OR COALESCE(SUM(gl.credit), 0) != 0
                ORDER BY coa.code
            """, params)
            rows = cur.fetchall()

        assets = []
        liabilities = []
        equity = []
        total_assets = Decimal("0.00")
        total_liabilities = Decimal("0.00")
        total_equity = Decimal("0.00")

        # Revenue/Expenses contribute to net income → retained earnings
        total_revenue = Decimal("0.00")
        total_expenses = Decimal("0.00")
        total_cogs = Decimal("0.00")

        for row in rows:
            code, name, acct_type, normal, debits_raw, credits_raw = row
            debits = Decimal(str(debits_raw)).quantize(Decimal("0.01"), ROUND_HALF_UP)
            credits = Decimal(str(credits_raw)).quantize(Decimal("0.01"), ROUND_HALF_UP)

            if acct_type == "asset":
                balance = debits - credits
                total_assets += balance
                assets.append({"code": code, "name": name, "amount": balance})
            elif acct_type == "liability":
                balance = credits - debits
                total_liabilities += balance
                liabilities.append({"code": code, "name": name, "amount": balance})
            elif acct_type == "equity":
                balance = credits - debits
                total_equity += balance
                equity.append({"code": code, "name": name, "amount": balance})
            elif acct_type == "revenue":
                total_revenue += (credits - debits)
            elif acct_type in ("expense", "cogs"):
                if acct_type == "cogs":
                    total_cogs += (debits - credits)
                else:
                    total_expenses += (debits - credits)

        # Net income is rolled into equity as "Retained Earnings (Current Period)"
        net_income = total_revenue - total_expenses - total_cogs
        total_equity_with_income = total_equity + net_income

        total_l_and_e = total_liabilities + total_equity_with_income
        is_balanced = total_assets == total_l_and_e

        return {
            "as_of": (as_of or date.today()).isoformat(),
            "schema": schema,
            "assets": {"total": total_assets, "accounts": assets},
            "liabilities": {"total": total_liabilities, "accounts": liabilities},
            "equity": {
                "total": total_equity_with_income,
                "retained_equity": total_equity,
                "accounts": equity,
            },
            "net_income": net_income,
            "total_equity_and_liabilities": total_l_and_e,
            "is_balanced": is_balanced,
            "delta": total_assets - total_l_and_e,
        }
    finally:
        conn.close()


# =============================================================================
# FORMATTED OUTPUT (for Streamlit / Terminal)
# =============================================================================

def format_trial_balance(tb: Dict[str, Any]) -> str:
    """Pretty-print a trial balance."""
    lines = []
    lines.append(f"{'='*72}")
    lines.append(f"  TRIAL BALANCE — {tb['schema'].upper()}")
    lines.append(f"  As of: {tb['as_of']}")
    lines.append(f"{'='*72}")
    lines.append(f"  {'Code':<8} {'Account':<30} {'Debits':>12} {'Credits':>12}")
    lines.append(f"  {'-'*8} {'-'*30} {'-'*12} {'-'*12}")

    for acct in tb["accounts"]:
        lines.append(
            f"  {acct['code']:<8} {acct['name']:<30} "
            f"{acct['debits']:>12,.2f} {acct['credits']:>12,.2f}"
        )

    lines.append(f"  {'-'*8} {'-'*30} {'-'*12} {'-'*12}")
    lines.append(
        f"  {'TOTAL':<8} {'':<30} "
        f"{tb['total_debits']:>12,.2f} {tb['total_credits']:>12,.2f}"
    )
    lines.append(f"{'='*72}")
    status = "BALANCED" if tb["is_balanced"] else f"IMBALANCED (delta: {tb['imbalance']})"
    lines.append(f"  STATUS: {status}")
    lines.append(f"{'='*72}")
    return "\n".join(lines)


def format_pnl(pnl: Dict[str, Any]) -> str:
    """Pretty-print a Profit & Loss statement."""
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"  PROFIT & LOSS — {pnl['schema'].upper()}")
    lines.append(f"  Period: {pnl['period']['start']} to {pnl['period']['end']}")
    lines.append(f"{'='*60}")

    lines.append(f"\n  REVENUE")
    lines.append(f"  {'-'*50}")
    for acct in pnl["revenue"]["accounts"]:
        lines.append(f"    {acct['code']}  {acct['name']:<32} {acct['amount']:>10,.2f}")
    lines.append(f"  {'Total Revenue':<40} {pnl['revenue']['total']:>10,.2f}")

    if pnl["cogs"]["accounts"]:
        lines.append(f"\n  COST OF GOODS SOLD")
        lines.append(f"  {'-'*50}")
        for acct in pnl["cogs"]["accounts"]:
            lines.append(f"    {acct['code']}  {acct['name']:<32} {acct['amount']:>10,.2f}")
        lines.append(f"  {'Total COGS':<40} {pnl['cogs']['total']:>10,.2f}")

    lines.append(f"\n  {'GROSS PROFIT':<40} {pnl['gross_profit']:>10,.2f}")

    lines.append(f"\n  EXPENSES")
    lines.append(f"  {'-'*50}")
    for acct in pnl["expenses"]["accounts"]:
        lines.append(f"    {acct['code']}  {acct['name']:<32} {acct['amount']:>10,.2f}")
    lines.append(f"  {'Total Expenses':<40} {pnl['expenses']['total']:>10,.2f}")

    lines.append(f"\n{'='*60}")
    lines.append(f"  {'NET INCOME':<40} {pnl['net_income_formatted']:>10}")
    lines.append(f"{'='*60}")
    return "\n".join(lines)


def format_balance_sheet(bs: Dict[str, Any]) -> str:
    """Pretty-print a Balance Sheet."""
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"  BALANCE SHEET — {bs['schema'].upper()}")
    lines.append(f"  As of: {bs['as_of']}")
    lines.append(f"{'='*60}")

    lines.append(f"\n  ASSETS")
    lines.append(f"  {'-'*50}")
    for acct in bs["assets"]["accounts"]:
        lines.append(f"    {acct['code']}  {acct['name']:<32} {acct['amount']:>10,.2f}")
    lines.append(f"  {'Total Assets':<40} {bs['assets']['total']:>10,.2f}")

    lines.append(f"\n  LIABILITIES")
    lines.append(f"  {'-'*50}")
    for acct in bs["liabilities"]["accounts"]:
        lines.append(f"    {acct['code']}  {acct['name']:<32} {acct['amount']:>10,.2f}")
    lines.append(f"  {'Total Liabilities':<40} {bs['liabilities']['total']:>10,.2f}")

    lines.append(f"\n  EQUITY")
    lines.append(f"  {'-'*50}")
    for acct in bs["equity"]["accounts"]:
        lines.append(f"    {acct['code']}  {acct['name']:<32} {acct['amount']:>10,.2f}")
    if bs["net_income"] != Decimal("0.00"):
        lines.append(f"    {'':4}  {'Net Income (Current Period)':<32} {bs['net_income']:>10,.2f}")
    lines.append(f"  {'Total Equity':<40} {bs['equity']['total']:>10,.2f}")

    lines.append(f"\n{'='*60}")
    lines.append(
        f"  {'Total L + E':<40} "
        f"{bs['total_equity_and_liabilities']:>10,.2f}"
    )
    status = "BALANCED (A = L + E)" if bs["is_balanced"] else f"IMBALANCED (delta: {bs['delta']})"
    lines.append(f"  STATUS: {status}")
    lines.append(f"{'='*60}")
    return "\n".join(lines)
