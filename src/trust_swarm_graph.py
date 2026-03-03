"""
Trust Accounting Swarm — GAAP Double-Entry Cognitive Engine

Tripartite LangGraph pipeline that converts unstructured trust-domain
invoices into mathematically balanced journal entries for the CF-04
Iron Dome ledger (fortress_guest database):

  1. Entity Resolver  — fuzzy property name → canonical property_id
  2. Ledger Coder     — HYDRA-powered double-entry JSON generation
  3. Fiduciary Auditor — pre-flight operating-funds sufficiency check

Invoked by the Trust Consumer Daemon after the Triage Router dispatches
a payload to ``trust.accounting.staged``.

Usage (import only — no standalone daemon):
    from src.trust_swarm_graph import trust_swarm
"""

import os
import sys
import json
import time
import re
import logging
import psycopg2
from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, END
from openai import NotFoundError, APIConnectionError, APITimeoutError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_inference_client

log = logging.getLogger("trust_swarm")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = "fortress_guest"
DB_USER = os.getenv("FGP_DB_USER", "fgp_app")
DB_PASS = os.getenv("FGP_DB_PASS", "F0rtr3ss_Gu3st_2026!")

CAPEX_THRESHOLD = float(os.getenv("CAPEX_APPROVAL_THRESHOLD", "500.00"))

LLM_MAX_RETRIES = 8


class TrustState(TypedDict):
    raw_text: str
    vendor: str
    amount: float
    description: str
    property_id: str
    property_name: str
    markup_percentage: float
    total_charged_to_owner: float
    journal_lines: List[Dict[str, Any]]
    compliance_status: str
    audit_trail: List[str]


def _get_db_connection():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)


def _llm_with_retry(client_type: str, prompt: str, is_json: bool = False):
    """Resilient LLM invocation surviving dead Nginx upstream nodes.

    Uses Nginx LB first; after consecutive failures falls back to the
    direct Captain endpoint (port 11434) where both qwen2.5:7b and
    deepseek-r1:70b are loaded.
    """
    from openai import OpenAI as _OpenAI

    INFERENCE_DIRECT = "http://192.168.0.106:11434/v1"  # Spark-04 (Sovereign)

    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            if attempt <= 4:
                client, model = get_inference_client(client_type)
            else:
                _, model = get_inference_client(client_type)
                client = _OpenAI(base_url=INFERENCE_DIRECT, api_key="not-needed", timeout=300.0)
                log.info("[LLM] Falling back to direct inference node (attempt %d)", attempt)

            kwargs = {
                "model": model,
                "messages": [{"role": "system", "content": prompt}],
                "temperature": 0.0,
            }
            if is_json:
                kwargs["response_format"] = {"type": "json_object"}

            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content
        except (NotFoundError, APIConnectionError, APITimeoutError) as e:
            if attempt == LLM_MAX_RETRIES:
                raise
            log.warning(
                "[LLM] Attempt %d/%d failed (%s), retrying...",
                attempt, LLM_MAX_RETRIES, type(e).__name__,
            )
            time.sleep(0.5 * attempt)


# ---------------------------------------------------------------------------
# Node 1: Entity Resolver — semantic-to-relational bridge
# ---------------------------------------------------------------------------

