"""
MODULE CF-04: AUDIT LEDGER ENGINE
==================================
Fortress Prime | Cabin Rentals of Georgia
Lead Architect: Gary M. Knight

GAAP-compliant double-entry trust accounting engine.
This is the "Iron Dome" for your money.

Core Capabilities:
    - post_transaction():  Strict double-entry with DB-enforced balance constraint
    - detect_anomaly():    AI-powered anomaly detection (>20% historical deviation)
    - get_trial_balance(): Live trial balance across all accounts
    - get_trust_balance(): Real-time owner vs. operating fund tracking
    - void_entry():        Reversible voiding (audit trail preserved)
    - import_streamline(): Ingest Streamline VRS financial exports

Database: PostgreSQL on Captain Node (Spark 2)
AI Model: DeepSeek-R1:70b (local, via Ollama)
"""

import os
import re
import json
import logging
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, List, Any, Tuple

import psycopg2
import psycopg2.extras

# Fortress imports
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from config import (
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD,
    captain_think, CAPTAIN_MODEL,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = "/mnt/fortress_nas/fortress_data/ai_brain/logs"
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("CF04_AuditLedger")
logger.setLevel(logging.INFO)

_fh = logging.FileHandler(os.path.join(LOG_DIR, "audit_ledger.log"))
_fh.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(_ch)


# ---------------------------------------------------------------------------
# Helper: Strip DeepSeek <think> tags from LLM output
# ---------------------------------------------------------------------------
def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from DeepSeek R1 responses."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


# ===========================================================================
# AUDIT LEDGER ENGINE
# ===========================================================================

class AuditLedger:
    """
    GAAP-compliant double-entry trust accounting engine.

    Every financial transaction flows through this class.
    The PostgreSQL constraint trigger (trg_verify_balance) is the final
    backstop: if debits != credits, the DB itself rejects the commit.
    """

    def __init__(self, db_url: Optional[str] = None):
        """
        Initialize the ledger engine with a database connection.

        Args:
            db_url: PostgreSQL connection string. Falls back to config.py defaults.
        """
        self.conn_params = {
            "host": DB_HOST,
            "port": DB_PORT,
            "dbname": DB_NAME,
            "user": DB_USER,
            "password": DB_PASSWORD,
        }
        self._conn = None
        logger.info("[LEDGER] Audit Ledger Engine initialized.")

    # -- Connection Management -----------------------------------------------

    def _get_conn(self):
        """Get or create a database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self.conn_params)
        return self._conn

    def close(self):
        """Close the database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
            logger.info("[LEDGER] Database connection closed.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # -- Schema Initialization -----------------------------------------------

    def init_schema(self):
        """
        Execute schema_finance.sql to create all tables, triggers, and seed data.
        Safe to run multiple times (IF NOT EXISTS / idempotent).
        """
        schema_path = os.path.join(os.path.dirname(__file__), "schema_finance.sql")
        if not os.path.exists(schema_path):
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        conn = self._get_conn()
        cur = conn.cursor()
        try:
            with open(schema_path, "r") as f:
                sql = f.read()
            cur.execute(sql)
            conn.commit()
            logger.info("[LEDGER] Schema initialized successfully.")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"[LEDGER] Schema init failed: {e}")
            raise
        finally:
            cur.close()

    # ========================================================================
    # CORE: POST TRANSACTION (Double-Entry)
    # ========================================================================

    def post_transaction(
        self,
        debit_acct: str,
        credit_acct: str,
        amount: float,
        description: str,
        property_id: Optional[str] = None,
        reference_id: Optional[str] = None,
        reference_type: Optional[str] = None,
        entry_date: Optional[date] = None,
        posted_by: str = "system",
        source_system: str = "fortress",
        memo: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Post a double-entry transaction to the ledger.

        Creates a journal entry with exactly two line items:
          - DEBIT to debit_acct
          - CREDIT to credit_acct

        The PostgreSQL constraint trigger enforces balance at commit time.
        If debits != credits, the entire transaction is rolled back.

        Args:
            debit_acct:     Account code to debit (e.g., "1000")
            credit_acct:    Account code to credit (e.g., "4000")
            amount:         Transaction amount (positive decimal)
            description:    Human-readable description
            property_id:    Cabin/property identifier (optional)
            reference_id:   External reference number (optional)
            reference_type: Type of reference (booking, invoice, etc.)
            entry_date:     Date of the transaction (defaults to today)
            posted_by:      Who posted this (user or agent name)
            source_system:  Source system identifier
            memo:           Additional memo for line items

        Returns:
            dict with entry_id, status, and transaction details

        Raises:
            ValueError: If amount <= 0 or accounts not found
            psycopg2.Error: If balance constraint fails (Iron Dome activated)
        """
        # Validate amount
        try:
            amount = Decimal(str(amount))
        except (InvalidOperation, ValueError):
            raise ValueError(f"Invalid amount: {amount}")

        if amount <= 0:
            raise ValueError(f"Amount must be positive. Got: {amount}")

        if not description or not description.strip():
            raise ValueError("Description is required.")

        if entry_date is None:
            entry_date = date.today()

        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            # Resolve account codes to IDs
            debit_account = self._resolve_account(cur, debit_acct)
            credit_account = self._resolve_account(cur, credit_acct)

            if not debit_account:
                raise ValueError(f"Debit account not found: {debit_acct}")
            if not credit_account:
                raise ValueError(f"Credit account not found: {credit_acct}")

            # 1. Create the journal entry (header)
            cur.execute("""
                INSERT INTO journal_entries
                    (entry_date, description, reference_id, reference_type,
                     property_id, posted_by, source_system)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, created_at
            """, (entry_date, description, reference_id, reference_type,
                  property_id, posted_by, source_system))

            entry = cur.fetchone()
            entry_id = entry["id"]

            # 2. Create the DEBIT line item
            cur.execute("""
                INSERT INTO journal_line_items
                    (journal_entry_id, account_id, debit, credit, memo)
                VALUES (%s, %s, %s, 0, %s)
            """, (entry_id, debit_account["id"], amount,
                  memo or f"DR: {debit_account['name']}"))

            # 3. Create the CREDIT line item
            cur.execute("""
                INSERT INTO journal_line_items
                    (journal_entry_id, account_id, debit, credit, memo)
                VALUES (%s, %s, 0, %s, %s)
            """, (entry_id, credit_account["id"], amount,
                  memo or f"CR: {credit_account['name']}"))

            # 4. COMMIT — the constraint trigger fires here.
            #    If debits != credits, PostgreSQL rejects the transaction.
            conn.commit()

            result = {
                "status": "POSTED",
                "entry_id": entry_id,
                "entry_date": str(entry_date),
                "description": description,
                "amount": str(amount),
                "debit_account": f"{debit_account['code']} - {debit_account['name']}",
                "credit_account": f"{credit_account['code']} - {credit_account['name']}",
                "property_id": property_id,
                "reference_id": reference_id,
                "posted_by": posted_by,
                "created_at": str(entry["created_at"]),
            }

            logger.info(
                f"[LEDGER] POSTED Entry #{entry_id}: "
                f"DR {debit_acct} / CR {credit_acct} — ${amount} — {description}"
            )

            # 5. Run anomaly detection on the new entry
            try:
                anomaly = self.detect_anomaly(entry_id)
                if anomaly and anomaly.get("is_anomaly"):
                    result["anomaly_flag"] = anomaly
                    logger.warning(
                        f"[ANOMALY] Entry #{entry_id} flagged: "
                        f"{anomaly.get('flag_type')} — {anomaly.get('deviation_pct', 0):.1f}% deviation"
                    )
            except Exception as e:
                logger.warning(f"[ANOMALY] Detection failed for entry #{entry_id}: {e}")

            return result

        except psycopg2.Error as db_err:
            conn.rollback()
            logger.error(f"[IRON DOME] Transaction REJECTED: {db_err}")
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"[LEDGER] Transaction failed: {e}")
            raise
        finally:
            cur.close()

    # ========================================================================
    # CORE: POST COMPOUND TRANSACTION (Multi-Leg)
    # ========================================================================

    def post_compound_transaction(
        self,
        line_items: List[Dict[str, Any]],
        description: str,
        property_id: Optional[str] = None,
        reference_id: Optional[str] = None,
        reference_type: Optional[str] = None,
        entry_date: Optional[date] = None,
        posted_by: str = "system",
        source_system: str = "fortress",
    ) -> Dict[str, Any]:
        """
        Post a compound transaction with multiple debit/credit legs.

        For complex transactions like booking revenue splits:
          DR Cash                   $1,200
            CR Rental Revenue         $1,000
            CR Cleaning Fee Revenue   $  150
            CR Sales Tax Payable      $   50

        Args:
            line_items: List of dicts with keys:
                - account_code (str): Account code
                - debit (float): Debit amount (0 if credit)
                - credit (float): Credit amount (0 if debit)
                - memo (str, optional): Line item memo

        Returns:
            dict with entry_id and line details

        Raises:
            ValueError: If debits != credits in the provided line items
        """
        if entry_date is None:
            entry_date = date.today()

        # Pre-validate balance before hitting the DB
        total_debits = sum(Decimal(str(li.get("debit", 0))) for li in line_items)
        total_credits = sum(Decimal(str(li.get("credit", 0))) for li in line_items)

        if total_debits != total_credits:
            raise ValueError(
                f"[PRE-CHECK] Debits (${total_debits}) != Credits (${total_credits}). "
                f"Delta: ${abs(total_debits - total_credits)}"
            )

        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            # Create journal entry header
            cur.execute("""
                INSERT INTO journal_entries
                    (entry_date, description, reference_id, reference_type,
                     property_id, posted_by, source_system)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, created_at
            """, (entry_date, description, reference_id, reference_type,
                  property_id, posted_by, source_system))

            entry = cur.fetchone()
            entry_id = entry["id"]

            # Insert each line item
            posted_lines = []
            for li in line_items:
                account = self._resolve_account(cur, li["account_code"])
                if not account:
                    raise ValueError(f"Account not found: {li['account_code']}")

                debit = Decimal(str(li.get("debit", 0)))
                credit = Decimal(str(li.get("credit", 0)))
                memo = li.get("memo", "")

                cur.execute("""
                    INSERT INTO journal_line_items
                        (journal_entry_id, account_id, debit, credit, memo)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (entry_id, account["id"], debit, credit, memo))

                line = cur.fetchone()
                posted_lines.append({
                    "line_id": line["id"],
                    "account": f"{account['code']} - {account['name']}",
                    "debit": str(debit) if debit > 0 else None,
                    "credit": str(credit) if credit > 0 else None,
                    "memo": memo,
                })

            conn.commit()

            logger.info(
                f"[LEDGER] COMPOUND Entry #{entry_id}: {len(posted_lines)} legs — "
                f"${total_debits} balanced — {description}"
            )

            return {
                "status": "POSTED",
                "entry_id": entry_id,
                "entry_date": str(entry_date),
                "description": description,
                "total_amount": str(total_debits),
                "line_count": len(posted_lines),
                "lines": posted_lines,
                "property_id": property_id,
                "posted_by": posted_by,
                "created_at": str(entry["created_at"]),
            }

        except psycopg2.Error as db_err:
            conn.rollback()
            logger.error(f"[IRON DOME] Compound transaction REJECTED: {db_err}")
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"[LEDGER] Compound transaction failed: {e}")
            raise
        finally:
            cur.close()

    # ========================================================================
    # AI FEATURE: ANOMALY DETECTION
    # ========================================================================

    def detect_anomaly(
        self,
        entry_id: int,
        threshold_pct: float = 20.0,
        use_ai: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Detect if a transaction deviates >20% from the historical average
        for that specific account/property combination.

        The detection pipeline:
          1. Pull the entry's line items and their account/property context
          2. Calculate historical average for each account+property
          3. Flag if any line item exceeds the threshold
          4. (Optional) Ask DeepSeek R1 for an AI explanation

        Args:
            entry_id:      The journal entry ID to analyze
            threshold_pct: Deviation threshold (default: 20%)
            use_ai:        Whether to generate AI explanation (default: True)

        Returns:
            dict with anomaly details, or None if no anomaly detected
        """
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            # Fetch the entry and its line items
            cur.execute("""
                SELECT
                    je.id, je.entry_date, je.description, je.property_id,
                    je.reference_type, je.source_system,
                    jli.id AS line_id, jli.account_id, jli.debit, jli.credit,
                    a.code AS account_code, a.name AS account_name,
                    a.account_type, a.sub_type
                FROM journal_entries je
                JOIN journal_line_items jli ON jli.journal_entry_id = je.id
                JOIN accounts a ON a.id = jli.account_id
                WHERE je.id = %s AND je.is_void = FALSE
            """, (entry_id,))

            lines = cur.fetchall()
            if not lines:
                return None

            entry_desc = lines[0]["description"]
            property_id = lines[0]["property_id"]

            # Check each line item against historical averages
            worst_deviation = None
            worst_line = None

            for line in lines:
                amount = line["debit"] if line["debit"] > 0 else line["credit"]
                account_id = line["account_id"]

                # Get historical average for this account + property
                cur.execute("""
                    SELECT
                        AVG(CASE WHEN jli.debit > 0 THEN jli.debit ELSE jli.credit END) AS avg_amount,
                        STDDEV(CASE WHEN jli.debit > 0 THEN jli.debit ELSE jli.credit END) AS stddev_amount,
                        COUNT(*) AS txn_count
                    FROM journal_line_items jli
                    JOIN journal_entries je ON je.id = jli.journal_entry_id
                    WHERE jli.account_id = %s
                      AND je.is_void = FALSE
                      AND je.id != %s
                      {property_filter}
                """.format(
                    property_filter="AND je.property_id = %s" if property_id else ""
                ), (account_id, entry_id, property_id) if property_id else (account_id, entry_id))

                stats = cur.fetchone()

                if not stats or stats["txn_count"] < 3:
                    # Not enough history to judge — skip
                    continue

                avg_amount = stats["avg_amount"]
                if avg_amount and avg_amount > 0:
                    deviation_pct = abs(float(amount - avg_amount) / float(avg_amount)) * 100

                    if deviation_pct > threshold_pct:
                        if worst_deviation is None or deviation_pct > worst_deviation:
                            worst_deviation = deviation_pct
                            worst_line = {
                                **dict(line),
                                "amount": float(amount),
                                "avg_amount": float(avg_amount),
                                "stddev": float(stats["stddev_amount"]) if stats["stddev_amount"] else 0,
                                "txn_count": stats["txn_count"],
                                "deviation_pct": deviation_pct,
                            }

            if worst_deviation is None:
                return None

            # Determine severity
            if worst_deviation > 100:
                severity = "critical"
            elif worst_deviation > 50:
                severity = "high"
            elif worst_deviation > 30:
                severity = "medium"
            else:
                severity = "low"

            # Build the anomaly record
            anomaly = {
                "is_anomaly": True,
                "entry_id": entry_id,
                "flag_type": "amount_deviation",
                "severity": severity,
                "deviation_pct": round(worst_deviation, 2),
                "expected_amount": round(worst_line["avg_amount"], 2),
                "actual_amount": round(worst_line["amount"], 2),
                "account_code": worst_line["account_code"],
                "account_name": worst_line["account_name"],
                "property_id": property_id,
                "description": entry_desc,
                "historical_count": worst_line["txn_count"],
            }

            # Optional: Ask the Captain (DeepSeek R1) for an AI explanation
            ai_explanation = None
            if use_ai:
                try:
                    ai_explanation = self._ai_explain_anomaly(anomaly)
                    anomaly["ai_explanation"] = ai_explanation
                except Exception as e:
                    logger.warning(f"[ANOMALY] AI explanation failed: {e}")
                    anomaly["ai_explanation"] = None

            # Persist the anomaly flag
            cur.execute("""
                INSERT INTO anomaly_flags
                    (journal_entry_id, account_id, flag_type, severity,
                     deviation_pct, expected_amount, actual_amount, ai_explanation)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                entry_id, worst_line["account_id"], "amount_deviation",
                severity, worst_deviation, worst_line["avg_amount"],
                worst_line["amount"], ai_explanation
            ))
            conn.commit()

            flag_record = cur.fetchone()
            anomaly["flag_id"] = flag_record["id"] if flag_record else None

            logger.warning(
                f"[ANOMALY] FLAGGED Entry #{entry_id}: "
                f"{worst_line['account_code']} — {severity.upper()} — "
                f"{worst_deviation:.1f}% deviation "
                f"(${worst_line['amount']:.2f} vs avg ${worst_line['avg_amount']:.2f})"
            )

            return anomaly

        except Exception as e:
            conn.rollback()
            logger.error(f"[ANOMALY] Detection error for entry #{entry_id}: {e}")
            return None
        finally:
            cur.close()

    def _ai_explain_anomaly(self, anomaly: Dict[str, Any]) -> Optional[str]:
        """
        Ask DeepSeek R1 to explain a financial anomaly in plain English.
        """
        prompt = f"""You are a forensic accountant reviewing a flagged transaction.

FLAGGED TRANSACTION:
- Entry ID: {anomaly['entry_id']}
- Description: {anomaly['description']}
- Account: {anomaly['account_code']} - {anomaly['account_name']}
- Amount: ${anomaly['actual_amount']:,.2f}
- Historical Average: ${anomaly['expected_amount']:,.2f}
- Deviation: {anomaly['deviation_pct']:.1f}%
- Severity: {anomaly['severity'].upper()}
- Property: {anomaly.get('property_id', 'N/A')}
- Historical Transaction Count: {anomaly['historical_count']}

Provide a brief (2-3 sentence) explanation of:
1. Why this might be flagged
2. What a property manager should check
3. Whether this is likely a legitimate transaction or warrants investigation

Be specific to cabin rental / property management context. Respond in plain text only."""

        system_role = (
            "You are the Chief Financial Officer AI for Cabin Rentals of Georgia. "
            "You analyze flagged transactions with forensic precision. "
            "Be concise, specific, and actionable."
        )

        response = captain_think(prompt, system_role=system_role, temperature=0.3)
        return _strip_think_tags(response)

    # ========================================================================
    # REPORTING: TRIAL BALANCE
    # ========================================================================

    def get_trial_balance(self) -> List[Dict[str, Any]]:
        """
        Returns the current trial balance across all active accounts.
        Total debits must equal total credits (fundamental accounting equation).
        """
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("SELECT * FROM v_trial_balance")
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            cur.close()

    # ========================================================================
    # REPORTING: TRUST BALANCE
    # ========================================================================

    def get_trust_balance(self, property_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Returns current trust balance — owner funds vs. operating funds.

        Args:
            property_id: Filter by specific property (optional)
        """
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            if property_id:
                cur.execute(
                    "SELECT * FROM v_trust_summary WHERE property_id = %s",
                    (property_id,)
                )
            else:
                cur.execute("SELECT * FROM v_trust_summary")
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            cur.close()

    def update_trust_balance(
        self,
        property_id: str,
        owner_delta: Decimal = Decimal("0"),
        operating_delta: Decimal = Decimal("0"),
        escrow_delta: Decimal = Decimal("0"),
        security_delta: Decimal = Decimal("0"),
        entry_id: Optional[int] = None,
    ):
        """
        Adjust the trust balance for a property after a transaction posts.

        Uses UPSERT to create or update the balance record.
        """
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO trust_balance
                    (property_id, owner_funds, operating_funds, escrow_funds,
                     security_deps, last_entry_id, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (property_id)
                DO UPDATE SET
                    owner_funds     = trust_balance.owner_funds     + EXCLUDED.owner_funds,
                    operating_funds = trust_balance.operating_funds + EXCLUDED.operating_funds,
                    escrow_funds    = trust_balance.escrow_funds    + EXCLUDED.escrow_funds,
                    security_deps   = trust_balance.security_deps   + EXCLUDED.security_deps,
                    last_entry_id   = EXCLUDED.last_entry_id,
                    last_updated    = CURRENT_TIMESTAMP
            """, (property_id, owner_delta, operating_delta, escrow_delta,
                  security_delta, entry_id))
            conn.commit()
            logger.info(
                f"[TRUST] Updated balance for {property_id}: "
                f"owner={owner_delta}, operating={operating_delta}, "
                f"escrow={escrow_delta}, security={security_delta}"
            )
        except Exception as e:
            conn.rollback()
            logger.error(f"[TRUST] Balance update failed for {property_id}: {e}")
            raise
        finally:
            cur.close()

    # ========================================================================
    # VOID ENTRY (Audit-Safe Reversal)
    # ========================================================================

    def void_entry(
        self,
        entry_id: int,
        reason: str,
        voided_by: str = "system",
    ) -> Dict[str, Any]:
        """
        Void a journal entry. Does NOT delete — marks as void with reason.
        All voided entries remain in the audit trail.

        Args:
            entry_id:  The journal entry ID to void
            reason:    Why this entry is being voided
            voided_by: Who is voiding it
        """
        if not reason or not reason.strip():
            raise ValueError("Void reason is required for audit trail.")

        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("""
                UPDATE journal_entries
                SET is_void = TRUE,
                    void_reason = %s,
                    voided_at = CURRENT_TIMESTAMP,
                    voided_by = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND is_void = FALSE
                RETURNING id, description, entry_date
            """, (reason, voided_by, entry_id))

            voided = cur.fetchone()
            if not voided:
                raise ValueError(
                    f"Entry #{entry_id} not found or already voided."
                )

            conn.commit()

            logger.info(
                f"[LEDGER] VOIDED Entry #{entry_id}: {voided['description']} — "
                f"Reason: {reason} — By: {voided_by}"
            )

            return {
                "status": "VOIDED",
                "entry_id": entry_id,
                "description": voided["description"],
                "entry_date": str(voided["entry_date"]),
                "void_reason": reason,
                "voided_by": voided_by,
            }

        except Exception as e:
            conn.rollback()
            logger.error(f"[LEDGER] Void failed for entry #{entry_id}: {e}")
            raise
        finally:
            cur.close()

    # ========================================================================
    # QUERY: JOURNAL ENTRIES
    # ========================================================================

    def get_journal_entries(
        self,
        property_id: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        reference_type: Optional[str] = None,
        include_void: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query journal entries with optional filters.
        """
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        conditions = []
        params = []

        if not include_void:
            conditions.append("je.is_void = FALSE")
        if property_id:
            conditions.append("je.property_id = %s")
            params.append(property_id)
        if start_date:
            conditions.append("je.entry_date >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("je.entry_date <= %s")
            params.append(end_date)
        if reference_type:
            conditions.append("je.reference_type = %s")
            params.append(reference_type)

        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        params.append(limit)

        try:
            cur.execute(f"""
                SELECT
                    je.*,
                    json_agg(json_build_object(
                        'line_id', jli.id,
                        'account_code', a.code,
                        'account_name', a.name,
                        'debit', jli.debit,
                        'credit', jli.credit,
                        'memo', jli.memo
                    ) ORDER BY jli.id) AS line_items
                FROM journal_entries je
                LEFT JOIN journal_line_items jli ON jli.journal_entry_id = je.id
                LEFT JOIN accounts a ON a.id = jli.account_id
                WHERE {where_clause}
                GROUP BY je.id
                ORDER BY je.entry_date DESC, je.id DESC
                LIMIT %s
            """, params)

            return [dict(r) for r in cur.fetchall()]
        finally:
            cur.close()

    # ========================================================================
    # QUERY: ACCOUNT LOOKUP
    # ========================================================================

    def get_accounts(
        self,
        account_type: Optional[str] = None,
        active_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return the chart of accounts, optionally filtered by type."""
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            conditions = []
            params = []
            if active_only:
                conditions.append("is_active = TRUE")
            if account_type:
                conditions.append("account_type = %s")
                params.append(account_type)

            where_clause = " AND ".join(conditions) if conditions else "TRUE"

            cur.execute(
                f"SELECT * FROM accounts WHERE {where_clause} ORDER BY code",
                params,
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            cur.close()

    # ========================================================================
    # QUERY: ANOMALY FLAGS
    # ========================================================================

    def get_anomaly_flags(
        self,
        reviewed: Optional[bool] = None,
        severity: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return anomaly flags, optionally filtered."""
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            conditions = []
            params = []
            if reviewed is not None:
                conditions.append("af.reviewed = %s")
                params.append(reviewed)
            if severity:
                conditions.append("af.severity = %s")
                params.append(severity)

            where_clause = " AND ".join(conditions) if conditions else "TRUE"
            params.append(limit)

            cur.execute(f"""
                SELECT
                    af.*,
                    je.description AS entry_description,
                    je.entry_date,
                    je.property_id,
                    a.code AS account_code,
                    a.name AS account_name
                FROM anomaly_flags af
                JOIN journal_entries je ON je.id = af.journal_entry_id
                LEFT JOIN accounts a ON a.id = af.account_id
                WHERE {where_clause}
                ORDER BY af.created_at DESC
                LIMIT %s
            """, params)

            return [dict(r) for r in cur.fetchall()]
        finally:
            cur.close()

    def review_anomaly(
        self,
        flag_id: int,
        reviewed_by: str,
        notes: str,
    ) -> Dict[str, Any]:
        """Mark an anomaly flag as reviewed."""
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("""
                UPDATE anomaly_flags
                SET reviewed = TRUE,
                    reviewed_by = %s,
                    reviewed_at = CURRENT_TIMESTAMP,
                    review_notes = %s
                WHERE id = %s
                RETURNING id, flag_type, severity
            """, (reviewed_by, notes, flag_id))

            result = cur.fetchone()
            conn.commit()

            if not result:
                raise ValueError(f"Anomaly flag #{flag_id} not found.")

            return {
                "status": "REVIEWED",
                "flag_id": flag_id,
                "reviewed_by": reviewed_by,
                "notes": notes,
            }
        except Exception as e:
            conn.rollback()
            raise
        finally:
            cur.close()

    # ========================================================================
    # INTERNAL HELPERS
    # ========================================================================

    def _resolve_account(self, cur, code_or_name: str) -> Optional[Dict[str, Any]]:
        """Resolve an account by code or name."""
        cur.execute(
            "SELECT id, code, name, account_type, normal_balance "
            "FROM accounts WHERE code = %s AND is_active = TRUE",
            (code_or_name,)
        )
        result = cur.fetchone()
        if result:
            return dict(result)

        # Fallback: try by name (case-insensitive)
        cur.execute(
            "SELECT id, code, name, account_type, normal_balance "
            "FROM accounts WHERE LOWER(name) = LOWER(%s) AND is_active = TRUE",
            (code_or_name,)
        )
        result = cur.fetchone()
        return dict(result) if result else None


# ===========================================================================
# CLI: Quick test / schema init
# ===========================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CF-04 Audit Ledger Engine")
    parser.add_argument("--init", action="store_true", help="Initialize the database schema")
    parser.add_argument("--trial-balance", action="store_true", help="Print trial balance")
    parser.add_argument("--accounts", action="store_true", help="Print chart of accounts")
    parser.add_argument("--test", action="store_true", help="Post a test transaction")
    args = parser.parse_args()

    with AuditLedger() as ledger:
        if args.init:
            print("=" * 60)
            print("  CF-04 AUDIT LEDGER — SCHEMA INITIALIZATION")
            print("=" * 60)
            ledger.init_schema()
            print("  Schema initialized. Iron Dome is ARMED.")
            print("=" * 60)

        elif args.trial_balance:
            print("=" * 60)
            print("  TRIAL BALANCE")
            print("=" * 60)
            tb = ledger.get_trial_balance()
            total_dr = Decimal("0")
            total_cr = Decimal("0")
            for row in tb:
                dr = row["total_debits"]
                cr = row["total_credits"]
                if dr > 0 or cr > 0:
                    print(f"  {row['code']:6s}  {row['account_name']:35s}  "
                          f"DR ${dr:>12,.2f}  CR ${cr:>12,.2f}")
                    total_dr += dr
                    total_cr += cr
            print("-" * 80)
            print(f"  {'TOTALS':42s}  DR ${total_dr:>12,.2f}  CR ${total_cr:>12,.2f}")
            if total_dr == total_cr:
                print("  STATUS: BALANCED")
            else:
                print(f"  STATUS: OUT OF BALANCE by ${abs(total_dr - total_cr):,.2f}")
            print("=" * 60)

        elif args.accounts:
            print("=" * 60)
            print("  CHART OF ACCOUNTS")
            print("=" * 60)
            accounts = ledger.get_accounts()
            current_type = None
            for acct in accounts:
                if acct["account_type"] != current_type:
                    current_type = acct["account_type"]
                    print(f"\n  --- {current_type.upper()} ---")
                print(f"  {acct['code']:6s}  {acct['name']:40s}  "
                      f"({acct['normal_balance']})")
            print(f"\n  Total accounts: {len(accounts)}")
            print("=" * 60)

        elif args.test:
            print("=" * 60)
            print("  CF-04 AUDIT LEDGER — TEST TRANSACTION")
            print("=" * 60)
            result = ledger.post_transaction(
                debit_acct="1000",        # Cash - Operating
                credit_acct="4000",       # Rental Revenue
                amount=1250.00,
                description="Test booking revenue — Mountain View Cabin",
                property_id="mountain_view_cabin",
                reference_id="TEST-001",
                reference_type="booking",
                posted_by="architect_test",
            )
            print(f"  Status:   {result['status']}")
            print(f"  Entry ID: {result['entry_id']}")
            print(f"  Amount:   ${Decimal(result['amount']):,.2f}")
            print(f"  Debit:    {result['debit_account']}")
            print(f"  Credit:   {result['credit_account']}")
            if result.get("anomaly_flag"):
                print(f"  ANOMALY:  {result['anomaly_flag']['severity'].upper()} — "
                      f"{result['anomaly_flag']['deviation_pct']:.1f}% deviation")
            print("=" * 60)

        else:
            parser.print_help()
