"""
Phase E tests — PDF rendering for owner statements.

Test groups:
  --- Unit tests (no DB) ---
  1.  Currency formatting: _fmt() for positive, negative, zero
  2.  Status badge: each status maps to the correct text and colour

  --- Integration tests (DB) ---
  3.  Valid PDF produced for zero-activity statement
  4.  Negative closing balance renders in parentheses
  5.  Valid PDF produced for multi-reservation statement
  6.  Cross-period reservation gets asterisk and footnote
  7.  YTD column accumulates across multiple periods
  8.  Owner reserve section renders zeros

  --- Endpoint tests ---
  9.  PDF endpoint returns application/pdf content type
  10. PDF endpoint returns 404 for a missing period
  11. PDF endpoint filename in Content-Disposition is well-formed

  --- Fixture comparison tests ---
  12. Knight / Cherokee Sunrise / Feb 2026 fixture renders successfully
  13. Dutil / Above the Timberline / Jan 2026 fixture renders successfully
"""
from __future__ import annotations

import io
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

import psycopg2
import pypdf
import pytest

DSN = "postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow"


# ── DB helpers ────────────────────────────────────────────────────────────────

def _make_opa(
    uid: str,
    owner_name: str,
    prop_id: Optional[str] = None,
    commission_rate: Decimal = Decimal("0.3000"),
    stripe_account_id: Optional[str] = None,
) -> int:
    """Upsert an owner_payout_accounts row and return its id."""
    if prop_id is None:
        prop_id = f"phaseee-{uid}"
    if stripe_account_id is None:
        stripe_account_id = f"acct_e_{uid}"
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, owner_email, stripe_account_id,
             commission_rate, account_status)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (property_id) DO UPDATE
            SET owner_name        = EXCLUDED.owner_name,
                owner_email       = EXCLUDED.owner_email,
                stripe_account_id = EXCLUDED.stripe_account_id,
                commission_rate   = EXCLUDED.commission_rate,
                account_status    = EXCLUDED.account_status,
                updated_at        = now()
        RETURNING id
    """, (
        prop_id,
        owner_name,
        f"{owner_name.lower().replace(' ', '.')}@test.com",
        stripe_account_id,
        commission_rate,
        "active",
    ))
    opa_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return opa_id


def _make_obp(
    opa_id: int,
    period_start: date,
    period_end: date,
    *,
    opening_balance: Decimal = Decimal("0.00"),
    total_revenue: Decimal = Decimal("0.00"),
    total_commission: Decimal = Decimal("0.00"),
    total_charges: Decimal = Decimal("0.00"),
    total_payments: Decimal = Decimal("0.00"),
    total_owner_income: Decimal = Decimal("0.00"),
    status: str = "approved",
) -> int:
    """Insert an OwnerBalancePeriod row and return its id.

    closing_balance is computed to satisfy the DB CHECK constraint:
        closing = opening + revenue - commission - charges - payments + owner_income
    """
    closing = (
        opening_balance
        + total_revenue
        - total_commission
        - total_charges
        - total_payments
        + total_owner_income
    )
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_balance_periods
            (owner_payout_account_id, period_start, period_end,
             opening_balance, closing_balance,
             total_revenue, total_commission, total_charges,
             total_payments, total_owner_income, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        opa_id, period_start, period_end,
        opening_balance, closing,
        total_revenue, total_commission, total_charges,
        total_payments, total_owner_income, status,
    ))
    obp_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return obp_id


def _pdf_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF bytes object."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return " ".join(page.extract_text() or "" for page in reader.pages)


def _make_property(uid: str) -> str:
    """Insert a minimal test property row and return its UUID string.

    Each call creates a *fresh* property with a uid-derived UUID so that
    tests remain fully isolated across runs — no shared OPAs or OBP conflicts.
    The property has renting_state='active' (default) so compute_owner_statement
    will proceed past the property check.
    """
    import uuid as _uuid_module
    # Deterministic but uid-unique UUID: namespace + uid
    prop_uuid = str(_uuid_module.uuid5(_uuid_module.NAMESPACE_DNS, f"phaseee-prop-{uid}"))
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO properties (id, name, slug, property_type, bedrooms, bathrooms, max_guests)
        VALUES (%s, %s, %s, 'cabin', 3, 2, 6)
        ON CONFLICT (id) DO UPDATE
            SET name = EXCLUDED.name
        RETURNING id
    """, (prop_uuid, f"E Test Property {uid}", f"e-test-property-{uid}"))
    conn.commit()
    conn.close()
    return prop_uuid