def entity_resolver_node(state: TrustState) -> dict:
    """Resolve fuzzy property text to a canonical property_id from the DB."""
    log.info("[TRUST SWARM] Resolving physical property entity...")

    property_lookup_lines: list[str] = []
    try:
        with _get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tbc.property_id, COALESCE(p.name, 'Unknown') AS name "
                    "FROM trust_balance_cache tbc "
                    "LEFT JOIN properties p "
                    "ON p.streamline_property_id = tbc.property_id"
                )
                for row in cur.fetchall():
                    property_lookup_lines.append(f"  - {row[0]}: {row[1]}")
    except Exception as e:
        log.error("DB connection failed in resolver: %s", e)

    property_lookup_text = "\n".join(property_lookup_lines) or "  (no properties loaded)"

    prompt = (
        "You are the Entity Resolver for the CROG Trust Swarm.\n"
        "Your job is to read an invoice or email text and identify the "
        "exact property_id it belongs to.\n\n"
        "PROPERTY LOOKUP TABLE:\n"
        f"{property_lookup_text}\n\n"
        f"TEXT: {state['raw_text']} | {state['description']}\n\n"
        "Return ONLY valid JSON with the matching property_id from the "
        "lookup table above. If you cannot determine the property with "
        "100%% certainty, return UNKNOWN.\n\n"
        'Format: {"property_id": "EXACT_ID_FROM_TABLE"}'
    )

    try:
        content = _llm_with_retry("SWARM", prompt, is_json=True)
        pid = json.loads(content).get("property_id", "UNKNOWN")
    except Exception as e:
        log.error("Resolver LLM failed: %s", e)
        pid = "UNKNOWN"

    markup_pct = 0.0
    if pid != "UNKNOWN":
        try:
            with _get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT markup_percentage FROM owner_markup_rules
                        WHERE property_id = %s
                          AND (expense_category = 'ALL' OR expense_category = 'MAINTENANCE')
                        ORDER BY CASE WHEN expense_category = 'MAINTENANCE'
                                 THEN 0 ELSE 1 END
                        LIMIT 1
                    """, (pid,))
                    row = cur.fetchone()
                    if row:
                        markup_pct = float(row[0])
        except Exception as e:
            log.error("Failed to fetch markup rules: %s", e)

    total_charge = round(state["amount"] + (state["amount"] * (markup_pct / 100)), 2)

    return {
        "property_id": pid,
        "property_name": pid,
        "markup_percentage": markup_pct,
        "total_charged_to_owner": total_charge,
        "audit_trail": state["audit_trail"] + [
            f"RESOLVED ENTITY: {pid} | MARGIN: {markup_pct}% | "
            f"Total charged: ${total_charge:.2f}"
        ],
    }


# ---------------------------------------------------------------------------
# Node 2: Ledger Coder — GAAP double-entry JSON generator
# ---------------------------------------------------------------------------

CHART_OF_ACCOUNTS_PROMPT = """\
CHART OF ACCOUNTS (CF-04 Iron Dome):
  ASSET ACCOUNTS (normal balance = debit):
    1000  Cash - Operating
    1010  Cash - Trust
  LIABILITY ACCOUNTS (normal balance = credit):
    2000  Trust Liability - Owners
    2100  Accounts Payable
  REVENUE ACCOUNTS (normal balance = credit):
    4100  PM Overhead & Maintenance Revenue
  EXPENSE ACCOUNTS (normal balance = debit):
    5000  Cleaning Expense
    5010  Maintenance & Repairs
    5020  Utilities
    5030  Supplies
    5040  Insurance
    5050  Property Tax
    5060  Advertising & Marketing
    5070  Software & Technology
    5080  Professional Fees
    5090  Payroll
    5100  Commission Expense
    5200  Owner Payout
    5900  Miscellaneous Expense
