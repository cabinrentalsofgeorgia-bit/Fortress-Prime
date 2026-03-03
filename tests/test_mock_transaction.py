#!/usr/bin/env python3
"""
Mock Transaction Test — End-to-End OODA Cycle Verification
============================================================
Sends mock Plaid-style transactions to the webhook server's test
endpoint to verify the full pipeline without a real bank deposit.

Run the webhook server first:
    python3 webhook_server.py

Then in another terminal:
    python3 tests/test_mock_transaction.py

This tests BOTH divisions:
    - Division A: NVIDIA GPU purchase, AWS bill, Verses in Bloom investment
    - Division B: Guest deposit, Blue Ridge Electric, vendor payout
"""

import json
import sys
import requests
from datetime import date

# =============================================================================
# CONFIGURATION
# =============================================================================

WEBHOOK_URL = "http://localhost:8006/webhook/test"
HEALTH_URL = "http://localhost:8006/health"


# =============================================================================
# MOCK TRANSACTIONS
# =============================================================================

DIVISION_A_TRANSACTIONS = [
    {
        "transaction_id": "mock_a_001",
        "date": date.today().isoformat(),
        "amount": -4999.00,
        "name": "NVIDIA CORPORATION DGX CLOUD",
        "merchant_name": "NVIDIA",
        "account_id": "holding_corp_checking",
        "category": ["Computers", "Hardware"],
    },
    {
        "transaction_id": "mock_a_002",
        "date": date.today().isoformat(),
        "amount": -189.43,
        "name": "AWS SERVICES",
        "merchant_name": "Amazon Web Services",
        "account_id": "holding_corp_checking",
        "category": ["Service", "Cloud Computing"],
    },
    {
        "transaction_id": "mock_a_003",
        "date": date.today().isoformat(),
        "amount": -25000.00,
        "name": "VERSES IN BLOOM LLC INVESTMENT",
        "merchant_name": "Verses in Bloom",
        "account_id": "holding_investment",
        "category": ["Transfer", "Investment"],
    },
    {
        "transaction_id": "mock_a_004",
        "date": date.today().isoformat(),
        "amount": 12500.00,
        "name": "MANAGEMENT FEE - CABIN RENTALS",
        "merchant_name": "Cabin Rentals of Georgia",
        "account_id": "holding_corp_checking",
        "category": ["Income", "Management Fee"],
    },
]

DIVISION_B_TRANSACTIONS = [
    {
        "transaction_id": "mock_b_001",
        "date": date.today().isoformat(),
        "amount": 2850.00,
        "name": "GUEST DEPOSIT - MOUNTAIN MAJESTY",
        "merchant_name": "Stripe",
        "account_id": "pm_trust",
        "division_account_type": "trust",
        "trust_related": True,
        "category": ["Payment", "Guest Deposit"],
    },
    {
        "transaction_id": "mock_b_002",
        "date": date.today().isoformat(),
        "amount": -347.82,
        "name": "BLUE RIDGE ELECTRIC MEMBERSHIP",
        "merchant_name": "Blue Ridge Electric",
        "account_id": "pm_operating",
        "division_account_type": "operating",
        "predicted_amount": -325.00,  # Utility prediction for OODA variance check
        "category": ["Utilities", "Electric"],
    },
    {
        "transaction_id": "mock_b_003",
        "date": date.today().isoformat(),
        "amount": -1200.00,
        "name": "MOUNTAIN CABIN MAINTENANCE LLC",
        "merchant_name": "Mountain Cabin Maintenance",
        "account_id": "pm_operating",
        "division_account_type": "operating",
        "category": ["Service", "Maintenance"],
    },
    {
        "transaction_id": "mock_b_004",
        "date": date.today().isoformat(),
        "amount": -89.99,
        "name": "WINDSTREAM COMMUNICATIONS",
        "merchant_name": "Windstream",
        "account_id": "pm_operating",
        "division_account_type": "operating",
        "predicted_amount": -89.99,  # Exact match — no variance
        "category": ["Utilities", "Internet"],
    },
    {
        "transaction_id": "mock_b_005",
        "date": date.today().isoformat(),
        "amount": -450.00,
        "name": "FANNIN COUNTY TAX COMMISSIONER",
        "merchant_name": "Fannin County",
        "account_id": "pm_operating",
        "division_account_type": "operating",
        "category": ["Government", "Tax"],
    },
]


# =============================================================================
# TEST RUNNER
# =============================================================================

