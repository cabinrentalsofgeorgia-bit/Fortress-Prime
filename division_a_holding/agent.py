"""
Division A Agent — "The CFO / Venture Capitalist"
===================================================
The primary operational agent for CROG, LLC (Holding Company).

Persona:
    Aggressive, growth-oriented, alpha-seeking.
    Focuses on capital allocation, ROI optimization, and venture oversight.

Responsibilities:
    1. Monitor corporate & investment accounts via Plaid
    2. Categorize and log all holding-company transactions
    3. Generate capital allocation recommendations
    4. Report metrics UP to the Sovereign (never laterally to Division B)
    5. Self-improve via the OODA recursive loop when variance > 5%
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from config import captain_think, CAPTAIN_URL

logger = logging.getLogger("division_a.agent")

# Division identifier (used by firewall and sovereign)
DIVISION_ID = "division_a"
DIVISION_NAME = "CROG, LLC — Holding Company"

# Categorization uses the lightweight 8b model for speed.
# The 70b model is reserved for the Sovereign's meta-reasoning.
CATEGORIZATION_MODEL = "deepseek-r1:8b"


def _fast_categorize(prompt: str, system_role: str, temperature: float = 0.2) -> str:
    """
    Fast LLM call using deepseek-r1:8b for routine categorization.

    The 70b model takes minutes per call — fine for Sovereign reasoning,
    but too slow for batch transaction processing. The 8b handles
    categorization with sufficient accuracy at ~10x the speed.

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
class HoldingAgentState:
    """Operational state for the Division A agent."""

    # Current cycle
    cycle_id: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Transaction processing
    pending_transactions: List[Dict[str, Any]] = field(default_factory=list)
    categorized_transactions: List[Dict[str, Any]] = field(default_factory=list)
    ambiguous_transactions: List[Dict[str, Any]] = field(default_factory=list)

    # Metrics for Sovereign reporting
    metrics: Dict[str, float] = field(default_factory=dict)
    anomalies: List[Dict[str, Any]] = field(default_factory=list)

    # Learning state (vendor rules the agent has written for itself)
    vendor_rules: Dict[str, Dict[str, str]] = field(default_factory=dict)


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = """You are the CFO/Venture Capitalist agent for CROG, LLC.

DIVISION: Holding Company (Division A)
PERSONA: Aggressive, growth-oriented. You seek maximum alpha.
SCOPE: Corporate accounts, investment portfolios, venture capital (Verses in Bloom),
       asset management (DGX/Compute Cluster costs), market investments.

RULES:
1. Categorize every transaction into one of: INVESTMENT, OPERATING, ASSET, VENTURE, TAX, TRANSFER
2. For ambiguous transactions, attempt categorization using context. If confidence < 80%,
   flag as AMBIGUOUS and provide your best guess plus reasoning.
3. Always compute ROI impact for investment transactions.
4. NEVER access or reference Division B (Property Management) data.
5. Report anomalies (>5% variance from predictions) immediately.

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
    Categorize a single transaction using LLM reasoning.

    If a vendor rule already exists (from prior self-learning), apply it
    directly without calling the LLM. This is the "never ask twice" behavior.

    Args:
        transaction: Plaid transaction object
        vendor_rules: Existing vendor→category mappings (learned rules)

    Returns:
        Enriched transaction with category, confidence, reasoning.
    """
    vendor = transaction.get("merchant_name") or transaction.get("name", "UNKNOWN")
    amount = transaction.get("amount", 0)

    # Check learned rules first (skip LLM if we already know this vendor)
    if vendor_rules and vendor in vendor_rules:
        rule = vendor_rules[vendor]
        logger.info(f"Applied learned rule for vendor '{vendor}': {rule['category']}")
        return {
            **transaction,
            "category": rule["category"],
            "confidence": 0.99,
            "reasoning": f"Learned rule: {rule.get('reasoning', 'previously categorized')}",
            "method": "learned_rule",
        }

    # LLM categorization
    prompt = (
        f"Categorize this holding company transaction:\n"
        f"  Vendor: {vendor}\n"
        f"  Amount: ${amount:,.2f}\n"
        f"  Date: {transaction.get('date', 'N/A')}\n"
        f"  Description: {transaction.get('name', 'N/A')}\n\n"
        f"Respond with JSON: "
        f'{{"category": "...", "confidence": 0.0-1.0, "reasoning": "...", '
        f'"roi_impact": "positive|negative|neutral"}}'
    )

    response = _fast_categorize(prompt, system_role=SYSTEM_PROMPT, temperature=0.2)

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
            "roi_impact": parsed.get("roi_impact", "neutral"),
            "method": "llm_categorization",
        }
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse LLM response for {vendor}: {clean[:200]}")
        return {
            **transaction,
            "category": "AMBIGUOUS",
            "confidence": 0.0,
            "reasoning": f"LLM parse failure: {clean[:200]}",
            "method": "failed",
        }


