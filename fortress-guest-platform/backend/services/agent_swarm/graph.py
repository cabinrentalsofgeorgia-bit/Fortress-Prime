"""
Agent Swarm Graph — LangGraph StateGraph compilation.

Topology:
  rag_researcher ──> pricing_calculator ──> lead_copywriter ──> compliance_auditor
                                                  ^                       │
                                                  │    audit_passed=False │
                                                  └───────────────────────┘
                                                       (max 2 rewrites)

When compliance_auditor sets audit_passed=True, the graph terminates at END.
When audit_passed=False, the graph loops back to lead_copywriter with
audit_notes injected so the copywriter can self-correct.

Rule 1: Multi-agent orchestration with fact-checking between agents.
Rule 5: Every node has try/except — graph never crashes silently.
"""
from __future__ import annotations

import structlog
from langgraph.graph import StateGraph, END

from backend.services.agent_swarm.state import QuoteState
from backend.services.agent_swarm.nodes import (
    rag_researcher,
    pricing_calculator,
    lead_copywriter,
    compliance_auditor,
)

logger = structlog.get_logger(service="agent_swarm_graph")


def _should_rewrite(state: QuoteState) -> str:
    """Conditional edge: route to rewrite or terminate."""
    if state.get("audit_passed", False):
        return "end"
    return "rewrite"


def build_quote_graph() -> StateGraph:
    """Compile and return the multi-agent quote generation graph."""

    graph = StateGraph(QuoteState)

    graph.add_node("rag_researcher", rag_researcher)
    graph.add_node("pricing_calculator", pricing_calculator)
    graph.add_node("lead_copywriter", lead_copywriter)
    graph.add_node("compliance_auditor", compliance_auditor)

    graph.set_entry_point("rag_researcher")

    graph.add_edge("rag_researcher", "pricing_calculator")
    graph.add_edge("pricing_calculator", "lead_copywriter")
    graph.add_edge("lead_copywriter", "compliance_auditor")

    graph.add_conditional_edges(
        "compliance_auditor",
        _should_rewrite,
        {
            "end": END,
            "rewrite": "lead_copywriter",
        },
    )

    return graph.compile()


quote_swarm = build_quote_graph()