def check_health():
    """Verify the webhook server is running."""
    print("[0] Checking webhook server health...")
    try:
        resp = requests.get(HEALTH_URL, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            print(f"    Server: {data.get('status', 'unknown')}")
            agents = data.get("agents", {})
            print(f"    Division A: initialized={agents.get('division_a', {}).get('initialized')}")
            print(f"    Division B: initialized={agents.get('division_b', {}).get('initialized')}")
            print(f"    Database: {data.get('database', 'unknown')}")
            return True
        else:
            print(f"    Server returned {resp.status_code}")
            return False
    except requests.ConnectionError:
        print("    FAILED: Cannot connect to http://localhost:8000")
        print("    Start the server first: python3 webhook_server.py")
        return False


def send_mock_transactions(division: str, transactions: list) -> dict:
    """Send mock transactions to the test endpoint."""
    payload = {
        "division": division,
        "transactions": transactions,
    }
    resp = requests.post(WEBHOOK_URL, json=payload, timeout=600)
    return resp.json()


def print_result(label: str, result: dict):
    """Pretty-print the OODA cycle result."""
    inner = result.get("result", result)
    print(f"    Event ID:           {inner.get('event_id', 'N/A')}")
    print(f"    Success:            {inner.get('success', 'N/A')}")
    print(f"    Transactions:       {inner.get('transactions_processed', 0)}")
    print(f"    Ambiguous:          {inner.get('ambiguous_count', 0)}")
    print(f"    Needs Optimization: {inner.get('needs_optimization', False)}")
    if inner.get("optimization_reason"):
        print(f"    Reason:             {inner['optimization_reason']}")
    if "trust_balanced" in inner:
        print(f"    Trust Balanced:     {inner['trust_balanced']}")

    # Show report summary
    report = inner.get("report", {})
    by_cat = report.get("by_category", {})
    if by_cat:
        print(f"    Categories:")
        for cat, amt in sorted(by_cat.items()):
            print(f"      {cat:.<30} ${amt:>12,.2f}")

    anomalies = report.get("anomalies", [])
    if anomalies:
        print(f"    Anomalies ({len(anomalies)}):")
        for a in anomalies:
            print(f"      [{a.get('severity', 'INFO')}] {a.get('type')}: {a.get('detail', a.get('count', ''))}")


def main():
    print()
    print("=" * 64)
    print("  FORTRESS PRIME — MOCK TRANSACTION TEST")
    print("=" * 64)
    print()

    # Health check
    if not check_health():
        sys.exit(1)
    print()

    # --- Division A: The CFO ---
    print("[1/2] Division A: CROG, LLC — The CFO / Venture Capitalist")
    print(f"      Injecting {len(DIVISION_A_TRANSACTIONS)} mock transactions...")
    print()
    try:
        result_a = send_mock_transactions("A", DIVISION_A_TRANSACTIONS)
        print_result("Division A", result_a)
    except Exception as e:
        print(f"    FAILED: {e}")
        result_a = {"error": str(e)}
    print()

    # --- Division B: The Controller ---
    print("[2/2] Division B: Cabin Rentals of GA — The Controller")
    print(f"      Injecting {len(DIVISION_B_TRANSACTIONS)} mock transactions...")
    print(f"      (Includes utility predictions for OODA variance test)")
    print()
    try:
        result_b = send_mock_transactions("B", DIVISION_B_TRANSACTIONS)
        print_result("Division B", result_b)
    except Exception as e:
        print(f"    FAILED: {e}")
        result_b = {"error": str(e)}
    print()

    # --- Summary ---
    print("=" * 64)
    a_ok = result_a.get("result", result_a).get("success", False)
    b_ok = result_b.get("result", result_b).get("success", False)

    if a_ok and b_ok:
        print("  BOTH DIVISIONS PROCESSED SUCCESSFULLY.")
        print("  The OODA loop is alive.")
    elif a_ok or b_ok:
        print("  PARTIAL SUCCESS. One division had issues — check logs.")
    else:
        print("  BOTH DIVISIONS FAILED. Check the webhook server logs.")

    # Check if optimization was triggered
    a_opt = result_a.get("result", result_a).get("needs_optimization", False)
    b_opt = result_b.get("result", result_b).get("needs_optimization", False)
    if a_opt or b_opt:
        print()
        print("  RECURSIVE TRIGGER DETECTED:")
        if a_opt:
            reason = result_a.get("result", result_a).get("optimization_reason", "")
            print(f"    Division A → Optimization needed: {reason}")
        if b_opt:
            reason = result_b.get("result", result_b).get("optimization_reason", "")
            print(f"    Division B → Optimization needed: {reason}")
        print("  The Sovereign (r1) would now analyze and rewrite agent prompts.")

    print()
    print("  Next: Check detailed status at http://localhost:8000/status/divisions")
    print("=" * 64)
    print()


if __name__ == "__main__":
    main()
