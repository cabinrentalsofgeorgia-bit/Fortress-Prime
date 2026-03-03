"""
Division B Handlers — Specialized Processing Pipelines
=========================================================
Each handler encapsulates a specific workflow that the PropertyAgent
triggers during its OODA loop.

Handlers:
    revenue_realizer — Stripe deposit → forecast reversal + actual revenue posting
"""

__all__ = ["revenue_realizer"]
