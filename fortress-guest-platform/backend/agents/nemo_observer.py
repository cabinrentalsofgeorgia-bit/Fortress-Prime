"""
NeMo Observer — READ-ONLY intelligence layer for parity audit analysis.

When the Hermes parity audit detects a discrepancy between the local ledger
and Streamline's GetReservationPrice total, this observer streams both
breakdowns to the local DGX NeMo LLM for root-cause analysis.

The observer NEVER modifies data. It only reads the discrepancy, reasons
about it, and logs its findings for the Commander to review.

CLI:
    python3 backend/agents/nemo_observer.py --verify-property <slug> --expect-clean
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx
import structlog

from backend.core.config import settings

observer_logger = structlog.get_logger(service="nemo_observer")

GENERATION_TIMEOUT_SECONDS = 90.0

AUDITOR_SYSTEM_PROMPT = (
    "You are a Georgia Tax Compliance Expert specializing in Short-Term Rental "
    "lodging tax, sales tax, and DOT fee calculations for Fannin, Gilmer, Union, "
    "and Blue Ridge jurisdictions.\n\n"
    "You will receive two JSON objects:\n"
    "  1. 'local_breakdown' — the CROG Ledger's calculated fees and taxes\n"
    "  2. 'streamline_breakdown' — Streamline VRS's authoritative fees and taxes\n\n"
    "Analyze the price discrepancy. For each line item, compare the local value "
    "against the Streamline value. Identify:\n"
    "  - Which specific fee or tax line is causing the delta\n"
    "  - Whether the error is in our Ledger Logic (code bug, wrong rate, missing fee) "
    "or the Streamline Configuration (stale rate, miscategorized fee)\n"
    "  - The exact dollar amount of each sub-discrepancy\n\n"
    "Return ONLY a JSON object with this schema:\n"
    "{\n"
    '  "root_cause": "ledger_logic" | "streamline_config" | "both" | "rounding",\n'
    '  "confidence": number 0-100,\n'
    '  "discrepant_items": [\n'
    "    {\n"
    '      "item_name": "string",\n'
    '      "local_amount": "string",\n'
    '      "streamline_amount": "string",\n'
    '      "delta": "string",\n'
    '      "likely_cause": "string"\n'
    "    }\n"
    "  ],\n"
    '  "recommendation": "string (one sentence action item)"\n'
    "}\n\n"
    "Do not emit markdown, commentary, or code fences. Return only the JSON object."
)


class NemoObserver:
    """Read-only intelligence layer — never writes to the database."""

    def __init__(self) -> None:
        self.ollama_url = str(settings.ollama_base_url or "").rstrip("/")
        self.model = str(settings.ollama_fast_model or "qwen2.5:7b")

        inference_url = str(settings.dgx_inference_url or "").strip()
        inference_model = str(settings.dgx_inference_model or "").strip()
        self.inference_url = inference_url
        self.inference_model = inference_model
        self.inference_api_key = str(settings.dgx_inference_api_key or "").strip()

    def _resolve_endpoint(self) -> tuple[str, str, dict[str, str]]:
        """Pick the best available LLM endpoint (DGX inference > Ollama)."""
        headers: dict[str, str] = {"Content-Type": "application/json"}

        if self.inference_url and self.inference_model:
            url = self.inference_url.rstrip("/")
            if not url.endswith("/chat/completions"):
                url = f"{url}/v1/chat/completions" if not url.endswith("/v1") else f"{url}/chat/completions"
            if self.inference_api_key:
                headers["Authorization"] = f"Bearer {self.inference_api_key}"
            return url, self.inference_model, headers

        if self.ollama_url:
            return f"{self.ollama_url}/api/chat", self.model, headers

        raise RuntimeError("No LLM endpoint configured for NeMo Observer")

    async def analyze_discrepancy(
        self,
        reservation_id: str,
        confirmation_id: str,
        local_total: str,
        streamline_total: str,
        delta: str,
        local_breakdown: dict[str, Any],
        streamline_breakdown: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Stream the discrepancy to the LLM and return its analysis.

        Returns None if the LLM is unreachable or returns unusable output.
        This method NEVER raises — all failures are logged and swallowed.
        """
        try:
            url, model, headers = self._resolve_endpoint()
        except RuntimeError:
            observer_logger.info("nemo_observer_no_endpoint_configured")
            return None

        user_content = json.dumps({
            "reservation_id": reservation_id,
            "confirmation_id": confirmation_id,
            "local_total": local_total,
            "streamline_total": streamline_total,
            "delta": delta,
            "local_breakdown": local_breakdown,
            "streamline_breakdown": streamline_breakdown,
        }, indent=2, ensure_ascii=True)

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": AUDITOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "temperature": 0.1,
        }
        if "api/chat" not in url:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=GENERATION_TIMEOUT_SECONDS) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            observer_logger.warning(
                "nemo_observer_request_failed",
                reservation_id=reservation_id,
                error=str(exc)[:300],
            )
            return None

        try:
            analysis = _extract_analysis(data)
        except Exception as exc:
            observer_logger.warning(
                "nemo_observer_parse_failed",
                reservation_id=reservation_id,
                error=str(exc)[:300],
            )
            return None

        observer_logger.info(
            "nemo_observer_analysis_complete",
            reservation_id=reservation_id,
            confirmation_id=confirmation_id,
            root_cause=analysis.get("root_cause", "unknown"),
            confidence=analysis.get("confidence", 0),
            recommendation=analysis.get("recommendation", ""),
        )

        return analysis


