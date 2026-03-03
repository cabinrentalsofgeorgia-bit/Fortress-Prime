"""
STREAMLINE VRS — Legacy PHP SDK Clone (Python)
================================================
Fortress Prime | Cabin Rentals of Georgia

This replicates the EXACT request format from Streamline's PHP SDK:
  - POST to /api/json
  - Body: {"methodName": "...", "params": {"token_key": "...", "token_secret": "..."}}

This is NOT REST, NOT JSON-RPC. It's Streamline's custom RPC format.

Usage:
    python3 src/bridges/streamline_legacy_connect.py
"""

import os
import sys
import json
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Credentials from .env (never hardcoded in source)
# ---------------------------------------------------------------------------
TOKEN_KEY = os.getenv("STREAMLINE_TOKEN_KEY", "")
TOKEN_SECRET = os.getenv("STREAMLINE_TOKEN_SECRET", "")

# ---------------------------------------------------------------------------
# Known Streamline PHP SDK endpoints (try all 3)
# ---------------------------------------------------------------------------
ENDPOINTS = [
    "https://web.streamlinevrs.com/api/json",
    "https://web.streamlinevrs.com/api/v1/json",
    "https://api.streamlinevrs.com/api/json",
]


def call_streamline_api(method_name: str, extra_params: dict = None) -> dict:
    """
    Call the Streamline API using the exact PHP SDK format.

    The PHP SDK builds this payload:
        {
            "methodName": "GetPropertyList",
            "params": {
                "token_key": "...",
                "token_secret": "...",
                "status_id": 1
            }
        }
    """
    if extra_params is None:
        extra_params = {}

    # Build params block (exactly like PHP SDK)
    params = {
        "token_key": TOKEN_KEY,
        "token_secret": TOKEN_SECRET,
    }
    params.update(extra_params)

    # Build the body
    payload = {
        "methodName": method_name,
        "params": params,
    }

    headers = {"Content-Type": "application/json"}

    print(f"\n  Calling: {method_name}")

    for url in ENDPOINTS:
        try:
            print(f"    -> {url} ...", end="", flush=True)
            response = requests.post(url, json=payload, headers=headers, timeout=15)

            ct = response.headers.get("content-type", "")

            if response.status_code == 200 and "json" in ct:
                print(f" CONNECTED! (200 JSON)")
                return {"status": "success", "url": url, "data": response.json()}

            elif response.status_code == 200 and "html" in ct:
                print(f" HTML (admin SPA redirect)")

            elif response.status_code == 403:
                print(f" 403 Forbidden (IP not whitelisted?)")
                # 403 means the endpoint EXISTS but we're blocked
                return {"status": "forbidden", "url": url, "code": 403}

            elif response.status_code == 401:
                print(f" 401 Unauthorized (bad credentials)")
                return {"status": "unauthorized", "url": url, "code": 401}

            elif response.status_code == 404:
                print(f" 404 Not Found")

            elif response.status_code == 405:
                print(f" 405 Method Not Allowed (endpoint exists, wrong HTTP method?)")

            else:
                body_preview = response.text[:200].replace("\n", " ")
                is_html = "<html" in body_preview.lower()
                if is_html:
                    print(f" {response.status_code} (HTML)")
                else:
                    print(f" {response.status_code}")
                    print(f"      Body: {body_preview}")

        except requests.exceptions.ConnectionError:
            print(f" Connection refused")
        except requests.exceptions.Timeout:
            print(f" Timeout (15s)")
        except Exception as e:
            print(f" Error: {e}")

    return {"status": "failed", "reason": "All endpoints exhausted"}


