"""
QBO Chart of Accounts Importer — Clone the Host's Brain
===========================================================
Imports the Chart of Accounts from a QuickBooks Online CSV export
into Fortress's PostgreSQL database.

HOW TO EXPORT FROM QBO:
    1. Log into QuickBooks Online
    2. Settings (gear icon) → Chart of Accounts
    3. Click the "Run Report" pencil icon, or go to:
       Reports → Accounting → Account List
    4. Export as CSV (Excel download → save as CSV)

Expected CSV columns (QBO standard export):
    Account, Type, Detail Type, Description, Balance

The importer maps QBO account types to Fortress's standardized types:
    QBO "Bank"         → Asset
    QBO "Accounts Receivable" → Asset
    QBO "Fixed Asset"  → Asset
    QBO "Other Current Asset" → Asset
    QBO "Accounts Payable" → Liability
    QBO "Credit Card"  → Liability
    QBO "Other Current Liability" → Liability
    QBO "Long Term Liability" → Liability
    QBO "Equity"       → Equity
    QBO "Income"       → Revenue
    QBO "Other Income" → Revenue
    QBO "Expense"      → Expense
    QBO "Other Expense"→ Expense
    QBO "Cost of Goods Sold" → COGS

Usage:
    python -m accounting.import_qbo_coa --csv chart_of_accounts.csv --schema division_b
    python -m accounting.import_qbo_coa --default --schema division_b  # seed defaults
"""

import argparse
import csv
import logging
import sys
from typing import Any, Dict, List, Optional

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
from accounting.models import Account, AccountType

logger = logging.getLogger("accounting.import_qbo_coa")


# =============================================================================
# QBO TYPE → FORTRESS TYPE MAPPING
# =============================================================================

QBO_TYPE_MAP: Dict[str, AccountType] = {
    # Assets
    "bank": AccountType.ASSET,
    "accounts receivable": AccountType.ASSET,
    "accounts receivable (a/r)": AccountType.ASSET,
    "other current asset": AccountType.ASSET,
    "other current assets": AccountType.ASSET,
    "fixed asset": AccountType.ASSET,
    "fixed assets": AccountType.ASSET,
    "other asset": AccountType.ASSET,
    "other assets": AccountType.ASSET,
    # Liabilities
    "accounts payable": AccountType.LIABILITY,
    "accounts payable (a/p)": AccountType.LIABILITY,
    "credit card": AccountType.LIABILITY,
    "other current liability": AccountType.LIABILITY,
    "other current liabilities": AccountType.LIABILITY,
    "long term liability": AccountType.LIABILITY,
    "long term liabilities": AccountType.LIABILITY,
    "other liability": AccountType.LIABILITY,
    # Equity
    "equity": AccountType.EQUITY,
    # Revenue
    "income": AccountType.REVENUE,
    "other income": AccountType.REVENUE,
    # Expenses
    "expense": AccountType.EXPENSE,
    "expenses": AccountType.EXPENSE,
    "other expense": AccountType.EXPENSE,
    "other expenses": AccountType.EXPENSE,
    # COGS
    "cost of goods sold": AccountType.COGS,
    "cogs": AccountType.COGS,
}

# Standard account code ranges
CODE_COUNTERS = {
    AccountType.ASSET: 1000,
    AccountType.LIABILITY: 2000,
    AccountType.EQUITY: 3000,
    AccountType.REVENUE: 4000,
    AccountType.EXPENSE: 5000,
    AccountType.COGS: 6000,
}


# =============================================================================
# CSV PARSER
# =============================================================================

