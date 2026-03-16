#!/usr/bin/env python3
"""
Folio Aggregator Backtest
=========================
Connects directly to the DB, calls the internal _aggregate_folio() function
(no HTTP needed), and prints the validated JSON for 3 known reservations.

Run:  cd fortress-guest-platform && python3 -m backend.tests.test_folio_aggregator

Success criteria:
  - All 3 folios return without exceptions
  - Pydantic validates every field (no ValidationError)
  - Financial amounts are floats, not None
  - Messages/claims/agreements are present where expected
  - aggregation_errors is empty for healthy data
"""
import asyncio
import json
import os
import sys
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

TEST_RESERVATIONS = [
    # Case 1: Reservation with 7 messages
    ("b0ef7e74-6fba-4ff6-87f7-25524e51bd37", "53845", "has_messages"),
    # Case 2: Reservation with a $2,850 damage claim
    ("1f77c75e-fe08-44fb-8836-397df023cfa3", "53544", "has_damage_claim"),
    # Case 3: Reservation with a signed rental agreement
    ("335f232c-7aca-4027-a34e-3eab9230490b", "53989", "has_agreement"),
]

PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"
WARN = "\033[93m⚠ WARN\033[0m"


def check(condition: bool, label: str) -> bool:
    print(f"  {PASS if condition else FAIL}  {label}")
    return condition


