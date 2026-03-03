"""
Sovereign Orchestrator — The DCG State Machine
================================================
Uses LangGraph to implement the Directed Cyclic Graph described in the SOW.

Flow:
    1. Receive aggregated division reports (A + B)
    2. Evaluate system health (health_monitor)
    3. If health score < threshold → trigger recursive optimization
    4. Dispatch updated directives back to divisions
    5. Loop (this is the "cyclic" part — it never terminates)

The orchestrator runs on the Captain Node (Spark 2) using DeepSeek-r1:70b.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from config import captain_think, CAPTAIN_MODEL

logger = logging.getLogger("sovereign.orchestrator")


# =============================================================================
# STATE DEFINITIONS
# =============================================================================

class SystemHealthStatus(str, Enum):
    """Overall system health classification."""
    OPTIMAL = "optimal"          # All metrics green
    NOMINAL = "nominal"          # Minor deviations within tolerance
    DEGRADED = "degraded"        # One or more metrics exceed 5% variance
    CRITICAL = "critical"        # Requires immediate r1 intervention


@dataclass
class DivisionReport:
    """Aggregated report from a Tier 2 division."""
    division: str                          # "holding" or "property"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metrics: Dict[str, float] = field(default_factory=dict)
    anomalies: List[Dict[str, Any]] = field(default_factory=list)
    pending_decisions: List[Dict[str, Any]] = field(default_factory=list)
    raw_transactions: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SovereignState:
    """
    The global state object passed through the LangGraph DCG.

    This is the single source of truth for the current orchestration cycle.
    """
    cycle_id: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    health_status: SystemHealthStatus = SystemHealthStatus.NOMINAL

    # Division reports (populated each cycle)
    division_a_report: Optional[DivisionReport] = None
    division_b_report: Optional[DivisionReport] = None
    division_engineering_report: Optional[DivisionReport] = None

    # Sovereign decisions
    directives: List[Dict[str, Any]] = field(default_factory=list)
    optimization_triggers: List[Dict[str, Any]] = field(default_factory=list)

    # Audit trail
    history: List[Dict[str, Any]] = field(default_factory=list)


# =============================================================================
# ORCHESTRATION NODES (LangGraph)
# =============================================================================

def _query_division_state(schema: str, division_name: str) -> Optional[DivisionReport]:
    """
    Pull real division state from PostgreSQL.

    Queries the division's transactions table, GL summary, and recent
    anomalies to build a DivisionReport the Sovereign can reason over.
    """
    try:
        import psycopg2
        from dotenv import load_dotenv
        import os
        load_dotenv()

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            database=os.getenv("DB_NAME", "fortress_db"),
            user=os.getenv("DB_USER", "miner_bot"),
            password=os.getenv("DB_PASSWORD", os.getenv("DB_PASS", "")),
            connect_timeout=5,
        )
        cur = conn.cursor()

        # Recent transaction count and volume (last 24h)
        metrics = {}
        raw_transactions = []
        anomalies = []
        pending_decisions = []

        try:
            cur.execute(f"""
                SELECT COUNT(*), COALESCE(SUM(ABS(amount)), 0)
                FROM {schema}.transactions
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """)
            row = cur.fetchone()
            metrics["txn_count_24h"] = int(row[0]) if row else 0
            metrics["txn_volume_24h"] = float(row[1]) if row else 0.0
        except Exception:
            metrics["txn_count_24h"] = 0
            metrics["txn_volume_24h"] = 0.0

        # Total transactions (all time)
        try:
            cur.execute(f"SELECT COUNT(*) FROM {schema}.transactions")
            metrics["total_transactions"] = int(cur.fetchone()[0])
        except Exception:
            metrics["total_transactions"] = 0

        # GL health — total debits and credits
        try:
            cur.execute(f"""
                SELECT
                    COALESCE(SUM(debit), 0),
                    COALESCE(SUM(credit), 0),
                    COUNT(DISTINCT journal_id)
                FROM {schema}.general_ledger
            """)
            row = cur.fetchone()
            metrics["gl_total_debits"] = float(row[0])
            metrics["gl_total_credits"] = float(row[1])
            metrics["gl_journal_count"] = int(row[2])
            imbalance = abs(float(row[0]) - float(row[1]))
            if imbalance > 0.01:
                anomalies.append({
                    "type": "GL_IMBALANCE",
                    "severity": "CRITICAL",
                    "detail": f"Imbalance: ${imbalance:,.2f}",
                })
        except Exception:
            metrics["gl_total_debits"] = 0.0
            metrics["gl_total_credits"] = 0.0
            metrics["gl_journal_count"] = 0

        # Chart of Accounts size
        try:
            cur.execute(f"SELECT COUNT(*) FROM {schema}.chart_of_accounts")
            metrics["coa_accounts"] = int(cur.fetchone()[0])
        except Exception:
            metrics["coa_accounts"] = 0

        # Trust ledger (Division B only)
        if schema == "division_b":
            try:
                cur.execute("""
                    SELECT
                        COALESCE(SUM(CASE WHEN entry_type='deposit' THEN amount ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN entry_type='payout' THEN amount ELSE 0 END), 0)
                    FROM division_b.trust_ledger
                """)
                row = cur.fetchone()
                deposits, payouts = float(row[0]), float(row[1])
                metrics["trust_deposits"] = deposits
                metrics["trust_payouts"] = payouts
                metrics["trust_net"] = deposits - payouts
                if abs(deposits - payouts) > 0.01 and deposits > 0:
                    anomalies.append({
                        "type": "TRUST_IMBALANCE",
                        "severity": "CRITICAL",
                        "detail": f"Trust delta: ${deposits - payouts:,.2f}",
                    })
            except Exception:
                pass

        # Recent uncategorized / ambiguous (predictions with low confidence)
        try:
            cur.execute(f"""
                SELECT COUNT(*)
                FROM {schema}.predictions
                WHERE confidence < 0.5
                  AND created_at > NOW() - INTERVAL '7 days'
            """)
            ambiguous = int(cur.fetchone()[0])
            metrics["ambiguous_7d"] = ambiguous
            if ambiguous > 10:
                anomalies.append({
                    "type": "HIGH_AMBIGUITY",
                    "severity": "HIGH",
                    "detail": f"{ambiguous} low-confidence predictions in 7d",
                })
        except Exception:
            pass

        conn.close()

        return DivisionReport(
            division=division_name,
            metrics=metrics,
            anomalies=anomalies,
            pending_decisions=pending_decisions,
            raw_transactions=raw_transactions,
        )

    except Exception as e:
        logger.warning(f"Could not query {schema}: {e}")
        return None


def ingest_reports(state: SovereignState) -> SovereignState:
    """
    Node 1: Ingest division reports.

    Pulls real-time state from PostgreSQL for both divisions.
    If pre-populated reports exist on the state (e.g., from a webhook
    that just completed an OODA cycle), those take priority.
    Otherwise, queries the DB directly.

    Enforces the firewall — divisions never see each other's data;
    only the Sovereign sees both.
    """
    logger.info(f"[Cycle {state.cycle_id}] Ingesting division reports...")

    # Pull from DB if not pre-populated
    if state.division_a_report is None:
        state.division_a_report = _query_division_state("division_a", "holding")
    if state.division_b_report is None:
        state.division_b_report = _query_division_state("division_b", "property")

    if state.division_a_report:
        logger.info(
            f"  Division A (Holding): "
            f"{state.division_a_report.metrics.get('total_transactions', 0)} total txns, "
            f"{state.division_a_report.metrics.get('txn_count_24h', 0)} in last 24h, "
            f"{len(state.division_a_report.anomalies)} anomalies"
        )
    else:
        logger.warning("  Division A: No data available")

    if state.division_b_report:
        logger.info(
            f"  Division B (Property): "
            f"{state.division_b_report.metrics.get('total_transactions', 0)} total txns, "
            f"{state.division_b_report.metrics.get('txn_count_24h', 0)} in last 24h, "
            f"{len(state.division_b_report.anomalies)} anomalies"
        )
    else:
        logger.warning("  Division B: No data available")

    if state.division_engineering_report:
        logger.info(
            f"  Division Engineering: "
            f"{state.division_engineering_report.metrics.get('total_documents', 0)} "
            f"documents, {len(state.division_engineering_report.anomalies)} anomalies"
        )

    return state


def evaluate_health(state: SovereignState) -> SovereignState:
    """
    Node 2: Evaluate system health.

    Delegates to health_monitor.score_system() to compute a holistic
    health score from both divisions' metrics. Updates state.health_status.
    """
    from sovereign.health_monitor import score_system

    logger.info(f"[Cycle {state.cycle_id}] Evaluating system health...")

    health = score_system(
        division_a=state.division_a_report,
        division_b=state.division_b_report,
    )

    state.health_status = health["status"]
    logger.info(f"  Health: {state.health_status.value} (score={health.get('score', 'N/A')})")

    # If degraded or critical, flag for optimization
    if state.health_status in (SystemHealthStatus.DEGRADED, SystemHealthStatus.CRITICAL):
        state.optimization_triggers.append({
            "cycle": state.cycle_id,
            "reason": health.get("reason", "Variance exceeded threshold"),
            "affected_divisions": health.get("affected_divisions", []),
            "metrics": health.get("failing_metrics", {}),
        })

    return state


def sovereign_reason(state: SovereignState) -> SovereignState:
    """
    Node 3: The Sovereign thinks.

    Uses DeepSeek-r1 to perform meta-cognition over the combined state.
    Produces directives for subordinate divisions and/or triggers the
    recursive optimization loop.
    """
    logger.info(f"[Cycle {state.cycle_id}] Sovereign reasoning (r1)...")

    # Build the reasoning prompt from current state
    context_parts = [
        f"Cycle: {state.cycle_id}",
        f"Health: {state.health_status.value}",
        f"Optimization triggers: {len(state.optimization_triggers)}",
    ]

    if state.division_a_report:
        context_parts.append(
            f"Division A anomalies: {len(state.division_a_report.anomalies)}"
        )
    if state.division_b_report:
        context_parts.append(
            f"Division B anomalies: {len(state.division_b_report.anomalies)}"
        )
    if state.division_engineering_report:
        eng = state.division_engineering_report
        context_parts.append(
            f"Division Engineering anomalies: {len(eng.anomalies)}"
        )
        context_parts.append(
            f"Division Engineering compliance issues: "
            f"{eng.metrics.get('compliance_critical', 0)} critical, "
            f"{eng.metrics.get('compliance_high', 0)} high"
        )
        context_parts.append(
            f"Division Engineering active projects: "
            f"{eng.metrics.get('active_projects', 0)}"
        )

    reasoning_prompt = (
        "You are the Sovereign Orchestrator of the Fortress financial system.\n"
        "Review the following cycle state and produce directives:\n\n"
        + "\n".join(context_parts) + "\n\n"
        "Respond with a JSON object containing:\n"
        '  "directives": [{"division": "A"|"B", "action": "...", "priority": "high"|"medium"|"low"}]\n'
        '  "optimize": true/false (should we trigger prompt rewriting?)\n'
        '  "reasoning": "brief explanation"'
    )

    system_role = (
        "You are the Tier 1 Sovereign of a recursive AI enterprise system. "
        "You oversee Division A (CROG LLC Holding — aggressive growth), "
        "Division B (Cabin Rentals of Georgia — conservative compliance), and "
        "Division Engineering (The Drawing Board — architectural & engineering "
        "intelligence, code compliance, construction projects). "
        "Your role is strategic arbitration and meta-cognition. "
        "Engineering compliance issues (CRITICAL/HIGH) require immediate attention. "
        "Respond ONLY with valid JSON."
    )

    response = captain_think(reasoning_prompt, system_role=system_role, temperature=0.3)

    # Strip DeepSeek <think> tags before parsing
    import re, json
    clean = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()

    # Strip markdown code fences (r1 often wraps JSON in ```json ... ```)
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean, flags=re.DOTALL)
    if fence_match:
        clean = fence_match.group(1)
    else:
        # Try to extract raw JSON object
        json_match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
        if json_match:
            clean = json_match.group(0)

    # Attempt to parse the r1 response
    try:
        parsed = json.loads(clean)
        state.directives = parsed.get("directives", [])
        if parsed.get("optimize"):
            state.optimization_triggers.append({
                "cycle": state.cycle_id,
                "reason": parsed.get("reasoning", "r1 requested optimization"),
                "source": "sovereign_reasoning",
            })
    except json.JSONDecodeError:
        logger.warning(f"  r1 response was not valid JSON. Raw: {clean[:200]}")
        state.directives = []

    # Record in history
    state.history.append({
        "cycle": state.cycle_id,
        "timestamp": state.timestamp.isoformat(),
        "health": state.health_status.value,
        "directives_issued": len(state.directives),
        "optimizations_triggered": len(state.optimization_triggers),
    })

    return state


def _persist_directives(state: SovereignState) -> None:
    """
    Persist sovereign directives and cycle results to PostgreSQL.

    Creates the sovereign_cycles table if it doesn't exist, then inserts
    the current cycle's health status, directives, and optimization triggers.
    """
    try:
        import psycopg2
        import psycopg2.extras
        import json as _json
        from dotenv import load_dotenv
        import os
        load_dotenv()

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            database=os.getenv("DB_NAME", "fortress_db"),
            user=os.getenv("DB_USER", "miner_bot"),
            password=os.getenv("DB_PASSWORD", os.getenv("DB_PASS", "")),
            connect_timeout=5,
        )
        cur = conn.cursor()

        # Ensure the sovereign_cycles table exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sovereign_cycles (
                id              SERIAL PRIMARY KEY,
                cycle_id        INTEGER NOT NULL,
                timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                health_status   TEXT NOT NULL,
                health_score    REAL,
                directives      JSONB DEFAULT '[]'::jsonb,
                optimization_triggers JSONB DEFAULT '[]'::jsonb,
                division_a_summary    JSONB,
                division_b_summary    JSONB,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Build summaries (strip raw_transactions to keep rows small)
        div_a_summary = None
        if state.division_a_report:
            div_a_summary = _json.dumps({
                "division": state.division_a_report.division,
                "metrics": state.division_a_report.metrics,
                "anomalies": state.division_a_report.anomalies,
                "pending_decisions": state.division_a_report.pending_decisions,
            }, default=str)

        div_b_summary = None
        if state.division_b_report:
            div_b_summary = _json.dumps({
                "division": state.division_b_report.division,
                "metrics": state.division_b_report.metrics,
                "anomalies": state.division_b_report.anomalies,
                "pending_decisions": state.division_b_report.pending_decisions,
            }, default=str)

        cur.execute("""
            INSERT INTO sovereign_cycles
                (cycle_id, timestamp, health_status, directives,
                 optimization_triggers, division_a_summary, division_b_summary)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            state.cycle_id,
            state.timestamp.isoformat(),
            state.health_status.value,
            _json.dumps(state.directives, default=str),
            _json.dumps(state.optimization_triggers, default=str),
            div_a_summary,
            div_b_summary,
        ))

        conn.commit()
        conn.close()
        logger.info(f"  Cycle {state.cycle_id} persisted to sovereign_cycles")

    except Exception as e:
        logger.error(f"Failed to persist directives: {e}")


