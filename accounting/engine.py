"""
Accounting Engine — The Double-Entry Posting Machine
=======================================================
This is the core of Operation Strangler Fig. It:
    1. Validates journal entries (sum(debits) == sum(credits))
    2. Posts them to the general_ledger in PostgreSQL
    3. Computes account balances
    4. Prevents unbalanced entries (raises AccountingError — FATAL)

No entry reaches the database unless it passes validation.
"""

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

from accounting.models import (
    Account, AccountingError, AccountType,
    JournalEntry, LedgerLine,
)

logger = logging.getLogger("accounting.engine")


# =============================================================================
# DATABASE HELPERS
# =============================================================================

def _connect():
    import psycopg2
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )


# =============================================================================
# CHART OF ACCOUNTS OPERATIONS
# =============================================================================

def get_account(code: str, schema: str = "division_b") -> Optional[Account]:
    """Fetch a single account by code."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT code, name, account_type, parent_code, description, "
                f"is_active, qbo_id, qbo_name "
                f"FROM {schema}.chart_of_accounts WHERE code = %s",
                (code,),
            )
            row = cur.fetchone()
            if row:
                return Account(
                    code=row[0], name=row[1], account_type=AccountType(row[2]),
                    parent_code=row[3], description=row[4], is_active=row[5],
                    qbo_id=row[6], qbo_name=row[7],
                )
            return None
    finally:
        conn.close()


def list_accounts(
    schema: str = "division_b",
    account_type: Optional[str] = None,
    active_only: bool = True,
) -> List[Account]:
    """List all accounts, optionally filtered by type."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            sql = f"SELECT code, name, account_type, parent_code, description, " \
                  f"is_active, qbo_id, qbo_name FROM {schema}.chart_of_accounts"
            conditions = []
            params = []
            if active_only:
                conditions.append("is_active = TRUE")
            if account_type:
                conditions.append("account_type = %s")
                params.append(account_type)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY code"
            cur.execute(sql, params)
            return [
                Account(
                    code=row[0], name=row[1], account_type=AccountType(row[2]),
                    parent_code=row[3], description=row[4], is_active=row[5],
                    qbo_id=row[6], qbo_name=row[7],
                )
                for row in cur.fetchall()
            ]
    finally:
        conn.close()


def upsert_account(account: Account, schema: str = "division_b") -> bool:
    """Insert or update an account in the chart of accounts."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {schema}.chart_of_accounts
                    (code, name, account_type, parent_code, description,
                     is_active, qbo_id, qbo_name, normal_balance)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    account_type = EXCLUDED.account_type,
                    parent_code = EXCLUDED.parent_code,
                    description = EXCLUDED.description,
                    is_active = EXCLUDED.is_active,
                    qbo_id = EXCLUDED.qbo_id,
                    qbo_name = EXCLUDED.qbo_name,
                    normal_balance = EXCLUDED.normal_balance,
                    updated_at = NOW()
            """, (
                account.code, account.name, account.account_type.value,
                account.parent_code, account.description, account.is_active,
                account.qbo_id, account.qbo_name,
                account.account_type.normal_balance,
            ))
        conn.commit()
        logger.info(f"Upserted account: {account.code} - {account.name}")
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to upsert account {account.code}: {e}")
        return False
    finally:
        conn.close()


# =============================================================================
# JOURNAL ENTRY POSTING — THE CORE MACHINE
# =============================================================================

def post_journal_entry(entry: JournalEntry, schema: str = "division_b") -> bool:
    """
    Validate and post a journal entry to the general ledger.

    This is an atomic operation: either ALL lines are posted, or NONE.
    If sum(debits) != sum(credits), an AccountingError is raised and
    NOTHING is written.

    Args:
        entry: The JournalEntry to post (must have >= 2 balanced lines)
        schema: Target division schema

    Returns:
        True if posted successfully

    Raises:
        AccountingError: if the entry is unbalanced
    """
    # ===== VALIDATION GATE =====
    entry.validate()  # Raises AccountingError if unbalanced

    conn = _connect()
    try:
        with conn.cursor() as cur:
            # 1. Verify all account codes exist
            for line in entry.lines:
                cur.execute(
                    f"SELECT code FROM {schema}.chart_of_accounts WHERE code = %s",
                    (line.account_code,),
                )
                if not cur.fetchone():
                    raise AccountingError(
                        f"Account code '{line.account_code}' not found in "
                        f"{schema}.chart_of_accounts. Cannot post."
                    )

            # 2. Insert journal entry header
            cur.execute(f"""
                INSERT INTO {schema}.journal_entries
                    (entry_id, entry_date, description, source_type,
                     source_ref, memo, is_posted, created_by, posted_at)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s, NOW())
                ON CONFLICT (entry_id) DO NOTHING
            """, (
                entry.entry_id, entry.date, entry.description,
                entry.source_type, entry.source_ref, entry.memo,
                entry.created_by,
            ))

            # 3. Insert all ledger lines
            for line in entry.lines:
                cur.execute(f"""
                    INSERT INTO {schema}.general_ledger
                        (journal_entry_id, account_code, account_name,
                         debit, credit, memo)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    entry.entry_id, line.account_code, line.account_name,
                    float(line.debit), float(line.credit), line.memo,
                ))

        conn.commit()
        entry.is_posted = True
        logger.info(
            f"POSTED: {entry.entry_id} | {entry.description} | "
            f"D={entry.total_debits} C={entry.total_credits} | "
            f"{len(entry.lines)} lines → {schema}"
        )
        return True

    except AccountingError:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to post {entry.entry_id}: {e}")
        raise AccountingError(f"Database error posting {entry.entry_id}: {e}")
    finally:
        conn.close()


# =============================================================================
# BALANCE QUERIES
# =============================================================================

def get_account_balance(
    account_code: str,
    schema: str = "division_b",
    as_of: Optional[date] = None,
) -> Decimal:
    """
    Get the current balance of an account.

    For normal-debit accounts (Asset, Expense, COGS): balance = debits - credits
    For normal-credit accounts (Liability, Equity, Revenue): balance = credits - debits
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            date_clause = ""
            params = [account_code]
            if as_of:
                date_clause = " AND je.entry_date <= %s"
                params.append(as_of)

            cur.execute(f"""
                SELECT
                    coa.normal_balance,
                    COALESCE(SUM(gl.debit), 0),
                    COALESCE(SUM(gl.credit), 0)
                FROM {schema}.chart_of_accounts coa
                LEFT JOIN {schema}.general_ledger gl
                    ON gl.account_code = coa.code
                LEFT JOIN {schema}.journal_entries je
                    ON gl.journal_entry_id = je.entry_id
                WHERE coa.code = %s{date_clause}
                GROUP BY coa.normal_balance
            """, params)
            row = cur.fetchone()
            if not row:
                return Decimal("0.00")

            normal_balance, total_debits, total_credits = row
            total_debits = Decimal(str(total_debits))
            total_credits = Decimal(str(total_credits))

            if normal_balance == "debit":
                return (total_debits - total_credits).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP,
                )
            else:
                return (total_credits - total_debits).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP,
                )
    finally:
        conn.close()