async def run_backtest():
    from backend.core.database import AsyncSessionLocal
    from backend.api.reservations import _aggregate_folio

    total_checks = 0
    passed_checks = 0

    for res_id, conf_code, test_case in TEST_RESERVATIONS:
        print(f"\n{'='*70}")
        print(f"BACKTEST: {conf_code} ({test_case})")
        print(f"{'='*70}")

        async with AsyncSessionLocal() as db:
            try:
                folio = await _aggregate_folio(UUID(res_id), db)
                folio_dict = folio.model_dump()
            except Exception as e:
                print(f"  {FAIL}  _aggregate_folio raised: {e}")
                total_checks += 1
                continue

        # ── Universal checks (apply to all folios) ──

        total_checks += 1
        if check(folio_dict["stay"]["confirmation_code"] == conf_code, f"confirmation_code == {conf_code}"):
            passed_checks += 1

        total_checks += 1
        if check(isinstance(folio_dict["guest"]["first_name"], str), "guest.first_name is str"):
            passed_checks += 1

        total_checks += 1
        guest_name = f"{folio_dict['guest']['first_name']} {folio_dict['guest']['last_name']}".strip()
        if check(len(guest_name) > 0, f"guest full name = '{guest_name}'"):
            passed_checks += 1

        total_checks += 1
        if check(isinstance(folio_dict["financials"]["total_amount"], float), "financials.total_amount is float"):
            passed_checks += 1

        total_checks += 1
        if check(folio_dict["financials"]["total_amount"] > 0, f"financials.total_amount = ${folio_dict['financials']['total_amount']:,.2f}"):
            passed_checks += 1

        total_checks += 1
        if check(folio_dict["financials"]["currency"] == "USD", "financials.currency == USD"):
            passed_checks += 1

        total_checks += 1
        if check(isinstance(folio_dict["financials"]["line_items"], list), "financials.line_items is list"):
            passed_checks += 1

        total_checks += 1
        if check(len(folio_dict["financials"]["line_items"]) > 0, f"financials.line_items count = {len(folio_dict['financials']['line_items'])}"):
            passed_checks += 1

        total_checks += 1
        if check(folio_dict["stay"]["nights"] > 0, f"stay.nights = {folio_dict['stay']['nights']}"):
            passed_checks += 1

        total_checks += 1
        if check(folio_dict["stay"]["status"] in ("confirmed", "checked_in", "checked_out", "cancelled"), f"stay.status = {folio_dict['stay']['status']}"):
            passed_checks += 1

        total_checks += 1
        if check(len(folio_dict["stay"]["property_name"]) > 0, f"stay.property_name = '{folio_dict['stay']['property_name']}'"):
            passed_checks += 1

        total_checks += 1
        if check(len(folio_dict.get("aggregation_errors", [])) == 0, "aggregation_errors is empty (clean aggregation)"):
            passed_checks += 1

        # ── Case-specific checks ──

        if test_case == "has_messages":
            total_checks += 1
            msg_count = len(folio_dict["messages"])
            if check(msg_count > 0, f"messages count = {msg_count} (expected >0)"):
                passed_checks += 1
            if msg_count > 0:
                m = folio_dict["messages"][0]
                total_checks += 1
                if check(m["direction"] in ("inbound", "outbound"), f"messages[0].direction = '{m['direction']}'"):
                    passed_checks += 1
                total_checks += 1
                if check(len(m["body"]) > 0, f"messages[0].body length = {len(m['body'])}"):
                    passed_checks += 1

        elif test_case == "has_damage_claim":
            total_checks += 1
            dc_count = len(folio_dict["damage_claims"])
            if check(dc_count > 0, f"damage_claims count = {dc_count} (expected >0)"):
                passed_checks += 1
            if dc_count > 0:
                dc = folio_dict["damage_claims"][0]
                total_checks += 1
                if check(dc["estimated_cost"] >= 0, f"damage_claims[0].estimated_cost = ${dc['estimated_cost']:,.2f}"):
                    passed_checks += 1
                total_checks += 1
                if check(isinstance(dc["has_legal_draft"], bool), "damage_claims[0].has_legal_draft is bool"):
                    passed_checks += 1

        elif test_case == "has_agreement":
            total_checks += 1
            if check(folio_dict["agreement"] is not None, "agreement is present"):
                passed_checks += 1
            if folio_dict["agreement"]:
                total_checks += 1
                if check(folio_dict["agreement"]["status"] == "signed", f"agreement.status = '{folio_dict['agreement']['status']}'"):
                    passed_checks += 1
                total_checks += 1
                if check(folio_dict["agreement"]["signed_at"] is not None, f"agreement.signed_at = {folio_dict['agreement']['signed_at']}"):
                    passed_checks += 1

        # Print condensed JSON
        print(f"\n  --- JSON Summary (key fields) ---")
        print(f"  Guest:      {folio_dict['guest']['first_name']} {folio_dict['guest']['last_name']} ({folio_dict['guest']['email']})")
        print(f"  Property:   {folio_dict['stay']['property_name']}")
        print(f"  Dates:      {folio_dict['stay']['check_in_date']} → {folio_dict['stay']['check_out_date']} ({folio_dict['stay']['nights']} nights)")
        print(f"  Total:      ${folio_dict['financials']['total_amount']:,.2f}")
        print(f"  Paid:       ${folio_dict['financials']['paid_amount']:,.2f}")
        print(f"  Balance:    ${folio_dict['financials']['balance_due']:,.2f}")
        print(f"  Line Items: {len(folio_dict['financials']['line_items'])}")
        print(f"  Messages:   {len(folio_dict['messages'])}")
        print(f"  Work Orders:{len(folio_dict['work_orders'])}")
        print(f"  Claims:     {len(folio_dict['damage_claims'])}")
        print(f"  Agreement:  {'Yes' if folio_dict['agreement'] else 'None'}")
        print(f"  Lifecycle:  {json.dumps(folio_dict['lifecycle'])}")
        print(f"  Errors:     {folio_dict['aggregation_errors'] or 'None'}")

    # ── Final Score ──
    print(f"\n{'='*70}")
    print(f"BACKTEST RESULTS: {passed_checks}/{total_checks} checks passed")
    if passed_checks == total_checks:
        print(f"{PASS}  ALL CHECKS PASSED — Folio Aggregator is production-ready")
    else:
        print(f"{FAIL}  {total_checks - passed_checks} checks failed — review above")
    print(f"{'='*70}")

    return passed_checks == total_checks


if __name__ == "__main__":
    success = asyncio.run(run_backtest())
    sys.exit(0 if success else 1)
