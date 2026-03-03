"""
Plaid Base Client — Read-Only Sensory Feed
=============================================
SOW Task A: Standardized PlaidClient class acting as a read-only sensory feed.

This is the ONLY module that communicates with the Plaid API.
Division-specific clients (division_a/plaid_client.py, division_b/plaid_client.py)
wrap this base class with their own account boundaries.

Security Constraints:
    - Financial data NEVER leaves the local cluster
    - All processing occurs on DGX Spark / local LLM endpoints
    - Plaid credentials stored in environment variables only
    - Read-only operations — no transfers or account modifications
"""

import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("integrations.plaid")


# =============================================================================
# CONFIGURATION
# =============================================================================

PLAID_ENV = os.getenv("PLAID_ENV", "sandbox")  # sandbox, development, production
PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "")
PLAID_SECRET = os.getenv("PLAID_SECRET", "")


# =============================================================================
# BASE PLAID CLIENT
# =============================================================================

class PlaidClient:
    """
    Base Plaid API client — read-only sensory feed.

    This client provides:
        1. Transaction retrieval
        2. Balance checking
        3. Investment holdings retrieval
        4. Webhook processing

    It does NOT provide:
        - Fund transfers
        - Account modifications
        - Any write operations

    All financial data stays on the local cluster.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        secret: Optional[str] = None,
        environment: Optional[str] = None,
    ):
        self._client_id = client_id or PLAID_CLIENT_ID
        self._secret = secret or PLAID_SECRET
        self._env = environment or PLAID_ENV
        self._client = None

        if not self._client_id or not self._secret:
            logger.warning(
                "Plaid credentials not configured. Set PLAID_CLIENT_ID and "
                "PLAID_SECRET environment variables."
            )

    @property
    def client(self):
        """Lazy-initialize the Plaid API client."""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self):
        """Create the Plaid API client instance."""
        try:
            import plaid
            from plaid.api import plaid_api
            from plaid.model.products import Products

            env_map = {
                "sandbox": plaid.Environment.Sandbox,
                "development": plaid.Environment.Development,
                "production": plaid.Environment.Production,
            }

            configuration = plaid.Configuration(
                host=env_map.get(self._env, plaid.Environment.Sandbox),
                api_key={
                    "clientId": self._client_id,
                    "secret": self._secret,
                },
            )

            api_client = plaid.ApiClient(configuration)
            return plaid_api.PlaidApi(api_client)

        except ImportError:
            logger.error(
                "plaid-python not installed. Install with: pip install plaid-python"
            )
            return None

    # =========================================================================
    # READ-ONLY OPERATIONS (Sensory Feed)
    # =========================================================================

    def get_transactions(
        self,
        access_token: str,
        start_date: str,
        end_date: str,
        count: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        Fetch transactions for an access token.

        This is the primary "Observe" input for the OODA loop.

        Args:
            access_token: Plaid access token for the account
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            count: Maximum number of transactions

        Returns:
            List of transaction dicts.
        """
        if not self.client:
            logger.error("Plaid client not initialized")
            return []

        try:
            from plaid.model.transactions_get_request import TransactionsGetRequest
            from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions

            request = TransactionsGetRequest(
                access_token=access_token,
                start_date=date.fromisoformat(start_date),
                end_date=date.fromisoformat(end_date),
                options=TransactionsGetRequestOptions(count=count),
            )

            response = self.client.transactions_get(request)
            transactions = response.to_dict().get("transactions", [])

            logger.info(f"Fetched {len(transactions)} transactions ({start_date} to {end_date})")
            return transactions

        except Exception as e:
            logger.error(f"Failed to fetch transactions: {e}")
            return []

    def get_balances(self, access_token: str) -> List[Dict[str, Any]]:
        """
        Get current account balances.

        Used by the Sovereign's health_monitor for cash flow scoring.
        """
        if not self.client:
            return []

        try:
            from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest

            request = AccountsBalanceGetRequest(access_token=access_token)
            response = self.client.accounts_balance_get(request)
            accounts = response.to_dict().get("accounts", [])

            logger.info(f"Fetched balances for {len(accounts)} accounts")
            return accounts

        except Exception as e:
            logger.error(f"Failed to fetch balances: {e}")
            return []

    def get_investment_holdings(self, access_token: str) -> List[Dict[str, Any]]:
        """
        Get investment holdings (stocks, bonds, etc.).

        Used by Division A for ROI calculations.
        """
        if not self.client:
            return []

        try:
            from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest

            request = InvestmentsHoldingsGetRequest(access_token=access_token)
            response = self.client.investments_holdings_get(request)
            holdings = response.to_dict().get("holdings", [])

            logger.info(f"Fetched {len(holdings)} investment holdings")
            return holdings

        except Exception as e:
            logger.error(f"Failed to fetch investment holdings: {e}")
            return []


# =============================================================================
# WEBHOOK HANDLER
# =============================================================================

class WebhookHandler:
    """
    Plaid Webhook Handler — triggers agents on transaction receipt.

    SOW requirement: "Implement WebhookHandler to trigger agents immediately
    upon transaction receipt."

    Integration:
        - Receives Plaid webhook POST requests (via FastAPI endpoint)
        - Determines which division the transaction belongs to
        - Triggers the appropriate division's OODA loop
    """

    def __init__(self):
        self._handlers: Dict[str, Any] = {}
        logger.info("Plaid WebhookHandler initialized")

    def register_handler(self, webhook_type: str, handler_fn) -> None:
        """Register a handler function for a specific webhook type."""
        self._handlers[webhook_type] = handler_fn
        logger.info(f"Registered webhook handler: {webhook_type}")

    async def process_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process an incoming Plaid webhook.

        Webhook types we handle:
            - TRANSACTIONS: New transactions detected
            - DEFAULT_UPDATE: New transactions available
            - HISTORICAL_UPDATE: Historical transactions ready
            - HOLDINGS: Investment holdings updated

        Args:
            payload: The raw webhook payload from Plaid

        Returns:
            Processing result dict.
        """
        webhook_type = payload.get("webhook_type", "UNKNOWN")
        webhook_code = payload.get("webhook_code", "UNKNOWN")

        logger.info(f"Received webhook: {webhook_type}/{webhook_code}")

        handler = self._handlers.get(webhook_type)
        if handler is None:
            logger.warning(f"No handler registered for webhook type: {webhook_type}")
            return {"status": "unhandled", "type": webhook_type}

        try:
            result = await handler(payload)
            return {"status": "processed", "type": webhook_type, "result": result}
        except Exception as e:
            logger.error(f"Webhook handler failed: {e}")
            return {"status": "error", "type": webhook_type, "error": str(e)}

    def verify_webhook(self, body: bytes, headers: Dict[str, str]) -> bool:
        """
        Verify a Plaid webhook signature.

        SECURITY: Always verify webhooks before processing.
        """
        try:
            from plaid.model.webhook_verification_key_get_request import (
                WebhookVerificationKeyGetRequest,
            )
            # TODO: Implement full JWT verification per Plaid docs
            # For now, log and trust (sandbox only)
            if PLAID_ENV == "sandbox":
                logger.debug("Webhook verification skipped (sandbox mode)")
                return True

            logger.warning("Webhook verification not yet implemented for production")
            return False

        except Exception as e:
            logger.error(f"Webhook verification failed: {e}")
            return False