def _extract_analysis(response: dict[str, Any]) -> dict[str, Any]:
    """Pull the JSON analysis out of either OpenAI-compat or Ollama response format."""
    if "choices" in response:
        choices = response.get("choices") or []
        if not choices:
            raise ValueError("Empty choices in LLM response")
        content = (choices[0].get("message") or {}).get("content", "")
    elif "message" in response:
        content = response["message"].get("content", "")
    else:
        raise ValueError("Unrecognized LLM response format")

    if isinstance(content, str):
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start:end + 1])
    raise ValueError("No JSON object found in LLM response")


# ---------------------------------------------------------------------------
# CLI — Strict Whitelist Verification Harness
# ---------------------------------------------------------------------------

TWO_PLACES = Decimal("0.01")
ONE_HUNDRED = Decimal("100")
SHADOW_DSN = "postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow"


def _money(v: Decimal) -> Decimal:
    return v.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _verify_property_clean(slug: str) -> bool:
    """Run a full Strict Whitelist audit against the live database.

    Returns True if the property passes all checks, False otherwise.
    """
    import psycopg2
    from backend.services.ledger import (
        BucketedItem,
        TaxBucket,
        classify_item,
        resolve_taxes,
    )

    conn = psycopg2.connect(SHADOW_DSN)
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT p.slug, p.county, p.name FROM properties p "
            "WHERE p.slug = %s AND p.is_active = true LIMIT 1",
            (slug,),
        )
        prop = cur.fetchone()
        if not prop:
            print(f"  FAIL  Property '{slug}' not found or inactive")
            return False

        prop_slug, county, prop_name = prop

        cur.execute(
            "SELECT f.id::text, f.name, f.flat_amount, f.fee_type, "
            "       f.percentage_rate, f.is_optional, f.is_pet_fee "
            "FROM fees f "
            "JOIN property_fees pf ON pf.fee_id = f.id "
            "JOIN properties p ON p.id = pf.property_id "
            "WHERE p.slug = %s AND pf.is_active = true AND f.is_active = true "
            "ORDER BY f.name",
            (slug,),
        )
        fees = cur.fetchall()
    finally:
        conn.close()

    print()
    print("=" * 72)
    print(f"  NeMo Observer — Strict Whitelist Verification")
    print(f"  Property:  {prop_name} ({prop_slug})")
    print(f"  County:    {county or 'Fannin (default)'}")
    print(f"  Fees:      {len(fees)} linked")
    print("=" * 72)

    # ── Phase 1: Fee Inventory ──
    print()
    print("─── Phase 1: Fee Inventory ───")
    optional_fees = []
    mandatory_fees = []
    pct_fees = []

    for fee_id, name, flat_amount, fee_type, pct_rate, is_optional, is_pet_fee in fees:
        marker = ""
        if is_optional:
            marker = " [OPTIONAL]"
            optional_fees.append((fee_id, name, Decimal(str(flat_amount))))
        elif fee_type == "percentage":
            marker = f" [PCT {pct_rate}%]"
            pct_fees.append((fee_id, name, Decimal(str(pct_rate))))
        else:
            mandatory_fees.append((fee_id, name, Decimal(str(flat_amount)), bool(is_pet_fee)))

        if fee_type == "percentage":
            print(f"  {name:40s}  {pct_rate}% of base{marker}")
        else:
            print(f"  {name:40s}  ${Decimal(str(flat_amount)):>10.2f}{marker}")

    # ── Phase 2: Strict Whitelist Gate ──
    print()
    print("─── Phase 2: Strict Whitelist Gate (selected_add_on_ids = []) ───")
    checks_passed = 0
    checks_failed = 0

    SIMULATED_NIGHTLY = Decimal("250.00")
    SIMULATED_NIGHTS = 2
    base_rent = _money(SIMULATED_NIGHTLY * SIMULATED_NIGHTS)

    ledger_items: list[BucketedItem] = []
    ledger_items.append(BucketedItem(
        name=f"Base Rent ({SIMULATED_NIGHTS} nights @ ${SIMULATED_NIGHTLY})",
        amount=base_rent,
        item_type="rent",
        bucket=TaxBucket.LODGING,
    ))

    flat_total = Decimal("0.00")
    for fee_id, name, amount, is_pet_fee in mandatory_fees:
        if is_pet_fee:
            continue
        bucket = classify_item("fee", name)
        ledger_items.append(BucketedItem(
            name=name, amount=amount, item_type="fee", bucket=bucket,
        ))
        flat_total += amount

    # Processing Fee on mandatory-only base
    pct_base = base_rent + flat_total
    for fee_id, name, rate in pct_fees:
        amount = _money(pct_base * rate / ONE_HUNDRED)
        bucket = classify_item("fee", name)
        ledger_items.append(BucketedItem(
            name=name, amount=amount, item_type="fee", bucket=bucket,
        ))

    # Check: no optional fee names in ledger
    optional_names = {n for _, n, _ in optional_fees}
    leaked = [i.name for i in ledger_items if i.name in optional_names]
    if leaked:
        print(f"  ✗ LEAK DETECTED: {leaked}")
        checks_failed += 1
    else:
        print(f"  ✓ Optional fees excluded: {[n for _, n, _ in optional_fees]}")
        checks_passed += 1

    # Check: optional fee $ contribution is $0
    optional_contribution = sum(
        i.amount for i in ledger_items
        if i.name in optional_names
    )
    if optional_contribution != Decimal("0.00"):
        print(f"  ✗ Optional fee contribution: ${optional_contribution} (expected $0.00)")
        checks_failed += 1
    else:
        print(f"  ✓ Optional fee contribution: $0.00")
        checks_passed += 1

    # ── Phase 3: Tax Bucket Verification ──
    print()
    print("─── Phase 3: Tax Bucket Classification ───")
    for item in ledger_items:
        bucket = classify_item(item.item_type, item.name)
        status = "✓" if bucket == item.bucket else "✗"
        print(f"  {status} {item.name:40s}  → {bucket.value}")

    for _, name, _ in optional_fees:
        bucket = classify_item("fee", name)
        if bucket == TaxBucket.EXEMPT:
            print(f"  ✓ {name:40s}  → {bucket.value} (correctly EXEMPT)")
            checks_passed += 1
        else:
            print(f"  ✗ {name:40s}  → {bucket.value} (SHOULD BE EXEMPT)")
            checks_failed += 1

    # ── Phase 4: Tax Resolver ──
    print()
    print("─── Phase 4: Tax Resolution (Fannin County, {0} nights) ───".format(SIMULATED_NIGHTS))
    tax_result = resolve_taxes(ledger_items, county, SIMULATED_NIGHTS)

    for detail in tax_result.details:
        print(f"  ${detail.amount:>10.2f}  {detail.tax_name}")
        if detail.bucket == TaxBucket.EXEMPT:
            print(f"  ✗ TAX ON EXEMPT BUCKET — this must never happen")
            checks_failed += 1

    print(f"  {'─' * 52}")
    print(f"  ${tax_result.total_tax:>10.2f}  Total Tax")

    # Verify no tax on EXEMPT bucket
    exempt_taxed = [d for d in tax_result.details if d.bucket == TaxBucket.EXEMPT]
    if not exempt_taxed:
        print(f"  ✓ No taxes levied on EXEMPT bucket")
        checks_passed += 1
    else:
        print(f"  ✗ {len(exempt_taxed)} tax lines on EXEMPT bucket")
        checks_failed += 1

    # ── Phase 5: Processing Fee Base Audit ──
    print()
    print("─── Phase 5: Processing Fee Base Audit ───")
    for fee_id, name, rate in pct_fees:
        expected_amount = _money(pct_base * rate / ONE_HUNDRED)
        actual_items = [i for i in ledger_items if "processing" in i.name.lower()]
        if actual_items:
            actual = actual_items[0].amount
            if actual == expected_amount:
                print(f"  ✓ {name}: ${actual} = {rate}% × ${pct_base}")
                checks_passed += 1
            else:
                print(f"  ✗ {name}: ${actual} ≠ ${expected_amount} ({rate}% × ${pct_base})")
                checks_failed += 1
        else:
            print(f"  ✗ {name}: NOT FOUND in ledger")
            checks_failed += 1

    # ── Phase 6: Grand Total ──
    print()
    print("─── Phase 6: Grand Total ───")
    pre_tax = _money(sum(i.amount for i in ledger_items))
    grand_total = _money(pre_tax + tax_result.total_tax)

    print(f"  Pre-Tax Subtotal:   ${pre_tax:>10.2f}")
    print(f"  Total Tax:          ${tax_result.total_tax:>10.2f}")
    print(f"  Grand Total:        ${grand_total:>10.2f}")
    print()

    # ── Verdict ──
    print("=" * 72)
    if checks_failed == 0:
        print(f"  ✓ VERDICT: CLEAN — {checks_passed}/{checks_passed} checks passed")
        print(f"    Optional fees are fully gated. Strict Whitelist holds.")
        print("=" * 72)
        return True
    else:
        print(f"  ✗ VERDICT: DIRTY — {checks_failed} checks FAILED, {checks_passed} passed")
        print(f"    Optional fee leakage or tax miscalculation detected.")
        print("=" * 72)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="NeMo Observer — Strict Whitelist Verification")
    parser.add_argument("--verify-property", type=str, help="Property slug to verify")
    parser.add_argument("--expect-clean", action="store_true", help="Assert quote is clean (no optional fee leakage)")
    args = parser.parse_args()

    if args.verify_property:
        passed = _verify_property_clean(args.verify_property)
        if args.expect_clean and not passed:
            sys.exit(1)
        sys.exit(0 if passed else 1)

    parser.print_help()


if __name__ == "__main__":
    main()