def parse_qbo_csv(filepath: str) -> List[Account]:
    """
    Parse a QBO Chart of Accounts CSV export.

    Expected columns (flexible matching — handles QBO variations):
        Account (or Name), Type, Detail Type, Description, Balance

    Returns a list of Account objects ready for DB insertion.
    """
    accounts = []
    code_counters = dict(CODE_COUNTERS)  # Mutable copy

    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        # Normalize column names (QBO exports vary)
        if reader.fieldnames:
            col_map = {}
            for col in reader.fieldnames:
                lower = col.strip().lower()
                if lower in ("account", "name", "account name"):
                    col_map["name"] = col
                elif lower == "type":
                    col_map["type"] = col
                elif lower in ("detail type", "detail"):
                    col_map["detail_type"] = col
                elif lower == "description":
                    col_map["description"] = col
                elif lower == "balance":
                    col_map["balance"] = col
        else:
            logger.error("CSV has no headers")
            return []

        for row in reader:
            name = row.get(col_map.get("name", "Account"), "").strip()
            qbo_type = row.get(col_map.get("type", "Type"), "").strip()
            detail_type = row.get(col_map.get("detail_type", "Detail Type"), "").strip()
            description = row.get(col_map.get("description", "Description"), "").strip()

            if not name:
                continue

            # Map QBO type to Fortress type
            acct_type = QBO_TYPE_MAP.get(qbo_type.lower())
            if not acct_type:
                logger.warning(
                    f"Unknown QBO type '{qbo_type}' for account '{name}'. "
                    f"Defaulting to EXPENSE."
                )
                acct_type = AccountType.EXPENSE

            # Auto-assign a code
            code = str(code_counters[acct_type])
            code_counters[acct_type] += 10  # Leave gaps for sub-accounts

            account = Account(
                code=code,
                name=name,
                account_type=acct_type,
                description=description or detail_type,
                qbo_name=name,
                is_active=True,
            )
            accounts.append(account)
            logger.info(f"Parsed: {code} {name} ({acct_type.value})")

    logger.info(f"Parsed {len(accounts)} accounts from QBO CSV")
    return accounts


# =============================================================================
# DEFAULT CHART OF ACCOUNTS (for Property Management)
# =============================================================================

