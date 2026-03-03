#!/usr/bin/env python3
"""
Pre-Flight Validation — Swarm API Endpoint (Rule 7)

Tests the POST /api/leads/{lead_id}/swarm/run endpoint directly
against the FGP backend (port 8100) to prove the LangGraph swarm
is callable via HTTP before wiring the UI.

Usage:
    python3 tools/test_swarm_api.py
"""
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FGP_API = "http://127.0.0.1:8100"

LEAD_ID = "1218a1e7-62eb-4fa5-8aec-7023b9063eda"  # David Mitchell

PROPERTY_IDS = [
    "06859d6b-5645-4070-895f-e9eb316c08e9",  # Aska Escape Lodge (3BR)
    "51c3193a-d15b-45a1-aa24-068087f46828",  # Cohutta Sunset (3BR)
]

PAYLOAD = {
    "property_ids": PROPERTY_IDS,
    "check_in_date": "2026-11-24",
    "check_out_date": "2026-11-29",
}


def get_service_token() -> str:
    """Mint a JWT for the FGP backend auth gate using the correct security module."""
    try:
        from backend.core.security import create_access_token
        return create_access_token(
            user_id="940f2bca-07d4-41e0-8d36-188bb72be872",
            role="admin",
            email="taylor.knight@cabin-rentals-of-georgia.com",
        )
    except Exception as e:
        print(f"  WARNING: JWT generation failed ({e}), trying unauthenticated...")
        return ""


def main():
    print("=" * 72)
    print("  SWARM API PRE-FLIGHT — POST /api/leads/{id}/swarm/run")
    print("=" * 72)
    print(f"\n  Lead:       {LEAD_ID}")
    print(f"  Properties: {len(PROPERTY_IDS)}")
    print(f"  Dates:      {PAYLOAD['check_in_date']} -> {PAYLOAD['check_out_date']}")
    print()

    token = get_service_token()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{FGP_API}/api/leads/{LEAD_ID}/swarm/run"
    print(f"  POST {url}")
    print("  Waiting for swarm (HYDRA 70B + auditor)...\n")

    t0 = time.time()
    try:
        resp = requests.post(url, json=PAYLOAD, headers=headers, timeout=300)
    except requests.Timeout:
        print("  TIMEOUT — swarm took longer than 300s")
        sys.exit(1)
    except requests.ConnectionError:
        print(f"  CONNECTION REFUSED — is the FGP backend running on {FGP_API}?")
        sys.exit(1)

    elapsed = time.time() - t0

    print(f"  Status:  {resp.status_code}")
    print(f"  Elapsed: {elapsed:.1f}s")

    if resp.status_code != 200:
        print(f"\n  ERROR: {resp.text[:500]}")
        sys.exit(1)

    data = resp.json()
    print(f"  Model:   {data.get('draft_model')}")
    print(f"  Audit:   {'PASS' if data.get('audit_passed') else 'FAIL'}")
    print(f"  Rewrites:{data.get('rewrite_count', 0)}")
    print(f"  Quote ID:{data.get('quote_id', 'none')}")

    print("\n--- NODE EXECUTION LOG ---")
    for entry in data.get("node_log", []):
        print(f"  {entry}")

    print("\n--- PRICING MATH ---")
    for opt in data.get("pricing_math", []):
        print(f"  {opt['property_name']} ({opt['bedrooms']}BR): ${opt['total_price']} [{opt['pricing_source']}]")

    print("\n--- FINAL AI-DRAFTED EMAIL ---")
    print(data.get("draft_email", "(no draft)"))

    print(f"\n{'=' * 72}")
    print(f"  SWARM API PRE-FLIGHT: {'PASS' if resp.status_code == 200 else 'FAIL'}")
    print(f"  Total: {elapsed:.1f}s | Audit: {'PASS' if data.get('audit_passed') else 'FAIL'}")
    print(f"{'=' * 72}")


if __name__ == "__main__":
    main()