def learn_vendor_rule(
    vendor: str,
    category: str,
    reasoning: str,
    state: HoldingAgentState,
) -> HoldingAgentState:
    """
    Write a permanent vendor categorization rule (self-improvement).

    This is the "ask once, then rewrite your own rule" behavior from the SOW.
    Next time this vendor appears, the LLM is skipped entirely.
    """
    state.vendor_rules[vendor] = {
        "category": category,
        "reasoning": reasoning,
        "learned_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"Learned new vendor rule: {vendor} → {category}")

    # Persist to disk (NAS-first)
    _persist_vendor_rules(state.vendor_rules)

    return state


def generate_report(state: HoldingAgentState) -> Dict[str, Any]:
    """
    Generate an aggregated report for the Sovereign.

    This is what flows UP to Tier 1. It never flows laterally to Division B.
    """
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
            **state.metrics,
        },
        "by_category": by_category,
        "anomalies": state.anomalies,
    }


# =============================================================================
# AGENT CLASS (OODA-Integrated)
# =============================================================================

class HoldingAgent:
    """
    The CFO / Venture Capitalist — Division A Agent.

    This is the live agent class instantiated by the webhook server.
    It wraps all Division A operations with an OODA loop so that every
    transaction cycle is self-monitoring and self-improving.

    Usage:
        agent = HoldingAgent()
        result = await agent.run_ooda_cycle(webhook_data=payload)
    """

    def __init__(self):
        self.state = HoldingAgentState(
            vendor_rules=load_vendor_rules(),
        )
        self._ooda = None  # Lazy init (avoid import at module load)
        logger.info(
            f"HoldingAgent initialized "
            f"({len(self.state.vendor_rules)} learned vendor rules)"
        )

    @property
    def ooda(self):
        """Lazy-initialize the OODA loop (avoids circular imports)."""
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
        Run a complete OODA cycle for Division A.

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
            event_id=f"div_a_{uuid.uuid4().hex[:8]}",
            division=DIVISION_ID,
            observation={
                "webhook_data": webhook_data,
                "injected_transactions": transactions,
                "trigger": "webhook" if webhook_data else (
                    "injection" if transactions else "scheduled"
                ),
            },
        )

        # Run the sync OODA loop in a thread so we don't block the event loop
        result = await asyncio.to_thread(self.ooda.run, event)

        # Build response
        report = generate_report(self.state)

        return {
            "division": DIVISION_ID,
            "event_id": event.event_id,
            "success": result.success,
            "needs_optimization": result.needs_optimization,
            "optimization_reason": result.optimization_reason,
            "transactions_processed": len(self.state.categorized_transactions),
            "ambiguous_count": len(self.state.ambiguous_transactions),
            "report": report,
        }

    # =========================================================================
    # OODA PHASE HANDLERS
    # =========================================================================

    def _observe(self, event):
        """
        OBSERVE: Ingest raw transaction data.

        Sources (in priority order):
            1. Injected transactions (for testing)
            2. Plaid sync triggered by webhook
            3. Scheduled Plaid pull
        """
        from recursive_core.ooda_loop import OODAEvent

        injected = event.observation.get("injected_transactions")
        webhook = event.observation.get("webhook_data")

        if injected:
            # Direct injection (testing / mock)
            raw_txns = injected
            logger.info(f"  OBSERVE: {len(raw_txns)} injected transactions")
        elif webhook:
            # Plaid webhook triggered — fetch new transactions
            raw_txns = self._fetch_plaid_transactions()
            logger.info(f"  OBSERVE: {len(raw_txns)} transactions from Plaid")
        else:
            # Scheduled pull
            raw_txns = self._fetch_plaid_transactions()
            logger.info(f"  OBSERVE: {len(raw_txns)} transactions (scheduled)")

        event.observation["raw_transactions"] = raw_txns
        event.observation["count"] = len(raw_txns)
        self.state.pending_transactions = raw_txns
        return event

    def _orient(self, event):
        """
        ORIENT: Categorize transactions and compare with predictions.

        Each transaction is run through the LLM categorizer (or matched
        against learned vendor rules). Variance is computed against any
        existing predictions.
        """
        raw_txns = event.observation.get("raw_transactions", [])
        categorized = []
        ambiguous = []
        total_variance = 0.0
        variance_count = 0

        for txn in raw_txns:
            result = categorize_transaction(txn, self.state.vendor_rules)
            confidence = result.get("confidence", 0)

            if result.get("category") == "AMBIGUOUS" or confidence < 0.8:
                ambiguous.append(result)
                # Self-learn: if we got a best guess, learn it for next time
                if confidence >= 0.5 and result.get("category") != "AMBIGUOUS":
                    vendor = result.get("merchant_name") or result.get("name", "UNKNOWN")
                    learn_vendor_rule(
                        vendor=vendor,
                        category=result["category"],
                        reasoning=result.get("reasoning", "auto-learned from first encounter"),
                        state=self.state,
                    )
            else:
                categorized.append(result)
                # Learn high-confidence categorizations permanently
                if confidence >= 0.9 and result.get("method") == "llm_categorization":
                    vendor = result.get("merchant_name") or result.get("name", "UNKNOWN")
                    learn_vendor_rule(
                        vendor=vendor,
                        category=result["category"],
                        reasoning=result.get("reasoning", "high-confidence LLM categorization"),
                        state=self.state,
                    )

            # Compute variance against predictions (if we have them)
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
            "total_processed": len(raw_txns),
        }

        # Set variance on the event for the REFLECT phase
        if variance_count > 0:
            event.variance_pct = total_variance / variance_count
        event.predicted_value = variance_count  # number of predictions we had
        event.actual_value = float(len(categorized))  # successful categorizations

        return event

    def _decide(self, event):
        """
        DECIDE: Determine what actions to take based on orientation.
        """
        ambiguous_count = event.orientation.get("ambiguous", 0)
        categorized_count = event.orientation.get("categorized", 0)

        actions = []
        if categorized_count > 0:
            actions.append({"action": "persist_to_ledger", "count": categorized_count})
        if ambiguous_count > 0:
            actions.append({"action": "flag_for_review", "count": ambiguous_count})
            self.state.anomalies.append({
                "type": "AMBIGUOUS_TRANSACTIONS",
                "count": ambiguous_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        event.decision = {
            "action": "categorize_and_persist",
            "sub_actions": actions,
        }
        return event

    def _act(self, event):
        """
        ACT: Persist categorized transactions to the Division A ledger.
        """
        from division_a_holding.ledger import insert_transaction

        success_count = 0
        error_count = 0

        for txn in self.state.categorized_transactions:
            try:
                if insert_transaction(txn):
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"Failed to persist transaction: {e}")
                error_count += 1

        event.action_result = {
            "success": error_count == 0,
            "persisted": success_count,
            "errors": error_count,
        }

        if error_count > 0:
            event.action_result["error"] = f"{error_count} transactions failed to persist"

        logger.info(f"  ACT: Persisted {success_count}/{success_count + error_count} transactions")
        return event

    # =========================================================================
    # PLAID INTEGRATION
    # =========================================================================

    def _fetch_plaid_transactions(self) -> List[Dict[str, Any]]:
        """Fetch recent transactions from Division A Plaid accounts."""
        try:
            from division_a_holding.plaid_client import HoldingPlaidClient
            from datetime import timedelta

            client = HoldingPlaidClient()
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
        rules_path = paths.base_dir / "division_a" / "vendor_rules.json"
    except ImportError:
        from pathlib import Path
        rules_path = Path("data/division_a/vendor_rules.json")

    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(json.dumps(rules, indent=2, default=str), encoding="utf-8")
    logger.info(f"Persisted {len(rules)} vendor rules to {rules_path}")


def load_vendor_rules() -> Dict[str, Dict[str, str]]:
    """Load previously learned vendor rules."""
    try:
        from src.fortress_paths import paths
        rules_path = paths.base_dir / "division_a" / "vendor_rules.json"
    except ImportError:
        from pathlib import Path
        rules_path = Path("data/division_a/vendor_rules.json")

    if rules_path.exists():
        return json.loads(rules_path.read_text(encoding="utf-8"))
    return {}
