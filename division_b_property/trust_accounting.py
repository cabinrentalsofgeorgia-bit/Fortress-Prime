"""
Trust Accounting Engine — Guest Escrow & Vendor Payouts
=========================================================
Zero-error trust accounting for Cabin Rentals of Georgia.

Trust accounting rules (Georgia law):
    - Guest deposits held in escrow until checkout + 7 days
    - Vendor payouts require matched invoice
    - All trust movements must balance to zero
    - Owner distributions only after all obligations cleared
    - Security deposits returned within 30 days of checkout

This module is the HEART of Division B compliance.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

logger = logging.getLogger("division_b.trust")


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class EscrowEntry:
    """A single escrow hold (guest payment awaiting release)."""
    reservation_id: str
    guest_name: str
    cabin_id: str
    amount: Decimal
    deposit_date: date
    checkout_date: Optional[date] = None
    release_date: Optional[date] = None      # checkout + 7 days
    status: str = "held"                       # held, released, disputed, refunded
    notes: str = ""


@dataclass
class VendorPayout:
    """A vendor payout request (must match invoice)."""
    vendor_name: str
    amount: Decimal
    invoice_number: str
    invoice_date: date
    cabin_id: Optional[str] = None
    category: str = "MAINTENANCE"
    status: str = "pending"                    # pending, approved, paid, disputed
    approved_by: str = ""


@dataclass
class TrustLedger:
    """The trust account ledger — must always balance to zero."""
    entries: List[Dict[str, Any]] = field(default_factory=list)
    balance: Decimal = Decimal("0.00")


# =============================================================================
# SCHEMA
# =============================================================================

SCHEMA = "division_b"

INIT_SQL = f"""
-- Division B: Cabin Rentals of Georgia Trust Accounting
-- FIREWALL: This schema is ONLY accessible by Division B agents.

CREATE SCHEMA IF NOT EXISTS {SCHEMA};

