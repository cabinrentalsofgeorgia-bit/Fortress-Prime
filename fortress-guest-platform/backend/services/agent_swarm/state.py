"""
QuoteState — Shared state schema for the multi-agent LangGraph workflow.

Every node reads from and writes to this TypedDict. The graph passes the
full state through the pipeline: RAG -> Pricing -> Copywriter -> Auditor.
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional, Annotated
from typing_extensions import TypedDict

from langgraph.graph import add_messages


class QuoteState(TypedDict, total=False):
    """Shared state flowing through the 4-node agent swarm."""

    # ── Inputs (set by the caller before graph invocation) ──
    lead_id: str
    lead_name: str
    guest_message: str
    property_ids: List[str]
    check_in_date: str
    check_out_date: str

    # ── Node 1: RAG Researcher output ──
    rag_context: str

    # ── Node 2: Pricing Calculator output ──
    pricing_math: List[Dict[str, Any]]

    # ── Node 3: Lead Copywriter output ──
    draft_email: str
    draft_model: str

    # ── Node 4: Compliance Auditor output ──
    audit_passed: bool
    audit_notes: str

    # ── Control flow ──
    rewrite_count: int
    node_log: List[str]
