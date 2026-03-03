"""
Division A Ledger — Corporate Financial Records
=================================================
PostgreSQL-backed ledger for CROG, LLC holding company transactions.

All writes go through this module to ensure:
    1. Every transaction is categorized before storage
    2. The corporate veil is maintained (Division B cannot read this)
    3. Full audit trail for Sovereign health monitoring
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

logger = logging.getLogger("division_a.ledger")

# Schema constants
SCHEMA = "division_a"
TABLE_TRANSACTIONS = f"{SCHEMA}.transactions"
TABLE_PREDICTIONS = f"{SCHEMA}.predictions"
TABLE_AUDIT_LOG = f"{SCHEMA}.audit_log"


# =============================================================================
# SCHEMA INITIALIZATION
# =============================================================================

INIT_SQL = f"""
-- Division A: CROG LLC Holding Company Ledger
-- FIREWALL: This schema is ONLY accessible by Division A agents.

CREATE SCHEMA IF NOT EXISTS {SCHEMA};

CREATE TABLE IF NOT EXISTS {TABLE_TRANSACTIONS} (
    id              SERIAL PRIMARY KEY,
    plaid_txn_id    TEXT UNIQUE,
    date            DATE NOT NULL,
    vendor          TEXT NOT NULL,
    amount          NUMERIC(12, 2) NOT NULL,
    category        TEXT NOT NULL DEFAULT 'UNCATEGORIZED',
    confidence      NUMERIC(4, 3) DEFAULT 0.0,
    roi_impact      TEXT DEFAULT 'neutral',
    reasoning       TEXT,
    method          TEXT DEFAULT 'manual',
    account_id      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {TABLE_PREDICTIONS} (
    id              SERIAL PRIMARY KEY,
    metric_name     TEXT NOT NULL,
    predicted_value NUMERIC(14, 4),
    actual_value    NUMERIC(14, 4),
    variance_pct    NUMERIC(8, 4),
    cycle_id        INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {TABLE_AUDIT_LOG} (
    id              SERIAL PRIMARY KEY,
    action          TEXT NOT NULL,
    agent           TEXT DEFAULT 'division_a.agent',
    detail          JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_div_a_txn_date ON {TABLE_TRANSACTIONS}(date);
CREATE INDEX IF NOT EXISTS idx_div_a_txn_vendor ON {TABLE_TRANSACTIONS}(vendor);
CREATE INDEX IF NOT EXISTS idx_div_a_txn_category ON {TABLE_TRANSACTIONS}(category);
CREATE INDEX IF NOT EXISTS idx_div_a_pred_metric ON {TABLE_PREDICTIONS}(metric_name);
"""


def init_schema() -> bool:
    """Create the Division A schema and tables if they don't exist."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
        )
        with conn.cursor() as cur:
            cur.execute(INIT_SQL)
        conn.commit()
        conn.close()
        logger.info("Division A schema initialized.")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize Division A schema: {e}")
        return False


# =============================================================================
# TRANSACTION OPERATIONS
# =============================================================================

def insert_transaction(txn: Dict[str, Any]) -> bool:
    """Insert a categorized transaction into the Division A ledger."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
        )
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {TABLE_TRANSACTIONS}
                    (plaid_txn_id, date, vendor, amount, category,
                     confidence, roi_impact, reasoning, method, account_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (plaid_txn_id) DO UPDATE SET
                    category = EXCLUDED.category,
                    confidence = EXCLUDED.confidence,
                    updated_at = NOW()
            """, (
                txn.get("transaction_id"),
                txn.get("date"),
                txn.get("merchant_name") or txn.get("name", "UNKNOWN"),
                txn.get("amount", 0),
                txn.get("category", "UNCATEGORIZED"),
                txn.get("confidence", 0),
                txn.get("roi_impact", "neutral"),
                txn.get("reasoning", ""),
                txn.get("method", "llm"),
                txn.get("account_id"),
            ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Failed to insert transaction: {e}")
        return False


def record_prediction(
    metric_name: str,
    predicted: float,
    actual: float,
    cycle_id: int = 0,
) -> Optional[float]:
    """
    Record a prediction vs actual, computing variance.

    Returns the variance percentage (used by optimization_loop to trigger REFLECT).
    """
    if predicted == 0:
        variance_pct = 100.0 if actual != 0 else 0.0
    else:
        variance_pct = abs((actual - predicted) / predicted) * 100

    try:
        import psycopg2
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
        )
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {TABLE_PREDICTIONS}
                    (metric_name, predicted_value, actual_value, variance_pct, cycle_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (metric_name, predicted, actual, variance_pct, cycle_id))
        conn.commit()
        conn.close()
        logger.info(
            f"Prediction recorded: {metric_name} "
            f"(predicted={predicted}, actual={actual}, variance={variance_pct:.2f}%)"
        )
        return variance_pct
    except Exception as e:
        logger.error(f"Failed to record prediction: {e}")
        return None


def get_high_variance_events(
    threshold_pct: float = 5.0,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Retrieve predictions that exceeded the variance threshold."""
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
        )
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                SELECT * FROM {TABLE_PREDICTIONS}
                WHERE variance_pct > %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (threshold_pct, limit))
            rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to fetch high-variance events: {e}")
        return []
