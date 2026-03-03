"""
QuickBooks Online Integration — Operation Strangler Fig
==========================================================
The intelligence pipeline that reads QBO's brain before we kill it.

Phase 1 (NOW):   Read-only. Pull CoA, P&L, Balance Sheet, Trial Balance.
                  Compare against Fortress GL. Prove parity.
Phase 2 (NEXT):  Write-back. Push journal entries to QBO for CPA review.
Phase 3 (FINAL): Cut the cord. QBO subscription cancelled.

Sub-modules:
    auth    — OAuth2 flow (authorize, callback, token refresh, storage)
    client  — QBO API client (query accounts, reports, journal entries)
    sync    — Reconciliation bridge (Fortress GL vs QBO reports)

Security:
    - OAuth tokens stored on NAS (never in code or git)
    - All API responses processed locally on DGX Spark cluster
    - Client credentials in .env only
"""

__all__ = ["auth", "client", "sync"]