# ── 1. Currency formatting ────────────────────────────────────────────────────

def test_currency_formatting():
    from backend.services.statement_pdf import _fmt

    assert _fmt(Decimal("1234.56")) == "$1,234.56"
    assert _fmt(Decimal("0.00"))    == "$0.00"
    assert _fmt(Decimal("0"))       == "$0.00"

    # Negative with parentheses (default)
    assert _fmt(Decimal("-312.50"))   == "($312.50)"
    assert _fmt(Decimal("-3001.91"))  == "($3,001.91)"

    # Negative without parentheses
    assert _fmt(Decimal("-99.00"), parens=False) == "-$99.00"

    # Large positive
    assert _fmt(Decimal("64822.71")) == "$64,822.71"


# ── 2. Status badge ───────────────────────────────────────────────────────────

def test_status_badge_for_each_status():
    from backend.services.statement_pdf import _status_badge

    # All finalized "paid" states should render as APPROVED
    for status in ("approved", "paid", "emailed"):
        text, _ = _status_badge(status)
        assert text == "APPROVED", f"Expected APPROVED for status={status!r}, got {text!r}"

    text, _ = _status_badge("pending_approval")
    assert text == "UNAPPROVED"

    text, _ = _status_badge("draft")
    assert text == "DRAFT"

    text, _ = _status_badge("voided")
    assert text == "VOIDED"


# ── 3. Valid PDF for zero-activity statement ─────────────────────────────────

@pytest.mark.asyncio
async def test_valid_pdf_for_zero_activity_statement():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa(uid, f"E Zero Test {uid}")
    obp_id = _make_obp(opa_id, date(2085, 1, 1), date(2085, 1, 31), status="approved")

    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)

    assert pdf_bytes[:4] == b"%PDF", "PDF output must start with %PDF header"
    assert len(pdf_bytes) > 2000, "PDF must be non-trivial size"

    text = _pdf_text(pdf_bytes)
    assert "OWNER STATEMENT" in text
    assert "E Zero Test" in text
    assert "APPROVED" in text


# ── 4. Negative closing balance renders in parentheses ───────────────────────

