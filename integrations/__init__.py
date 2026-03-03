"""
Integrations — Shared External Service Connectors
====================================================
Cross-cutting integrations used by both divisions.

RULE: Financial data from these integrations NEVER leaves the local
      DGX Spark cluster. All processing is on-premise.

Sub-modules:
    plaid_base  — Base PlaidClient (read-only sensory feed + webhook handler)
    quickbooks  — QBO OAuth2 + API client (Operation Strangler Fig reconciliation)
"""

__all__ = ["plaid_base", "quickbooks"]
