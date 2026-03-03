"""
Accounting Mapper — Plaid Transaction → Journal Entry Converter
=================================================================
The "brain" of the Strangler Fig. This agent maps every Plaid
transaction to the correct Chart of Accounts entries using:

    1. Learned vendor rules (DB lookup — instant, no LLM)
    2. LLM categorization (deepseek-r1:8b — when unknown vendor)
    3. Rule persistence (once learned, NEVER ask again)

Integration:
    Called from the OODA loop ORIENT phase in each Division Agent.
    Produces a JournalEntry that the ACT phase posts via engine.py.
"""

import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import requests

from config import CAPTAIN_URL, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
from accounting.models import (
    AccountingError, AccountType, JournalEntry, LedgerLine,
)

logger = logging.getLogger("accounting.mapper")

# LLM model for mapping decisions
MAPPER_MODEL = "deepseek-r1:8b"


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
# LEARNED MAPPINGS: THE "NEVER ASK TWICE" ENGINE
# =============================================================================

def get_learned_mapping(
    vendor_name: str, schema: str = "division_b",
) -> Optional[Dict[str, str]]:
    """
    Check if we already know how to categorize this vendor.

    Returns:
        {"debit_account": "5200", "credit_account": "1000", ...}
        or None if unknown.

    Priority: qbo_import rules (trained from QBO history) take precedence
    over LLM-derived rules due to higher confidence.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # Normalize: lowercase + strip for matching
            normalized = vendor_name.strip().lower()
            # ORDER BY: prefer qbo_import over llm, then highest confidence
            cur.execute(f"""
                SELECT debit_account, credit_account, confidence,
                       reasoning, source
                FROM {schema}.account_mappings
                WHERE LOWER(TRIM(vendor_name)) = %s
                ORDER BY
                    CASE source
                        WHEN 'qbo_import' THEN 0
                        WHEN 'manual' THEN 1
                        WHEN 'llm' THEN 2
                        ELSE 3
                    END,
                    confidence DESC
                LIMIT 1
            """, (normalized,))
            row = cur.fetchone()
            if row:
                source = row[4] if row[4] else "learned_rule"
                tag = "QBO" if source == "qbo_import" else (
                    "manual" if source == "manual" else "LLM"
                )
                logger.info(
                    f"[MAPPER] Instant rule [{tag}] for '{vendor_name}': "
                    f"Dr {row[0]} / Cr {row[1]} (conf={row[2]})"
                )
                return {
                    "debit_account": row[0],
                    "credit_account": row[1],
                    "confidence": float(row[2]),
                    "reasoning": row[3],
                    "source": source,
                }
            return None
    finally:
        conn.close()


def save_learned_mapping(
    vendor_name: str,
    debit_account: str,
    credit_account: str,
    confidence: float = 0.8,
    reasoning: str = "",
    source: str = "llm",
    schema: str = "division_b",
) -> bool:
    """
    Persist a vendor → account mapping so we never ask the LLM again.
    Uses upsert: if the vendor already exists, update its mapping.

    Protection: QBO-trained rules (source='qbo_import') are NOT overwritten
    by lower-confidence LLM rules. Only manual or qbo_import updates can
    replace a qbo_import mapping.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {schema}.account_mappings
                    (vendor_name, debit_account, credit_account,
                     confidence, reasoning, source, learned_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (vendor_name) DO UPDATE SET
                    debit_account = CASE
                        WHEN {schema}.account_mappings.source = 'qbo_import'
                             AND EXCLUDED.source = 'llm'
                        THEN {schema}.account_mappings.debit_account
                        ELSE EXCLUDED.debit_account
                    END,
                    credit_account = CASE
                        WHEN {schema}.account_mappings.source = 'qbo_import'
                             AND EXCLUDED.source = 'llm'
                        THEN {schema}.account_mappings.credit_account
                        ELSE EXCLUDED.credit_account
                    END,
                    confidence = CASE
                        WHEN {schema}.account_mappings.source = 'qbo_import'
                             AND EXCLUDED.source = 'llm'
                        THEN {schema}.account_mappings.confidence
                        ELSE GREATEST(
                            {schema}.account_mappings.confidence,
                            EXCLUDED.confidence
                        )
                    END,
                    reasoning = CASE
                        WHEN {schema}.account_mappings.source = 'qbo_import'
                             AND EXCLUDED.source = 'llm'
                        THEN {schema}.account_mappings.reasoning
                        ELSE EXCLUDED.reasoning
                    END,
                    source = CASE
                        WHEN {schema}.account_mappings.source = 'qbo_import'
                             AND EXCLUDED.source = 'llm'
                        THEN {schema}.account_mappings.source
                        ELSE EXCLUDED.source
                    END,
                    learned_at = CASE
                        WHEN {schema}.account_mappings.source = 'qbo_import'
                             AND EXCLUDED.source = 'llm'
                        THEN {schema}.account_mappings.learned_at
                        ELSE NOW()
                    END
            """, (
                vendor_name.strip(), debit_account, credit_account,
                confidence, reasoning, source,
            ))
        conn.commit()
        logger.info(
            f"[MAPPER] Learned rule saved: '{vendor_name}' → "
            f"Dr {debit_account} / Cr {credit_account} [{source}]"
        )
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[MAPPER] Failed to save mapping for '{vendor_name}': {e}")
        return False
    finally:
        conn.close()


# =============================================================================
# CHART OF ACCOUNTS LOOKUP
# =============================================================================

def get_account_info(code: str, schema: str = "division_b") -> Optional[Dict]:
    """Fetch account name and type for a given code."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT code, name, account_type FROM {schema}.chart_of_accounts "
                f"WHERE code = %s AND is_active = TRUE",
                (code,),
            )
            row = cur.fetchone()
            if row:
                return {"code": row[0], "name": row[1], "account_type": row[2]}
            return None
    finally:
        conn.close()


