#!/usr/bin/env python3
"""
QBO OAuth2 — One-Shot Token Capture Server
=============================================
Temporary local server that handles the full OAuth2 flow:
    1. Opens the Intuit authorization URL
    2. Catches the callback with the auth code
    3. Exchanges the code for tokens INSTANTLY (before expiry)
    4. Saves tokens to NAS
    5. Shuts down

Usage:
    python3 tools/qbo_auth_server.py

    Then open the printed URL in your browser.
    After authorizing, tokens are saved automatically.
"""

import json
import os
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode

import requests

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

# Configuration
CLIENT_ID = os.getenv("QBO_CLIENT_ID")
CLIENT_SECRET = os.getenv("QBO_CLIENT_SECRET")
REALM_ID = os.getenv("QBO_REALM_ID", "9341456362983434")
ENVIRONMENT = os.getenv("QBO_ENVIRONMENT", "sandbox")

# This server's port — pick something not in use
PORT = 9876
REDIRECT_URI = f"http://localhost:{PORT}/callback"

TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
TOKEN_PATH = "/mnt/fortress_nas/fortress_data/ai_brain/secrets/qbo_tokens.json"
LOCAL_TOKEN_PATH = os.path.expanduser("~/.fortress/secrets/qbo_tokens.json")


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth2 callback and exchanges the code for tokens."""

    success = False
    tokens = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        # Check for errors
        if "error" in params:
            error = params["error"][0]
            desc = params.get("error_description", [""])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"<html><body><h1>Authorization Failed</h1>"
                f"<p>{error}: {desc}</p></body></html>".encode()
            )
            print(f"\n  FAILED: {error} — {desc}")
            return

        # Get the authorization code
        code = params.get("code", [None])[0]
        realm_id = params.get("realmId", [REALM_ID])[0]

        if not code:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Missing auth code</h1></body></html>")
            return

        print(f"\n  Got auth code: {code[:20]}...")
        print(f"  Realm ID:      {realm_id}")
        print(f"  Exchanging for tokens...")

        # Exchange IMMEDIATELY
        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                },
                auth=(CLIENT_ID, CLIENT_SECRET),
                headers={"Accept": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()

            token_data = resp.json()
            token_data["realm_id"] = realm_id
            token_data["expires_at"] = time.time() + token_data.get("expires_in", 3600)
            token_data["refresh_expires_at"] = (
                time.time() + token_data.get("x_refresh_token_expires_in", 8726400)
            )
            token_data["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            token_data["saved_by"] = "fortress_qbo_auth"
            token_data["environment"] = ENVIRONMENT

            # Save tokens
            save_path = TOKEN_PATH
            try:
                os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
                with open(TOKEN_PATH, "w") as f:
                    json.dump(token_data, f, indent=2)
                os.chmod(TOKEN_PATH, 0o600)
            except OSError:
                save_path = LOCAL_TOKEN_PATH
                os.makedirs(os.path.dirname(LOCAL_TOKEN_PATH), exist_ok=True)
                with open(LOCAL_TOKEN_PATH, "w") as f:
                    json.dump(token_data, f, indent=2)
                os.chmod(LOCAL_TOKEN_PATH, 0o600)

            OAuthCallbackHandler.success = True
            OAuthCallbackHandler.tokens = token_data

            # Success response
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"<html><body style='font-family:monospace;background:#1a1a2e;color:#0f0;padding:40px'>"
                f"<h1>FORTRESS PRIME — QBO CONNECTED</h1>"
                f"<p>Realm ID: {realm_id}</p>"
                f"<p>Environment: {ENVIRONMENT}</p>"
                f"<p>Access token expires in: {token_data.get('expires_in')}s</p>"
                f"<p>Refresh token expires in: {token_data.get('x_refresh_token_expires_in')}s</p>"
                f"<p>Saved to: {save_path}</p>"
                f"<br><p><b>You can close this tab.</b></p>"
                f"</body></html>".encode()
            )

            print(f"\n  {'='*60}")
            print(f"  SUCCESS — QBO TOKENS ACQUIRED")
            print(f"  {'='*60}")
            print(f"  Realm ID:           {realm_id}")
            print(f"  Environment:        {ENVIRONMENT}")
            print(f"  Access expires in:  {token_data.get('expires_in')}s")
            print(f"  Refresh expires in: {token_data.get('x_refresh_token_expires_in')}s")
            print(f"  Saved to:           {save_path}")
            print(f"  {'='*60}")

            # Schedule shutdown
            threading.Timer(1.0, self.server.shutdown).start()

        except requests.exceptions.HTTPError as e:
            error_body = ""
            try:
                error_body = resp.text[:500]
            except Exception:
                pass
            self.send_response(500)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"<html><body><h1>Token Exchange Failed</h1>"
                f"<p>{e}</p><pre>{error_body}</pre></body></html>".encode()
            )
            print(f"\n  TOKEN EXCHANGE FAILED: {e}")
            print(f"  Body: {error_body}")

            # Shutdown anyway
            threading.Timer(1.0, self.server.shutdown).start()

    def log_message(self, format, *args):
        pass  # Suppress default HTTP logs


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: QBO_CLIENT_ID and QBO_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    # IMPORTANT: This redirect_uri must be registered in the Intuit Developer Portal
    # Go to: https://developer.intuit.com → Your App → Keys & credentials
    # Add this redirect URI: http://localhost:9876/callback
    auth_params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting",
        "state": "fortress_strangler_fig",
    }
    auth_url = f"https://appcenter.intuit.com/connect/oauth2?{urlencode(auth_params)}"

    print(f"\n{'='*70}")
    print(f"  QBO OAuth2 — One-Shot Token Capture")
    print(f"  Environment: {ENVIRONMENT}")
    print(f"  Realm ID:    {REALM_ID}")
    print(f"{'='*70}")
    print(f"\n  STEP 1: Add this Redirect URI to your Intuit app settings:")
    print(f"          {REDIRECT_URI}")
    print(f"\n  STEP 2: Open this URL in your browser:\n")
    print(f"  {auth_url}")
    print(f"\n  Waiting for callback on port {PORT}...")
    print(f"  (The server will shut down automatically after token capture)")
    print()

    server = HTTPServer(("0.0.0.0", PORT), OAuthCallbackHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Cancelled.")
    finally:
        server.server_close()

    if OAuthCallbackHandler.success:
        print("\n  The Strangler Fig has eyes into QBO. Connection alive.\n")
    else:
        print("\n  No tokens captured. Try again.\n")


if __name__ == "__main__":
    main()
