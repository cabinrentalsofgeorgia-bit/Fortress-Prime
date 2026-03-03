"""
Division B Agent — "The Controller"
=====================================
The primary operational agent for Cabin Rentals of Georgia (PM).

Persona:
    Conservative, risk-averse, highly detailed.
    Zero tolerance for trust accounting errors.
    Focuses on compliance, accuracy, and operational efficiency.

Responsibilities:
    1. Monitor operating & trust accounts via Plaid
    2. Categorize and log all PM transactions
    3. Maintain trust accounting accuracy (guest escrow, vendor payouts)
    4. Monitor Blue Ridge property utilities
    5. Ensure Fannin County tax compliance
    6. Report metrics UP to the Sovereign (never laterally to Division A)
    7. Self-improve via the OODA recursive loop when variance > 5%
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from config import captain_think, CAPTAIN_URL

logger = logging.getLogger("division_b.agent")

# Division identifier (used by firewall and sovereign)
DIVISION_ID = "division_b"
DIVISION_NAME = "Cabin Rentals of Georgia — Property Management"

# Categorization uses the lightweight 8b model for speed.
# The 70b model is reserved for the Sovereign's meta-reasoning.
CATEGORIZATION_MODEL = "deepseek-r1:8b"


def _fast_categorize(prompt: str, system_role: str, temperature: float = 0.1) -> str:
    """
    Fast LLM call using deepseek-r1:8b for routine categorization.
    Division B uses an even lower temperature (0.1) for conservative precision.

    Uses Ollama's format:"json" to guarantee valid JSON output, and
    the /api/generate endpoint (faster than /api/chat for single-turn).
    """
    full_prompt = f"System: {system_role}\n\nUser: {prompt}"
    payload = {
        "model": CATEGORIZATION_MODEL,
        "prompt": full_prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 512},
    }
    try:
        resp = requests.post(
            f"{CAPTAIN_URL}/api/generate", json=payload, timeout=300,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        return f"[CATEGORIZE ERROR] {e}"


# =============================================================================
# AGENT STATE
# =============================================================================

@dataclass
class PropertyAgentState:
    """Operational state for the Division B agent."""

    # Current cycle
    cycle_id: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Transaction processing
    pending_transactions: List[Dict[str, Any]] = field(default_factory=list)
    categorized_transactions: List[Dict[str, Any]] = field(default_factory=list)
    ambiguous_transactions: List[Dict[str, Any]] = field(default_factory=list)

    # Trust accounting state
    escrow_balance: float = 0.0
    pending_payouts: List[Dict[str, Any]] = field(default_factory=list)

    # Metrics for Sovereign reporting
    metrics: Dict[str, float] = field(default_factory=dict)
    anomalies: List[Dict[str, Any]] = field(default_factory=list)

    # Learned vendor rules
    vendor_rules: Dict[str, Dict[str, str]] = field(default_factory=dict)


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = """You are the Controller agent for Cabin Rentals of Georgia.

DIVISION: Property Management (Division B)
PERSONA: Conservative, risk-averse, highly detailed. Zero tolerance for error.
SCOPE: Trust accounts, guest escrow, vendor payouts, utility monitoring (Blue Ridge),
       Fannin County tax compliance, operating expenses.

RULES:
1. Categorize every transaction into one of: TRUST_DEPOSIT, TRUST_PAYOUT, VENDOR,
   UTILITY, TAX, MAINTENANCE, OPERATING, GUEST_REFUND, INSURANCE, TRANSFER
2. Trust account transactions MUST be traced to a specific reservation/guest.
3. Vendor payouts MUST match an approved vendor in the registry.
4. For ambiguous transactions, flag as AMBIGUOUS with detailed reasoning.
   NEVER guess on trust accounting — precision is mandatory.
5. NEVER access or reference Division A (Holding Company) data.
6. Report anomalies immediately (any trust accounting discrepancy is CRITICAL).