def main():
    print("=" * 64)
    print("  STREAMLINE VRS — PHP SDK CLONE — CONNECTIVITY TEST")
    print("=" * 64)

    if not TOKEN_KEY or not TOKEN_SECRET:
        print("\n  ERROR: Missing STREAMLINE_TOKEN_KEY or STREAMLINE_TOKEN_SECRET")
        sys.exit(1)

    print(f"\n  Token Key:    {TOKEN_KEY[:8]}...{TOKEN_KEY[-4:]}")
    print(f"  Token Secret: {TOKEN_SECRET[:8]}...{TOKEN_SECRET[-4:]}")

    # ----- Test 1: GetPropertyList (the standard PHP SDK test) -----
    print("\n  " + "-" * 56)
    print("  TEST 1: GetPropertyList (status_id=1 → Active properties)")
    print("  " + "-" * 56)

    result = call_streamline_api("GetPropertyList", {"status_id": 1})

    if result["status"] == "success":
        data = result["data"]
        # Streamline returns vary — could be list, dict with 'data', etc.
        if isinstance(data, list):
            properties = data
        elif isinstance(data, dict):
            properties = data.get("data", data.get("properties", data.get("result", [])))
            if isinstance(properties, dict):
                properties = [properties]
            # Check for error response
            if "error" in data or "fault" in data:
                error_msg = data.get("error", data.get("fault", "Unknown error"))
                print(f"\n  AUTH SUCCEEDED but method returned error:")
                print(f"    {error_msg}")
                print(f"\n  This means credentials are VALID. Trying other methods...")
                properties = []
        else:
            properties = []

        if properties and len(properties) > 0:
            print(f"\n  SUCCESS! Found {len(properties)} active properties.")
            print(f"\n  --- PROPERTY LIST ---")
            for i, prop in enumerate(properties[:25]):
                name = (prop.get("name") or prop.get("property_name")
                        or prop.get("unit_name") or prop.get("title") or "Unknown")
                pid = (prop.get("id") or prop.get("property_id")
                       or prop.get("unit_id") or "?")
                print(f"    {i+1:3d}. {name} (ID: {pid})")

            if len(properties) > 25:
                print(f"    ... and {len(properties) - 25} more")

            # Dump full structure of first property
            print(f"\n  --- FIRST PROPERTY (full data shape) ---")
            print(f"  {json.dumps(properties[0], indent=4, default=str)[:2000]}")

        elif not properties:
            # Method might be wrong — try alternatives
            _try_alternative_methods()

    elif result["status"] == "forbidden":
        print(f"\n  ENDPOINT IS ALIVE but returned 403 Forbidden.")
        print(f"  URL: {result['url']}")
        print()
        print("  The Captain's public IP needs to be whitelisted.")
        print("  Go to Streamline Partner Portal:")
        print("    Administration -> Allowed IP Addresses -> Add IP Address")
        print()
        _print_our_ip()

    elif result["status"] == "unauthorized":
        print(f"\n  ENDPOINT IS ALIVE but returned 401 Unauthorized.")
        print(f"  URL: {result['url']}")
        print("  The token_key or token_secret may be expired or invalid.")

    else:
        print(f"\n  All endpoints returned HTML or failed to connect.")
        print("  The legacy API may be fully decommissioned for this account.")
        print()
        # Still try alternative methods on the off chance
        _try_alternative_methods()


def _try_alternative_methods():
    """Try different method names in case GetPropertyList is wrong."""
    print("\n  " + "-" * 56)
    print("  TRYING ALTERNATIVE METHODS...")
    print("  " + "-" * 56)

    alt_methods = [
        ("GetPropertyIDs", {}),
        ("GetUnitIDs", {}),
        ("GetUnitList", {"status_id": 1}),
        ("GetTokenInfo", {}),
        ("GetReservationList", {}),
        ("GetCompanyInfo", {}),
    ]

    for method, params in alt_methods:
        result = call_streamline_api(method, params)
        if result["status"] == "success":
            data = result["data"]
            print(f"\n  METHOD '{method}' SUCCEEDED!")
            print(f"  URL: {result['url']}")
            print(f"  Response: {json.dumps(data, indent=2, default=str)[:1000]}")
            return
        elif result["status"] in ("forbidden", "unauthorized"):
            print(f"\n  Endpoint alive at {result['url']} — {result['status']}")
            return


def _print_our_ip():
    """Fetch and display the Captain's public IP."""
    try:
        resp = requests.get("https://api.ipify.org?format=json", timeout=5)
        ip = resp.json().get("ip", "unknown")
        print(f"  Captain's Public IP: {ip}")
        print(f"  (This is the IP to whitelist)")
    except Exception:
        print("  Could not determine public IP automatically.")
        print("  Run: curl https://api.ipify.org")


if __name__ == "__main__":
    main()
    print()