def _process_escalations_async() -> int:
    """
    Trigger the escalation processor to handle any OODA REFLECT escalations.

    Returns the number of escalations processed.
    """
    try:
        from sovereign.process_escalations import process_all
        decisions = process_all()
        return len(decisions)
    except Exception as e:
        logger.error(f"Escalation processing failed: {e}")
        return 0


def dispatch_directives(state: SovereignState) -> SovereignState:
    """
    Node 4: Dispatch directives to divisions.

    Sends the Sovereign's decisions back down to Division A and/or
    Division B agents. Persists the full cycle to PostgreSQL.
    If optimization was triggered, delegates to the Prompt Governor
    via the escalation processor.
    """
    logger.info(f"[Cycle {state.cycle_id}] Dispatching {len(state.directives)} directives...")

    for directive in state.directives:
        division = directive.get("division", "?")
        action = directive.get("action", "no-op")
        priority = directive.get("priority", "medium")
        logger.info(f"  → Division {division} [{priority}]: {action}")

    # Persist the complete cycle to PostgreSQL
    _persist_directives(state)

    # If optimization triggers exist, process escalations
    if state.optimization_triggers:
        logger.info(
            f"  Processing {len(state.optimization_triggers)} optimization triggers..."
        )
        escalations_handled = _process_escalations_async()
        logger.info(f"  Escalation processor handled {escalations_handled} event(s)")

    # Log cycle to reflection log (NAS-first, DB backup)
    try:
        from recursive_core.reflection_log import log_optimization
        log_optimization(
            agent_id="sovereign.orchestrator",
            action="cycle_complete",
            old_value=f"cycle_{state.cycle_id}",
            new_value=(
                f"health={state.health_status.value}, "
                f"directives={len(state.directives)}, "
                f"triggers={len(state.optimization_triggers)}"
            ),
            reasoning="Sovereign orchestration cycle completed",
        )
    except Exception as e:
        logger.debug(f"Could not log to reflection_log: {e}")

    # Advance cycle
    state.cycle_id += 1
    state.timestamp = datetime.now(timezone.utc)

    return state


