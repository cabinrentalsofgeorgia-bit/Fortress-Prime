"""
QuickBooks OAuth2 — Token Lifecycle Manager
==============================================
Handles the complete OAuth2 lifecycle for QBO API access:

    1. Generate authorization URL (user clicks → Intuit login)
    2. Exchange authorization code for tokens (callback)
    3. Refresh expired access tokens (automatic)
    4. Persist tokens securely on NAS
    5. Revoke tokens (when we cancel QBO)

Token storage:
    Tokens are stored as JSON on the NAS at:
    /mnt/fortress_nas/fortress_data/ai_brain/secrets/qbo_tokens.json

    This file is NEVER committed to git. The NAS is encrypted at rest.

OAuth2 Flow:
    1. Call get_auth_url() → redirect user to Intuit
    2. User authorizes → Intuit redirects to callback with ?code=...&realmId=...
    3. Call exchange_code(code, realm_id) → stores tokens
    4. Call get_client() → returns authenticated session (auto-refreshes)

Module: CF-04 Treasury / Operation Strangler Fig
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("integrations.quickbooks.auth")

# =============================================================================
# CONFIGURATION
# =============================================================================

QBO_CLIENT_ID = os.getenv("QBO_CLIENT_ID", "")
QBO_CLIENT_SECRET = os.getenv("QBO_CLIENT_SECRET", "")

# Build default redirect URI from Cloudflare config (single source of truth)
try:
    from config import PUBLIC_DASHBOARD_URL as _dash_url
    _default_qbo_redirect = f"{_dash_url}/qbo/callback"
except ImportError:
    _default_qbo_redirect = "https://fortress.crog-ai.com/qbo/callback"

QBO_REDIRECT_URI = os.getenv("QBO_REDIRECT_URI", _default_qbo_redirect)
QBO_ENVIRONMENT = os.getenv("QBO_ENVIRONMENT", "production")
QBO_REALM_ID = os.getenv("QBO_REALM_ID", "")

# Intuit OAuth2 endpoints
AUTHORIZATION_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"
USERINFO_URL = "https://accounts.platform.intuit.com/v1/openid_connect/userinfo"

# QBO API base URLs
API_BASE_URLS = {
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
    "production": "https://quickbooks.api.intuit.com",
}

# Scopes
ACCOUNTING_SCOPE = "com.intuit.quickbooks.accounting"
OPENID_SCOPES = "openid profile email phone address"

# Token storage
TOKEN_DIR = "/mnt/fortress_nas/fortress_data/ai_brain/secrets"
TOKEN_FILE = os.path.join(TOKEN_DIR, "qbo_tokens.json")

# Fallback token storage (if NAS not mounted)
LOCAL_TOKEN_DIR = os.path.expanduser("~/.fortress/secrets")
LOCAL_TOKEN_FILE = os.path.join(LOCAL_TOKEN_DIR, "qbo_tokens.json")


# =============================================================================
# TOKEN STORAGE
# =============================================================================

def _get_token_path() -> str:
    """Determine where to store tokens (NAS first, local fallback)."""
    if os.path.isdir(os.path.dirname(TOKEN_FILE)):
        return TOKEN_FILE
    else:
        logger.warning(
            f"NAS path not available ({TOKEN_DIR}), "
            f"falling back to {LOCAL_TOKEN_FILE}"
        )
        return LOCAL_TOKEN_FILE


def save_tokens(token_data: Dict[str, Any]) -> str:
    """
    Persist OAuth tokens to secure storage.

    Args:
        token_data: Dict containing access_token, refresh_token, realm_id, etc.

    Returns:
        Path where tokens were saved.
    """
    token_path = _get_token_path()
    os.makedirs(os.path.dirname(token_path), exist_ok=True)

    # Add metadata
    token_data["saved_at"] = datetime.now(timezone.utc).isoformat()
    token_data["saved_by"] = "fortress_qbo_auth"

    # Calculate expiry timestamps
    if "expires_in" in token_data and "expires_at" not in token_data:
        token_data["expires_at"] = time.time() + token_data["expires_in"]
    if "x_refresh_token_expires_in" in token_data and "refresh_expires_at" not in token_data:
        token_data["refresh_expires_at"] = (
            time.time() + token_data["x_refresh_token_expires_in"]
        )

    with open(token_path, "w") as f:
        json.dump(token_data, f, indent=2)

    # Restrict file permissions (owner read/write only)
    os.chmod(token_path, 0o600)

    logger.info(f"QBO tokens saved to {token_path}")
    return token_path


def load_tokens() -> Optional[Dict[str, Any]]:
    """
    Load stored OAuth tokens.

    Returns:
        Token dict, or None if no tokens stored.
    """
    token_path = _get_token_path()

    if not os.path.exists(token_path):
        logger.info("No stored QBO tokens found")
        return None

    try:
        with open(token_path, "r") as f:
            data = json.load(f)
        logger.info(
            f"Loaded QBO tokens (realm_id={data.get('realm_id', '?')}, "
            f"saved_at={data.get('saved_at', '?')})"
        )
        return data
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load QBO tokens: {e}")
        return None


def clear_tokens() -> bool:
    """Delete stored tokens (for re-authorization or revocation)."""
    token_path = _get_token_path()
    if os.path.exists(token_path):
        os.remove(token_path)
        logger.info(f"QBO tokens cleared from {token_path}")
        return True
    return False


# =============================================================================
# OAUTH2 FLOW
# =============================================================================

def get_auth_url(state: str = "fortress_strangler_fig") -> str:
    """
    Generate the Intuit OAuth2 authorization URL.

    The user must open this URL in a browser, log into their
    QBO account, and authorize the Fortress app. Intuit will
    redirect to our callback URL with an authorization code.

    Args:
        state: CSRF protection token (should be random in production)

    Returns:
        Full authorization URL to redirect the user to.
    """
    if not QBO_CLIENT_ID:
        raise ValueError(
            "QBO_CLIENT_ID not set. Add it to .env file."
        )

    params = {
        "client_id": QBO_CLIENT_ID,
        "redirect_uri": QBO_REDIRECT_URI,
        "response_type": "code",
        "scope": ACCOUNTING_SCOPE,
        "state": state,
    }

    url = f"{AUTHORIZATION_URL}?{urlencode(params)}"
    logger.info(f"Generated QBO auth URL (redirect_uri={QBO_REDIRECT_URI})")
    return url


def exchange_code(
    authorization_code: str,
    realm_id: str,
) -> Dict[str, Any]:
    """
    Exchange an authorization code for access + refresh tokens.

    Called from the OAuth callback endpoint after the user authorizes.

    Args:
        authorization_code: The code from the callback URL parameter
        realm_id: The QBO company ID from the callback URL parameter

    Returns:
        Token dict with access_token, refresh_token, realm_id, etc.

    Raises:
        requests.HTTPError: If Intuit rejects the code.
    """
    if not QBO_CLIENT_ID or not QBO_CLIENT_SECRET:
        raise ValueError(
            "QBO_CLIENT_ID and QBO_CLIENT_SECRET must be set in .env"
        )

    payload = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": QBO_REDIRECT_URI,
    }

    resp = requests.post(
        TOKEN_URL,
        data=payload,
        auth=(QBO_CLIENT_ID, QBO_CLIENT_SECRET),
        headers={"Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()

    token_data = resp.json()
    token_data["realm_id"] = realm_id

    # Save immediately
    save_tokens(token_data)

    logger.info(
        f"QBO tokens obtained for realm_id={realm_id} "
        f"(access expires in {token_data.get('expires_in', '?')}s, "
        f"refresh expires in {token_data.get('x_refresh_token_expires_in', '?')}s)"
    )
    return token_data


def refresh_access_token(
    refresh_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Refresh an expired access token using the refresh token.

    QBO access tokens expire every 60 minutes.
    Refresh tokens last 100 days.

    Args:
        refresh_token: The refresh token. If None, loads from storage.

    Returns:
        Updated token dict.

    Raises:
        ValueError: If no refresh token is available.
        requests.HTTPError: If Intuit rejects the refresh.
    """
    if not refresh_token:
        stored = load_tokens()
        if not stored or "refresh_token" not in stored:
            raise ValueError(
                "No refresh token available. Re-authorize at: "
                + get_auth_url()
            )
        refresh_token = stored["refresh_token"]
        realm_id = stored.get("realm_id", "")
    else:
        stored = load_tokens()
        realm_id = stored.get("realm_id", "") if stored else ""

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    resp = requests.post(
        TOKEN_URL,
        data=payload,
        auth=(QBO_CLIENT_ID, QBO_CLIENT_SECRET),
        headers={"Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()

    token_data = resp.json()
    token_data["realm_id"] = realm_id

    # Save updated tokens
    save_tokens(token_data)

    logger.info("QBO access token refreshed successfully")
    return token_data


def revoke_tokens(token: Optional[str] = None) -> bool:
    """
    Revoke a QBO token (access or refresh).

    Call this when we cancel QBO (Phase 4 of Strangler Fig).

    Args:
        token: The token to revoke. If None, revokes the refresh token.

    Returns:
        True if revocation succeeded.
    """
    if not token:
        stored = load_tokens()
        if not stored:
            logger.warning("No tokens to revoke")
            return False
        token = stored.get("refresh_token", stored.get("access_token"))

    if not token:
        return False

    payload = {"token": token}

    try:
        resp = requests.post(
            REVOKE_URL,
            data=payload,
            auth=(QBO_CLIENT_ID, QBO_CLIENT_SECRET),
            headers={"Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        clear_tokens()
        logger.info("QBO tokens revoked and cleared")
        return True
    except Exception as e:
        logger.error(f"Token revocation failed: {e}")
        return False


# =============================================================================
# AUTHENTICATED SESSION
# =============================================================================

def is_token_expired(token_data: Optional[Dict] = None) -> bool:
    """Check if the access token has expired (with 5-minute buffer)."""
    if not token_data:
        token_data = load_tokens()
    if not token_data:
        return True

    expires_at = token_data.get("expires_at", 0)
    return time.time() > (expires_at - 300)  # 5 min buffer


def get_valid_tokens() -> Dict[str, Any]:
    """
    Get valid (non-expired) tokens, refreshing if necessary.

    Returns:
        Token dict with a valid access_token.

    Raises:
        ValueError: If no tokens available and can't refresh.
    """
    tokens = load_tokens()
    if not tokens:
        raise ValueError(
            "No QBO tokens found. Authorize first:\n"
            f"  {get_auth_url()}"
        )

    if is_token_expired(tokens):
        logger.info("QBO access token expired, refreshing...")
        tokens = refresh_access_token(tokens.get("refresh_token"))

    return tokens


def get_api_base_url() -> str:
    """Get the QBO API base URL for the configured environment."""
    return API_BASE_URLS.get(QBO_ENVIRONMENT, API_BASE_URLS["production"])


def get_auth_header() -> Dict[str, str]:
    """
    Get an Authorization header with a valid access token.

    Auto-refreshes if expired.

    Returns:
        {"Authorization": "Bearer <access_token>"}
    """
    tokens = get_valid_tokens()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def get_realm_id() -> str:
    """Get the stored QBO company (realm) ID."""
    # Check environment variable first (useful for sandbox)
    if QBO_REALM_ID:
        return QBO_REALM_ID
    tokens = load_tokens()
    if not tokens or "realm_id" not in tokens:
        raise ValueError("No QBO realm_id stored. Authorize first.")
    return tokens["realm_id"]


# =============================================================================
# STATUS
# =============================================================================

def get_status() -> Dict[str, Any]:
    """
    Get the current QBO connection status.

    Returns:
        {
            "connected": bool,
            "realm_id": str,
            "environment": str,
            "token_expired": bool,
            "refresh_expires_at": str,
            "saved_at": str,
        }
    """
    tokens = load_tokens()

    if not tokens:
        return {
            "connected": False,
            "environment": QBO_ENVIRONMENT,
            "message": "Not authorized. Run auth flow first.",
            "auth_url": get_auth_url() if QBO_CLIENT_ID else "QBO_CLIENT_ID not set",
        }

    expired = is_token_expired(tokens)
    refresh_expires = tokens.get("refresh_expires_at", 0)
    refresh_expired = time.time() > refresh_expires if refresh_expires else True

    return {
        "connected": not refresh_expired,
        "realm_id": tokens.get("realm_id", "unknown"),
        "environment": QBO_ENVIRONMENT,
        "access_token_expired": expired,
        "refresh_token_valid": not refresh_expired,
        "saved_at": tokens.get("saved_at", "unknown"),
        "can_auto_refresh": expired and not refresh_expired,
    }


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="QBO OAuth2 — Token Lifecycle Manager",
    )
    parser.add_argument(
        "--authorize", action="store_true",
        help="Generate the authorization URL",
    )
    parser.add_argument(
        "--callback", nargs=2, metavar=("CODE", "REALM_ID"),
        help="Exchange authorization code for tokens",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Refresh the access token",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Check connection status",
    )
    parser.add_argument(
        "--revoke", action="store_true",
        help="Revoke tokens and disconnect",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [QBO AUTH] %(message)s",
    )

    if args.authorize:
        url = get_auth_url()
        print(f"\n{'='*70}")
        print(f"  QUICKBOOKS ONLINE — Authorization")
        print(f"{'='*70}")
        print(f"\n  Open this URL in your browser:\n")
        print(f"  {url}\n")
        print(f"  After authorizing, you'll be redirected to:")
        print(f"  {QBO_REDIRECT_URI}?code=...&realmId=...\n")
        print(f"  Then run:")
        print(f"  python -m integrations.quickbooks.auth "
              f"--callback <CODE> <REALM_ID>")
        print(f"\n{'='*70}\n")

    elif args.callback:
        code, realm_id = args.callback
        print(f"\n  Exchanging authorization code...")
        try:
            tokens = exchange_code(code, realm_id)
            print(f"  SUCCESS! Connected to QBO.")
            print(f"  Realm ID:       {realm_id}")
            print(f"  Access expires:  {tokens.get('expires_in', '?')} seconds")
            print(f"  Refresh expires: "
                  f"{tokens.get('x_refresh_token_expires_in', '?')} seconds")
        except Exception as e:
            print(f"  FAILED: {e}")

    elif args.refresh:
        try:
            tokens = refresh_access_token()
            print(f"  Access token refreshed successfully.")
        except Exception as e:
            print(f"  Refresh failed: {e}")

    elif args.status:
        status = get_status()
        print(f"\n{'='*60}")
        print(f"  QBO CONNECTION STATUS")
        print(f"{'='*60}")
        for k, v in status.items():
            print(f"  {k:30s}  {v}")
        print(f"{'='*60}\n")

    elif args.revoke:
        ok = revoke_tokens()
        print(f"  Revocation: {'SUCCESS' if ok else 'FAILED'}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
