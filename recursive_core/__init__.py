"""
Recursive Core — Tier 3: The OODA Learning Engine
====================================================
The defining feature of the Fortress stack. The system does not just
execute; it LEARNS.

OODA Loop Phases:
    Observe   → Ingest real-time data via Plaid Webhooks
    Orient    → Compare actuals vs. predictions
    Decide    → Execute necessary transfers or alerts
    Act       → Call tools (API requests, DB writes)
    REFLECT   → If variance > 5%, trigger self-correction

Sub-modules:
    ooda_loop          — The full Observe-Orient-Decide-Act cycle
    optimization_loop  — The "Judge" — expected vs actual comparison
    prompt_optimizer   — DSPy integration for prompt rewriting
    firewall           — Division data separation enforcement
    reflection_log     — Audit trail for all recursive rewrites
"""

__all__ = [
    "ooda_loop",
    "optimization_loop",
    "prompt_optimizer",
    "firewall",
    "reflection_log",
]
