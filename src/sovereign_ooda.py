"""
SOVEREIGN OODA LOOP — Mandated Reflection Pattern (Constitution Article III)
=============================================================================
Fortress Prime | Every major agent action must follow Observe-Orient-Decide-Act.

This module provides:
    1. SovereignState — the TypedDict all LangGraph agents must use.
    2. OODAGraph — a reusable StateGraph skeleton with the five mandated nodes.
    3. write_post_mortem() — persists audit records to system_post_mortems.

Usage:
    from src.sovereign_ooda import SovereignState, build_ooda_graph, write_post_mortem

    # Build a sector-specific OODA agent
    graph = build_ooda_graph(
        observe_fn=my_observe,
        orient_fn=my_orient,
        decide_fn=my_decide,
        act_fn=my_act,
    )
    agent = graph.compile()
    result = agent.invoke({"sector": "crog", "query": "Generate owner report"})

Governing Documents:
    CONSTITUTION.md  — Article III (Self-Healing & Recursive Growth)
    REQUIREMENTS.md  — Section 3.5 (LangGraph Agent Pattern)
    .cursor/rules/002-sovereign-constitution.mdc
"""

from __future__ import annotations

import os
import logging
import traceback
from datetime import datetime, timezone
from typing import TypedDict, Callable, Optional, Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("sovereign.ooda")


# =============================================================================
# I. THE SOVEREIGN STATE (Mandated by Constitution Article III)
# =============================================================================

class SovereignState(TypedDict):
    """
    Every LangGraph agent in the Fortress MUST use this state shape.

    The five fields map directly to the OODA loop + Article III post-mortem:
        observation    — Raw data from Synology/Streamline/Postgres/Qdrant
        orientation    — Gemini 3 Pro context/analysis (or fast Ollama classification)
        decision       — R1's final logic/recommendation (or SWARM-mode fast decision)
        action_result  — Success/Failure log of the executed action
        post_mortem    — Article III Self-Healing Audit record
    """
    # --- Context ---
    sector: str                     # Atlas sector slug: crog, dev, comp, bloom, legal
    query: str                      # The triggering request or event

    # --- OODA Cycle ---
    observation: str                # OBSERVE: raw data gathered
    orientation: str                # ORIENT: analysis / legal context / classification
    decision: str                   # DECIDE: the chosen action + reasoning
    action_result: str              # ACT: outcome of execution

    # --- Article III Mandate ---
    post_mortem: str                # Self-Healing audit (always populated)
    audit_trail: list[str]          # Running log of every step taken
    confidence: float               # 0.0-1.0 confidence in the final result
    severity: str                   # critical, warning, info


# =============================================================================
# II. POST-MORTEM WRITER (Constitution Article III, Section 3.1)
# =============================================================================

class PostMortemRecord(BaseModel):
    """Pydantic model for system_post_mortems table rows."""
    sector: str = Field(..., min_length=2, max_length=10)
    severity: str = Field(default="info")
    component: str = Field(..., min_length=1)
    error_summary: str = Field(default="")
    root_cause: Optional[str] = None
    remediation: Optional[str] = None
    status: str = Field(default="open")
    resolved_by: Optional[str] = None

    @field_validator("severity")
    @classmethod
    def valid_severity(cls, v: str) -> str:
        allowed = {"critical", "warning", "info"}
        if v.lower() not in allowed:
            raise ValueError(f"severity must be one of {allowed}")
        return v.lower()

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        allowed = {"open", "mitigated", "resolved"}
        if v.lower() not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v.lower()