@pytest.mark.asyncio
async def test_negative_closing_balance_renders_in_parens():
    """
    Mirrors the Dutil fixture: opening=$3,001.91, charges=$312.50,
    payment=$3,001.91 → closing=($312.50) negative balance.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa(uid, f"E Negative Test {uid}")
    obp_id = _make_obp(
        opa_id,
        date(2085, 2, 1), date(2085, 2, 28),
        opening_balance=Decimal("3001.91"),
        total_charges=Decimal("312.50"),
        total_payments=Decimal("3001.91"),
        status="approved",
    )

    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)

    text = _pdf_text(pdf_bytes)
    # closing = 3001.91 - 312.50 - 3001.91 = -312.50
    assert "($312.50)" in text, (
        f"Expected ($312.50) for negative closing balance, text snippet: "
        f"{text[:300]!r}"
    )


# ── 5. Valid PDF for multi-reservation statement ──────────────────────────────

@pytest.mark.asyncio
async def test_valid_pdf_for_multi_reservation_statement():
    """
    Creates two reservations in the period and verifies they appear in the PDF.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.models.reservation import Reservation
    from backend.models.guest import Guest
    from backend.services.statement_pdf import render_owner_statement_pdf
    import uuid as _uuid

    uid = uuid.uuid4().hex[:8]
    prop_id = _make_property(uid)
    opa_id = _make_opa(uid, f"E Multi Test {uid}", prop_id=prop_id)

    # year derived from uid for uniqueness across runs
    year = 2055 + (int(uid, 16) % 30)

    async with AsyncSessionLocal() as db:
        g1 = Guest(email=f"e5a-{uid}@test.com", first_name="Alice", last_name="Tester",
                   phone=f"404-{uid[:4]}-0001")
        g2 = Guest(email=f"e5b-{uid}@test.com", first_name="Bob",   last_name="Tester",
                   phone=f"404-{uid[:4]}-0002")
        db.add_all([g1, g2])
        await db.flush()

        res1 = Reservation(
            confirmation_code=f"E5-{uid}-A",
            guest_id=g1.id,
            property_id=_uuid.UUID(prop_id),
            guest_email=g1.email,
            guest_name="Alice Tester",
            check_in_date=date(year, 3, 5),
            check_out_date=date(year, 3, 8),
            num_guests=2, status="confirmed",
            nightly_rate=Decimal("300.00"), nights_count=3,
            total_amount=Decimal("900.00"),
            is_owner_booking=False, booking_source="direct",
        )
        res2 = Reservation(
            confirmation_code=f"E5-{uid}-B",
            guest_id=g2.id,
            property_id=_uuid.UUID(prop_id),
            guest_email=g2.email,
            guest_name="Bob Tester",
            check_in_date=date(year, 3, 12),
            check_out_date=date(year, 3, 16),
            num_guests=1, status="confirmed",
            nightly_rate=Decimal("250.00"), nights_count=4,
            total_amount=Decimal("1000.00"),
            is_owner_booking=False, booking_source="direct",
        )
        db.add_all([res1, res2])
        await db.commit()

    # 3 nights × $300 + 4 nights × $250 = $1,900 gross; commission 30% = $570
    obp_id = _make_obp(
        opa_id,
        date(year, 3, 1), date(year, 3, 31),
        total_revenue=Decimal("1900.00"),
        total_commission=Decimal("570.00"),
        status="approved",
    )

    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)

    assert pdf_bytes[:4] == b"%PDF"
    text = _pdf_text(pdf_bytes)

    # Both reservation codes should appear in the reservations table
    assert f"E5-{uid}-A" in text, "First reservation code must appear in PDF"
    assert f"E5-{uid}-B" in text, "Second reservation code must appear in PDF"


# ── 6. Cross-period reservation gets asterisk and footnote ───────────────────

@pytest.mark.asyncio
async def test_cross_period_reservation_gets_asterisk_and_footnote():
    """
    A reservation with check_out past period_end should render with an asterisk
    on the confirmation code and a footnote explaining the cross-boundary split.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.models.reservation import Reservation
    from backend.models.guest import Guest
    from backend.services.statement_pdf import render_owner_statement_pdf
    import uuid as _uuid

    uid = uuid.uuid4().hex[:8]
    prop_id = _make_property(uid)
    opa_id = _make_opa(uid, f"E Crossover Test {uid}", prop_id=prop_id)

    # year derived from full uid for maximum spread across runs
    year = 2055 + (int(uid, 16) % 30)

    async with AsyncSessionLocal() as db:
        g = Guest(email=f"e6-{uid}@test.com", first_name="Carol", last_name="Crossover",
                  phone=f"404-{uid[:4]}-0003")
        db.add(g)
        await db.flush()

        # Reservation that straddles Jan → Feb boundary
        # check_in Jan 29, check_out Feb 4 (6 nights total, 3 in Jan period)
        res = Reservation(
            confirmation_code=f"E6-{uid}-X",
            guest_id=g.id,
            property_id=_uuid.UUID(prop_id),
            guest_email=g.email,
            guest_name="Carol Crossover",
            check_in_date=date(year, 1, 29),
            check_out_date=date(year, 2, 4),
            num_guests=2, status="confirmed",
            nightly_rate=Decimal("200.00"), nights_count=6,
            total_amount=Decimal("1200.00"),
            is_owner_booking=False, booking_source="direct",
        )
        db.add(res)
        await db.commit()

    # Period covers only January — reservation crosses into Feb
    # 3 of 6 nights in period → 50% = $600 allocated; commission 30% = $180
    obp_id = _make_obp(
        opa_id,
        date(year, 1, 1), date(year, 1, 31),
        total_revenue=Decimal("600.00"),
        total_commission=Decimal("180.00"),
        status="approved",
    )

    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)

    text = _pdf_text(pdf_bytes)

    # The confirmation code should appear with an asterisk
    assert f"E6-{uid}-X*" in text, (
        f"Cross-period reservation code must have asterisk; snippet: {text[:400]!r}"
    )
    # Footnote text should be present
    assert "carries over" in text.lower() or "carried over" in text.lower(), (
        "Footnote about cross-period reservation must appear"
    )


# ── 7. YTD column accumulates across periods ──────────────────────────────────

@pytest.mark.asyncio
async def test_ytd_accumulates_across_periods():
    """
    Two non-voided periods in the same year: when rendering the second period,
    the YTD column should sum both periods.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa(uid, f"E YTD Test {uid}")

    year = 2088 + (int(uid[:2], 16) % 10)

    # Period 1: Jan — revenue=$1,000, commission=$300
    _make_obp(
        opa_id,
        date(year, 1, 1), date(year, 1, 31),
        total_revenue=Decimal("1000.00"),
        total_commission=Decimal("300.00"),
        status="approved",
    )

    # Period 2: Feb — revenue=$1,500, commission=$450
    obp2_id = _make_obp(
        opa_id,
        date(year, 2, 1), date(year, 2, 28),
        opening_balance=Decimal("700.00"),  # = closing of period 1
        total_revenue=Decimal("1500.00"),
        total_commission=Decimal("450.00"),
        status="approved",
    )

    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp2_id)

    text = _pdf_text(pdf_bytes)

    # YTD revenue should be $2,500 (1,000 + 1,500)
    assert "$2,500.00" in text, (
        f"YTD revenue $2,500.00 must appear in period 2 PDF; snippet: {text[:500]!r}"
    )
    # YTD commission should be $750 (300 + 450)
    assert "$750.00" in text, (
        f"YTD commission $750.00 must appear in period 2 PDF; snippet: {text[:500]!r}"
    )


