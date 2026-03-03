"""
Division B: Cabin Rentals of Georgia — Property Management
============================================================
Tier 2B of the Fortress recursive stack.

Scope:
    - Trust Accounting (Guest Escrow, Vendor Payouts)
    - Utility Monitoring (Blue Ridge properties)
    - Fannin County Tax Compliance
    - Operational Efficiency

Agent Persona: "The Controller"
    Conservative, risk-averse, highly detailed.
    Primary Goal: Operational Efficiency, Zero-Error Trust Compliance.

Key Integration: Plaid (Operating & Trust Accounts)

FIREWALL: This division NEVER accesses Division A (Holding) ledgers.
          Shared insights flow UP to the Sovereign only, never laterally.
"""

__all__ = ["agent", "trust_accounting", "plaid_client", "tax_compliance", "handlers"]