CREATE TABLE IF NOT EXISTS {SCHEMA}.escrow (
    id              SERIAL PRIMARY KEY,
    reservation_id  TEXT UNIQUE NOT NULL,
    guest_name      TEXT NOT NULL,
    cabin_id        TEXT NOT NULL,
    amount          NUMERIC(12, 2) NOT NULL,
    deposit_date    DATE NOT NULL,
    checkout_date   DATE,
    release_date    DATE,
    status          TEXT DEFAULT 'held',
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.vendor_payouts (
    id              SERIAL PRIMARY KEY,
    vendor_name     TEXT NOT NULL,
    amount          NUMERIC(12, 2) NOT NULL,
    invoice_number  TEXT,
    invoice_date    DATE,
    cabin_id        TEXT,
    category        TEXT DEFAULT 'MAINTENANCE',
    status          TEXT DEFAULT 'pending',
    approved_by     TEXT,
    plaid_txn_id    TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.trust_ledger (
    id              SERIAL PRIMARY KEY,
    entry_type      TEXT NOT NULL,  -- deposit, payout, refund, distribution
    amount          NUMERIC(12, 2) NOT NULL,
    reference_id    TEXT,           -- reservation_id or vendor_payout_id
    description     TEXT,
    running_balance NUMERIC(14, 2),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.transactions (
    id              SERIAL PRIMARY KEY,
    plaid_txn_id    TEXT UNIQUE,
    date            DATE NOT NULL,
    vendor          TEXT NOT NULL,
    amount          NUMERIC(12, 2) NOT NULL,
    category        TEXT NOT NULL DEFAULT 'UNCATEGORIZED',
    confidence      NUMERIC(4, 3) DEFAULT 0.0,
    trust_related   BOOLEAN DEFAULT FALSE,
    reservation_id  TEXT,
    reasoning       TEXT,
    method          TEXT DEFAULT 'manual',
    account_id      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.predictions (
    id              SERIAL PRIMARY KEY,
    metric_name     TEXT NOT NULL,
    predicted_value NUMERIC(14, 4),
    actual_value    NUMERIC(14, 4),
    variance_pct    NUMERIC(8, 4),
    cycle_id        INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_div_b_escrow_status ON {SCHEMA}.escrow(status);
CREATE INDEX IF NOT EXISTS idx_div_b_escrow_cabin ON {SCHEMA}.escrow(cabin_id);
CREATE INDEX IF NOT EXISTS idx_div_b_txn_date ON {SCHEMA}.transactions(date);
CREATE INDEX IF NOT EXISTS idx_div_b_txn_trust ON {SCHEMA}.transactions(trust_related);
"""


def init_schema() -> bool:
    """Create the Division B schema and tables if they don't exist."""
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
        logger.info("Division B schema initialized.")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize Division B schema: {e}")
        return False


# =============================================================================
# ESCROW OPERATIONS
# =============================================================================

def deposit_escrow(entry: EscrowEntry) -> bool:
    """
    Record a guest escrow deposit.
    Automatically sets release_date to checkout_date + 7 days.
    """
    if entry.checkout_date:
        entry.release_date = entry.checkout_date + timedelta(days=7)

    try:
        import psycopg2
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
        )
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {SCHEMA}.escrow
                    (reservation_id, guest_name, cabin_id, amount,
                     deposit_date, checkout_date, release_date, status, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (reservation_id) DO UPDATE SET
                    amount = EXCLUDED.amount,
                    status = EXCLUDED.status,
                    updated_at = NOW()
            """, (
                entry.reservation_id, entry.guest_name, entry.cabin_id,
                float(entry.amount), entry.deposit_date, entry.checkout_date,
                entry.release_date, entry.status, entry.notes,
            ))

            # Record in trust ledger
            cur.execute(f"""
                INSERT INTO {SCHEMA}.trust_ledger
                    (entry_type, amount, reference_id, description)
                VALUES ('deposit', %s, %s, %s)
            """, (
                float(entry.amount),
                entry.reservation_id,
                f"Guest escrow: {entry.guest_name} @ {entry.cabin_id}",
            ))

        conn.commit()
        conn.close()
        logger.info(
            f"Escrow deposited: ${entry.amount} for {entry.guest_name} "
            f"(res: {entry.reservation_id})"
        )
        return True
    except Exception as e:
        logger.error(f"Escrow deposit failed: {e}")
        return False


def get_releasable_escrows(as_of: Optional[date] = None) -> List[Dict[str, Any]]:
    """
    Get all escrow entries that are eligible for release.

    An escrow is releasable when:
        status = 'held' AND release_date <= today
    """
    if as_of is None:
        as_of = date.today()

    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
        )
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                SELECT * FROM {SCHEMA}.escrow
                WHERE status = 'held' AND release_date <= %s
                ORDER BY release_date
            """, (as_of,))
            rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to fetch releasable escrows: {e}")
        return []


# =============================================================================
# TRUST BALANCE VERIFICATION
# =============================================================================

def verify_trust_balance() -> Dict[str, Any]:
    """
    Verify the trust ledger balances to zero (deposits = payouts + refunds).

    This is the single most important compliance check in Division B.
    Any non-zero result triggers a CRITICAL anomaly to the Sovereign.
    """
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
        )
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT
                    COALESCE(SUM(CASE WHEN entry_type = 'deposit' THEN amount ELSE 0 END), 0) as deposits,
                    COALESCE(SUM(CASE WHEN entry_type = 'payout' THEN amount ELSE 0 END), 0) as payouts,
                    COALESCE(SUM(CASE WHEN entry_type = 'refund' THEN amount ELSE 0 END), 0) as refunds,
                    COALESCE(SUM(CASE WHEN entry_type = 'distribution' THEN amount ELSE 0 END), 0) as distributions
                FROM {SCHEMA}.trust_ledger
            """)
            row = cur.fetchone()
        conn.close()

        deposits, payouts, refunds, distributions = row
        net = float(deposits) - float(payouts) - float(refunds) - float(distributions)

        return {
            "deposits": float(deposits),
            "payouts": float(payouts),
            "refunds": float(refunds),
            "distributions": float(distributions),
            "net_balance": net,
            "balanced": abs(net) < 0.01,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Trust balance verification failed: {e}")
        return {"error": str(e), "balanced": False}
