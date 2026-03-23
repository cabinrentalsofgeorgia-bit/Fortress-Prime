"""
Deterministic financial math helpers for the swarm trust perimeter.
"""
from __future__ import annotations


def validate_double_entry_balance(entries: list[dict]) -> bool:
    """Return True when debit and credit cents balance exactly."""
    debit_total = 0
    credit_total = 0

    for entry in entries:
        amount = entry.get("amount_cents")
        if isinstance(amount, float):
            raise ValueError("Floating point amounts are forbidden in trust ledger entries.")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise ValueError("Trust ledger amounts must be integer cents.")

        entry_type = entry.get("entry_type")
        if entry_type == "debit":
            debit_total += amount
        elif entry_type == "credit":
            credit_total += amount

    return debit_total == credit_total