def write_post_mortem(record: PostMortemRecord) -> int:
    """
    Persist a post-mortem to the system_post_mortems table.

    Returns the inserted row ID, or -1 if the write fails (non-critical).
    Failures here are logged but never raise — the OODA loop must not break
    due to audit infrastructure issues.
    """
    try:
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "192.168.0.100"),
            dbname=os.getenv("DB_NAME", "fortress_db"),
            user=os.getenv("DB_USER", "miner_bot"),
            password=os.getenv("DB_PASS", os.getenv("ADMIN_DB_PASS", "")),
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        cur = conn.cursor()

        # Ensure the table exists (idempotent)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.system_post_mortems (
                id              SERIAL PRIMARY KEY,
                occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                sector          VARCHAR(10) NOT NULL,
                severity        VARCHAR(10) NOT NULL,
                component       TEXT NOT NULL,
                error_summary   TEXT NOT NULL,
                root_cause      TEXT,
                remediation     TEXT,
                status          VARCHAR(20) DEFAULT 'open',
                resolved_by     VARCHAR(50),
                resolved_at     TIMESTAMPTZ
            )
        """)

        cur.execute("""
            INSERT INTO public.system_post_mortems
                (sector, severity, component, error_summary, root_cause,
                 remediation, status, resolved_by)
            VALUES (%(sector)s, %(severity)s, %(component)s, %(error_summary)s,
                    %(root_cause)s, %(remediation)s, %(status)s, %(resolved_by)s)
            RETURNING id
        """, record.model_dump())

        row = cur.fetchone()
        conn.commit()
        row_id = row["id"] if row else -1
        conn.close()
        logger.info(f"Post-mortem #{row_id} written: [{record.severity}] {record.component}")
        return row_id

    except Exception as e:
        logger.error(f"Failed to write post-mortem (non-fatal): {e}")
        return -1


# =============================================================================
# III. OODA NODE IMPLEMENTATIONS (Default Behaviors)
# =============================================================================

def _default_observe(state: SovereignState) -> SovereignState:
    """
    OBSERVE: Gather raw data relevant to the query.
    Override this with your sector-specific data gathering logic.
    """
    state["observation"] = f"[Default Observer] Query received: {state['query']}"
    state["audit_trail"].append(
        f"[{datetime.now(timezone.utc).isoformat()}] OBSERVE: Default observer invoked"
    )
    return state


def _default_orient(state: SovereignState) -> SovereignState:
    """
    ORIENT: Analyze and contextualize the observation.
    In production, this calls the Architect (Gemini) or SWARM Ollama for classification.
    """
    state["orientation"] = (
        f"[Default Orienter] Sector={state['sector']}. "
        f"Observation length={len(state.get('observation', ''))} chars."
    )
    state["audit_trail"].append(
        f"[{datetime.now(timezone.utc).isoformat()}] ORIENT: Default orienter invoked"
    )
    return state


def _default_decide(state: SovereignState) -> SovereignState:
    """
    DECIDE: Choose the action based on orientation.
    In TITAN mode, this calls R1 for deep reasoning.
    In SWARM mode, this uses fast Ollama inference.
    """
    state["decision"] = (
        f"[Default Decider] Based on orientation, proceeding with standard action."
    )
    state["confidence"] = 0.5
    state["audit_trail"].append(
        f"[{datetime.now(timezone.utc).isoformat()}] DECIDE: Default decider invoked "
        f"(confidence={state['confidence']})"
    )
    return state


def _default_act(state: SovereignState) -> SovereignState:
    """
    ACT: Execute the decision and record outcome.
    Override this with your sector-specific execution logic.
    """
    state["action_result"] = "[Default Actor] No action taken (override required)."
    state["audit_trail"].append(
        f"[{datetime.now(timezone.utc).isoformat()}] ACT: Default actor invoked"
    )
    return state


def _post_mortem_node(state: SovereignState) -> SovereignState:
    """
    POST-MORTEM: Mandatory terminal node (Constitution Article III).

    Analyzes the full OODA cycle, determines severity, and persists
    the audit record to system_post_mortems.
    """
    # Determine severity from action result
    action = state.get("action_result", "")
    if "error" in action.lower() or "fail" in action.lower():
        severity = "critical" if state.get("confidence", 0) < 0.3 else "warning"
    else:
        severity = "info"

    state["severity"] = severity

    # Build the post-mortem summary
    pm_lines = [
        f"Sector: {state['sector']}",
        f"Query: {state['query'][:200]}",
        f"Confidence: {state.get('confidence', 0):.2f}",
        f"Severity: {severity}",
        f"Decision: {state.get('decision', 'none')[:200]}",
        f"Outcome: {action[:200]}",
        f"Steps: {len(state.get('audit_trail', []))}",
    ]
    state["post_mortem"] = "\n".join(pm_lines)

    # Persist to database
    record = PostMortemRecord(
        sector=state["sector"][:10],
        severity=severity,
        component=f"ooda:{state['sector']}",
        error_summary=state.get("action_result", "")[:500],
        root_cause=state.get("orientation", "")[:500] if severity != "info" else None,
        remediation=state.get("decision", "")[:500] if severity != "info" else None,
        status="resolved" if severity == "info" else "open",
        resolved_by="auto" if severity == "info" else None,
    )
    pm_id = write_post_mortem(record)

    state["audit_trail"].append(
        f"[{datetime.now(timezone.utc).isoformat()}] POST-MORTEM: "
        f"Severity={severity}, DB record #{pm_id}"
    )

    return state


# =============================================================================
# IV. OODA GRAPH BUILDER
# =============================================================================

def build_ooda_graph(
    observe_fn: Callable = None,
    orient_fn: Callable = None,
    decide_fn: Callable = None,
    act_fn: Callable = None,
) -> Any:
    """
    Build a LangGraph StateGraph implementing the OODA Reflection Loop.

    The graph has five nodes executed sequentially:
        observe -> orient -> decide -> act -> post_mortem -> END

    Args:
        observe_fn: Custom OBSERVE function (default: logs the query).
        orient_fn:  Custom ORIENT function (default: classifies by sector).
        decide_fn:  Custom DECIDE function (default: placeholder).
        act_fn:     Custom ACT function (default: no-op).

    Returns:
        A LangGraph StateGraph (not yet compiled — call .compile() on it).

    Example:
        graph = build_ooda_graph(
            observe_fn=my_data_gatherer,
            decide_fn=my_r1_reasoner,
            act_fn=my_report_generator,
        )
        agent = graph.compile()
        result = agent.invoke({
            "sector": "crog",
            "query": "Generate owner statement for property 12345",
            "observation": "",
            "orientation": "",
            "decision": "",
            "action_result": "",
            "post_mortem": "",
            "audit_trail": [],
            "confidence": 0.0,
            "severity": "info",
        })
    """
    from langgraph.graph import StateGraph, END

    graph = StateGraph(SovereignState)

    # Add nodes
    graph.add_node("observe", observe_fn or _default_observe)
    graph.add_node("orient", orient_fn or _default_orient)
    graph.add_node("decide", decide_fn or _default_decide)
    graph.add_node("act", act_fn or _default_act)
    graph.add_node("post_mortem", _post_mortem_node)

    # Wire the OODA sequence
    graph.set_entry_point("observe")
    graph.add_edge("observe", "orient")
    graph.add_edge("orient", "decide")
    graph.add_edge("decide", "act")
    graph.add_edge("act", "post_mortem")
    graph.add_edge("post_mortem", END)

    return graph


# =============================================================================
# V. CONVENIENCE: Build initial state
# =============================================================================

def make_initial_state(sector: str, query: str) -> SovereignState:
    """
    Create a clean initial SovereignState for invoking an OODA agent.

    Args:
        sector: Atlas sector slug (crog, dev, comp, bloom, legal).
        query: The triggering request or event description.

    Returns:
        A SovereignState dict ready for graph.invoke().
    """
    return SovereignState(
        sector=sector,
        query=query,
        observation="",
        orientation="",
        decision="",
        action_result="",
        post_mortem="",
        audit_trail=[],
        confidence=0.0,
        severity="info",
    )