# ── 8. Owner reserve renders zeros ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_owner_reserve_renders_zeros():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa(uid, f"E Reserve Test {uid}")
    obp_id = _make_obp(opa_id, date(2089, 1, 1), date(2089, 1, 31), status="approved")

    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)

    text = _pdf_text(pdf_bytes)
    assert "Owner Reserve" in text, "Owner Reserve section must be present"
    # The section renders both balances as $0.00 (not yet implemented)
    assert "$0.00" in text


# ── 9. PDF endpoint returns application/pdf ───────────────────────────────────

@pytest.mark.asyncio
async def test_pdf_endpoint_returns_pdf_content_type():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_statements_workflow import download_statement_pdf

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa(uid, f"E Endpoint Test {uid}")
    obp_id = _make_obp(opa_id, date(2090, 1, 1), date(2090, 1, 31), status="approved")

    async with AsyncSessionLocal() as db:
        response = await download_statement_pdf(period_id=obp_id, db=db)

    assert response.media_type == "application/pdf"
    assert response.body[:4] == b"%PDF"


# ── 10. PDF endpoint 404 for missing period ───────────────────────────────────

@pytest.mark.asyncio
async def test_pdf_endpoint_404_for_missing_period():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_statements_workflow import download_statement_pdf
    from fastapi import HTTPException

    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await download_statement_pdf(period_id=999_999_999, db=db)

    assert exc.value.status_code == 404


# ── 11. PDF endpoint filename in Content-Disposition ─────────────────────────

@pytest.mark.asyncio
async def test_pdf_endpoint_filename_in_content_disposition():
    """
    The Content-Disposition header must use the format:
        owner_statement_{owner_slug}_{prop_slug}_{YYYY-MM}.pdf
    """
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_statements_workflow import download_statement_pdf

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa(uid, f"Filename Test {uid}")
    obp_id = _make_obp(opa_id, date(2090, 2, 1), date(2090, 2, 28), status="approved")

    async with AsyncSessionLocal() as db:
        response = await download_statement_pdf(period_id=obp_id, db=db)

    cd = response.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "owner_statement_" in cd
    assert "2090-02" in cd
    assert cd.endswith('.pdf"')


# ── 12. Knight / Cherokee Sunrise fixture renders ─────────────────────────────

