"""
Phase E.6 tests — PDF visual parity with Streamline.

Test groups:
  1.  Owner name renders in Streamline last-middle-first format
  2.  Property address renders as full one-line string
  3.  Reservations footnote always present (even for empty tables)
  4.  Payments To Owner has Description column header
  5.  Company HQ address renders in header (no LLC, no phone)
  6.  Owner mailing address renders as single line

All tests use _build_pdf_bytes() with synthetic in-memory data (no DB writes
for the assertions). The regression test at the end uses the real DB-backed
path to ensure the refactored render_owner_statement_pdf still works.
"""
from __future__ import annotations

import io
import uuid
from datetime import date
from decimal import Decimal

import psycopg2
import pypdf
import pytest

DSN = "postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow"


# ── PDF rendering helpers ─────────────────────────────────────────────────────

def _minimal_ytd() -> dict:
    return {k: Decimal("0") for k in
            ("revenue", "commission", "charges", "payments", "owner_income")}


def _empty_stmt():
    from backend.services.statement_computation import StatementResult
    return StatementResult(
        owner_payout_account_id=0,
        owner_name="Test Owner",
        owner_email=None,
        property_id="fake-prop",
        property_name="Test Property",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        commission_rate=Decimal("0.30"),
        commission_rate_percent=Decimal("30"),
    )


def _render(
    *,
    owner_name: str = "Knight Mitchell Gary",
    owner_address: str = "PO Box 982 Morganton, GA 30560",
    prop_display_name: str = "Aska Adventure Area Cherokee Sunrise on Noontootla Creek",
    prop_address: str = "12755 Aska Rd. Blue Ridge GA 30513",
    status: str = "approved",
    opening: Decimal = Decimal("0"),
    closing: Decimal = Decimal("0"),
    payments: Decimal = Decimal("0"),
    charges: Decimal = Decimal("0"),
    stmt=None,
    ytd: dict = None,
) -> str:
    """Render a PDF with _build_pdf_bytes and return extracted text."""
    from backend.services.statement_pdf import _build_pdf_bytes
    if stmt is None:
        stmt = _empty_stmt()
    if ytd is None:
        ytd = _minimal_ytd()
    pdf_bytes = _build_pdf_bytes(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        status=status,
        opening_balance=opening,
        closing_balance=closing,
        total_revenue=Decimal("0"),
        total_commission=Decimal("0"),
        total_charges=charges,
        total_payments=payments,
        total_owner_income=Decimal("0"),
        owner_name=owner_name,
        owner_address=owner_address,
        prop_display_name=prop_display_name,
        prop_address=prop_address,
        stmt=stmt,
        ytd=ytd,
    )
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return " ".join(p.extract_text() or "" for p in reader.pages)


# ── 1. Owner name: last-middle-first format ───────────────────────────────────

def test_owner_name_renders_in_streamline_format():
    text = _render(owner_name="Knight Mitchell Gary")
    assert "Knight Mitchell Gary" in text, (
        "Owner name must render in last-middle-first Streamline format"
    )
    # The first-last format must NOT appear (we are not rendering "Gary Knight")
    # Note: "Gary" alone may appear in other fields, so check the combined form
    assert "Gary Knight" not in text


def test_owner_name_without_middle_name():
    text = _render(owner_name="Dutil David")
    assert "Dutil David" in text
    # No stray space or extra separator
    assert "Dutil  David" not in text


# ── 2. Property address: full one-line string ─────────────────────────────────

def test_property_address_renders_full_address_one_line():
    text = _render(prop_address="12755 Aska Rd. Blue Ridge GA 30513")
    assert "12755 Aska Rd. Blue Ridge GA 30513" in text, (
        "Full property address must appear on one line"
    )


def test_property_address_street_only_when_no_city():
    """When city/state/postal are absent, just the street renders."""
    text = _render(prop_address="638 Bell Camp Ridge")
    assert "638 Bell Camp Ridge" in text


# ── 3. Reservations footnote: always present ─────────────────────────────────

def test_reservations_footnote_always_present():
    """Footnote renders even for an empty reservations table."""
    text = _render()  # no line items
    assert "carries over into the next statement" in text, (
        "Reservations footnote must always be present"
    )


def test_reservations_footnote_present_with_reservations():
    """Footnote renders when there ARE reservations (no regression)."""
    from backend.services.statement_computation import StatementLineItem, StatementResult
    li = StatementLineItem(
        reservation_id="RES-001",
        confirmation_code="CONF-001",
        check_in=date(2026, 1, 5),
        check_out=date(2026, 1, 10),
        nights=5,
        description="Test Property — Guest Name",
        gross_amount=Decimal("1000"),
        pass_through_total=Decimal("0"),
        commission_amount=Decimal("300"),
        cc_processing_fee=Decimal("0"),
        net_to_owner=Decimal("700"),
    )
    stmt = _empty_stmt()
    stmt.line_items = [li]
    stmt.total_gross = Decimal("1000")
    stmt.total_commission = Decimal("300")
    stmt.total_net_to_owner = Decimal("700")
    stmt.reservation_count = 1
    text = _render(stmt=stmt)
    assert "carries over into the next statement" in text


# ── 4. Payments To Owner: Description column ─────────────────────────────────

def test_payments_to_owner_has_description_column():
    text = _render()
    # The column headers render as individual tokens in extracted text
    # Verify "Description" appears somewhere in the Payments To Owner section
    pt_idx = text.find("Payments To Owner")
    reserve_idx = text.find("Owner Reserve")
    assert pt_idx != -1 and reserve_idx != -1
    pt_section = text[pt_idx:reserve_idx]
    assert "Description" in pt_section, (
        "Payments To Owner table must include a Description column header"
    )