# =============================================================================
# GRAPH BUILDER (LangGraph)
# =============================================================================

def build_sovereign_graph():
    """
    Build the LangGraph state machine for the Sovereign Orchestrator.

    This creates the Directed Cyclic Graph:

        ingest_reports → evaluate_health → sovereign_reason → dispatch_directives
              ↑                                                        │
              └────────────────────────────────────────────────────────┘

    Returns:
        A compiled LangGraph that can be invoked with .invoke(state).
    """
    try:
        from langgraph.graph import StateGraph, END

        graph = StateGraph(SovereignState)

        # Add nodes
        graph.add_node("ingest_reports", ingest_reports)
        graph.add_node("evaluate_health", evaluate_health)
        graph.add_node("sovereign_reason", sovereign_reason)
        graph.add_node("dispatch_directives", dispatch_directives)

        # Define edges (the DCG cycle)
        graph.set_entry_point("ingest_reports")
        graph.add_edge("ingest_reports", "evaluate_health")
        graph.add_edge("evaluate_health", "sovereign_reason")
        graph.add_edge("sovereign_reason", "dispatch_directives")

        # The cycle: dispatch loops back to ingest for the next cycle
        # In production, this edge is conditional on a shutdown signal
        graph.add_edge("dispatch_directives", END)

        return graph.compile()

    except ImportError:
        logger.warning(
            "LangGraph not installed. Install with: pip install langgraph\n"
            "The Sovereign orchestrator requires LangGraph for stateful cyclic workflows."
        )
        return None


# =============================================================================
# ENTRY POINT
# =============================================================================

def run_cycle(state: Optional[SovereignState] = None) -> SovereignState:
    """
    Run a single orchestration cycle.

    Can be called repeatedly in a loop, or triggered by a webhook/cron.
    """
    if state is None:
        state = SovereignState()

    graph = build_sovereign_graph()
    if graph is None:
        logger.error("Cannot run cycle without LangGraph. Falling back to sequential.")
        state = ingest_reports(state)
        state = evaluate_health(state)
        state = sovereign_reason(state)
        state = dispatch_directives(state)
        return state

    return graph.invoke(state)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_cycle()
    print(f"\nCycle complete. Health: {result.health_status.value}")
    print(f"Directives issued: {len(result.directives)}")
    print(f"Optimization triggers: {len(result.optimization_triggers)}")
