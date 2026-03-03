"""
STREAMLINE API — Connectivity Handshake
=========================================
Fortress Prime | Cabin Rentals of Georgia

Streamline VRS has migrated to the Intellistack platform.
  - Legacy API:  webapi.streamlinevrs.com (DEAD — redirects to admin SPA)
  - New API:     api-us.streamline.intellistack.ai/v1/ (PAT Bearer auth)

Your token_key / token_secret credentials are LEGACY format.
The new API requires a Personal Access Token (PAT) from:
    https://us.streamline.intellistack.ai/access-keys

Usage:
    python3 src/bridges/streamline_api_test.py
    python3 src/bridges/streamline_api_test.py --pat <your_new_pat_token>
"""

import os
import sys
import json
import argparse
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LEGACY_TOKEN_KEY = os.getenv("STREAMLINE_TOKEN_KEY", "")
LEGACY_TOKEN_SECRET = os.getenv("STREAMLINE_TOKEN_SECRET", "")
PAT_TOKEN = os.getenv("STREAMLINE_PAT", "")

INTELLISTACK_BASE = "https://api-us.streamline.intellistack.ai/v1"
LEGACY_BASE = "https://webapi.streamlinevrs.com/api/v1"


def test_intellistack(pat: str) -> dict:
    """Test the new Intellistack Streamline API with a PAT token."""
    print(f"\n  Testing Intellistack API...")
    print(f"  URL: {INTELLISTACK_BASE}")
    print(f"  Token: {pat[:8]}{'*' * (len(pat) - 8)}")

    headers = {
        "Authorization": f"Bearer {pat}",
        "Content-Type": "application/json",
    }

    # Test 1: current-user (the documented test endpoint)
    endpoints = [
        ("/current-user", "User Identity"),
        ("/audit-logs", "Audit Logs"),
    ]

    for path, label in endpoints:
        try:
            resp = requests.get(
                f"{INTELLISTACK_BASE}{path}",
                headers=headers,
                timeout=15,
            )
            ct = resp.headers.get("content-type", "")

            if resp.status_code == 200 and "json" in ct:
                data = resp.json()
                print(f"\n  SUCCESS on {path} ({label})")
                print(f"  Response: {json.dumps(data, indent=2, default=str)[:1000]}")
                return {"status": "CONNECTED", "endpoint": path, "data": data}
            elif resp.status_code == 200:
                print(f"  {path}: 200 but not JSON (CT: {ct})")
            elif resp.status_code == 401:
                print(f"  {path}: 401 Unauthorized — token rejected")
            elif resp.status_code == 403:
                print(f"  {path}: 403 Forbidden — token lacks permissions or wrong format")
            else:
                print(f"  {path}: {resp.status_code}")
                body = resp.text[:200]
                if body and "html" not in body.lower():
                    print(f"    Body: {body}")

        except requests.exceptions.ConnectionError:
            print(f"  {path}: Connection failed")
        except requests.exceptions.Timeout:
            print(f"  {path}: Timeout")
        except Exception as e:
            print(f"  {path}: {e}")

    return {"status": "FAILED"}


def test_legacy() -> dict:
    """Test the legacy Streamline VRS API (likely deprecated)."""
    print(f"\n  Testing Legacy API...")
    print(f"  URL: {LEGACY_BASE}")
    print(f"  Token Key: {LEGACY_TOKEN_KEY[:5]}***")

    # Try various auth methods against legacy endpoint
    methods = [
        ("Headers", {"X-Streamline-Token": LEGACY_TOKEN_KEY,
                      "X-Streamline-Secret": LEGACY_TOKEN_SECRET}),
        ("Bearer-Key", {"Authorization": f"Bearer {LEGACY_TOKEN_KEY}"}),
        ("Bearer-Secret", {"Authorization": f"Bearer {LEGACY_TOKEN_SECRET}"}),
    ]

    for name, headers in methods:
        try:
            resp = requests.get(
                f"{LEGACY_BASE}/properties",
                headers={**headers, "Content-Type": "application/json"},
                timeout=10,
            )
            ct = resp.headers.get("content-type", "")

            if resp.status_code == 200 and "json" in ct:
                data = resp.json()
                print(f"\n  SUCCESS with {name} auth!")
                print(f"  Response: {json.dumps(data, indent=2, default=str)[:1000]}")
                return {"status": "CONNECTED", "method": name, "data": data}
            elif "html" in ct:
                print(f"  {name}: Got HTML (admin SPA redirect) — legacy API is dead")
                break  # No point trying more methods against the same dead endpoint
            else:
                print(f"  {name}: {resp.status_code} {ct}")

        except Exception as e:
            print(f"  {name}: {e}")

    return {"status": "FAILED", "reason": "Legacy API retired — redirects to admin SPA"}


def main():
    parser = argparse.ArgumentParser(description="Streamline API Handshake")
    parser.add_argument("--pat", type=str, help="Personal Access Token for Intellistack API")
    args = parser.parse_args()

    print("=" * 64)
    print("  STREAMLINE API — HANDSHAKE REPORT")
    print("=" * 64)

    # Determine which token to use
    pat = args.pat or PAT_TOKEN

    # Test 1: Legacy API
    print("\n  [1/2] LEGACY API (webapi.streamlinevrs.com)")
    legacy_result = test_legacy()

    # Test 2: Intellistack API
    print("\n  [2/2] INTELLISTACK API (api-us.streamline.intellistack.ai)")
    if pat:
        intel_result = test_intellistack(pat)
    else:
        print("\n  SKIPPED — No PAT token available.")
        print("  To test, either:")
        print("    1. Set STREAMLINE_PAT in .env")
        print("    2. Run: python3 src/bridges/streamline_api_test.py --pat <token>")
        intel_result = {"status": "SKIPPED"}

    # Verdict
    print("\n" + "=" * 64)
    print("  VERDICT")
    print("=" * 64)

    if legacy_result["status"] == "CONNECTED":
        print("  Legacy API: CONNECTED (surprising — should be deprecated)")
        print("  Action: Use legacy endpoints for now, plan migration")
    elif intel_result.get("status") == "CONNECTED":
        print("  Intellistack API: CONNECTED")
        print("  Action: Ready to pull properties and reservations")
    else:
        print("  Both APIs: NOT CONNECTED")
        print()
        print("  DIAGNOSIS:")
        print("    The legacy Streamline API (webapi.streamlinevrs.com) has been")
        print("    retired and now redirects to the Intellistack admin SPA.")
        print()
        print("    Your token_key/token_secret credentials are LEGACY format.")
        print("    The new API requires a Personal Access Token (PAT).")
        print()
        print("  NEXT STEPS:")
        print("    1. Log into: https://us.streamline.intellistack.ai/access-keys")
        print("    2. Click 'Generate Token'")
        print("    3. Copy the token IMMEDIATELY (shown only once)")
        print("    4. Add to .env:  STREAMLINE_PAT=<your_new_token>")
        print("    5. Re-run: python3 src/bridges/streamline_api_test.py")
        print()
        print("  ALTERNATIVE (no API needed):")
        print("    1. Log into Streamline VRS web interface")
        print("    2. Reports → Nightly Audit or Owner Statement")
        print("    3. Export as CSV")
        print("    4. Upload to: /mnt/fortress_nas/Financial_Ledger/Streamline_Exports/")
        print("    5. Run: python3 src/bridges/streamline_ingest.py --detect <file.csv>")

    print("=" * 64)


if __name__ == "__main__":
    main()