def get_default_property_coa() -> List[Account]:
    """
    A standard Chart of Accounts for a property management company.
    Use this if you don't have a QBO CSV export yet, or to seed
    the database for testing.

    Follows the QBO structure that Cabin Rentals of Georgia uses.
    """
    return [
        # ===== ASSETS (1xxx) =====
        Account("1000", "Bank:Operating", AccountType.ASSET,
                description="Primary operating checking account"),
        Account("1010", "Bank:Trust", AccountType.ASSET,
                description="Trust/Escrow account for guest deposits"),
        Account("1020", "Bank:Savings", AccountType.ASSET,
                description="Business savings account"),
        Account("1100", "Accounts Receivable", AccountType.ASSET,
                description="Money owed to us by guests/owners"),
        Account("1150", "Accounts Receivable:Forecast Revenue", AccountType.ASSET,
                description="QuantRevenue forecast accruals (auto-reversed on booking)"),
        Account("1200", "Prepaid Expenses", AccountType.ASSET,
                description="Advance payments (insurance, deposits)"),
        Account("1300", "Security Deposits Held", AccountType.ASSET,
                description="Guest security deposits receivable"),
        Account("1500", "Fixed Assets:Furniture", AccountType.ASSET,
                description="Cabin furnishings and fixtures"),
        Account("1510", "Fixed Assets:Equipment", AccountType.ASSET,
                description="Maintenance equipment"),
        Account("1520", "Fixed Assets:Vehicles", AccountType.ASSET,
                description="Company vehicles"),
        Account("1600", "Accumulated Depreciation", AccountType.ASSET,
                description="Contra-asset: depreciation"),

        # ===== LIABILITIES (2xxx) =====
        Account("2000", "Accounts Payable", AccountType.LIABILITY,
                description="Money we owe vendors"),
        Account("2100", "Credit Card", AccountType.LIABILITY,
                description="Company credit card balance"),
        Account("2200", "Trust:Guest Escrow", AccountType.LIABILITY,
                description="Guest deposits held in trust"),
        Account("2210", "Trust:Owner Payable", AccountType.LIABILITY,
                description="Rental income owed to property owners"),
        Account("2220", "Trust:Cleaning Fees Payable", AccountType.LIABILITY,
                description="Cleaning fees pending distribution"),
        Account("2300", "Sales Tax Payable", AccountType.LIABILITY,
                description="Collected occupancy/sales tax"),
        Account("2310", "Lodging Tax Payable", AccountType.LIABILITY,
                description="Fannin County lodging tax"),
        Account("2400", "Payroll Liabilities", AccountType.LIABILITY,
                description="Accrued wages and payroll taxes"),

        # ===== EQUITY (3xxx) =====
        Account("3000", "Owner's Equity", AccountType.EQUITY,
                description="Gary M. Knight's equity in the business"),
        Account("3100", "Retained Earnings", AccountType.EQUITY,
                description="Accumulated profits/losses"),
        Account("3200", "Owner's Draws", AccountType.EQUITY,
                description="Distributions to owner"),

        # ===== REVENUE (4xxx) =====
        Account("4000", "Rental Income:Management Fees", AccountType.REVENUE,
                description="PM management fee (% of booking)"),
        Account("4010", "Rental Income:Booking Fees", AccountType.REVENUE,
                description="Guest booking/service fees"),
        Account("4020", "Rental Income:Cleaning Fees", AccountType.REVENUE,
                description="Cleaning fees charged to guests"),
        Account("4050", "Rental Income:Forecast", AccountType.REVENUE,
                description="QuantRevenue forecast revenue (auto-reversed on booking)"),
        Account("4100", "Other Income:Late Fees", AccountType.REVENUE,
                description="Late payment fees from owners"),
        Account("4110", "Other Income:Interest", AccountType.REVENUE,
                description="Bank account interest"),
        Account("4200", "Reimbursed Expenses", AccountType.REVENUE,
                description="Owner-reimbursed maintenance costs"),

        # ===== EXPENSES (5xxx) =====
        Account("5000", "Utilities:Electric", AccountType.EXPENSE,
                description="Electricity (Blue Ridge Electric)"),
        Account("5010", "Utilities:Water", AccountType.EXPENSE,
                description="Water/Sewer"),
        Account("5020", "Utilities:Gas/Propane", AccountType.EXPENSE,
                description="Natural gas or propane"),
        Account("5030", "Utilities:Internet/Cable", AccountType.EXPENSE,
                description="WiFi, TV, streaming"),
        Account("5040", "Utilities:Trash", AccountType.EXPENSE,
                description="Waste removal"),
        Account("5100", "Maintenance:Repairs", AccountType.EXPENSE,
                description="General cabin repairs"),
        Account("5110", "Maintenance:Landscaping", AccountType.EXPENSE,
                description="Lawn, trees, gravel"),
        Account("5120", "Maintenance:Pest Control", AccountType.EXPENSE,
                description="Pest and wildlife control"),
        Account("5130", "Maintenance:HVAC", AccountType.EXPENSE,
                description="Heating/cooling repairs"),
        Account("5140", "Maintenance:Plumbing", AccountType.EXPENSE,
                description="Plumbing repairs"),
        Account("5200", "Cleaning:Turnover", AccountType.EXPENSE,
                description="Guest turnover cleaning costs"),
        Account("5210", "Cleaning:Deep Clean", AccountType.EXPENSE,
                description="Periodic deep cleaning"),
        Account("5300", "Insurance:Property", AccountType.EXPENSE,
                description="Cabin property insurance"),
        Account("5310", "Insurance:Liability", AccountType.EXPENSE,
                description="Business liability insurance"),
        Account("5400", "Taxes:Property Tax", AccountType.EXPENSE,
                description="Fannin County property tax"),
        Account("5410", "Taxes:Occupancy Tax", AccountType.EXPENSE,
                description="State/County occupancy tax remittance"),
        Account("5500", "Marketing:Online Listings", AccountType.EXPENSE,
                description="Airbnb, VRBO, Booking.com fees"),
        Account("5510", "Marketing:Website", AccountType.EXPENSE,
                description="crog.com hosting, SEO"),
        Account("5520", "Marketing:Photography", AccountType.EXPENSE,
                description="Professional cabin photography"),
        Account("5600", "Payroll:Wages", AccountType.EXPENSE,
                description="Employee wages"),
        Account("5610", "Payroll:Taxes", AccountType.EXPENSE,
                description="Employer payroll taxes"),
        Account("5620", "Payroll:Benefits", AccountType.EXPENSE,
                description="Employee benefits"),
        Account("5700", "Office:Supplies", AccountType.EXPENSE,
                description="Office supplies"),
        Account("5710", "Office:Software", AccountType.EXPENSE,
                description="SaaS tools, subscriptions"),
        Account("5720", "Office:Phone", AccountType.EXPENSE,
                description="Business phone lines"),
        Account("5800", "Professional Services:Legal", AccountType.EXPENSE,
                description="Attorney fees"),
        Account("5810", "Professional Services:Accounting", AccountType.EXPENSE,
                description="CPA/bookkeeping fees"),
        Account("5900", "Vehicle:Fuel", AccountType.EXPENSE,
                description="Fuel for company vehicles"),
        Account("5910", "Vehicle:Maintenance", AccountType.EXPENSE,
                description="Vehicle repairs and maintenance"),
        Account("5950", "Miscellaneous Expense", AccountType.EXPENSE,
                description="Uncategorized expenses"),

        # ===== COGS (6xxx) =====
        Account("6000", "COGS:Guest Supplies", AccountType.COGS,
                description="Toiletries, linens, welcome baskets"),
        Account("6010", "COGS:Cabin Supplies", AccountType.COGS,
                description="Firewood, hot tub chemicals, etc."),
        Account("6020", "COGS:Merchant Processing Fees", AccountType.COGS,
                description="Stripe / credit card processing fees"),
    ]


