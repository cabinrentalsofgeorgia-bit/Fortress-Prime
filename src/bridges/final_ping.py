"""
STREAMLINE VRS — Final Ping (IP Whitelist Verification)
========================================================
Fortress Prime | Cabin Rentals of Georgia

Minimal probe: calls GetTokenExpiration to verify IP whitelist status.
"""

import os
import json
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TOKEN = os.getenv("STREAMLINE_TOKEN_KEY", "")
SECRET = os.getenv("STREAMLINE_TOKEN_SECRET", "")
URL = "https://web.streamlinevrs.com/api/json"


def ping():
    print(f"  Sending 'GetTokenExpiration' to {URL}...")

    payload = {
        "methodName": "GetTokenExpiration",
        "params": {
            "token_key": TOKEN,
            "token_secret": SECRET,
        }
    }

    try:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        }

        response = requests.post(URL, json=payload, headers=headers, timeout=10)

        print(f"  Status Code: {response.status_code}")

        if response.status_code == 200:
            try:
                data = response.json()
                print(f"  SUCCESS (200 JSON):")
                print(json.dumps(data, indent=2))
            except json.JSONDecodeError:
                print(f"  200 OK but NOT JSON (login page redirect?):")
                print(response.text[:300])
        else:
            print(f"  FAILED: {response.status_code}")
            print(f"  Response: {response.text[:300]}")

    except Exception as e:
        print(f"  ERROR: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("  STREAMLINE — FINAL PING")
    print("=" * 60)
    ping()
    print("=" * 60)
