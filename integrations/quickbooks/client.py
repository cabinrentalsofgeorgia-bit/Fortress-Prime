"""
QuickBooks Online API Client — Reading the Host's Brain
===========================================================
Read-only client for pulling financial data from QBO.

This is the Strangler Fig's intelligence pipeline:
    - Chart of Accounts (their structure → our structure)
    - Trial Balance (their numbers → our numbers)
    - Profit & Loss (the success metric: must match to the penny)
    - Balance Sheet (assets = liabilities + equity)
    - General Ledger detail (transaction-level reconciliation)
    - Journal Entries (manual entries made by CPA)
    - Vendors, Customers (for mapper training)

All data pulled here is processed locally on the DGX Spark cluster.
No financial data is sent to any external service.

Module: CF-04 Treasury / Operation Strangler Fig
"""

import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests

from integrations.quickbooks.auth import (
    get_auth_header,
    get_api_base_url,
    get_realm_id,
    get_valid_tokens,
)

logger = logging.getLogger("integrations.quickbooks.client")

# Request defaults
TIMEOUT = 30
MINOR_VERSION = 73  # QBO API minor version (latest stable)


# =============================================================================
# BASE API CALLER
# =============================================================================

class QBOClient:
    """
    QuickBooks Online API Client.

    All methods are read-only. This client NEVER modifies QBO data.
    (Write operations will be added in Phase 2 of Strangler Fig.)

    Usage:
        client = QBOClient()
        accounts = client.get_chart_of_accounts()
        pnl = client.get_profit_and_loss("2026-01-01", "2026-01-31")
    """

    def __init__(self):
        self._base_url = get_api_base_url()
        self._realm_id = None

    @property
    def realm_id(self) -> str:
        if not self._realm_id:
            self._realm_id = get_realm_id()
        return self._realm_id

    @property
    def company_url(self) -> str:
        return f"{self._base_url}/v3/company/{self.realm_id}"

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Make an authenticated request to the QBO API.

        Handles:
            - Bearer token injection (auto-refresh if expired)
            - Minor version parameter
            - JSON response parsing
            - Error handling with clear messages

        Returns:
            Parsed JSON response dict.
        """
        url = f"{self.company_url}/{endpoint}"
        headers = get_auth_header()
        headers["Accept"] = "application/json"
        headers["Content-Type"] = "application/json"

        if params is None:
            params = {}
        params["minorversion"] = MINOR_VERSION

        try:
            resp = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=data,
                timeout=TIMEOUT,
            )

            if resp.status_code == 401:
                # Token expired mid-request — force refresh and retry once
                logger.info("QBO returned 401, refreshing token and retrying...")
                from integrations.quickbooks.auth import refresh_access_token
                refresh_access_token()
                headers = get_auth_header()
                headers["Accept"] = "application/json"
                headers["Content-Type"] = "application/json"
                resp = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=data,
                    timeout=TIMEOUT,
                )

            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.HTTPError as e:
            error_body = ""
            try:
                error_body = resp.text[:500]
            except Exception:
                pass
            logger.error(f"QBO API error: {e}\nBody: {error_body}")
            raise
        except Exception as e:
            logger.error(f"QBO API request failed: {e}")
            raise

    def _query(self, query_string: str) -> List[Dict[str, Any]]:
        """
        Execute a QBO query (SQL-like syntax).

        QBO supports a subset of SQL: SELECT, FROM, WHERE, ORDER BY, MAXRESULTS.
        Example: "SELECT * FROM Account WHERE AccountType = 'Expense'"

        Returns:
            List of entity dicts.
        """
        resp = self._request(
            "GET",
            "query",
            params={"query": query_string},
        )

        # QBO wraps results in QueryResponse → Entity type
        query_response = resp.get("QueryResponse", {})

        # Find the entity key (e.g., "Account", "JournalEntry", etc.)
        for key, value in query_response.items():
            if isinstance(value, list):
                return value

        return []

    # =========================================================================
    # CHART OF ACCOUNTS
    # =========================================================================

    def get_chart_of_accounts(
        self,
        active_only: bool = True,
        account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Pull the full Chart of Accounts from QBO.

        Args:
            active_only: Only return active accounts
            account_type: Filter by QBO account type
                (Bank, Accounts Receivable, Other Current Asset, Fixed Asset,
                 Accounts Payable, Credit Card, Other Current Liability,
                 Long Term Liability, Equity, Income, Other Income,
                 Expense, Other Expense, Cost of Goods Sold)

        Returns:
            List of account dicts with keys:
                Id, Name, AccountType, AccountSubType, CurrentBalance,
                FullyQualifiedName, Classification, etc.
        """
        where_clauses = []
        if active_only:
            where_clauses.append("Active = true")
        if account_type:
            where_clauses.append(f"AccountType = '{account_type}'")

        where = " AND ".join(where_clauses) if where_clauses else ""
        query = f"SELECT * FROM Account"
        if where:
            query += f" WHERE {where}"
        query += " ORDERBY AccountType, Name MAXRESULTS 1000"

        accounts = self._query(query)
        logger.info(f"Fetched {len(accounts)} accounts from QBO")
        return accounts

    def get_account_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Find a specific QBO account by name."""
        accounts = self._query(
            f"SELECT * FROM Account WHERE Name = '{name}'"
        )
        return accounts[0] if accounts else None

    # =========================================================================
    # FINANCIAL REPORTS
    # =========================================================================

    def get_profit_and_loss(
        self,
        start_date: str,
        end_date: str,
        summarize_by: str = "Total",
    ) -> Dict[str, Any]:
        """
        Pull a Profit & Loss (Income Statement) report from QBO.

        Args:
            start_date: Period start (YYYY-MM-DD)
            end_date: Period end (YYYY-MM-DD)
            summarize_by: "Total", "Month", "Week", "Days"

        Returns:
            QBO report dict with Header, Columns, Rows structure.
        """
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "summarize_column_by": summarize_by,
        }
        resp = self._request("GET", "reports/ProfitAndLoss", params=params)
        logger.info(f"Fetched QBO P&L: {start_date} to {end_date}")
        return resp

    def get_balance_sheet(
        self,
        as_of: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Pull a Balance Sheet report from QBO.

        Args:
            as_of: Date for balance sheet (YYYY-MM-DD). Default: today.

        Returns:
            QBO report dict.
        """
        params = {}
        if as_of:
            params["date_macro"] = ""
            params["end_date"] = as_of
        resp = self._request("GET", "reports/BalanceSheet", params=params)
        logger.info(f"Fetched QBO Balance Sheet as of {as_of or 'today'}")
        return resp

    def get_trial_balance(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Pull a Trial Balance report from QBO.

        Returns:
            QBO report dict.
        """
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        resp = self._request("GET", "reports/TrialBalance", params=params)
        logger.info("Fetched QBO Trial Balance")
        return resp

    def get_general_ledger(
        self,
        start_date: str,
        end_date: str,
        account: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Pull a General Ledger detail report from QBO.

        Args:
            start_date: Period start
            end_date: Period end
            account: Optional account name or number to filter

        Returns:
            QBO report dict with transaction-level detail.
        """
        params = {
            "start_date": start_date,
            "end_date": end_date,
        }
        if account:
            params["account"] = account
        resp = self._request("GET", "reports/GeneralLedger", params=params)
        logger.info(f"Fetched QBO General Ledger: {start_date} to {end_date}")
        return resp

    # =========================================================================
    # JOURNAL ENTRIES
    # =========================================================================

    def get_journal_entries(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_results: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        Pull journal entries from QBO.

        Args:
            start_date: Filter entries on or after this date
            end_date: Filter entries on or before this date
            max_results: Maximum entries to return

        Returns:
            List of JournalEntry dicts with Line items.
        """
        where_clauses = []
        if start_date:
            where_clauses.append(f"TxnDate >= '{start_date}'")
        if end_date:
            where_clauses.append(f"TxnDate <= '{end_date}'")

        query = "SELECT * FROM JournalEntry"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += f" ORDERBY TxnDate MAXRESULTS {max_results}"

        entries = self._query(query)
        logger.info(f"Fetched {len(entries)} journal entries from QBO")
        return entries

    # =========================================================================
    # VENDORS & CUSTOMERS
    # =========================================================================

    def get_vendors(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Pull all vendors from QBO."""
        where = " WHERE Active = true" if active_only else ""
        vendors = self._query(
            f"SELECT * FROM Vendor{where} MAXRESULTS 1000"
        )
        logger.info(f"Fetched {len(vendors)} vendors from QBO")
        return vendors

    def get_customers(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Pull all customers from QBO."""
        where = " WHERE Active = true" if active_only else ""
        customers = self._query(
            f"SELECT * FROM Customer{where} MAXRESULTS 1000"
        )
        logger.info(f"Fetched {len(customers)} customers from QBO")
        return customers

    # =========================================================================
    # INVOICES & BILLS
    # =========================================================================

    def get_invoices(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_results: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Pull invoices from QBO."""
        where_clauses = []
        if start_date:
            where_clauses.append(f"TxnDate >= '{start_date}'")
        if end_date:
            where_clauses.append(f"TxnDate <= '{end_date}'")

        query = "SELECT * FROM Invoice"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += f" MAXRESULTS {max_results}"

        invoices = self._query(query)
        logger.info(f"Fetched {len(invoices)} invoices from QBO")
        return invoices

    def get_bills(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_results: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Pull bills from QBO."""
        where_clauses = []
        if start_date:
            where_clauses.append(f"TxnDate >= '{start_date}'")
        if end_date:
            where_clauses.append(f"TxnDate <= '{end_date}'")

        query = "SELECT * FROM Bill"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += f" MAXRESULTS {max_results}"

        bills = self._query(query)
        logger.info(f"Fetched {len(bills)} bills from QBO")
        return bills

    # =========================================================================
    # COMPANY INFO
    # =========================================================================

    def get_company_info(self) -> Dict[str, Any]:
        """
        Fetch the company profile from QBO.
        Useful to verify we're connected to the right company.
        """
        resp = self._request("GET", f"companyinfo/{self.realm_id}")
        info = resp.get("CompanyInfo", {})
        logger.info(
            f"Connected to QBO company: {info.get('CompanyName', '?')} "
            f"(realm={self.realm_id})"
        )
        return info


# =============================================================================
# REPORT PARSER — Convert QBO reports to Fortress format
# =============================================================================

def parse_qbo_report_rows(
    report: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Parse a QBO report (P&L, Balance Sheet, Trial Balance) into
    a flat list of rows with account name and amount.

    QBO reports have a nested Row/ColData structure. This flattens
    it into a simple list for comparison with Fortress statements.

    Returns:
        [{"account": "Rental Income", "amount": Decimal("12345.67"), "type": "Income"}, ...]
    """
    rows = []

    def _parse_rows(row_list, section=""):
        for row in row_list:
            row_type = row.get("type", "")

            if row_type == "Section":
                header = row.get("Header", {})
                header_cols = header.get("ColData", [])
                section_name = header_cols[0].get("value", "") if header_cols else section

                # Recurse into nested rows
                nested = row.get("Rows", {}).get("Row", [])
                if nested:
                    _parse_rows(nested, section_name)

                # Section summary
                summary = row.get("Summary", {})
                summary_cols = summary.get("ColData", [])
                if summary_cols and len(summary_cols) >= 2:
                    total_label = summary_cols[0].get("value", "")
                    total_value = summary_cols[-1].get("value", "")
                    if total_value and total_value.strip():
                        try:
                            rows.append({
                                "account": total_label,
                                "amount": Decimal(total_value.replace(",", "")),
                                "section": section_name,
                                "is_total": True,
                            })
                        except Exception:
                            pass

            elif row_type == "Data":
                col_data = row.get("ColData", [])
                if col_data and len(col_data) >= 2:
                    account_name = col_data[0].get("value", "")
                    amount_str = col_data[-1].get("value", "")
                    if amount_str and amount_str.strip():
                        try:
                            rows.append({
                                "account": account_name,
                                "amount": Decimal(amount_str.replace(",", "")),
                                "section": section,
                                "is_total": False,
                            })
                        except Exception:
                            pass

    report_rows = report.get("Rows", {}).get("Row", [])
    _parse_rows(report_rows)

    return rows


def parse_qbo_coa(accounts: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Convert QBO Chart of Accounts into a flat comparison format.

    Returns:
        [{
            "qbo_id": "123",
            "name": "Rental Income",
            "fully_qualified_name": "Income:Rental Income",
            "account_type": "Income",
            "account_sub_type": "ServiceFeeIncome",
            "balance": Decimal("12345.67"),
            "active": True,
        }, ...]
    """
    parsed = []
    for acct in accounts:
        try:
            balance = Decimal(str(acct.get("CurrentBalance", 0))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP,
            )
        except Exception:
            balance = Decimal("0.00")

        parsed.append({
            "qbo_id": str(acct.get("Id", "")),
            "name": acct.get("Name", ""),
            "fully_qualified_name": acct.get("FullyQualifiedName", ""),
            "account_type": acct.get("AccountType", ""),
            "account_sub_type": acct.get("AccountSubType", ""),
            "balance": balance,
            "active": acct.get("Active", True),
        })

    return parsed


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="QBO API Client — Read QuickBooks Data",
    )
    parser.add_argument("--coa", action="store_true", help="Fetch Chart of Accounts")
    parser.add_argument("--pnl", nargs=2, metavar=("START", "END"), help="Fetch P&L report")
    parser.add_argument("--balance-sheet", metavar="AS_OF", nargs="?", const="today", help="Fetch Balance Sheet")
    parser.add_argument("--trial-balance", action="store_true", help="Fetch Trial Balance")
    parser.add_argument("--journal-entries", nargs=2, metavar=("START", "END"), help="Fetch Journal Entries")
    parser.add_argument("--vendors", action="store_true", help="Fetch Vendors")
    parser.add_argument("--company", action="store_true", help="Fetch Company Info")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [QBO] %(message)s",
    )

    client = QBOClient()

    if args.company:
        info = client.get_company_info()
        print(f"\n{'='*60}")
        print(f"  QBO Company: {info.get('CompanyName', '?')}")
        print(f"  Legal Name:  {info.get('LegalName', '?')}")
        print(f"  Country:     {info.get('Country', '?')}")
        print(f"  Industry:    {info.get('IndustryType', '?')}")
        print(f"{'='*60}\n")

    elif args.coa:
        accounts = client.get_chart_of_accounts()
        if args.json:
            print(json.dumps(accounts, indent=2, default=str))
        else:
            parsed = parse_qbo_coa(accounts)
            print(f"\n{'='*70}")
            print(f"  QBO CHART OF ACCOUNTS ({len(parsed)} accounts)")
            print(f"{'='*70}")
            print(f"  {'ID':<6} {'Type':<22} {'Name':<30} {'Balance':>12}")
            print(f"  {'-'*6} {'-'*22} {'-'*30} {'-'*12}")
            for acct in parsed:
                print(
                    f"  {acct['qbo_id']:<6} "
                    f"{acct['account_type']:<22} "
                    f"{acct['name'][:30]:<30} "
                    f"{acct['balance']:>12,.2f}"
                )
            print(f"{'='*70}\n")

    elif args.pnl:
        start, end = args.pnl
        report = client.get_profit_and_loss(start, end)
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            rows = parse_qbo_report_rows(report)
            print(f"\n{'='*60}")
            print(f"  QBO PROFIT & LOSS: {start} to {end}")
            print(f"{'='*60}")
            for row in rows:
                prefix = "  >> " if row["is_total"] else "     "
                print(f"{prefix}{row['account']:<40} {row['amount']:>12,.2f}")
            print(f"{'='*60}\n")

    elif args.balance_sheet is not None:
        as_of = None if args.balance_sheet == "today" else args.balance_sheet
        report = client.get_balance_sheet(as_of)
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            rows = parse_qbo_report_rows(report)
            print(f"\n{'='*60}")
            print(f"  QBO BALANCE SHEET: {as_of or 'today'}")
            print(f"{'='*60}")
            for row in rows:
                prefix = "  >> " if row["is_total"] else "     "
                print(f"{prefix}{row['account']:<40} {row['amount']:>12,.2f}")
            print(f"{'='*60}\n")

    elif args.trial_balance:
        report = client.get_trial_balance()
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            rows = parse_qbo_report_rows(report)
            print(f"\n{'='*60}")
            print(f"  QBO TRIAL BALANCE")
            print(f"{'='*60}")
            for row in rows:
                prefix = "  >> " if row["is_total"] else "     "
                print(f"{prefix}{row['account']:<40} {row['amount']:>12,.2f}")
            print(f"{'='*60}\n")

    elif args.journal_entries:
        start, end = args.journal_entries
        entries = client.get_journal_entries(start, end)
        if args.json:
            print(json.dumps(entries, indent=2, default=str))
        else:
            print(f"\n{'='*60}")
            print(f"  QBO JOURNAL ENTRIES: {start} to {end}")
            print(f"  ({len(entries)} entries)")
            print(f"{'='*60}")
            for entry in entries[:50]:
                txn_date = entry.get("TxnDate", "?")
                doc_num = entry.get("DocNumber", "")
                total = entry.get("TotalAmt", 0)
                print(f"  {txn_date}  #{doc_num:<8}  ${total:>10,.2f}")
                for line in entry.get("Line", []):
                    detail = line.get("JournalEntryLineDetail", {})
                    acct = detail.get("AccountRef", {}).get("name", "?")
                    posting = detail.get("PostingType", "?")
                    amt = line.get("Amount", 0)
                    print(f"    {posting:<8} {acct:<30} ${amt:>10,.2f}")
            print(f"{'='*60}\n")

    elif args.vendors:
        vendors = client.get_vendors()
        if args.json:
            print(json.dumps(vendors, indent=2, default=str))
        else:
            print(f"\n{'='*60}")
            print(f"  QBO VENDORS ({len(vendors)})")
            print(f"{'='*60}")
            for v in vendors:
                name = v.get("DisplayName", "?")
                balance = v.get("Balance", 0)
                print(f"  {name:<40} ${balance:>10,.2f}")
            print(f"{'='*60}\n")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
