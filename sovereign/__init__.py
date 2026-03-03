"""
Sovereign — Tier 1: The r1 Orchestrator
========================================
Strategic oversight, cross-division arbitration, and Meta-Cognition.

The Sovereign receives aggregated reports from Division A (Holding) and
Division B (Property Management), monitors system health, and holds
the authority to rewrite subordinate agent prompts via DSPy optimization.

Sub-modules:
    orchestrator    — The main LangGraph state machine (cyclic DCG)
    health_monitor  — Cash Flow / Tax Exposure / ROI scorecards
    prompt_governor — Rewrites Tier 2 system prompts when performance degrades
"""

__all__ = ["orchestrator", "health_monitor", "prompt_governor", "process_escalations"]
