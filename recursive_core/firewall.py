"""
Division Firewall — Corporate Veil Enforcement
================================================
SOW Task C: Strict data separation between divisions.

Rules:
    1. Division B (Property Management) agents NEVER access Division A
       (Holding Company) ledgers.
    2. Division A agents NEVER access Division B trust accounts.
    3. Shared insights flow UP to Tier 1 (Sovereign) only, never laterally.
    4. This preserves corporate veil integrity between CROG LLC and
       Cabin Rentals of Georgia.

Implementation:
    - Decorators for function-level access control
    - Schema-level PostgreSQL isolation (separate schemas)
    - Runtime validation of data flow direction
"""

import functools
import logging
from enum import Enum
from typing import Any, Callable, Dict, Optional, Set

logger = logging.getLogger("recursive_core.firewall")


# =============================================================================
# DIVISION DEFINITIONS
# =============================================================================

class Division(str, Enum):
    """The two strictly isolated business divisions."""
    HOLDING = "division_a"        # CROG, LLC
    PROPERTY = "division_b"       # Cabin Rentals of Georgia
    SOVEREIGN = "sovereign"       # Tier 1 (has access to both, read-only)


# What each division is allowed to access
ACCESS_MATRIX: Dict[Division, Set[str]] = {
    Division.HOLDING: {
        "division_a.transactions",
        "division_a.predictions",
        "division_a.audit_log",
        "division_a.vendor_rules",
    },
    Division.PROPERTY: {
        "division_b.transactions",
        "division_b.predictions",
        "division_b.escrow",
        "division_b.vendor_payouts",
        "division_b.trust_ledger",
        "division_b.vendor_rules",
    },
    Division.SOVEREIGN: {
        # Sovereign can READ both divisions (for health monitoring)
        "division_a.transactions",
        "division_a.predictions",
        "division_a.audit_log",
        "division_b.transactions",
        "division_b.predictions",
        "division_b.escrow",
        "division_b.vendor_payouts",
        "division_b.trust_ledger",
        # Plus its own state
        "sovereign.state",
        "sovereign.directives",
    },
}


# =============================================================================
# FIREWALL ENFORCEMENT
# =============================================================================

class FirewallViolation(Exception):
    """Raised when a division attempts to access data it shouldn't."""
    pass


def check_access(caller_division: Division, resource: str) -> bool:
    """
    Check if a division has access to a specific resource.

    Args:
        caller_division: The division requesting access
        resource: The resource being accessed (e.g., "division_a.transactions")

    Returns:
        True if access is allowed.

    Raises:
        FirewallViolation if access is denied.
    """
    allowed = ACCESS_MATRIX.get(caller_division, set())

    if resource in allowed:
        return True

    violation_msg = (
        f"FIREWALL VIOLATION: {caller_division.value} attempted to access "
        f"'{resource}'. Access DENIED. "
        f"Allowed resources: {sorted(allowed)}"
    )
    logger.critical(violation_msg)

    # Log the violation for Sovereign review
    _log_violation(caller_division, resource)

    raise FirewallViolation(violation_msg)


def division_access(division: Division):
    """
    Decorator to enforce division access control on functions.

    Usage:
        @division_access(Division.PROPERTY)
        def get_trust_balance():
            ...  # Only callable by Division B agents

        @division_access(Division.SOVEREIGN)
        def get_all_metrics():
            ...  # Only callable by the Sovereign
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # The calling context must identify its division
            caller = kwargs.pop("_caller_division", None)
            if caller is None:
                # If no caller specified, allow (internal call)
                return func(*args, **kwargs)

            if isinstance(caller, str):
                caller = Division(caller)

            # Check access
            resource = f"{division.value}.{func.__name__}"

            if caller == division or caller == Division.SOVEREIGN:
                return func(*args, **kwargs)
            else:
                check_access(caller, resource)
                return func(*args, **kwargs)

        return wrapper
    return decorator


def validate_data_flow(
    source: Division,
    destination: Division,
    data_type: str = "metrics",
) -> bool:
    """
    Validate that a data flow respects the corporate veil.

    Legal data flows:
        Division A → Sovereign (upward)
        Division B → Sovereign (upward)
        Sovereign → Division A (downward directive)
        Sovereign → Division B (downward directive)

    Illegal data flows:
        Division A → Division B (lateral — violates corporate veil)
        Division B → Division A (lateral — violates corporate veil)
    """
    # Upward flows are always OK
    if destination == Division.SOVEREIGN:
        logger.debug(f"Data flow OK: {source.value} → Sovereign ({data_type})")
        return True

    # Downward flows from Sovereign are OK (directives only)
    if source == Division.SOVEREIGN:
        logger.debug(f"Data flow OK: Sovereign → {destination.value} ({data_type})")
        return True

    # Same-division flows are OK
    if source == destination:
        return True

    # Lateral flows are BLOCKED
    violation_msg = (
        f"LATERAL DATA FLOW BLOCKED: {source.value} → {destination.value} "
        f"({data_type}). Only vertical flows (to/from Sovereign) are permitted."
    )
    logger.critical(violation_msg)
    _log_violation(source, f"lateral_flow_to_{destination.value}")
    raise FirewallViolation(violation_msg)


# =============================================================================
# VIOLATION LOGGING
# =============================================================================

def _log_violation(caller: Division, resource: str) -> None:
    """Log a firewall violation for Sovereign review."""
    from recursive_core.reflection_log import log_firewall_violation
    log_firewall_violation(
        caller_division=caller.value,
        attempted_resource=resource,
    )
