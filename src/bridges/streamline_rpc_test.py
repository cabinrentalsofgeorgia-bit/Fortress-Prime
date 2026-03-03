"""
STREAMLINE VRS — RPC Connectivity Test
=========================================
Fortress Prime | Cabin Rentals of Georgia

The legacy Streamline API is NOT REST — it's JSON-RPC style.
This script probes every known RPC endpoint pattern with
the token_key/token_secret credentials.

Usage:
    python3 src/bridges/streamline_rpc_test.py
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
# Credentials
# ---------------------------------------------------------------------------
TOKEN_KEY = os.getenv("STREAMLINE_TOKEN_KEY", "")
TOKEN_SECRET = os.getenv("STREAMLINE_TOKEN_SECRET", "")


def rpc_call(url: str, method: str, params: dict = None, auth_style: str = "body") -> dict:
    """
    Make a JSON-RPC style call to Streamline.
    Tries multiple authentication embedding patterns.
    """
    if params is None:
        params = {}

    # Build the payload based on auth style
    if auth_style == "body":
        # Token embedded directly in the JSON body
        payload = {
            "token_key": TOKEN_KEY,
            "token_secret": TOKEN_SECRET,
            "method": method,
            "params": json.dumps(params) if params else "{}",
        }
    elif auth_style == "flat":
        # Flat body with token fields at root
        payload = {
            "token_key": TOKEN_KEY,
            "token_secret": TOKEN_SECRET,
            **params,
        }
    elif auth_style == "jsonrpc":
        # Standard JSON-RPC 2.0 envelope
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": {
                "token_key": TOKEN_KEY,
                "token_secret": TOKEN_SECRET,
                **params,
            },
            "id": 1,
        }
    else:
        payload = {
            "token_key": TOKEN_KEY,
            "token_secret": TOKEN_SECRET,
        }

    headers = {"Content-Type": "application/json"}

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        ct = resp.headers.get("content-type", "")
        return {
            "status_code": resp.status_code,
            "content_type": ct,
            "is_json": "json" in ct,
            "is_html": "html" in ct.lower(),
            "body": resp.text[:1000],
            "url": url,
            "method": method,
            "auth_style": auth_style,
        }
    except requests.exceptions.ConnectionError:
        return {"status_code": -1, "body": "Connection refused", "url": url}
    except requests.exceptions.Timeout:
        return {"status_code": -2, "body": "Timeout", "url": url}
    except Exception as e:
        return {"status_code": -3, "body": str(e), "url": url}


def form_call(url: str, method: str, params: dict = None) -> dict:
    """
    Try form-encoded POST (some legacy APIs use this instead of JSON).
    """
    if params is None:
        params = {}

    payload = {
        "token_key": TOKEN_KEY,
        "token_secret": TOKEN_SECRET,
        "method": method,
        **params,
    }

    try:
        resp = requests.post(url, data=payload, timeout=20)
        ct = resp.headers.get("content-type", "")
        return {
            "status_code": resp.status_code,
            "content_type": ct,
            "is_json": "json" in ct,
            "is_html": "html" in ct.lower(),
            "body": resp.text[:1000],
            "url": url,
            "method": method,
            "auth_style": "form",
        }
    except Exception as e:
        return {"status_code": -3, "body": str(e), "url": url}


def query_call(url: str) -> dict:
    """
    Try GET with token_key/token_secret as query params.
    """
    try:
        resp = requests.get(
            url,
            params={"token_key": TOKEN_KEY, "token_secret": TOKEN_SECRET},
            timeout=20,
        )
        ct = resp.headers.get("content-type", "")
        return {
            "status_code": resp.status_code,
            "content_type": ct,
            "is_json": "json" in ct,
            "is_html": "html" in ct.lower(),
            "body": resp.text[:1000],
            "url": url,
            "auth_style": "query_params",
        }
    except Exception as e:
        return {"status_code": -3, "body": str(e), "url": url}


def main():
    print("=" * 64)
    print("  STREAMLINE VRS — RPC CONNECTIVITY TEST")
    print("=" * 64)

    if not TOKEN_KEY or not TOKEN_SECRET:
        print("\n  ERROR: Missing STREAMLINE_TOKEN_KEY or STREAMLINE_TOKEN_SECRET in .env")
        sys.exit(1)

    print(f"\n  Token Key:    {TOKEN_KEY[:8]}{'*' * 24}")
    print(f"  Token Secret: {TOKEN_SECRET[:8]}{'*' * 32}")

    # -----------------------------------------------------------------------
    # Phase 1: Discover the RPC endpoint
    # -----------------------------------------------------------------------
    # Streamline's RPC endpoint could be at any of these paths.
    # We try all combinations of URL + auth style + method.
    # -----------------------------------------------------------------------

    base_domains = [
        "https://webapi.streamlinevrs.com",
        "https://api.streamlinevrs.com",
        "https://app.streamlinevrs.com",
        "https://admin.streamlinevrs.com",
    ]

    rpc_paths = [
        "/api/json",
        "/api/xmlrpc",
        "/api/rpc",
        "/api/v1",
        "/api/v1/json",
        "/api",
        "/json",
        "/rpc",
        "/jsonrpc",
        "/ws",
        "/service",
        "/services",
        "/soap",
        "/partner/api",
        "/partner/json",
        "/ext/api",
        "/external/api",
        "/connect/api",
    ]

    rpc_methods = [
        "GetPropertyIDs",
        "GetPropertyList",
        "GetUnitIDs",
        "GetTokenInfo",
        "GetProperties",
        "ListProperties",
        "ping",
        "system.listMethods",
    ]

    auth_styles = ["body", "flat", "jsonrpc"]

    print(f"\n  Probing {len(base_domains)} domains x {len(rpc_paths)} paths...")
    print(f"  Methods: {', '.join(rpc_methods[:4])}...")
    print()

    hits = []
    tested = 0

    for domain in base_domains:
        for path in rpc_paths:
            url = f"{domain}{path}"

            # Quick check: try JSON POST with the primary method
            result = rpc_call(url, "GetPropertyIDs", auth_style="body")
            tested += 1

            if result.get("is_html"):
                # HTML = admin SPA, skip further tests on this URL
                continue

            if result["status_code"] == -1:
                # Connection refused, skip domain
                continue

            # Got a non-HTML response — this is interesting
            if result["status_code"] > 0:
                hits.append(result)
                print(f"  HIT: POST {url}")
                print(f"    Status: {result['status_code']}")
                print(f"    CT: {result.get('content_type', '?')}")
                print(f"    Body: {result['body'][:300]}")
                print()

                # If we got a hit, probe deeper with all methods and auth styles
                if result.get("is_json") or result["status_code"] in (200, 400, 401, 403, 405, 500):
                    for method in rpc_methods:
                        for style in auth_styles:
                            r = rpc_call(url, method, auth_style=style)
                            tested += 1
                            if r.get("is_json") or (r["status_code"] == 200 and not r.get("is_html")):
                                hits.append(r)
                                print(f"  DEEP HIT: {style}/{method} @ {url}")
                                print(f"    Status: {r['status_code']}")
                                print(f"    Body: {r['body'][:300]}")
                                print()

                    # Also try form-encoded
                    for method in rpc_methods[:4]:
                        r = form_call(url, method)
                        tested += 1
                        if r.get("is_json") or (r["status_code"] == 200 and not r.get("is_html")):
                            hits.append(r)
                            print(f"  FORM HIT: {method} @ {url}")
                            print(f"    Status: {r['status_code']}")
                            print(f"    Body: {r['body'][:300]}")
                            print()

            # Also try GET with query params
            r = query_call(url)
            tested += 1
            if r.get("is_json") or (r["status_code"] == 200 and not r.get("is_html")):
                hits.append(r)
                print(f"  QUERY HIT: GET {url}")
                print(f"    Status: {r['status_code']}")
                print(f"    Body: {r['body'][:300]}")
                print()

    # -----------------------------------------------------------------------
    # Phase 2: Try the Intellistack endpoint with legacy creds
    # -----------------------------------------------------------------------
    print("  --- Intellistack Endpoint (with legacy creds) ---")
    intel_base = "https://api-us.streamline.intellistack.ai"
    intel_paths = ["/v1", "/v1/current-user", "/v1/properties", "/api"]

    for path in intel_paths:
        url = f"{intel_base}{path}"
        for style in ["body", "flat"]:
            r = rpc_call(url, "GetPropertyIDs", auth_style=style)
            tested += 1
            if not r.get("is_html") and r["status_code"] > 0:
                hits.append(r)
                print(f"  INTEL: POST {url} ({style})")
                print(f"    Status: {r['status_code']}")
                print(f"    Body: {r['body'][:300]}")
                print()

    # -----------------------------------------------------------------------
    # Verdict
    # -----------------------------------------------------------------------
    print("=" * 64)
    print(f"  PROBE COMPLETE — {tested} requests sent")
    print("=" * 64)

    json_hits = [h for h in hits if h.get("is_json")]
    non_html_hits = [h for h in hits if not h.get("is_html") and h["status_code"] > 0]

    if json_hits:
        print(f"\n  JSON RESPONSES FOUND: {len(json_hits)}")
        for h in json_hits:
            print(f"\n  URL: {h['url']}")
            print(f"  Method: {h.get('method', '?')} | Auth: {h.get('auth_style', '?')}")
            print(f"  Status: {h['status_code']}")
            try:
                parsed = json.loads(h["body"])
                print(f"  Response: {json.dumps(parsed, indent=2)[:500]}")

                # Check for property data
                if isinstance(parsed, list):
                    print(f"\n  SUCCESS! Found {len(parsed)} items in response.")
                elif isinstance(parsed, dict):
                    if "error" in parsed:
                        print(f"\n  AUTH WORKED but method failed: {parsed['error']}")
                        print("  This is GOOD — we just need the right method name.")
                    elif "data" in parsed:
                        print(f"\n  SUCCESS! Found data key with {len(parsed['data'])} items.")
                    elif "result" in parsed:
                        print(f"\n  SUCCESS! Found result key.")
            except json.JSONDecodeError:
                print(f"  Raw: {h['body'][:300]}")
    elif non_html_hits:
        print(f"\n  Non-HTML responses: {len(non_html_hits)}")
        for h in non_html_hits[:5]:
            print(f"    [{h['status_code']}] {h['url']} — {h['body'][:200]}")
    else:
        print("\n  NO VALID ENDPOINTS FOUND")
        print()
        print("  Every Streamline domain returned HTML (admin SPA).")
        print("  The legacy RPC API appears to be fully decommissioned.")
        print()
        print("  RECOMMENDED ACTIONS:")
        print("    Option A: Generate a new PAT from Intellistack")
        print("      → https://us.streamline.intellistack.ai/access-keys")
        print("      → Then run: python3 src/bridges/streamline_api_test.py --pat <token>")
        print()
        print("    Option B: Export CSV manually from Streamline web UI")
        print("      → Reports → Nightly Audit → Export CSV")
        print("      → Upload to: /mnt/fortress_nas/Financial_Ledger/Streamline_Exports/")
        print("      → Then run: python3 src/bridges/streamline_ingest.py --detect <file.csv>")

    print("\n" + "=" * 64)


if __name__ == "__main__":
    main()
