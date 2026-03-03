"""
Fortress Prime — Gmail API Authentication
============================================
Handles OAuth2 credential setup, token persistence, and scope verification
for the Gmail Watcher service.

SETUP (one-time):
    1. Go to https://console.cloud.google.com/
    2. Create a project (or use existing "Fortress Prime")
    3. Enable the Gmail API
    4. Create OAuth 2.0 credentials (Desktop Application)
    5. Download the JSON file -> save as credentials/gmail_credentials.json
    6. Run: python -m src.gmail_auth
       This opens a browser for consent -> saves credentials/gmail_token.json

SCOPES (least-privilege):
    gmail.readonly  — Read email messages and metadata
    gmail.compose   — Create draft replies (NEVER sends)
    gmail.labels    — Create and manage labels
    gmail.modify    — Apply labels to messages, mark as read

    EXPLICITLY EXCLUDED:
    gmail.send      — We do NOT request send permission. Drafts only.
    mail.google.com — Full access. Never needed.

FILES:
    credentials/gmail_credentials.json  — OAuth client config (from Google Console)
    credentials/gmail_token.json        — Persisted access/refresh token (auto-generated)

Usage:
    from src.gmail_auth import get_gmail_service

    service = get_gmail_service()
    # service is a googleapiclient.discovery.Resource for Gmail API v1
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"
CREDENTIALS_FILE = CREDENTIALS_DIR / "gmail_credentials.json"
TOKEN_FILE = CREDENTIALS_DIR / "gmail_token.json"

# =============================================================================
# SCOPES — Intentionally narrow. NO send permission.
# =============================================================================

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",    # Read emails
    "https://www.googleapis.com/auth/gmail.compose",     # Create drafts (not send)
    "https://www.googleapis.com/auth/gmail.labels",      # Manage labels
    "https://www.googleapis.com/auth/gmail.modify",      # Apply labels to threads
]


def get_gmail_service():
    """
    Authenticate and return a Gmail API service object.

    On first run, opens a browser for OAuth2 consent.
    Subsequent runs use the cached token.

    Returns:
        googleapiclient.discovery.Resource: Gmail API v1 service.

    Raises:
        FileNotFoundError: If credentials file is missing.
        ImportError: If google-api-python-client is not installed.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("ERROR: Gmail API dependencies not installed.")
        print("Run:   pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")
        sys.exit(1)

    # Ensure credentials directory exists
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

    if not CREDENTIALS_FILE.exists():
        print("=" * 60)
        print("  GMAIL SETUP REQUIRED")
        print("=" * 60)
        print(f"\n  Missing: {CREDENTIALS_FILE}")
        print()
        print("  Steps:")
        print("  1. Go to https://console.cloud.google.com/")
        print("  2. Create/select a project")
        print("  3. Enable the 'Gmail API'")
        print("  4. Go to APIs & Services > Credentials")
        print("  5. Create OAuth 2.0 Client ID (Desktop Application)")
        print("  6. Download the JSON file")
        print(f"  7. Save it as: {CREDENTIALS_FILE}")
        print("  8. Re-run this script")
        print(f"\n{'=' * 60}")
        raise FileNotFoundError(f"Gmail credentials not found: {CREDENTIALS_FILE}")

    creds = None

    # Load existing token
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    # Refresh or re-authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                print("[AUTH] Token refreshed successfully.")
            except Exception as e:
                print(f"[AUTH] Token refresh failed: {e}")
                print("[AUTH] Re-authenticating...")
                creds = None

        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)
            print("[AUTH] Authentication successful.")

        # Save token for next run
        with open(TOKEN_FILE, "w") as token_file:
            token_file.write(creds.to_json())
            print(f"[AUTH] Token saved to {TOKEN_FILE}")

    service = build("gmail", "v1", credentials=creds)
    return service


def verify_scopes():
    """
    Verify that the current token has the correct scopes.
    Useful for auditing what permissions the watcher has.
    """
    try:
        from google.oauth2.credentials import Credentials
    except ImportError:
        print("google-auth not installed.")
        return

    if not TOKEN_FILE.exists():
        print("No token file found. Run authentication first.")
        return

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE))

    print("=" * 60)
    print("  GMAIL API — SCOPE VERIFICATION")
    print("=" * 60)
    print(f"\n  Token file: {TOKEN_FILE}")
    print(f"  Valid:      {creds.valid}")
    print(f"  Expired:    {creds.expired}")

    print(f"\n  GRANTED SCOPES:")
    if creds.scopes:
        for scope in sorted(creds.scopes):
            short = scope.replace("https://www.googleapis.com/auth/", "")
            # Safety check
            danger = ""
            if "send" in short:
                danger = " *** DANGER — SEND PERMISSION ***"
            elif "mail.google.com" in scope:
                danger = " *** DANGER — FULL ACCESS ***"
            print(f"    {short}{danger}")
    else:
        print("    (scopes not stored in token — normal for some flows)")

    # Check for dangerous scopes
    dangerous = [
        "https://www.googleapis.com/auth/gmail.send",
        "https://mail.google.com/",
    ]
    if creds.scopes:
        found_dangerous = [s for s in dangerous if s in creds.scopes]
        if found_dangerous:
            print(f"\n  *** WARNING: Dangerous scopes detected! ***")
            print(f"  Delete {TOKEN_FILE} and re-authenticate with narrower scopes.")
        else:
            print(f"\n  SAFE: No send or full-access permissions granted.")

    print(f"\n{'=' * 60}")


# =============================================================================
# CLI: python -m src.gmail_auth
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fortress Prime — Gmail Auth Setup")
    parser.add_argument("--verify", action="store_true", help="Verify current token scopes")
    parser.add_argument("--revoke", action="store_true", help="Delete saved token (re-auth needed)")
    args = parser.parse_args()

    if args.verify:
        verify_scopes()
    elif args.revoke:
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
            print(f"Token deleted: {TOKEN_FILE}")
            print("Re-run without --revoke to re-authenticate.")
        else:
            print("No token file to delete.")
    else:
        print("Authenticating with Gmail API...")
        service = get_gmail_service()
        # Quick verification
        profile = service.users().getProfile(userId="me").execute()
        print(f"\n  Authenticated as: {profile.get('emailAddress', 'unknown')}")
        print(f"  Messages total:   {profile.get('messagesTotal', 'unknown')}")
        print(f"  Threads total:    {profile.get('threadsTotal', 'unknown')}")
        print(f"\n  Gmail Watcher is ready to connect.")
        verify_scopes()