@pytest.mark.asyncio
async def test_knight_cherokee_sunrise_fixture_renders(tmp_path):
    """
    Creates an OPA for the Knight / Cherokee Sunrise scenario matching the
    reference fixture (Feb 2026, UNAPPROVED, zero activity, opening=$64,822.71)
    and verifies the rendered PDF is valid and contains key values.

    Reference fixture: backend/tests/fixtures/streamline_reference/
                       knight_cherokee_sunrise_2026_02.pdf
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    uid = uuid.uuid4().hex[:8]
    # Use a uid-scoped fake property_id so each run gets a fresh OPA
    # (avoids UniqueViolation on owner_balance_periods from prior test runs)
    prop_id = f"phaseee-knight-{uid}"
    opa_id = _make_opa(
        uid,
        "Knight Mitchell Gary",
        prop_id=prop_id,
        commission_rate=Decimal("0.3500"),
    )

    # Feb 2026: zero activity, opening balance matching the Streamline reference
    obp_id = _make_obp(
        opa_id,
        date(2026, 2, 1), date(2026, 2, 28),
        opening_balance=Decimal("64822.71"),
        status="pending_approval",  # UNAPPROVED in Streamline
    )

    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)

    assert pdf_bytes[:4] == b"%PDF"
    text = _pdf_text(pdf_bytes)

    assert "Knight" in text, f"Owner name 'Knight' must appear; snippet: {text[:300]!r}"
    assert "UNAPPROVED" in text, "Status must render as UNAPPROVED for pending_approval"
    assert "$64,822.71" in text, "Opening balance must appear"

    # Write to tmp_path (not crog_output/ — that is managed by the regeneration script)
    (tmp_path / "knight_cherokee_sunrise_2026_02.pdf").write_bytes(pdf_bytes)


# ── 13. Dutil / Above the Timberline fixture renders ──────────────────────────

@pytest.mark.asyncio
async def test_dutil_above_timberline_fixture_renders(tmp_path):
    """
    Creates an OPA for the Dutil / Above the Timberline scenario matching the
    reference fixture (Jan 2026, APPROVED, two charges, one payment).

    Key assertions from dutil_above_the_timberline_2026_01.txt:
      - Owner name contains "Dutil"
      - Status badge: APPROVED
      - Opening balance: $3,001.91
      - Total charges: $312.50
      - Closing balance: ($312.50) — negative, shown in parentheses
      - Payments to owner: $3,001.91
      - No reservations in table

    Reference fixture: backend/tests/fixtures/streamline_reference/
                       dutil_above_the_timberline_2026_01.txt
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    uid = uuid.uuid4().hex[:8]
    # Use a uid-scoped fake property_id so each run gets a fresh OPA
    # (avoids UniqueViolation on owner_balance_periods from prior test runs)
    prop_id = f"phaseee-dutil-{uid}"
    opa_id = _make_opa(
        uid,
        "Dutil David",
        prop_id=prop_id,
        commission_rate=Decimal("0.3000"),
    )

    # Add two charges matching the reference fixture ($200 + $112.50 = $312.50)
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_charges
            (owner_payout_account_id, posting_date, transaction_type,
             description, amount, created_by)
        VALUES
            (%s, '2026-01-10', 'maintenance',    'HVAC service call',        200.00, 'barbara@crog.com'),
            (%s, '2026-01-15', 'cleaning_fee',   'Deep clean after owner stay', 112.50, 'barbara@crog.com')
    """, (opa_id, opa_id))
    conn.commit()
    conn.close()

    # Jan 2026: opening=$3,001.91, charges=$312.50, payment=$3,001.91 → closing=($312.50)
    obp_id = _make_obp(
        opa_id,
        date(2026, 1, 1), date(2026, 1, 31),
        opening_balance=Decimal("3001.91"),
        total_charges=Decimal("312.50"),
        total_payments=Decimal("3001.91"),
        status="approved",
    )

    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)

    assert pdf_bytes[:4] == b"%PDF"
    text = _pdf_text(pdf_bytes)

    assert "Dutil" in text,          "Owner name 'Dutil' must appear"
    assert "APPROVED" in text,       "Status must render as APPROVED"
    assert "$3,001.91" in text,      "Opening balance $3,001.91 must appear"
    assert "($312.50)" in text,      "Negative closing balance ($312.50) must appear in parens"

    # Write to tmp_path (not crog_output/ — that is managed by the regeneration script)
    (tmp_path / "dutil_above_timberline_2026_01.pdf").write_bytes(pdf_bytes)