def get_all_accounts_summary(schema: str = "division_b") -> str:
    """
    Get a compact summary of the Chart of Accounts for the LLM prompt.
    Format: "code: name (type)"
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT code, name, account_type FROM {schema}.chart_of_accounts "
                f"WHERE is_active = TRUE ORDER BY code",
            )
            rows = cur.fetchall()
            if not rows:
                return "(No accounts in Chart of Accounts)"
            lines = [f"  {r[0]}: {r[1]} ({r[2]})" for r in rows]
            return "\n".join(lines)
    finally:
        conn.close()


# =============================================================================
# LLM-POWERED MAPPING (for unknown vendors)
# =============================================================================

def _ask_llm_for_mapping(
    vendor_name: str,
    amount: float,
    plaid_categories: List[str],
    description: str,
    coa_summary: str,
    division: str = "division_b",
) -> Dict[str, Any]:
    """
    Ask the LLM to determine the correct debit and credit accounts
    for a Plaid transaction.

    Returns:
        {"debit_account": "5200", "credit_account": "1000",
         "confidence": 0.85, "reasoning": "..."}
    """
    is_property = division == "division_b"
    persona = (
        "You are a conservative property management accountant (The Controller). "
        "Precision matters. Trust accounting errors are unacceptable."
        if is_property else
        "You are an aggressive CFO/Venture Capitalist. "
        "Focus on ROI optimization and capital allocation."
    )

    prompt = f"""You are mapping a bank transaction to a double-entry journal entry.

Transaction details:
- Vendor/Name: {vendor_name}
- Amount: ${abs(amount):.2f} {"(outflow/payment)" if amount > 0 else "(inflow/deposit)"}
- Plaid Categories: {', '.join(plaid_categories) if plaid_categories else 'Unknown'}
- Description: {description}

Available Chart of Accounts:
{coa_summary}

RULES:
1. Every transaction needs EXACTLY one debit account and one credit account
2. For payments (outflows): Debit an Expense/COGS account, Credit the bank Asset account
3. For deposits (inflows): Debit the bank Asset account, Credit a Revenue/Liability account
4. {"Trust deposits: Debit Assets:Bank:Trust, Credit Liabilities:Trust:GuestEscrow" if is_property else ""}
5. {"Trust payouts: Debit Liabilities:Trust:OwnerPayable, Credit Assets:Bank:Trust" if is_property else ""}
6. If unsure, pick the closest match and explain your reasoning