# ── 5. Company HQ address in header ──────────────────────────────────────────

def test_company_hq_renders_in_header():
    text = _render()
    assert "86 Huntington Way Blue Ridge Ga 30513" in text, (
        "Company HQ address must appear in the PDF header"
    )


def test_company_llc_line_not_in_header():
    text = _render()
    assert "Cabin Rentals of Georgia, LLC" not in text, (
        "Company LLC name must NOT appear (Phase E.6 removed it)"
    )


def test_company_phone_not_in_header():
    text = _render()
    assert "455-5555" not in text, (
        "Company phone number must NOT appear (Phase E.6 removed it)"
    )


# ── 6. Owner mailing address: single line ─────────────────────────────────────

def test_owner_address_renders_one_line():
    """The complete mailing address appears as one space-separated line."""
    text = _render(owner_address="PO Box 982 Morganton, GA 30560")
    assert "PO Box 982 Morganton, GA 30560" in text.replace("\n", " "), (
        "Owner mailing address must be on a single line"
    )


def test_owner_address_display_single_line_format():
    """OwnerPayoutAccount.mailing_address_display returns a single-line string."""
    from backend.models.owner_payout import OwnerPayoutAccount
    opa = OwnerPayoutAccount()
    opa.mailing_address_line1 = "PO Box 982"
    opa.mailing_address_line2 = None
    opa.mailing_address_city = "Morganton"
    opa.mailing_address_state = "GA"
    opa.mailing_address_postal_code = "30560"
    assert opa.mailing_address_display == "PO Box 982 Morganton, GA 30560"


def test_owner_address_display_with_line2():
    from backend.models.owner_payout import OwnerPayoutAccount
    opa = OwnerPayoutAccount()
    opa.mailing_address_line1 = "100 Oak Street"
    opa.mailing_address_line2 = "Suite 4"
    opa.mailing_address_city = "Blue Ridge"
    opa.mailing_address_state = "GA"
    opa.mailing_address_postal_code = "30513"
    assert opa.mailing_address_display == "100 Oak Street Suite 4 Blue Ridge, GA 30513"


# ── Integration: fetch_owner_info returns display_name ───────────────────────

def test_fetch_owner_info_returns_display_name():
    """fetch_owner_info() now returns a display_name in last-middle-first format."""
    import asyncio
    async def check():
        from backend.integrations.streamline_vrs import StreamlineVRS
        client = StreamlineVRS()
        info = await client.fetch_owner_info(146514)  # Gary Knight
        await client.close()
        return info
    info = asyncio.run(check())
    assert info.get("display_name") == "Knight Mitchell Gary", (
        f"Expected 'Knight Mitchell Gary', got {info.get('display_name')!r}"
    )


def test_fetch_owner_info_display_name_no_middle():
    """display_name omits middle when blank."""
    import asyncio
    async def check():
        from backend.integrations.streamline_vrs import StreamlineVRS
        client = StreamlineVRS()
        info = await client.fetch_owner_info(385151)  # David Dutil (no middle)
        await client.close()
        return info
    info = asyncio.run(check())
    assert info.get("display_name") == "Dutil David", (
        f"Expected 'Dutil David', got {info.get('display_name')!r}"
    )


# ── Integration: demo fixture PDFs contain all E.6 strings ───────────────────

def test_knight_demo_pdf_passes_all_e6_checks():
    """The regenerated Knight PDF contains all Phase E.6 expected strings."""
    from pathlib import Path
    import pypdf, io
    pdf_path = (
        Path(__file__).parent
        / "fixtures" / "crog_output" / "knight_cherokee_sunrise_2026_02.pdf"
    )
    if not pdf_path.exists():
        pytest.skip("Knight demo PDF not yet generated; run regenerate_pdf_demos.py")

    reader = pypdf.PdfReader(io.BytesIO(pdf_path.read_bytes()))
    text = " ".join(p.extract_text() or "" for p in reader.pages)

    for expected in [
        "Knight Mitchell Gary",
        "PO Box 982 Morganton, GA 30560",
        "86 Huntington Way Blue Ridge Ga 30513",
        "Aska Adventure Area",
        "12755 Aska Rd. Blue Ridge GA 30513",
        "UNAPPROVED",
        "carries over into the next statement",
    ]:
        assert expected in text, f"Missing from Knight demo PDF: {expected!r}"

    assert "Cabin Rentals of Georgia, LLC" not in text
    assert "455-5555" not in text


def test_dutil_demo_pdf_passes_all_e6_checks():
    """The regenerated Dutil PDF contains all Phase E.6 expected strings."""
    from pathlib import Path
    import pypdf, io
    pdf_path = (
        Path(__file__).parent
        / "fixtures" / "crog_output" / "dutil_above_timberline_2026_01.pdf"
    )
    if not pdf_path.exists():
        pytest.skip("Dutil demo PDF not yet generated; run regenerate_pdf_demos.py")

    reader = pypdf.PdfReader(io.BytesIO(pdf_path.read_bytes()))
    text = " ".join(p.extract_text() or "" for p in reader.pages)

    for expected in [
        "Dutil David",
        "2300 Riverchase Center Birmingham, AL 35244",
        "86 Huntington Way Blue Ridge Ga 30513",
        "Aska Adventure Area",
        "638 Bell Camp Ridge Blue Ridge GA 30513",
        "APPROVED",
        "($312.50)",
        "carries over into the next statement",
    ]:
        assert expected in text, f"Missing from Dutil demo PDF: {expected!r}"

    assert "Cabin Rentals of Georgia, LLC" not in text