TRUST ACCOUNTING RULES:
- Guest deposits must be held in escrow until checkout + 7 days.
- Vendor payouts require matching invoice.
- All trust movements must balance to zero (in = out).
- Any non-zero trust delta is an IMMEDIATE anomaly.

RESPONSE FORMAT: Always respond with valid JSON.
"""


# =============================================================================
# CORE OPERATIONS
# =============================================================================

def categorize_transaction(
    transaction: Dict[str, Any],
    vendor_rules: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Categorize a single PM transaction with trust-accounting precision.

    The Controller is MORE conservative than the CFO — it flags ambiguity
    rather than guessing, especially for trust-related transactions.
    """
    vendor = transaction.get("merchant_name") or transaction.get("name", "UNKNOWN")
    amount = transaction.get("amount", 0)

    # Check learned rules first
    if vendor_rules and vendor in vendor_rules:
        rule = vendor_rules[vendor]
        logger.info(f"Applied learned rule for vendor '{vendor}': {rule['category']}")
        return {
            **transaction,
            "category": rule["category"],
            "confidence": 0.99,
            "reasoning": f"Learned rule: {rule.get('reasoning', 'previously categorized')}",
            "method": "learned_rule",
            "trust_related": rule.get("trust_related", False),
        }

    # LLM categorization (conservative temperature)
    prompt = (
        f"Categorize this property management transaction:\n"
        f"  Vendor: {vendor}\n"
        f"  Amount: ${amount:,.2f}\n"
        f"  Date: {transaction.get('date', 'N/A')}\n"
        f"  Description: {transaction.get('name', 'N/A')}\n"
        f"  Account type: {transaction.get('division_account_type', 'N/A')}\n\n"
        f"Respond with JSON: "
        f'{{"category": "...", "confidence": 0.0-1.0, "reasoning": "...", '
        f'"trust_related": true/false, "reservation_id": "..." or null, '
        f'"requires_invoice_match": true/false}}'
    )

    response = _fast_categorize(prompt, system_role=SYSTEM_PROMPT, temperature=0.1)

    # Strip <think> tags from DeepSeek R1 output
    clean = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()

    # Try to extract JSON from the response (may be wrapped in markdown fences)
    json_match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
    json_str = json_match.group(0) if json_match else clean

    try:
        parsed = json.loads(json_str)
        return {
            **transaction,
            "category": parsed.get("category", "UNCATEGORIZED"),
            "confidence": parsed.get("confidence", 0.5),
            "reasoning": parsed.get("reasoning", ""),
            "trust_related": parsed.get("trust_related", False),
            "reservation_id": parsed.get("reservation_id"),
            "requires_invoice_match": parsed.get("requires_invoice_match", False),
            "method": "llm_categorization",
        }
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse LLM response for {vendor}: {clean[:200]}")
        return {
            **transaction,
            "category": "AMBIGUOUS",
            "confidence": 0.0,
            "reasoning": f"LLM parse failure — flagged for manual review",
            "trust_related": False,
            "method": "failed",
        }


