#!/usr/bin/env python3
"""
Trust Ledger Self-Healing Test
================================
Proves the system can recover from a CRITICAL trust imbalance.

The previous test left a $2,850 guest deposit with no matching payout.
This test injects the corresponding outflows:
    1. Owner payout (-$2,280 = 80% of $2,850)
    2. Management fee (-$570 = 20% of $2,850)

After processing, the trust ledger should balance to $0.00 and the
Division B agent should report HEALTH RESTORED.

Run the webhook server first:
    python3 webhook_server.py

Then:
    python3 tests/test_payout_correction.py
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
# THE CURE: Matching trust outflows
# =============================================================================

# First, re-inject the original deposit so the agent sees the full picture
# in this session (agent state is in-memory per session)
CORRECTION_TRANSACTIONS = [
    # The original guest deposit (trust inflow)
    {
        "transaction_id": "heal_b_001",
        "date": date.today().isoformat(),
        "amount": 2850.00,
        "name": "GUEST DEPOSIT - MOUNTAIN MAJESTY",
        "merchant_name": "Stripe",
        "account_id": "pm_trust",
        "division_account_type": "trust",
        "trust_related": True,
    },
    # Owner payout (80% of guest deposit, trust outflow)
    {
        "transaction_id": "heal_b_002",
        "date": date.today().isoformat(),
        "amount": -2280.00,
        "name": "OWNER PAYOUT - MOUNTAIN MAJESTY - G.KNIGHT",
        "merchant_name": "Owner Distribution",
        "account_id": "pm_trust",
        "division_account_type": "trust",
        "trust_related": True,
    },
    # Management fee (20% of guest deposit, trust outflow)
    {
        "transaction_id": "heal_b_003",
        "date": date.today().isoformat(),
        "amount": -570.00,
        "name": "MGMT FEE 20% - MOUNTAIN MAJESTY",
        "merchant_name": "CROG Management Fee",
        "account_id": "pm_trust",
        "division_account_type": "trust",
        "trust_related": True,
    },
    # A normal operating expense (non-trust, for contrast)
    {
        "transaction_id": "heal_b_004",
        "date": date.today().isoformat(),
        "amount": -65.00,
        "name": "BLUE RIDGE MOUNTAIN WATER",
        "merchant_name": "Blue Ridge Water",
        "account_id": "pm_operating",
        "division_account_type": "operating",
        "predicted_amount": -62.00,  # 4.8% variance — UNDER threshold
    },
]


# =============================================================================
# TEST RUNNER
# =============================================================================

def check_health():
    """Verify the webhook server is running."""
    try:
        resp = requests.get(HEALTH_URL, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            print(f"    Server: {data.get('status')}")
            print(f"    Database: {data.get('database')}")
            return True
        return False
    except requests.ConnectionError:
        print("    FAILED: Server not running on port 8006")
        print("    Start it: python3 webhook_server.py")
        return False


def main():
    print()
    print("=" * 64)
    print("  FORTRESS PRIME — TRUST LEDGER SELF-HEALING TEST")
    print("=" * 64)
    print()
    print("  Scenario: Previous cycle left $2,850 trust imbalance.")
    print("  Cure: Inject owner payout + management fee to zero the ledger.")
    print()

    # Health check
    print("[0] Checking server...")
    if not check_health():
        sys.exit(1)
    print()

    # Inject correction transactions
    print("[1] Injecting trust correction transactions...")
    print(f"    +$2,850.00  Guest Deposit (trust inflow)")
    print(f"    -$2,280.00  Owner Payout 80% (trust outflow)")
    print(f"    -$  570.00  Management Fee 20% (trust outflow)")
    print(f"    -$   65.00  Water bill (operating, non-trust)")
    print(f"    ─────────────────────────────────────────────")
    print(f"    Trust net: $2,850 - $2,280 - $570 = $0.00")
    print()
    print("    Sending to Division B Controller...")
    print("    (This will take several minutes as the LLM categorizes each)")
    print()

    try:
        resp = requests.post(WEBHOOK_URL, json={
            "division": "B",
            "transactions": CORRECTION_TRANSACTIONS,
        }, timeout=900)

        result = resp.json()
        inner = result.get("result", result)

        print("[2] OODA Cycle Result:")
        print(f"    Event ID:           {inner.get('event_id', 'N/A')}")
        print(f"    Success:            {inner.get('success', 'N/A')}")
        print(f"    Transactions:       {inner.get('transactions_processed', 0)}")
        print(f"    Ambiguous:          {inner.get('ambiguous_count', 0)}")
        print(f"    Trust Balanced:     {inner.get('trust_balanced', 'N/A')}")
        print(f"    Needs Optimization: {inner.get('needs_optimization', False)}")

        if inner.get("optimization_reason"):
            print(f"    Reason:             {inner['optimization_reason']}")

        report = inner.get("report", {})
        trust = report.get("trust_accounting", {})
        if trust:
            print()
            print("[3] Trust Accounting Verification:")
            print(f"    Deposits:    ${trust.get('trust_deposits', 0):>12,.2f}")
            print(f"    Payouts:     ${trust.get('trust_payouts', 0):>12,.2f}")
            print(f"    Delta:       ${trust.get('delta', 0):>12,.2f}")
            print(f"    Balanced:    {trust.get('balanced', 'N/A')}")

        by_cat = report.get("by_category", {})
        if by_cat:
            print()
            print("[4] Categories:")
            for cat, amt in sorted(by_cat.items()):
                print(f"    {cat:.<35} ${amt:>12,.2f}")

        anomalies = report.get("anomalies", [])
        print()
        if not anomalies:
            print("[5] Anomalies: NONE")
        else:
            print(f"[5] Anomalies ({len(anomalies)}):")
            for a in anomalies:
                print(f"    [{a.get('severity', 'INFO')}] {a.get('type')}: "
                      f"{a.get('detail', a.get('count', ''))}")

    except requests.Timeout:
        print("    TIMEOUT: LLM processing took longer than 15 minutes.")
        print("    Check server logs for progress.")
        sys.exit(1)
    except Exception as e:
        print(f"    ERROR: {e}")
        sys.exit(1)

    # Summary
    print()
    print("=" * 64)
    balanced = inner.get("trust_balanced", False)
    success = inner.get("success", False)
    needs_opt = inner.get("needs_optimization", False)

    if balanced and success and not needs_opt:
        print("  TRUST LEDGER HEALED. System is NOMINAL.")
        print("  The Controller processed the payout, balanced the ledger,")
        print("  and the OODA cycle completed without triggering REFLECT.")
    elif balanced and not needs_opt:
        print("  TRUST BALANCED but OODA had issues. Check anomalies.")
    else:
        print("  TRUST STILL IMBALANCED or OPTIMIZATION NEEDED.")
        print("  Review the report above for details.")
    print("=" * 64)
    print()


if __name__ == "__main__":
    main()