def get_default_holding_coa() -> List[Account]:
    """
    A standard Chart of Accounts for a holding company (CROG, LLC).
    """
    return [
        # ===== ASSETS =====
        Account("1000", "Bank:Primary Checking", AccountType.ASSET,
                description="Main operating account"),
        Account("1010", "Bank:Investment Account", AccountType.ASSET,
                description="Brokerage/investment account"),
        Account("1020", "Bank:Savings", AccountType.ASSET,
                description="Business savings"),
        Account("1100", "Accounts Receivable", AccountType.ASSET,
                description="Receivables from subsidiaries/clients"),
        Account("1200", "Investments:Verses in Bloom", AccountType.ASSET,
                description="VC investment in Verses in Bloom"),
        Account("1210", "Investments:Market Securities", AccountType.ASSET,
                description="Publicly traded securities"),
        Account("1220", "Investments:Other", AccountType.ASSET,
                description="Other investment holdings"),
        Account("1500", "Fixed Assets:Compute Cluster", AccountType.ASSET,
                description="DGX Spark cluster hardware"),
        Account("1510", "Fixed Assets:NAS Storage", AccountType.ASSET,
                description="Synology NAS infrastructure"),
        Account("1600", "Accumulated Depreciation", AccountType.ASSET,
                description="Contra-asset: depreciation"),

        # ===== LIABILITIES =====
        Account("2000", "Accounts Payable", AccountType.LIABILITY,
                description="Vendor payables"),
        Account("2100", "Credit Card", AccountType.LIABILITY,
                description="Business credit card"),
        Account("2200", "Loans Payable", AccountType.LIABILITY,
                description="Business loans and credit lines"),
        Account("2300", "Intercompany Payable", AccountType.LIABILITY,
                description="Amounts owed to Cabin Rentals of GA"),

        # ===== EQUITY =====
        Account("3000", "Owner's Equity", AccountType.EQUITY,
                description="Gary M. Knight's equity in CROG LLC"),
        Account("3100", "Retained Earnings", AccountType.EQUITY,
                description="Accumulated profits/losses"),
        Account("3200", "Owner's Draws", AccountType.EQUITY,
                description="Distributions"),

        # ===== REVENUE =====
        Account("4000", "Revenue:Management Fees", AccountType.REVENUE,
                description="Fees from Cabin Rentals of GA"),
        Account("4100", "Revenue:Investment Income", AccountType.REVENUE,
                description="Dividends, capital gains, interest"),
        Account("4200", "Revenue:Consulting", AccountType.REVENUE,
                description="Consulting or advisory fees"),
        Account("4300", "Revenue:Other", AccountType.REVENUE,
                description="Miscellaneous income"),

        # ===== EXPENSES =====
        Account("5000", "Compute:Cloud Services", AccountType.EXPENSE,
                description="AWS, GCP, cloud compute (if any)"),
        Account("5010", "Compute:Electricity", AccountType.EXPENSE,
                description="Power for DGX cluster"),
        Account("5020", "Compute:Networking", AccountType.EXPENSE,
                description="Internet, network infrastructure"),
        Account("5100", "Professional:Legal", AccountType.EXPENSE,
                description="Legal fees"),
        Account("5110", "Professional:Accounting", AccountType.EXPENSE,
                description="CPA/bookkeeping"),
        Account("5200", "Office:Rent", AccountType.EXPENSE,
                description="Office/workspace rent"),
        Account("5210", "Office:Supplies", AccountType.EXPENSE,
                description="Office supplies"),
        Account("5220", "Office:Software", AccountType.EXPENSE,
                description="SaaS subscriptions (excl. QBO soon)"),
        Account("5300", "Insurance:Business", AccountType.EXPENSE,
                description="Business insurance"),
        Account("5400", "Marketing:General", AccountType.EXPENSE,
                description="Marketing and advertising"),
        Account("5500", "Travel:Business", AccountType.EXPENSE,
                description="Business travel"),
        Account("5900", "Miscellaneous", AccountType.EXPENSE,
                description="Uncategorized"),

        # ===== COGS =====
        Account("6000", "COGS:Contractor Services", AccountType.COGS,
                description="Contracted development work"),
    ]


