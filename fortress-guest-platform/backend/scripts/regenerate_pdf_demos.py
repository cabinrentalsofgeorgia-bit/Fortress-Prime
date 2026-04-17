"""
Regenerate the demonstration PDFs in backend/tests/fixtures/crog_output/.

This script works WITHOUT persisting anything to the database.  It:

  1. Fetches real owner data from Streamline's GetOwnerInfo endpoint
  2. Loads the real Property records from the local database
  3. Constructs in-memory balance and statement data
  4. Calls _build_pdf_bytes() (the pure rendering function) directly
  5. Writes each PDF + a .txt companion file to crog_output/

Usage:
    .uv-venv/bin/python3 backend/scripts/regenerate_pdf_demos.py

Or as a module:
    .uv-venv/bin/python3 -m backend.scripts.regenerate_pdf_demos

Nothing is written to owner_payout_accounts or owner_balance_periods.
The Streamline API is called (read-only).
"""
from __future__ import annotations

import asyncio
import io
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pypdf

# Ensure the package root is importable when run directly
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

OUTPUT_DIR = REPO_ROOT / "backend" / "tests" / "fixtures" / "crog_output"

# ── Scenario definitions ──────────────────────────────────────────────────────

SCENARIOS = [
    {
        "label":                "Gary Knight / Cherokee Sunrise on Noontootla Creek / Feb 2026",
        "filename_stem":        "knight_cherokee_sunrise_2026_02",
        "sl_owner_id":          146514,          # GetOwnerInfo owner_id
        "property_uuid":        "50a9066d-fc2e-44c4-a716-25adb8fbad3e",
        # Balance fields for Feb 2026 (zero-activity month)
        "period_start":         date(2026, 2, 1),
        "period_end":           date(2026, 2, 28),
        "status":               "pending_approval",  # → UNAPPROVED badge
        "opening_balance":      Decimal("64822.71"),
        "closing_balance":      Decimal("64822.71"),
        "total_revenue":        Decimal("0.00"),
        "total_commission":     Decimal("0.00"),
        "total_charges":        Decimal("0.00"),
        "total_payments":       Decimal("0.00"),
        "total_owner_income":   Decimal("0.00"),
        # Synthetic charges (empty for Knight)
        "charges":              [],
        # YTD (no prior 2026 periods for this owner in Streamline)
        "ytd_revenue":          Decimal("0.00"),
        "ytd_commission":       Decimal("0.00"),
        "ytd_charges":          Decimal("0.00"),
        "ytd_payments":         Decimal("0.00"),
        "ytd_owner_income":     Decimal("0.00"),
        # Verification strings (Phase E.6 format)
        "expected": [
            "Knight Mitchell Gary",
            "PO Box 982 Morganton, GA 30560",
            "86 Huntington Way Blue Ridge Ga 30513",
            "Aska Adventure Area",
            "Cherokee Sunrise on Noontootla Creek",
            "Blue Ridge GA 30513",
            "UNAPPROVED",
            "$64,822.71",
            "minimum required balance",
            "Your payment amount of $0.00 has been processed.",
            "carries over into the next statement",
            "Description",
        ],
    },
    {
        "label":                "David Dutil / Above the Timberline / Jan 2026",
        "filename_stem":        "dutil_above_timberline_2026_01",
        "sl_owner_id":          385151,
        "property_uuid":        "50f8e859-c30c-4d4c-a32e-8c8189eebb6c",
        "period_start":         date(2026, 1, 1),
        "period_end":           date(2026, 1, 31),
        "status":               "approved",
        "opening_balance":      Decimal("3001.91"),
        "closing_balance":      Decimal("-312.50"),
        "total_revenue":        Decimal("0.00"),
        "total_commission":     Decimal("0.00"),
        "total_charges":        Decimal("312.50"),
        "total_payments":       Decimal("3001.91"),
        "total_owner_income":   Decimal("0.00"),
        # Synthetic charges matching the Streamline reference fixture
        "charges": [
            {
                "posting_date":             date(2026, 1, 10),
                "transaction_type":         "maintenance",
                "transaction_type_display": "Maintenance",
                "description":              "HVAC service call",
                "amount":                   Decimal("200.00"),
                "reference_id":             None,
            },
            {
                "posting_date":             date(2026, 1, 15),
                "transaction_type":         "cleaning_fee",
                "transaction_type_display": "Cleaning Fee",
                "description":              "Deep clean after owner stay",
                "amount":                   Decimal("112.50"),
                "reference_id":             None,
            },
        ],
        # YTD = same as period (Jan is the first month of the year)
        "ytd_revenue":          Decimal("0.00"),
        "ytd_commission":       Decimal("0.00"),
        "ytd_charges":          Decimal("312.50"),
        "ytd_payments":         Decimal("3001.91"),
        "ytd_owner_income":     Decimal("0.00"),
        "expected": [
            "Dutil David",
            "2300 Riverchase Center Birmingham, AL 35244",
            "86 Huntington Way Blue Ridge Ga 30513",
            "Aska Adventure Area",
            "Above the Timberline",
            "Blue Ridge GA 30513",
            "APPROVED",
            "$3,001.91",
            "($312.50)",
            "minimum required balance",
            "Your payment amount of $3,001.91 has been processed.",
            "HVAC service call",
            "Deep clean after owner stay",
            "carries over into the next statement",
            "Description",
        ],
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_text(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _owner_address_from_info(info: dict) -> str:
    """
    Build a single-line mailing address from GetOwnerInfo response.

    Format: "{line1}[ {line2}] {city}, {state} {postal}"
    Matches Streamline's one-line address format.
    Returns "" when address1 is missing.
    """
    def _s(v) -> str:
        return str(v).strip() if v and not isinstance(v, dict) else ""

    line1  = _s(info.get("address1"))
    line2  = _s(info.get("address2"))
    city   = _s(info.get("city"))
    state  = _s(info.get("state"))
    postal = _s(info.get("zip"))

    if not line1:
        return ""

    parts = [line1]
    if line2:
        parts.append(line2)
    city_state_zip = ", ".join(filter(None, [city, f"{state} {postal}".strip()]))
    if city_state_zip:
        parts.append(city_state_zip)
    return " ".join(parts)


async def _render_scenario(
    scenario: dict,
    db,
    sl_client,
) -> bytes:
    """
    Render one demo PDF using in-memory data only.
    No rows are written to the database.
    """
    import uuid as _uuid_mod
    from backend.services.statement_computation import (
        OwnerChargeLineItem, StatementResult,
    )
    from backend.services.statement_pdf import _build_pdf_bytes
    from backend.models.property import Property

    # ── 1. Fetch owner name and mailing address from Streamline ──────────────
    owner_info = await sl_client.fetch_owner_info(scenario["sl_owner_id"])
    if not owner_info:
        raise RuntimeError(
            f"GetOwnerInfo returned empty for sl_owner_id={scenario['sl_owner_id']}"
        )
    # Use Streamline's last-middle-first display_name (e.g. "Knight Mitchell Gary")
    owner_name = (
        owner_info.get("display_name", "")
        or f"(owner {scenario['sl_owner_id']})"
    )
    owner_address = _owner_address_from_info(owner_info)

    # ── 2. Fetch property from local DB ───────────────────────────────────────
    prop_uuid = _uuid_mod.UUID(scenario["property_uuid"])
    prop = await db.get(Property, prop_uuid)
    if prop is None:
        raise RuntimeError(f"Property {scenario['property_uuid']} not found in DB")

    prop_name = prop.name
    prop_group = prop.property_group or ""
    # Assemble full one-line address: "street city STATE postal"
    addr_parts = [
        prop.address or "",
        prop.city or "",
        (f"{prop.state or ''} {prop.postal_code or ''}").strip(),
    ]
    prop_address = " ".join(p for p in addr_parts if p).strip()
    prop_display_name = f"{prop_group} {prop_name}".strip() if prop_group else prop_name

    # ── 3. Build synthetic StatementResult ───────────────────────────────────
    charge_items = [
        OwnerChargeLineItem(
            posting_date=ch["posting_date"],
            transaction_type=ch["transaction_type"],
            transaction_type_display=ch["transaction_type_display"],
            description=ch["description"],
            amount=ch["amount"],
            reference_id=ch["reference_id"],
        )
        for ch in scenario["charges"]
    ]
    stmt = StatementResult(
        owner_payout_account_id=0,   # placeholder — not used in rendering
        owner_name=owner_name,
        owner_email=None,
        property_id=scenario["property_uuid"],
        property_name=prop_name,
        period_start=scenario["period_start"],
        period_end=scenario["period_end"],
        commission_rate=Decimal("0.00"),
        commission_rate_percent=Decimal("0.00"),
        line_items=[],
        owner_charges=charge_items,
        total_gross=Decimal("0.00"),
        total_pass_through=Decimal("0.00"),
        total_commission=Decimal("0.00"),
        total_cc_processing=Decimal("0.00"),
        total_net_to_owner=Decimal("0.00"),
        total_charges=scenario["total_charges"],
    )

    ytd = {
        "revenue":      scenario["ytd_revenue"],
        "commission":   scenario["ytd_commission"],
        "charges":      scenario["ytd_charges"],
        "payments":     scenario["ytd_payments"],
        "owner_income": scenario["ytd_owner_income"],
    }

    # ── 4. Render ─────────────────────────────────────────────────────────────
    pdf_bytes = _build_pdf_bytes(
        period_start=scenario["period_start"],
        period_end=scenario["period_end"],
        status=scenario["status"],
        opening_balance=scenario["opening_balance"],
        closing_balance=scenario["closing_balance"],
        total_revenue=scenario["total_revenue"],
        total_commission=scenario["total_commission"],
        total_charges=scenario["total_charges"],
        total_payments=scenario["total_payments"],
        total_owner_income=scenario["total_owner_income"],
        owner_name=owner_name,
        owner_address=owner_address,
        prop_display_name=prop_display_name,
        prop_address=prop_address,
        stmt=stmt,
        ytd=ytd,
    )
    return pdf_bytes


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    from backend.core.database import AsyncSessionLocal
    from backend.integrations.streamline_vrs import StreamlineVRS

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sl_client = StreamlineVRS()
    all_ok = True

    try:
        async with AsyncSessionLocal() as db:
            for scenario in SCENARIOS:
                print(f"\n{'='*72}")
                print(f"Rendering: {scenario['label']}")

                try:
                    pdf_bytes = await _render_scenario(scenario, db, sl_client)
                except Exception as exc:
                    print(f"  ERROR: {exc}")
                    all_ok = False
                    continue

                # Write PDF
                pdf_path = OUTPUT_DIR / f"{scenario['filename_stem']}.pdf"
                pdf_path.write_bytes(pdf_bytes)
                print(f"  PDF written : {pdf_path.name} ({len(pdf_bytes):,} bytes)")

                # Write companion .txt
                text = _extract_text(pdf_bytes)
                txt_path = OUTPUT_DIR / f"{scenario['filename_stem']}.pdf.txt"
                txt_path.write_text(text, encoding="utf-8")
                print(f"  Text written: {txt_path.name}")

                # Print extracted text for inline review
                print(f"\n--- Extracted text ---\n{text}\n--- End ---")

                # Spot-check expected strings
                missing = [s for s in scenario["expected"] if s not in text]
                if missing:
                    print(f"\n  VERIFICATION FAILED — missing strings:")
                    for s in missing:
                        print(f"    · {s!r}")
                    all_ok = False
                else:
                    print(f"\n  Verification: all {len(scenario['expected'])} expected strings present ✓")
    finally:
        await sl_client.close()

    print(f"\n{'='*72}")
    if all_ok:
        print("All demonstration PDFs regenerated successfully.")
        print(f"Output directory: {OUTPUT_DIR}")
    else:
        print("One or more scenarios failed — see errors above.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