Respond with ONLY valid JSON:
{{
    "debit_account": "<account_code>",
    "credit_account": "<account_code>",
    "confidence": <0.0 to 1.0>,
    "reasoning": "<one sentence explanation>"
}}"""

    payload = {
        "model": MAPPER_MODEL,
        "prompt": f"System: {persona}\n\nUser: {prompt}",
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 512},
    }

    try:
        resp = requests.post(
            f"{CAPTAIN_URL}/api/generate", json=payload, timeout=300,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")

        # Strip <think> tags from DeepSeek R1 output
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON from messy output
            match = re.search(r"\{[^}]+\}", raw, re.DOTALL)
            if match:
                return json.loads(match.group())
            logger.error(f"[MAPPER] Failed to parse LLM response: {raw[:200]}")
            return {
                "debit_account": "9999",
                "credit_account": "9999",
                "confidence": 0.0,
                "reasoning": f"PARSE_FAILED: {raw[:100]}",
            }
    except Exception as e:
        logger.error(f"[MAPPER] LLM call failed: {e}")
        return {
            "debit_account": "9999",
            "credit_account": "9999",
            "confidence": 0.0,
            "reasoning": f"LLM_ERROR: {e}",
        }


# =============================================================================
# THE MAIN MAPPER: Plaid Transaction → JournalEntry
# =============================================================================

def map_transaction(
    plaid_txn: Dict[str, Any],
    schema: str = "division_b",
) -> JournalEntry:
    """
    Convert a Plaid transaction into a validated JournalEntry.

    This is the heart of the Strangler Fig:
        1. Check learned rules (instant)
        2. If unknown, ask the LLM (slow, but only once per vendor)
        3. Save the rule (never ask again)
        4. Build and validate the JournalEntry

    Args:
        plaid_txn: Dict with keys: name, amount, date, category, transaction_id
        schema: Target division schema

    Returns:
        A validated JournalEntry (sum(debits) == sum(credits), guaranteed)
    """
    vendor = plaid_txn.get("name", "Unknown")
    # Plaid convention: positive = money out (payment), negative = money in (deposit)
    raw_amount = plaid_txn.get("amount", 0)
    amount = Decimal(str(abs(raw_amount))).quantize(Decimal("0.01"))
    txn_date = plaid_txn.get("date", date.today().isoformat())
    if isinstance(txn_date, str):
        txn_date = date.fromisoformat(txn_date)
    categories = plaid_txn.get("category", [])
    txn_id = plaid_txn.get("transaction_id", str(uuid.uuid4()))
    description = plaid_txn.get("name", "")

    # ===== STEP 1: Check learned rules =====
    mapping = get_learned_mapping(vendor, schema)

    # ===== STEP 2: Ask LLM if unknown =====
    if mapping is None:
        logger.info(f"[MAPPER] Unknown vendor '{vendor}' — asking LLM...")
        coa_summary = get_all_accounts_summary(schema)
        mapping = _ask_llm_for_mapping(
            vendor_name=vendor,
            amount=float(raw_amount),
            plaid_categories=categories,
            description=description,
            coa_summary=coa_summary,
            division=schema,
        )

        # ===== STEP 3: Save the rule =====
        if mapping.get("confidence", 0) > 0:
            save_learned_mapping(
                vendor_name=vendor,
                debit_account=mapping["debit_account"],
                credit_account=mapping["credit_account"],
                confidence=mapping.get("confidence", 0.5),
                reasoning=mapping.get("reasoning", ""),
                source="llm",
                schema=schema,
            )

    # ===== STEP 4: Build the JournalEntry =====
    debit_code = mapping["debit_account"]
    credit_code = mapping["credit_account"]

    # Resolve account names
    debit_info = get_account_info(debit_code, schema)
    credit_info = get_account_info(credit_code, schema)
    debit_name = debit_info["name"] if debit_info else f"Unknown ({debit_code})"
    credit_name = credit_info["name"] if credit_info else f"Unknown ({credit_code})"

    entry = JournalEntry(
        entry_id=str(uuid.uuid4()),
        date=txn_date,
        description=f"{vendor}: {description}" if description != vendor else vendor,
        lines=[
            LedgerLine(
                account_code=debit_code,
                account_name=debit_name,
                debit=amount,
                credit=Decimal("0.00"),
                memo=f"Plaid: {txn_id}",
            ),
            LedgerLine(
                account_code=credit_code,
                account_name=credit_name,
                debit=Decimal("0.00"),
                credit=amount,
                memo=f"Plaid: {txn_id}",
            ),
        ],
        source_type="plaid",
        source_ref=txn_id,
        division=schema,
        created_by="mapper_agent",
        memo=mapping.get("reasoning", ""),
    )

    # Validate — this MUST pass or we reject the transaction
    try:
        entry.validate()
    except AccountingError as e:
        logger.error(f"[MAPPER] VALIDATION FAILED for '{vendor}': {e}")
        raise

    source_tag = mapping.get("source", "unknown")
    if source_tag == "qbo_import":
        source_label = "QBO-trained"
    elif source_tag in ("learned_rule", "manual"):
        source_label = source_tag
    else:
        source_label = "llm"
    logger.info(
        f"[MAPPER] Mapped: {vendor} ${amount} → "
        f"Dr {debit_code} ({debit_name}) / Cr {credit_code} ({credit_name}) "
        f"[{source_label}]"
    )
    return entry


# =============================================================================
# BATCH MAPPING
# =============================================================================

def map_transactions(
    plaid_txns: List[Dict[str, Any]],
    schema: str = "division_b",
) -> List[JournalEntry]:
    """
    Map a batch of Plaid transactions to journal entries.

    Returns a list of validated JournalEntries. Transactions that
    fail mapping are logged and skipped (not included in results).
    """
    entries = []
    for txn in plaid_txns:
        try:
            entry = map_transaction(txn, schema)
            entries.append(entry)
        except AccountingError as e:
            logger.error(f"[MAPPER] Skipped transaction: {e}")
        except Exception as e:
            logger.error(
                f"[MAPPER] Unexpected error mapping "
                f"'{txn.get('name', '?')}': {e}"
            )
    return entries
