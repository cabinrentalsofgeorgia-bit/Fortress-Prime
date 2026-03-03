"""
Accounting Schema — PostgreSQL Tables for Double-Entry Ledger
================================================================
Creates the chart_of_accounts and general_ledger tables in each
division's schema. These are the tables that strangle QBO.

Tables per division:
    {schema}.chart_of_accounts  — The account tree (Assets, Liabilities, etc.)
    {schema}.general_ledger     — Every debit and credit line ever posted
    {schema}.journal_entries    — Header records grouping ledger lines
"""

import logging
from typing import Optional

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

logger = logging.getLogger("accounting.schema")


def _get_schema_sql(schema: str) -> str:
    """Generate the accounting schema DDL for a given division schema."""
    return f"""
-- =================================================================
-- OPERATION STRANGLER FIG: Double-Entry Accounting Tables
-- Schema: {schema}
-- =================================================================

-- Chart of Accounts (mirrors QBO structure)
CREATE TABLE IF NOT EXISTS {schema}.chart_of_accounts (
    id              SERIAL PRIMARY KEY,
    code            TEXT UNIQUE NOT NULL,       -- "1000", "5200.10"
    name            TEXT NOT NULL,              -- "Utilities:Electric"
    account_type    TEXT NOT NULL,              -- asset, liability, equity, revenue, expense, cogs
    parent_code     TEXT,                       -- Parent account code (NULL = top-level)
    description     TEXT DEFAULT '',
    is_active       BOOLEAN DEFAULT TRUE,
    qbo_id          TEXT,                       -- QBO account ID (for reconciliation)
    qbo_name        TEXT,                       -- QBO display name
    normal_balance  TEXT NOT NULL DEFAULT 'debit',  -- 'debit' or 'credit'
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT valid_account_type CHECK (
        account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense', 'cogs')
    ),
    CONSTRAINT valid_normal_balance CHECK (
        normal_balance IN ('debit', 'credit')
    )
);

-- Journal Entries (header: groups the ledger lines)
CREATE TABLE IF NOT EXISTS {schema}.journal_entries (
    id              SERIAL PRIMARY KEY,
    entry_id        TEXT UNIQUE NOT NULL,       -- UUID or structured ID
    entry_date      DATE NOT NULL,
    description     TEXT NOT NULL,
    source_type     TEXT DEFAULT 'plaid',       -- plaid, manual, import, adjustment
    source_ref      TEXT DEFAULT '',            -- plaid_txn_id, invoice number, etc.
    memo            TEXT DEFAULT '',
    is_posted       BOOLEAN DEFAULT FALSE,
    created_by      TEXT DEFAULT 'fortress',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    posted_at       TIMESTAMPTZ
);

-- General Ledger (every debit and credit line — THE SOURCE OF TRUTH)
CREATE TABLE IF NOT EXISTS {schema}.general_ledger (
    id              SERIAL PRIMARY KEY,
    journal_entry_id TEXT NOT NULL REFERENCES {schema}.journal_entries(entry_id),
    account_code    TEXT NOT NULL REFERENCES {schema}.chart_of_accounts(code),
    account_name    TEXT NOT NULL,
    debit           NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    credit          NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    memo            TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    -- The fundamental rule: a line is EITHER debit OR credit, never both
    CONSTRAINT debit_xor_credit CHECK (
        (debit > 0 AND credit = 0) OR (debit = 0 AND credit > 0)
    )
);

-- Account-to-Plaid mapping (self-learning: vendor → debit/credit accounts)
CREATE TABLE IF NOT EXISTS {schema}.account_mappings (
    id              SERIAL PRIMARY KEY,
    vendor_name     TEXT NOT NULL,
    plaid_category  TEXT DEFAULT '',
    debit_account   TEXT NOT NULL REFERENCES {schema}.chart_of_accounts(code),
    credit_account  TEXT NOT NULL REFERENCES {schema}.chart_of_accounts(code),
    confidence      NUMERIC(4, 3) DEFAULT 0.0,
    reasoning       TEXT DEFAULT '',
    learned_at      TIMESTAMPTZ DEFAULT NOW(),
    source          TEXT DEFAULT 'llm',         -- llm, manual, qbo_import

    CONSTRAINT unique_vendor_mapping UNIQUE (vendor_name)
);

-- Indexes for fast reporting
CREATE INDEX IF NOT EXISTS idx_{schema}_gl_entry ON {schema}.general_ledger(journal_entry_id);
CREATE INDEX IF NOT EXISTS idx_{schema}_gl_account ON {schema}.general_ledger(account_code);
CREATE INDEX IF NOT EXISTS idx_{schema}_gl_date ON {schema}.general_ledger(created_at);
CREATE INDEX IF NOT EXISTS idx_{schema}_je_date ON {schema}.journal_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_{schema}_je_source ON {schema}.journal_entries(source_ref);
CREATE INDEX IF NOT EXISTS idx_{schema}_coa_type ON {schema}.chart_of_accounts(account_type);
CREATE INDEX IF NOT EXISTS idx_{schema}_am_vendor ON {schema}.account_mappings(vendor_name);

-- View: Trial Balance (debits and credits per account)
CREATE OR REPLACE VIEW {schema}.trial_balance AS
SELECT
    coa.code,
    coa.name,
    coa.account_type,
    coa.normal_balance,
    COALESCE(SUM(gl.debit), 0) AS total_debits,
    COALESCE(SUM(gl.credit), 0) AS total_credits,
    COALESCE(SUM(gl.debit), 0) - COALESCE(SUM(gl.credit), 0) AS net_balance
FROM {schema}.chart_of_accounts coa
LEFT JOIN {schema}.general_ledger gl ON gl.account_code = coa.code
WHERE coa.is_active = TRUE
GROUP BY coa.code, coa.name, coa.account_type, coa.normal_balance
ORDER BY coa.code;

-- View: Balance verification (THE STRANGLER FIG HEALTH CHECK)
CREATE OR REPLACE VIEW {schema}.balance_check AS
SELECT
    SUM(debit) AS total_debits,
    SUM(credit) AS total_credits,
    SUM(debit) - SUM(credit) AS imbalance,
    CASE WHEN SUM(debit) = SUM(credit) THEN 'BALANCED' ELSE 'IMBALANCED' END AS status
FROM {schema}.general_ledger;
"""


def init_accounting_schema(schema: str = "division_b") -> bool:
    """
    Create the accounting tables in the given schema.

    Args:
        schema: PostgreSQL schema name ("division_a" or "division_b")

    Returns:
        True if successful.
    """
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
        )
        with conn.cursor() as cur:
            cur.execute(_get_schema_sql(schema))
        conn.commit()
        conn.close()
        logger.info(f"Accounting schema initialized for {schema}")
        return True
    except Exception as e:
        logger.error(f"Failed to init accounting schema for {schema}: {e}")
        return False


def init_all() -> dict:
    """Initialize accounting tables for both divisions."""
    results = {}
    for schema in ("division_a", "division_b"):
        results[schema] = init_accounting_schema(schema)
    return results
