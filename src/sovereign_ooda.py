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
# 0. INVOCATION RATE LIMITER (Bounded Recursion Enforcement)
# =============================================================================

import time as _time
import threading as _threading

_invocation_timestamps: list[float] = []
_rate_lock = _threading.Lock()
MAX_INVOCATIONS_PER_HOUR = 50


def _check_ooda_rate_limit() -> None:
    """Reject invocations that exceed the hourly budget."""
    global _invocation_timestamps
    now = _time.time()
    with _rate_lock:
        _invocation_timestamps = [ts for ts in _invocation_timestamps if now - ts < 3600]
        if len(_invocation_timestamps) >= MAX_INVOCATIONS_PER_HOUR:
            logger.critical(
                "OODA rate limit exceeded (%d/%d per hour). Blocking invocation.",
                len(_invocation_timestamps),
                MAX_INVOCATIONS_PER_HOUR,
            )
            raise RuntimeError(
                f"OODA Loop invocation limit exceeded ({MAX_INVOCATIONS_PER_HOUR}/hr). "
                "System locked to prevent runaway recursion."
            )
        _invocation_timestamps.append(now)


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

    God-Head escalation (Autonomous Swarm Directive Section VI):
    If confidence is below threshold and the sector maps to a God-Head domain,
    escalate to the appropriate external API via god_head_router.
    """
    state["decision"] = (
        f"[Default Decider] Based on orientation, proceeding with standard action."
    )
    state["confidence"] = 0.5

    try:
        from src.god_head_router import should_escalate, route as god_head_route

        sector = state.get("sector", "")
        domain_map = {"legal": "legal", "comp": "financial", "dev": "architecture"}
        domain = domain_map.get(sector, "general")

        if should_escalate(domain, state["confidence"]):
            logger.info(f"OODA escalating to God-Head: domain={domain}, confidence={state['confidence']}")
            result = god_head_route(
                domain=domain,
                prompt=state.get("query", ""),
                context=state.get("orientation", ""),
            )
            state["decision"] = (
                f"[God-Head Escalation] Provider={result['provider']}, "
                f"fallback={result['fallback_used']}: {result['response'][:500]}"
            )
            state["audit_trail"].append(
                f"[{datetime.now(timezone.utc).isoformat()}] DECIDE: Escalated to God-Head "
                f"domain={domain} provider={result['provider']} "
                f"escalation_id={result['escalation_id']}"
            )
            return state

    except Exception as exc:
        logger.debug(f"God-Head escalation skipped: {exc}")

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
# III-B. INSTITUTIONAL LESSON RETRIEVAL (Autonomous Swarm Directive — Pillar 3)
# =============================================================================

def _retrieve_institutional_lessons(state: SovereignState) -> SovereignState:
    """
    Inject institutional memory into the OODA cycle before the Decide phase.
    Queries Qdrant fortress_lessons collection for relevant past resolutions.
    Gracefully degrades if the collection does not exist yet.
    """
    query_text = f"{state.get('query', '')} {state.get('orientation', '')}"[:500]
    lessons_context = ""
    try:
        import requests as _req
        qdrant_url = os.getenv("QDRANT_URL", "http://192.168.0.100:6333")
        embed_url = os.getenv("EMBED_URL", "http://192.168.0.100/api/embeddings")

        embed_resp = _req.post(
            embed_url,
            json={"model": "nomic-embed-text", "prompt": query_text},
            timeout=10,
        )
        if embed_resp.status_code != 200:
            raise ValueError(f"embedding request failed: {embed_resp.status_code}")
        vector = embed_resp.json().get("embedding", [])
        if not vector:
            raise ValueError("empty embedding returned")

        search_resp = _req.post(
            f"{qdrant_url}/collections/fortress_lessons/points/search",
            json={"vector": vector, "limit": 3, "with_payload": True},
            timeout=5,
        )
        if search_resp.status_code == 200:
            results = search_resp.json().get("result", [])
            if results:
                lines = ["[Institutional Lessons Retrieved]"]
                for i, r in enumerate(results, 1):
                    p = r.get("payload", {})
                    lines.append(
                        f"  {i}. [{p.get('domain','?')}] {p.get('pattern','?')} "
                        f"— Fix: {p.get('fix_applied','?')}"
                    )
                lessons_context = "\n".join(lines)

    except Exception as exc:
        logger.debug(f"Institutional lesson retrieval skipped: {exc}")

    if lessons_context:
        state["orientation"] = state.get("orientation", "") + "\n\n" + lessons_context
        state["audit_trail"].append(
            f"[{datetime.now(timezone.utc).isoformat()}] LESSONS: Retrieved institutional memory"
        )
    else:
        state["audit_trail"].append(
            f"[{datetime.now(timezone.utc).isoformat()}] LESSONS: No relevant lessons found (collection may not exist yet)"
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

    def _rate_limit_gate(state: SovereignState) -> SovereignState:
        _check_ooda_rate_limit()
        return state

    graph = StateGraph(SovereignState)

    # Add nodes (rate_limit gate fires before observe on every invocation)
    graph.add_node("rate_limit", _rate_limit_gate)
    graph.add_node("observe", observe_fn or _default_observe)
    graph.add_node("orient", orient_fn or _default_orient)
    graph.add_node("decide", decide_fn or _default_decide)
    graph.add_node("act", act_fn or _default_act)
    graph.add_node("post_mortem", _post_mortem_node)

    # Wire the OODA sequence
    graph.add_node("retrieve_lessons", _retrieve_institutional_lessons)

    graph.set_entry_point("rate_limit")
    graph.add_edge("rate_limit", "observe")
    graph.add_edge("observe", "orient")
    graph.add_edge("orient", "retrieve_lessons")
    graph.add_edge("retrieve_lessons", "decide")
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


# =============================================================================
# VI. SEQUENTIAL OODA RUNNER (preserves full state dict)
# =============================================================================
# LangGraph's StateGraph only tracks channels declared in the TypedDict.
# Internal keys (prefixed with _) used for passing data between OODA nodes
# (e.g. _files, _chunks, _ingest_mod) are silently dropped between nodes.
#
# This sequential runner executes the same 5-step OODA cycle using plain
# function composition, preserving ALL dict keys. Use this for agents that
# pass internal state between nodes.

def run_ooda_sequence(
    state: dict,
    observe_fn: Callable,
    orient_fn: Callable,
    decide_fn: Callable,
    act_fn: Callable,
) -> dict:
    """
    Execute the full OODA cycle sequentially, preserving all state keys.

    Runs: observe -> orient -> decide -> act -> post_mortem -> return

    Unlike build_ooda_graph().compile().invoke(), this runner preserves
    internal keys (prefixed with _) that LangGraph's StateGraph channels
    would drop. Use this for agents that pass rich internal state between
    OODA phases.

    Args:
        state: Initial state dict (from make_initial_state + extra keys).
        observe_fn: OBSERVE function.
        orient_fn: ORIENT function.
        decide_fn: DECIDE function.
        act_fn: ACT function.

    Returns:
        Final state dict with all OODA fields and internal keys intact.
    """
    _check_ooda_rate_limit()
    state = observe_fn(state)
    state = orient_fn(state)
    state = decide_fn(state)
    state = act_fn(state)
    state = _post_mortem_node(state)
    return state


# =============================================================================
# VII. COUNCIL INTELLIGENCE OODA AGENT
# =============================================================================
# A complete closed-loop intelligence agent that wires the Council of Giants
# into the OODA framework. When triggered by an event:
#   OBSERVE  — Ingest market event (FRED data, VIX spike, news)
#   ORIENT   — Run Council.vote_on(event) to get consensus + all opinions
#   DECIDE   — Evaluate conviction threshold: escalate if high, log if low
#   ACT      — Send alert email, persist to PostgreSQL, update Grafana
#   POST_MORTEM — Write audit record, ready for accuracy resolution later

def _council_observe(state: SovereignState) -> SovereignState:
    """OBSERVE: Gather the raw event data."""
    event = state["query"]
    state["observation"] = f"Market event detected: {event}"
    state["audit_trail"].append(
        f"[{datetime.now(timezone.utc).isoformat()}] OBSERVE: Event ingested — {event[:100]}"
    )
    return state


def _council_orient(state: SovereignState) -> SovereignState:
    """ORIENT: Run Council vote on the event to get multi-persona analysis."""
    try:
        from persona_template import Persona, Council

        slugs = sorted(Persona.list_all())
        if not slugs:
            state["orientation"] = "No personas available for Council vote."
            state["confidence"] = 0.0
            return state

        personas = [Persona.load(s) for s in slugs]
        council = Council(personas)

        result = council.vote_on(state["query"])

        # Store the full result in orientation for the decide step
        state["orientation"] = (
            f"Council consensus: {result.get('consensus_signal', 'NEUTRAL')} | "
            f"Conviction: {result.get('consensus_conviction', 0):.0%} | "
            f"Agreement: {result.get('agreement_rate', 0):.0%} | "
            f"Bullish: {result.get('bullish_count', 0)} / "
            f"Bearish: {result.get('bearish_count', 0)} / "
            f"Neutral: {result.get('neutral_count', 0)}"
        )

        # Stash full result for decide/act steps
        state["_council_result"] = result
        state["confidence"] = result.get("consensus_conviction", 0.5)

        state["audit_trail"].append(
            f"[{datetime.now(timezone.utc).isoformat()}] ORIENT: "
            f"Council voted — {result.get('consensus_signal')} "
            f"({result.get('consensus_conviction', 0):.0%} conviction, "
            f"{result.get('elapsed_seconds', 0)}s)"
        )

    except Exception as e:
        logger.error(f"Council orient failed: {e}")
        state["orientation"] = f"Council vote failed: {str(e)[:200]}"
        state["confidence"] = 0.0
        state["_council_result"] = None

    return state


def _council_decide(state: SovereignState) -> SovereignState:
    """DECIDE: Evaluate if the signal warrants escalation."""
    result = state.get("_council_result")
    if not result:
        state["decision"] = "No Council data — cannot make decision. Logging as informational."
        state["confidence"] = 0.0
        return state

    conviction = result.get("consensus_conviction", 0)
    agreement = result.get("agreement_rate", 0)
    signal = result.get("consensus_signal", "NEUTRAL")

    if conviction > 0.8 and agreement > 0.7:
        state["decision"] = (
            f"ESCALATE: High-confidence signal — {signal} with "
            f"{conviction:.0%} conviction and {agreement:.0%} agreement. "
            f"Sending alert and persisting to database."
        )
        state["_escalate"] = True
    elif conviction > 0.6:
        state["decision"] = (
            f"LOG: Moderate signal — {signal} with "
            f"{conviction:.0%} conviction. Persisting to database for tracking."
        )
        state["_escalate"] = False
    else:
        state["decision"] = (
            f"MONITOR: Low-confidence signal — {signal} with "
            f"{conviction:.0%} conviction. Logging only."
        )
        state["_escalate"] = False

    state["audit_trail"].append(
        f"[{datetime.now(timezone.utc).isoformat()}] DECIDE: "
        f"{'ESCALATE' if state.get('_escalate') else 'LOG'} — "
        f"conviction={conviction:.0%}, agreement={agreement:.0%}"
    )

    return state


def _council_act(state: SovereignState) -> SovereignState:
    """ACT: Persist results, send alerts if escalated."""
    result = state.get("_council_result")
    actions_taken = []

    # Always persist to database
    if result:
        try:
            import sys
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
            from intelligence_engine import _persist_vote
            import uuid
            vote_id = str(uuid.uuid4())
            _persist_vote(vote_id, result, "qwen2.5:7b")
            actions_taken.append(f"Persisted vote {vote_id[:8]}... to PostgreSQL")
        except Exception as e:
            actions_taken.append(f"DB persistence failed: {str(e)[:60]}")

    # Send alert email if escalated
    if state.get("_escalate") and result:
        try:
            import smtplib
            from email.mime.text import MIMEText

            gmail = os.getenv("GMAIL_ADDRESS", "")
            gmail_pw = os.getenv("GMAIL_APP_PASSWORD", "")
            if gmail and gmail_pw:
                signal = result.get("consensus_signal", "NEUTRAL")
                body = (
                    f"Council OODA Alert\n\n"
                    f"Event: {state['query']}\n"
                    f"Signal: {signal}\n"
                    f"Conviction: {result.get('consensus_conviction', 0):.0%}\n"
                    f"Agreement: {result.get('agreement_rate', 0):.0%}\n\n"
                    f"Decision: {state.get('decision', 'N/A')}\n\n"
                    f"View: http://192.168.0.100:9800/intelligence"
                )
                msg = MIMEText(body)
                msg["Subject"] = f"[OODA] Council Alert: {signal} — {state['query'][:50]}"
                msg["From"] = gmail
                msg["To"] = gmail

                server = smtplib.SMTP("smtp.gmail.com", 587)
                server.starttls()
                server.login(gmail, gmail_pw)
                server.send_message(msg)
                server.quit()
                actions_taken.append("Alert email sent")
            else:
                actions_taken.append("Email not configured — alert skipped")
        except Exception as e:
            actions_taken.append(f"Email failed: {str(e)[:60]}")

    state["action_result"] = " | ".join(actions_taken) if actions_taken else "No action taken"
    state["audit_trail"].append(
        f"[{datetime.now(timezone.utc).isoformat()}] ACT: {state['action_result']}"
    )

    return state


def build_council_ooda_graph() -> Any:
    """
    Build a complete Council Intelligence OODA agent.

    Usage:
        from sovereign_ooda import build_council_ooda_graph, make_initial_state
        graph = build_council_ooda_graph()
        agent = graph.compile()
        result = agent.invoke(make_initial_state("intel", "VIX spikes to 35"))
    """
    return build_ooda_graph(
        observe_fn=_council_observe,
        orient_fn=_council_orient,
        decide_fn=_council_decide,
        act_fn=_council_act,
    )


def run_council_ooda(event: str) -> dict:
    """
    Convenience function: run the full Council OODA loop on an event.
    Uses the sequential runner to preserve internal state keys.

    Args:
        event: Market event description to analyze.

    Returns:
        Final OODA state dict with all fields populated.
    """
    state = make_initial_state(sector="intel", query=event)
    state["_council_result"] = None
    state["_escalate"] = False

    final = run_ooda_sequence(
        state,
        observe_fn=_council_observe,
        orient_fn=_council_orient,
        decide_fn=_council_decide,
        act_fn=_council_act,
    )

    return final
