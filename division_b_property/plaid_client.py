"""
Division B Plaid Client — Operating & Trust Accounts
======================================================
Specialized Plaid integration for Cabin Rentals of Georgia PM accounts.

FIREWALL: This client ONLY accesses Division B accounts (operating, trust).
It has NO access to Division A investment/corporate accounts.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("division_b.plaid")


# =============================================================================
# ACCOUNT CONFIGURATION
# =============================================================================

DIVISION_B_ACCOUNT_TYPES = {
    "operating": "Cabin Rentals operating account (day-to-day expenses)",
    "trust": "Guest escrow trust account (legally segregated)",
    "reserve": "Maintenance reserve fund",
}


# =============================================================================
# DIVISION B PLAID CLIENT
# =============================================================================

class PropertyPlaidClient:
    """
    Plaid client for Division B (Cabin Rentals of Georgia PM).

    Wraps the base PlaidClient and enforces Division B account boundaries.
    Financial data NEVER leaves the local cluster.
    """

    def __init__(self, access_tokens: Optional[Dict[str, str]] = None):
        from integrations.plaid_base import PlaidClient

        self._base = PlaidClient()
        self._access_tokens = access_tokens or self._load_tokens()

        logger.info(
            f"Division B Plaid client initialized "
            f"({len(self._access_tokens)} account types configured)"
        )

    def get_transactions(
        self,
        start_date: str,
        end_date: str,
        account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch transactions for Division B accounts only.
        Trust account transactions are flagged for escrow reconciliation.
        """
        tokens = self._access_tokens
        if account_type and account_type in tokens:
            tokens = {account_type: tokens[account_type]}

        all_txns = []
        for acct_type, token in tokens.items():
            txns = self._base.get_transactions(
                access_token=token,
                start_date=start_date,
                end_date=end_date,
            )
            for txn in txns:
                txn["division_account_type"] = acct_type
                txn["trust_related"] = (acct_type == "trust")
            all_txns.extend(txns)

        logger.info(
            f"Fetched {len(all_txns)} transactions for Division B "
            f"({start_date} to {end_date})"
        )
        return all_txns

    def get_balances(self, account_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get current balances for Division B accounts."""
        tokens = self._access_tokens
        if account_type and account_type in tokens:
            tokens = {account_type: tokens[account_type]}

        all_balances = []
        for acct_type, token in tokens.items():
            balances = self._base.get_balances(access_token=token)
            for bal in balances:
                bal["division_account_type"] = acct_type
            all_balances.extend(balances)

        return all_balances

    def get_trust_balance(self) -> Optional[Dict[str, Any]]:
        """Get the trust account balance specifically (for escrow verification)."""
        token = self._access_tokens.get("trust")
        if not token:
            logger.warning("No trust account token configured")
            return None

        balances = self._base.get_balances(access_token=token)
        return balances[0] if balances else None

    def _load_tokens(self) -> Dict[str, str]:
        """Load Division B Plaid access tokens from environment."""
        import os
        tokens = {}
        for acct_type in DIVISION_B_ACCOUNT_TYPES:
            env_key = f"PLAID_TOKEN_DIV_B_{acct_type.upper()}"
            token = os.getenv(env_key)
            if token:
                tokens[acct_type] = token
        return tokens