# =============================================================================
# DATABASE INSERTION
# =============================================================================

def insert_accounts(
    accounts: List[Account], schema: str = "division_b",
) -> Dict[str, int]:
    """
    Insert a list of Account objects into the chart_of_accounts table.
    Uses upsert — safe to run multiple times.

    Returns: {"inserted": N, "updated": M, "errors": E}
    """
    import psycopg2
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )
    stats = {"inserted": 0, "updated": 0, "errors": 0}

    try:
        with conn.cursor() as cur:
            for acct in accounts:
                try:
                    cur.execute(f"""
                        INSERT INTO {schema}.chart_of_accounts
                            (code, name, account_type, parent_code, description,
                             is_active, qbo_id, qbo_name, normal_balance)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (code) DO UPDATE SET
                            name = EXCLUDED.name,
                            account_type = EXCLUDED.account_type,
                            description = EXCLUDED.description,
                            qbo_name = EXCLUDED.qbo_name,
                            normal_balance = EXCLUDED.normal_balance,
                            updated_at = NOW()
                        RETURNING (xmax = 0) AS is_insert
                    """, (
                        acct.code, acct.name, acct.account_type.value,
                        acct.parent_code, acct.description, acct.is_active,
                        acct.qbo_id, acct.qbo_name,
                        acct.account_type.normal_balance,
                    ))
                    row = cur.fetchone()
                    if row and row[0]:
                        stats["inserted"] += 1
                    else:
                        stats["updated"] += 1
                except Exception as e:
                    logger.error(f"Error inserting {acct.code} ({acct.name}): {e}")
                    stats["errors"] += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Batch insert failed: {e}")
        raise
    finally:
        conn.close()

    return stats


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Import Chart of Accounts into Fortress",
    )
    parser.add_argument(
        "--csv", type=str, help="Path to QBO Chart of Accounts CSV export",
    )
    parser.add_argument(
        "--schema", type=str, default="division_b",
        choices=["division_a", "division_b"],
        help="Target division schema (default: division_b)",
    )
    parser.add_argument(
        "--default", action="store_true",
        help="Seed with default Chart of Accounts (skip CSV import)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.default:
        print(f"\n{'='*60}")
        print(f"  OPERATION STRANGLER FIG: Seeding Default CoA")
        print(f"  Target: {args.schema}")
        print(f"{'='*60}\n")

        if args.schema == "division_a":
            accounts = get_default_holding_coa()
        else:
            accounts = get_default_property_coa()

        stats = insert_accounts(accounts, args.schema)
        print(f"\n  Inserted: {stats['inserted']}")
        print(f"  Updated:  {stats['updated']}")
        print(f"  Errors:   {stats['errors']}")
        print(f"  Total:    {len(accounts)} accounts")
        print(f"\n  Chart of Accounts loaded into {args.schema}.")

    elif args.csv:
        print(f"\n{'='*60}")
        print(f"  OPERATION STRANGLER FIG: Importing QBO CoA")
        print(f"  Source: {args.csv}")
        print(f"  Target: {args.schema}")
        print(f"{'='*60}\n")

        accounts = parse_qbo_csv(args.csv)
        if not accounts:
            print("  ERROR: No accounts parsed from CSV. Check format.")
            sys.exit(1)

        stats = insert_accounts(accounts, args.schema)
        print(f"\n  Inserted: {stats['inserted']}")
        print(f"  Updated:  {stats['updated']}")
        print(f"  Errors:   {stats['errors']}")
        print(f"  Total:    {len(accounts)} accounts")
        print(f"\n  QBO Chart of Accounts cloned into {args.schema}.")

    else:
        print("Error: specify --csv <path> or --default")
        parser.print_help()
        sys.exit(1)

    print(f"\n  The Strangler Fig's roots are in place.\n")


if __name__ == "__main__":
    main()
