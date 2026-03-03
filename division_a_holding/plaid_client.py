"""
Division A Plaid Client — Investment & Corporate Accounts
==========================================================
Specialized Plaid integration for CROG LLC holding company accounts.

Extends the base PlaidClient from integrations/plaid_base.py with
Division A-specific account mappings and categorization logic.

FIREWALL: This client ONLY accesses Division A accounts (investment,
corporate). It has NO access to Division B trust/operating accounts.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("division_a.plaid")


# =============================================================================
# ACCOUNT CONFIGURATION
# =============================================================================

# Division A Plaid account types (configured at setup time)
DIVISION_A_ACCOUNT_TYPES = {
    "investment": "Investment portfolio accounts",
    "corporate_checking": "CROG LLC operating account",
    "corporate_savings": "CROG LLC reserve account",
}


# =============================================================================
# DIVISION A PLAID CLIENT
# =============================================================================

class HoldingPlaidClient:
    """
    Plaid client for Division A (CROG LLC Holding Company).

    Wraps the base PlaidClient and enforces Division A account boundaries.
    Financial data NEVER leaves the local cluster.
    """

    def __init__(self, access_tokens: Optional[Dict[str, str]] = None):
        """
        Initialize with Division A access tokens.

        Args:
            access_tokens: Mapping of account_type → Plaid access_token.
                          If None, reads from environment/config.
        """
        from integrations.plaid_base import PlaidClient

        self._base = PlaidClient()
        self._access_tokens = access_tokens or self._load_tokens()
        self._account_ids: Dict[str, List[str]] = {}

        logger.info(
            f"Division A Plaid client initialized "
            f"({len(self._access_tokens)} account types configured)"
        )

    def get_transactions(
        self,
        start_date: str,
        end_date: str,
        account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch transactions for Division A accounts only.

        Args:
            start_date: ISO date string (YYYY-MM-DD)
            end_date: ISO date string (YYYY-MM-DD)
            account_type: Specific account type or None for all Division A accounts

        Returns:
            List of Plaid transaction objects, filtered to Division A accounts only.
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
            all_txns.extend(txns)

        logger.info(
            f"Fetched {len(all_txns)} transactions for Division A "
            f"({start_date} to {end_date})"
        )
        return all_txns

    def get_balances(self, account_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get current balances for Division A accounts."""
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

    def get_investment_holdings(self) -> List[Dict[str, Any]]:
        """Get investment portfolio holdings (Division A only)."""
        token = self._access_tokens.get("investment")
        if not token:
            logger.warning("No investment account token configured")
            return []

        return self._base.get_investment_holdings(access_token=token)

    def _load_tokens(self) -> Dict[str, str]:
        """Load Division A Plaid access tokens from environment."""
        import os
        tokens = {}
        for acct_type in DIVISION_A_ACCOUNT_TYPES:
            env_key = f"PLAID_TOKEN_DIV_A_{acct_type.upper()}"
            token = os.getenv(env_key)
            if token:
                tokens[acct_type] = token
        return tokens