def learn_vendor_rule(
    vendor: str,
    category: str,
    reasoning: str,
    trust_related: bool,
    state: PropertyAgentState,
) -> PropertyAgentState:
    """
    Write a permanent vendor categorization rule.
    Same "ask once, rewrite your own rule" behavior as Division A.
    """
    state.vendor_rules[vendor] = {
        "category": category,
        "reasoning": reasoning,
        "trust_related": trust_related,
        "learned_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"Learned new vendor rule: {vendor} → {category} (trust={trust_related})")

    _persist_vendor_rules(state.vendor_rules)
    return state


def verify_trust_balance(state: PropertyAgentState) -> Dict[str, Any]:
    """
    Verify that trust accounting balances to zero (in = out).

    Any non-zero delta is flagged as a CRITICAL anomaly for the Sovereign.
    """
    trust_txns = [
        t for t in state.categorized_transactions
        if t.get("trust_related", False)
    ]

    deposits = sum(t["amount"] for t in trust_txns if t["amount"] > 0)
    payouts = sum(abs(t["amount"]) for t in trust_txns if t["amount"] < 0)
    delta = deposits - payouts

    result = {
        "trust_deposits": deposits,
        "trust_payouts": payouts,
        "delta": delta,
        "balanced": abs(delta) < 0.01,  # Penny tolerance
        "transaction_count": len(trust_txns),
    }

    if not result["balanced"]:
        anomaly = {
            "type": "TRUST_IMBALANCE",
            "severity": "CRITICAL",
            "delta": delta,
            "detail": f"Trust accounting delta: ${delta:,.2f}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        state.anomalies.append(anomaly)
        logger.critical(f"TRUST IMBALANCE DETECTED: ${delta:,.2f}")

    return result


def generate_report(state: PropertyAgentState) -> Dict[str, Any]:
    """
    Generate an aggregated report for the Sovereign.
    Flows UP to Tier 1 only. Never laterally to Division A.
    """
    trust_check = verify_trust_balance(state)

    total_amount = sum(
        t.get("amount", 0) for t in state.categorized_transactions
    )

    by_category = {}
    for t in state.categorized_transactions:
        cat = t.get("category", "UNKNOWN")
        by_category[cat] = by_category.get(cat, 0) + t.get("amount", 0)

    return {
        "division": DIVISION_ID,
        "division_name": DIVISION_NAME,
        "cycle_id": state.cycle_id,
        "timestamp": state.timestamp.isoformat(),
        "metrics": {
            "total_transactions": len(state.categorized_transactions),
            "total_amount": total_amount,
            "ambiguous_count": len(state.ambiguous_transactions),
            "vendor_rules_count": len(state.vendor_rules),
            "trust_balanced": trust_check["balanced"],
            "trust_delta": trust_check["delta"],
            "escrow_balance": state.escrow_balance,
            "pending_payouts": len(state.pending_payouts),
            **state.metrics,
        },
        "by_category": by_category,
        "trust_accounting": trust_check,
        "anomalies": state.anomalies,
    }


# =============================================================================
# AGENT CLASS (OODA-Integrated)
# =============================================================================

class PropertyAgent:
    """
    The Controller — Division B Agent.

    This is the live agent class instantiated by the webhook server.
    It wraps all Division B operations with an OODA loop, with extra
    trust-accounting verification at every step.

    Usage:
        agent = PropertyAgent()
        result = await agent.run_ooda_cycle(webhook_data=payload)
    """

    def __init__(self):
        self.state = PropertyAgentState(
            vendor_rules=load_vendor_rules(),
        )
        self._ooda = None
        logger.info(
            f"PropertyAgent initialized "
            f"({len(self.state.vendor_rules)} learned vendor rules)"
        )

    @property
    def ooda(self):
        """Lazy-initialize the OODA loop."""
        if self._ooda is None:
            from recursive_core.ooda_loop import OODALoop
            self._ooda = OODALoop(
                division=DIVISION_ID,
                observe_fn=self._observe,
                orient_fn=self._orient,
                decide_fn=self._decide,
                act_fn=self._act,
                variance_threshold=5.0,
            )
        return self._ooda

    async def run_ooda_cycle(
        self,
        webhook_data: Optional[Dict[str, Any]] = None,
        transactions: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Run a complete OODA cycle for Division B.

        Can be triggered by:
            - Plaid webhook (webhook_data)
            - Direct transaction injection (transactions)
            - Cron schedule (no args — fetches from Plaid)

        Returns:
            Cycle result dict for the webhook response.
        """
        import asyncio
        import uuid
        from recursive_core.ooda_loop import OODAEvent

        event = OODAEvent(
            event_id=f"div_b_{uuid.uuid4().hex[:8]}",
            division=DIVISION_ID,
            observation={
                "webhook_data": webhook_data,
                "injected_transactions": transactions,
                "trigger": "webhook" if webhook_data else (
                    "injection" if transactions else "scheduled"
                ),
            },
        )

        result = await asyncio.to_thread(self.ooda.run, event)

        report = generate_report(self.state)

        return {
            "division": DIVISION_ID,
            "event_id": event.event_id,
            "success": result.success,
            "needs_optimization": result.needs_optimization,
            "optimization_reason": result.optimization_reason,
            "transactions_processed": len(self.state.categorized_transactions),
            "ambiguous_count": len(self.state.ambiguous_transactions),
            "trust_balanced": report.get("trust_accounting", {}).get("balanced", True),
            "report": report,
        }

    # =========================================================================
    # OODA PHASE HANDLERS
    # =========================================================================

    def _observe(self, event):
        """
        OBSERVE: Ingest raw transaction data.
        Same pattern as Division A, but tags trust account transactions.
        """
        injected = event.observation.get("injected_transactions")
        webhook = event.observation.get("webhook_data")

        if injected:
            raw_txns = injected
            logger.info(f"  OBSERVE: {len(raw_txns)} injected transactions")
        elif webhook:
            raw_txns = self._fetch_plaid_transactions()
            logger.info(f"  OBSERVE: {len(raw_txns)} transactions from Plaid")
        else:
            raw_txns = self._fetch_plaid_transactions()
            logger.info(f"  OBSERVE: {len(raw_txns)} transactions (scheduled)")

        event.observation["raw_transactions"] = raw_txns
        event.observation["count"] = len(raw_txns)
        self.state.pending_transactions = raw_txns
        return event

    def _orient(self, event):
        """
        ORIENT: Categorize transactions with trust-accounting precision.

        The Controller is CONSERVATIVE — it flags ambiguity rather than
        guessing, especially for trust-related transactions.

        REVENUE REALIZATION: Stripe deposits are intercepted and routed
        through the Revenue Realizer before standard categorization.
        The Realizer matches deposits to fin_reservations and posts
        compound journal entries (Dr Bank + Dr Fees / Cr Revenue).
        """
        raw_txns = event.observation.get("raw_transactions", [])
        categorized = []
        ambiguous = []
        revenue_actions = []
        total_variance = 0.0
        variance_count = 0

        for txn in raw_txns:
            # ── Revenue Realization: Intercept Stripe deposits ──────
            if self._try_revenue_realization(txn, revenue_actions):
                continue  # Handled by realizer, skip standard categorization

            result = categorize_transaction(txn, self.state.vendor_rules)
            confidence = result.get("confidence", 0)

            if result.get("category") == "AMBIGUOUS" or confidence < 0.8:
                ambiguous.append(result)
                # Only learn NON-trust transactions automatically
                if (confidence >= 0.5
                        and result.get("category") != "AMBIGUOUS"
                        and not result.get("trust_related", False)):
                    vendor = result.get("merchant_name") or result.get("name", "UNKNOWN")
                    learn_vendor_rule(
                        vendor=vendor,
                        category=result["category"],
                        reasoning=result.get("reasoning", "auto-learned"),
                        trust_related=False,
                        state=self.state,
                    )
            else:
                categorized.append(result)
                # Learn high-confidence categorizations (including trust flag)
                if confidence >= 0.9 and result.get("method") == "llm_categorization":
                    vendor = result.get("merchant_name") or result.get("name", "UNKNOWN")
                    learn_vendor_rule(
                        vendor=vendor,
                        category=result["category"],
                        reasoning=result.get("reasoning", "high-confidence categorization"),
                        trust_related=result.get("trust_related", False),
                        state=self.state,
                    )

            # Variance tracking
            predicted = txn.get("predicted_amount")
            actual = txn.get("amount", 0)
            if predicted is not None and predicted != 0:
                v = abs((actual - predicted) / predicted) * 100
                total_variance += v
                variance_count += 1

        self.state.categorized_transactions.extend(categorized)
        self.state.ambiguous_transactions.extend(ambiguous)

        event.orientation = {
            "categorized": len(categorized),
            "ambiguous": len(ambiguous),
            "revenue_actions": revenue_actions,
            "total_processed": len(raw_txns),
        }

        if variance_count > 0:
            event.variance_pct = total_variance / variance_count
        event.predicted_value = variance_count
        event.actual_value = float(len(categorized))

        return event

    def _decide(self, event):
        """
        DECIDE: Determine actions — with mandatory trust balance check.
        """
        ambiguous_count = event.orientation.get("ambiguous", 0)
        categorized_count = event.orientation.get("categorized", 0)

        actions = []
        if categorized_count > 0:
            actions.append({"action": "persist_to_ledger", "count": categorized_count})
            actions.append({"action": "verify_trust_balance"})
        if ambiguous_count > 0:
            actions.append({"action": "flag_for_review", "count": ambiguous_count})
            # Trust-related ambiguity is ALWAYS an anomaly
            trust_ambiguous = [
                t for t in self.state.ambiguous_transactions
                if t.get("trust_related", False)
            ]
            if trust_ambiguous:
                self.state.anomalies.append({
                    "type": "TRUST_AMBIGUITY",
                    "severity": "CRITICAL",
                    "count": len(trust_ambiguous),
                    "detail": "Trust account transactions could not be categorized",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        event.decision = {
            "action": "categorize_persist_verify",
            "sub_actions": actions,
        }
        return event

    def _act(self, event):
        """
        ACT: Persist transactions and verify trust accounting.
        """
        success_count = 0
        error_count = 0

        # Persist to Division B ledger
        for txn in self.state.categorized_transactions:
            try:
                if self._insert_transaction(txn):
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"Failed to persist transaction: {e}")
                error_count += 1

        # Verify trust balance (the critical compliance check)
        trust_check = verify_trust_balance(self.state)

        event.action_result = {
            "success": error_count == 0 and trust_check.get("balanced", True),
            "persisted": success_count,
            "errors": error_count,
            "trust_balanced": trust_check.get("balanced", True),
            "trust_delta": trust_check.get("delta", 0),
        }

        if error_count > 0:
            event.action_result["error"] = f"{error_count} transactions failed"
        if not trust_check.get("balanced", True):
            event.action_result["error"] = (
                event.action_result.get("error", "") +
                f" | TRUST IMBALANCE: ${trust_check.get('delta', 0):,.2f}"
            ).strip(" |")

        logger.info(
            f"  ACT: Persisted {success_count}/{success_count + error_count} "
            f"| Trust balanced={trust_check.get('balanced', True)}"
        )
        return event

    def _insert_transaction(self, txn: Dict[str, Any]) -> bool:
        """Insert a categorized transaction into the Division B ledger."""
        try:
            import psycopg2
            from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
            conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                user=DB_USER, password=DB_PASSWORD,
            )
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO division_b.transactions
                        (plaid_txn_id, date, vendor, amount, category,
                         confidence, trust_related, reservation_id,
                         reasoning, method, account_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (plaid_txn_id) DO UPDATE SET
                        category = EXCLUDED.category,
                        confidence = EXCLUDED.confidence
                """, (
                    txn.get("transaction_id"),
                    txn.get("date"),
                    txn.get("merchant_name") or txn.get("name", "UNKNOWN"),
                    txn.get("amount", 0),
                    txn.get("category", "UNCATEGORIZED"),
                    txn.get("confidence", 0),
                    txn.get("trust_related", False),
                    txn.get("reservation_id"),
                    txn.get("reasoning", ""),
                    txn.get("method", "llm"),
                    txn.get("account_id"),
                ))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Division B insert failed: {e}")
            return False

    # =========================================================================
    # REVENUE REALIZATION (Stripe Deposit → GL)
    # =========================================================================

    def _try_revenue_realization(
        self,
        txn: Dict[str, Any],
        revenue_actions: List[Dict[str, Any]],
    ) -> bool:
        """
        Check if a transaction is a Stripe deposit and route it through
        the Revenue Realizer.

        Returns True if the transaction was handled (caller should skip
        standard categorization), False otherwise.
        """
        try:
            from division_b_property.handlers.revenue_realizer import (
                is_stripe_deposit,
                process_stripe_deposit,
            )

            if not is_stripe_deposit(txn):
                return False

            vendor = txn.get("merchant_name") or txn.get("name", "Stripe")
            amount = abs(txn.get("amount", 0))
            logger.info(
                f"  ORIENT/REALIZER: Stripe deposit detected — "
                f"${amount:,.2f} from {vendor}"
            )

            result = process_stripe_deposit(txn, schema=DIVISION_ID)
            revenue_actions.append(result)

            action = result.get("action", "unknown")
            if action == "auto_confirmed":
                logger.info(
                    f"  ORIENT/REALIZER: Auto-confirmed — "
                    f"{result.get('property_name', '?')} "
                    f"(res {result.get('reservation_id', '?')})"
                )
            elif action == "clarification_requested":
                logger.info(
                    f"  ORIENT/REALIZER: Clarification needed — "
                    f"{result.get('match_count', 0)} candidates, "
                    f"request {result.get('clarification_id', '?')}"
                )
                # Add to ambiguous so the Sovereign sees it
                self.state.ambiguous_transactions.append({
                    **txn,
                    "category": "REVENUE_CLARIFICATION",
                    "confidence": 0.5,
                    "reasoning": result.get("message", ""),
                    "method": "revenue_realizer",
                    "trust_related": False,
                    "clarification_id": result.get("clarification_id"),
                })
            elif action == "flagged":
                logger.warning(
                    f"  ORIENT/REALIZER: Unforecasted deposit — "
                    f"${amount:,.2f} flagged for review"
                )
                self.state.anomalies.append({
                    "type": "UNFORECASTED_DEPOSIT",
                    "severity": "MEDIUM",
                    "amount": amount,
                    "vendor": vendor,
                    "detail": result.get("message", ""),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "clarification_id": result.get("clarification_id"),
                })
            return True

        except ImportError:
            # Revenue realizer not available — fall through to standard categorization
            return False
        except Exception as e:
            logger.warning(f"  ORIENT/REALIZER: Error (non-fatal): {e}")
            return False

    # =========================================================================
    # PLAID INTEGRATION
    # =========================================================================

    def _fetch_plaid_transactions(self) -> List[Dict[str, Any]]:
        """Fetch recent transactions from Division B Plaid accounts."""
        try:
            from division_b_property.plaid_client import PropertyPlaidClient
            from datetime import timedelta

            client = PropertyPlaidClient()
            end = datetime.now(timezone.utc).date()
            start = end - timedelta(days=7)

            return client.get_transactions(
                start_date=start.isoformat(),
                end_date=end.isoformat(),
            )
        except Exception as e:
            logger.warning(f"Plaid fetch failed (may not be configured): {e}")
            return []


# =============================================================================
# PERSISTENCE
# =============================================================================

def _persist_vendor_rules(rules: Dict[str, Dict[str, str]]) -> None:
    """Save learned vendor rules to NAS (or local fallback)."""
    try:
        from src.fortress_paths import paths
        rules_path = paths.base_dir / "division_b" / "vendor_rules.json"
    except ImportError:
        from pathlib import Path
        rules_path = Path("data/division_b/vendor_rules.json")

    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(json.dumps(rules, indent=2, default=str), encoding="utf-8")
    logger.info(f"Persisted {len(rules)} vendor rules to {rules_path}")


def load_vendor_rules() -> Dict[str, Dict[str, str]]:
    """Load previously learned vendor rules."""
    try:
        from src.fortress_paths import paths
        rules_path = paths.base_dir / "division_b" / "vendor_rules.json"
    except ImportError:
        from pathlib import Path
        rules_path = Path("data/division_b/vendor_rules.json")

    if rules_path.exists():
        return json.loads(rules_path.read_text(encoding="utf-8"))
    return {}