def get_trial_balance(
    schema: str = "division_b",
    as_of: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """
    Pull the trial balance: every account with its debit/credit totals.

    The trial balance is the first check: total debits MUST equal total credits.
    If they don't, something is catastrophically wrong.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if as_of:
                cur.execute(f"""
                    SELECT
                        coa.code, coa.name, coa.account_type, coa.normal_balance,
                        COALESCE(SUM(gl.debit), 0) AS total_debits,
                        COALESCE(SUM(gl.credit), 0) AS total_credits
                    FROM {schema}.chart_of_accounts coa
                    LEFT JOIN {schema}.general_ledger gl ON gl.account_code = coa.code
                    LEFT JOIN {schema}.journal_entries je ON gl.journal_entry_id = je.entry_id
                        AND je.entry_date <= %s
                    WHERE coa.is_active = TRUE
                    GROUP BY coa.code, coa.name, coa.account_type, coa.normal_balance
                    ORDER BY coa.code
                """, (as_of,))
            else:
                cur.execute(f"""
                    SELECT code, name, account_type, normal_balance,
                           total_debits, total_credits, net_balance
                    FROM {schema}.trial_balance
                """)

            rows = cur.fetchall()
            results = []
            for row in rows:
                total_d = Decimal(str(row[4]))
                total_c = Decimal(str(row[5]))
                results.append({
                    "code": row[0],
                    "name": row[1],
                    "account_type": row[2],
                    "normal_balance": row[3],
                    "total_debits": total_d,
                    "total_credits": total_c,
                    "balance": total_d - total_c,
                })
            return results
    finally:
        conn.close()


def verify_balance(schema: str = "division_b") -> Dict[str, Any]:
    """
    THE STRANGLER FIG HEALTH CHECK.

    Queries the balance_check view. If total_debits != total_credits,
    the system is broken.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {schema}.balance_check")
            row = cur.fetchone()
            if not row or row[0] is None:
                return {
                    "total_debits": Decimal("0.00"),
                    "total_credits": Decimal("0.00"),
                    "imbalance": Decimal("0.00"),
                    "status": "EMPTY",
                }
            return {
                "total_debits": Decimal(str(row[0])),
                "total_credits": Decimal(str(row[1])),
                "imbalance": Decimal(str(row[2])),
                "status": row[3],
            }
    finally:
        conn.close()


# =============================================================================
# CONVENIENCE: Quick Journal Entry Builder
# =============================================================================

def create_simple_entry(
    date_: date,
    description: str,
    debit_account_code: str,
    debit_account_name: str,
    credit_account_code: str,
    credit_account_name: str,
    amount: Decimal,
    source_type: str = "plaid",
    source_ref: str = "",
    division: str = "division_b",
    memo: str = "",
) -> JournalEntry:
    """
    Create a simple 2-line journal entry (one debit, one credit).

    This covers ~80% of Plaid transactions. For compound entries
    (e.g., payroll with multiple deductions), build JournalEntry manually.
    """
    entry = JournalEntry(
        entry_id=str(uuid.uuid4()),
        date=date_,
        description=description,
        lines=[
            LedgerLine(
                account_code=debit_account_code,
                account_name=debit_account_name,
                debit=amount,
                credit=Decimal("0.00"),
                memo=memo,
            ),
            LedgerLine(
                account_code=credit_account_code,
                account_name=credit_account_name,
                debit=Decimal("0.00"),
                credit=amount,
                memo=memo,
            ),
        ],
        source_type=source_type,
        source_ref=source_ref,
        division=division,
        memo=memo,
    )
    return entry