"""


def ledger_coder_node(state: TrustState) -> dict:
    """Draft strictly balanced double-entry journal lines."""
    log.info("[TRUST SWARM] Coding Double-Entry Journal Lines...")

    if state["property_id"] == "UNKNOWN":
        return {
            "compliance_status": "REJECTED_UNMAPPED_PROPERTY",
            "audit_trail": state["audit_trail"]
            + ["REJECTED: Cannot code ledger without valid property_id."],
        }

    overhead_amount = round(state["total_charged_to_owner"] - state["amount"], 2)

    prompt = (
        "You are a strictly compliant Trust Accountant (GAAP) for a PM Company.\n"
        "Draft the journal entries for this maintenance invoice.\n\n"
        f"Vendor Cost: ${state['amount']:.2f} (Owed to {state['vendor']})\n"
        f"PM Overhead Markup: {state['markup_percentage']}%\n"
        f"Total Charged to Owner: ${state['total_charged_to_owner']:.2f}\n\n"
        f"{CHART_OF_ACCOUNTS_PROMPT}\n"
        "EXECUTE THE 3-WAY SPLIT:\n"
        f"1. DEBIT account 2000 for ${state['total_charged_to_owner']:.2f} "
        "(reduces owner funds by total charge).\n"
        f"2. CREDIT account 2100 for ${state['amount']:.2f} "
        "(stages vendor payable at actual cost).\n"
        f"3. CREDIT account 4100 for ${overhead_amount:.2f} "
        "(captures PM overhead profit).\n\n"
        "Requirements:\n"
        "1. Debits MUST equal Credits exactly.\n"
        '2. Output ONLY a JSON array: [{"code": "2000", "type": "debit", '
        '"amount": 287.50}, ...]\n'
        "3. Use the exact account codes from the chart above."
    )

    try:
        content = _llm_with_retry("SWARM", prompt, is_json=False)
        clean = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        json_match = re.search(r"\[.*\]", clean, re.DOTALL)

        if json_match:
            lines = json.loads(json_match.group(0))
            debits = sum(float(l["amount"]) for l in lines if l.get("type", "").lower() == "debit")
            credits = sum(float(l["amount"]) for l in lines if l.get("type", "").lower() == "credit")

            if abs(debits - credits) > 0.01:
                return {
                    "compliance_status": "REJECTED_UNBALANCED",
                    "audit_trail": state["audit_trail"]
                    + [f"REJECTED: Unbalanced entry (DR {debits} != CR {credits})"],
                }

            return {
                "journal_lines": lines,
                "audit_trail": state["audit_trail"]
                + [f"CODED LEDGER: {len(lines)} lines balanced at ${debits:.2f}"],
            }
    except Exception as e:
        log.error("Ledger Coder failed: %s", e)

    return {
        "compliance_status": "REJECTED_PARSE_ERROR",
        "audit_trail": state["audit_trail"]
        + ["REJECTED: Failed to parse valid JSON array from HYDRA."],
    }


# ---------------------------------------------------------------------------
# Node 3: Fiduciary Auditor — pre-flight operating-funds check
# ---------------------------------------------------------------------------

def fiduciary_auditor_node(state: TrustState) -> dict:
    """Verify sufficient operating funds before authorizing the commit."""
    log.info("[TRUST SWARM] Executing Fiduciary Audit...")

    if state.get("compliance_status", "").startswith("REJECTED"):
        return {}

    pid = state["property_id"]
    amount_needed = float(state.get("total_charged_to_owner", state["amount"]))
    status = "REJECTED_AUDIT_ERROR"
    audit_msg = "AUDIT FAILED: DB exception."

    try:
        with _get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT operating_funds FROM trust_balance_cache WHERE property_id = %s",
                    (pid,),
                )
                row = cur.fetchone()

                if not row:
                    status = "REJECTED_ACCOUNT_NOT_FOUND"
                    audit_msg = f"AUDIT FAILED: No trust account found for {pid}."
                else:
                    operating_funds = float(row[0])
                    if operating_funds < amount_needed:
                        status = "CAPITAL_CALL_REQUIRED"
                        audit_msg = (
                            f"AUDIT FLAG: Insufficient operating funds "
                            f"(${operating_funds:.2f}). "
                            f"Requires capital call for ${amount_needed:.2f} "
                            f"(vendor ${state['amount']:.2f} + "
                            f"overhead ${amount_needed - state['amount']:.2f})."
                        )
                    elif amount_needed >= CAPEX_THRESHOLD:
                        status = "PENDING_CAPEX_APPROVAL"
                        audit_msg = (
                            f"CAPEX GATE: Invoice ${amount_needed:.2f} >= "
                            f"threshold ${CAPEX_THRESHOLD:.2f}. "
                            f"Staged for owner approval. "
                            f"Funds available: ${operating_funds:.2f}."
                        )
                    else:
                        status = "CLEARED"
                        audit_msg = (
                            f"AUDIT PASSED: Sufficient funds. "
                            f"Balance: ${operating_funds:.2f} >= "
                            f"Required: ${amount_needed:.2f} "
                            f"(vendor ${state['amount']:.2f} + "
                            f"overhead ${amount_needed - state['amount']:.2f})"
                        )
    except Exception as e:
        log.error("Fiduciary audit failed: %s", e)

    return {
        "compliance_status": status,
        "audit_trail": state["audit_trail"] + [audit_msg],
    }


# ---------------------------------------------------------------------------
# Graph Assembly
# ---------------------------------------------------------------------------

workflow = StateGraph(TrustState)
workflow.add_node("entity_resolver", entity_resolver_node)
workflow.add_node("ledger_coder", ledger_coder_node)
workflow.add_node("fiduciary_auditor", fiduciary_auditor_node)

workflow.set_entry_point("entity_resolver")
workflow.add_edge("entity_resolver", "ledger_coder")
workflow.add_edge("ledger_coder", "fiduciary_auditor")
workflow.add_edge("fiduciary_auditor", END)

trust_swarm = workflow.compile()
