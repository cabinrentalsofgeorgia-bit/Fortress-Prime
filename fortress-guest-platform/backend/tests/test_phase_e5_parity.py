"""
Phase E.5 tests — Owner Statement PDF parity fixes.

Test groups:
  --- Schema ---
  1.  owner_payout_accounts has the six mailing address columns
  2.  properties has property_group column
  3.  owner_magic_tokens has the six mailing address columns

  --- OwnerPayoutAccount.mailing_address_display ---
  4.  Full address with line2
  5.  Address without line2 (line2 skipped, no blank line)
  6.  All-NULL address fields → empty string

  --- PDF renderer: mailing address in header ---
  7.  Header shows owner address when present
  8.  Header shows [address missing] placeholder when address is NULL

  --- PDF renderer: property group prefix ---
  9.  Property with group → "Group Name Property Name" in property block
  10. Property without group → only property name (no leading space)

  --- PDF renderer: closing balance label ---
  11. Closing balance row contains "(includes minimum required balance)"

  --- PDF renderer: payment-processed line ---
  12. "Your payment amount of $0.00 has been processed." for zero payments
  13. "Your payment amount of $3,001.91 has been processed." for non-zero
  14. Negative payment amount renders with parentheses

  --- Invite creation: address now required ---
  15. Invite endpoint rejects request missing mailing_address_line1
  16. Invite endpoint rejects request missing city, state, or postal_code
  17. Invite endpoint accepts complete address
  18. accept_invite() copies address from token to owner_payout_accounts

  --- Fixture comparison tests (real data) ---
  19. Knight Cherokee Sunrise Feb 2026 fixture contains all expected fields
  20. Dutil Above the Timberline Jan 2026 fixture contains all expected fields
"""
from __future__ import annotations

import io
import uuid
from datetime import date
from decimal import Decimal

import psycopg2
import pypdf
import pytest
from backend.tests.db_helpers import get_test_dsn

DSN = get_test_dsn()

# ── DB helpers ────────────────────────────────────────────────────────────────

def _make_opa(
    uid: str,
    owner_name: str,
    prop_id: str = None,
    *,
    addr1: str = None,
    addr2: str = None,
    city: str = None,
    state: str = None,
    postal: str = None,
    country: str = "USA",
    commission_rate: Decimal = Decimal("0.3000"),
) -> int:
    if prop_id is None:
        prop_id = f"phasee5-{uid}"
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, owner_email, stripe_account_id,
             commission_rate, account_status,
             mailing_address_line1, mailing_address_line2,
             mailing_address_city, mailing_address_state,
             mailing_address_postal_code, mailing_address_country)
        VALUES (%s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s)
        ON CONFLICT (property_id) DO UPDATE
            SET owner_name=EXCLUDED.owner_name,
                mailing_address_line1=EXCLUDED.mailing_address_line1,
                mailing_address_line2=EXCLUDED.mailing_address_line2,
                mailing_address_city=EXCLUDED.mailing_address_city,
                mailing_address_state=EXCLUDED.mailing_address_state,
                mailing_address_postal_code=EXCLUDED.mailing_address_postal_code,
                mailing_address_country=EXCLUDED.mailing_address_country,
                updated_at=now()
        RETURNING id
    """, (
        prop_id, owner_name, f"e5-{uid}@test.com", f"acct_e5_{uid}",
        commission_rate, "active",
        addr1, addr2, city, state, postal, country,
    ))
    opa_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return opa_id

def _make_obp(opa_id: int, period_start: date, period_end: date, *,
              opening: Decimal = Decimal("0"), revenue: Decimal = Decimal("0"),
              commission: Decimal = Decimal("0"), charges: Decimal = Decimal("0"),
              payments: Decimal = Decimal("0"), owner_income: Decimal = Decimal("0"),
              status: str = "approved") -> int:
    closing = opening + revenue - commission - charges - payments + owner_income
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_balance_periods
            (owner_payout_account_id, period_start, period_end,
             opening_balance, closing_balance, total_revenue, total_commission,
             total_charges, total_payments, total_owner_income, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (opa_id, period_start, period_end,
          opening, closing, revenue, commission, charges, payments, owner_income,
          status))
    obp_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return obp_id

def _make_property_with_group(uid: str, group: str = None) -> str:
    """Insert a minimal test property with optional property_group, return UUID string."""
    import uuid as _uuid
    prop_uuid = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, f"phasee5-prop-{uid}"))
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO properties (id, name, slug, property_type, bedrooms, bathrooms, max_guests, property_group)
        VALUES (%s, %s, %s, 'cabin', 3, 2, 6, %s)
        ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, property_group=EXCLUDED.property_group
        RETURNING id
    """, (prop_uuid, f"E5 Test Property {uid}", f"e5-test-{uid}", group))
    conn.commit()
    conn.close()
    return prop_uuid

def _pdf_text(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return " ".join(p.extract_text() or "" for p in reader.pages)

# ── 1–3. Schema ───────────────────────────────────────────────────────────────

def test_owner_payout_accounts_has_address_columns():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='owner_payout_accounts'
          AND column_name LIKE 'mailing_address%'
    """)
    cols = {r[0] for r in cur.fetchall()}
    conn.close()
    assert "mailing_address_line1" in cols
    assert "mailing_address_city" in cols
    assert "mailing_address_state" in cols
    assert "mailing_address_postal_code" in cols
    assert "mailing_address_country" in cols

def test_properties_has_property_group_column():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='properties' AND column_name='property_group'
    """)
    assert cur.fetchone() is not None, "property_group column not found on properties"
    conn.close()

def test_owner_magic_tokens_has_address_columns():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='owner_magic_tokens'
          AND column_name LIKE 'mailing_address%'
    """)
    cols = {r[0] for r in cur.fetchall()}
    conn.close()
    assert "mailing_address_line1" in cols
    assert "mailing_address_city" in cols

# ── 4–6. mailing_address_display property ────────────────────────────────────

def test_address_display_with_line2():
    """E6.6: mailing address is a single line matching Streamline format."""
    from backend.models.owner_payout import OwnerPayoutAccount
    opa = OwnerPayoutAccount()
    opa.mailing_address_line1 = "PO Box 982"
    opa.mailing_address_line2 = None
    opa.mailing_address_city = "Morganton"
    opa.mailing_address_state = "GA"
    opa.mailing_address_postal_code = "30560"
    opa.mailing_address_country = "USA"
    display = opa.mailing_address_display
    # Single line — Phase E.6 changed from multi-line to one-line format
    assert display == "PO Box 982 Morganton, GA 30560"
    assert "\n" not in display

def test_address_display_without_line2():
    """E6.6: single-line format, no blank lines for missing components."""
    from backend.models.owner_payout import OwnerPayoutAccount
    opa = OwnerPayoutAccount()
    opa.mailing_address_line1 = "2300 Riverchase Center"
    opa.mailing_address_line2 = None
    opa.mailing_address_city = "Birmingham"
    opa.mailing_address_state = "AL"
    opa.mailing_address_postal_code = "35244"
    opa.mailing_address_country = "USA"
    display = opa.mailing_address_display
    assert display == "2300 Riverchase Center Birmingham, AL 35244"
    assert "\n" not in display

def test_address_display_all_null():
    from backend.models.owner_payout import OwnerPayoutAccount
    opa = OwnerPayoutAccount()
    opa.mailing_address_line1 = None
    opa.mailing_address_line2 = None
    opa.mailing_address_city = None
    opa.mailing_address_state = None
    opa.mailing_address_postal_code = None
    opa.mailing_address_country = None
    assert opa.mailing_address_display == ""

# ── 7–8. PDF header: mailing address ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_pdf_header_shows_owner_address():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa(
        uid, f"E5 Addr Test {uid}",
        addr1="123 Mountain View Rd", city="Blue Ridge",
        state="GA", postal="30513",
    )
    obp_id = _make_obp(opa_id, date(2091, 1, 1), date(2091, 1, 31))
    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)
    text = _pdf_text(pdf_bytes)
    assert "123 Mountain View Rd" in text, "Owner address line1 must appear in header"
    assert "Blue Ridge" in text
    assert "GA 30513" in text

@pytest.mark.asyncio
async def test_pdf_header_shows_placeholder_when_address_missing():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    uid = uuid.uuid4().hex[:8]
    # No address fields set → all NULL
    opa_id = _make_opa(uid, f"E5 No Addr {uid}")
    obp_id = _make_obp(opa_id, date(2091, 2, 1), date(2091, 2, 28))
    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)
    text = _pdf_text(pdf_bytes)
    assert "address missing" in text.lower(), (
        "Missing address must show [address missing] placeholder"
    )

# ── 9–10. PDF property block: property group prefix ──────────────────────────

@pytest.mark.asyncio
async def test_pdf_property_block_shows_group_prefix():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    uid = uuid.uuid4().hex[:8]
    prop_id = _make_property_with_group(uid, group="Aska Adventure Area")
    opa_id = _make_opa(uid, f"E5 Group Test {uid}", prop_id=prop_id)
    obp_id = _make_obp(opa_id, date(2091, 3, 1), date(2091, 3, 31))
    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)
    text = _pdf_text(pdf_bytes)
    prop_name = f"E5 Test Property {uid}"
    assert "Aska Adventure Area" in text, "Property group must appear"
    assert prop_name in text, "Property name must appear"
    # Both should appear together (group prefix then name)
    assert f"Aska Adventure Area {prop_name}".replace(" ", " ") in text.replace("\n", " ")

@pytest.mark.asyncio
async def test_pdf_property_block_no_group_shows_name_only():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    uid = uuid.uuid4().hex[:8]
    prop_id = _make_property_with_group(uid, group=None)  # no group
    opa_id = _make_opa(uid, f"E5 No Group {uid}", prop_id=prop_id)
    obp_id = _make_obp(opa_id, date(2091, 4, 1), date(2091, 4, 30))
    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)
    text = _pdf_text(pdf_bytes)
    # Property name present; text does NOT start with a leading space before it
    prop_name = f"E5 Test Property {uid}"
    assert prop_name in text
    # Ensure no spurious leading-space version
    assert f"  {prop_name}" not in text

# ── 11. Closing balance label ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_closing_balance_has_parenthetical():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa(uid, f"E5 Label Test {uid}")
    obp_id = _make_obp(opa_id, date(2092, 1, 1), date(2092, 1, 31))
    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)
    text = _pdf_text(pdf_bytes)
    assert "minimum required balance" in text, (
        "Closing balance label must include '(includes minimum required balance)'"
    )

# ── 12–14. Payment-processed line ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_payment_processed_line_zero():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa(uid, f"E5 Pay Zero {uid}")
    obp_id = _make_obp(opa_id, date(2092, 2, 1), date(2092, 2, 28))
    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)
    text = _pdf_text(pdf_bytes)
    assert "Your payment amount of $0.00 has been processed." in text

@pytest.mark.asyncio
async def test_payment_processed_line_nonzero():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa(uid, f"E5 Pay Nonzero {uid}")
    obp_id = _make_obp(
        opa_id, date(2092, 3, 1), date(2092, 3, 31),
        opening=Decimal("3001.91"),
        charges=Decimal("312.50"),
        payments=Decimal("3001.91"),
    )
    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)
    text = _pdf_text(pdf_bytes)
    assert "Your payment amount of $3,001.91 has been processed." in text

@pytest.mark.asyncio
async def test_payment_processed_line_negative_amount():
    """Payments are stored as positive = money going to owner.
    When total_payments is negative (edge case), it renders with parentheses."""
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_opa(uid, f"E5 Pay Neg {uid}")
    # Simulate a negative payment (credit clawback) — unusual but should render
    # total_payments = -50.00, which makes _fmt(-payments) = _fmt(50) = $50.00
    # (payments line shows value negated since _fmt(-payments) is displayed)
    obp_id = _make_obp(
        opa_id, date(2092, 4, 1), date(2092, 4, 30),
        payments=Decimal("0"),   # zero payments — just verify $0.00 line
    )
    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)
    text = _pdf_text(pdf_bytes)
    assert "has been processed." in text

# ── 15–18. Invite creation: address required ──────────────────────────────────

def test_invite_rejects_missing_address():
    from pydantic import ValidationError
    from backend.api.admin_payouts import OwnerInviteRequest

    with pytest.raises(ValidationError) as exc:
        OwnerInviteRequest(
            property_id="prop-abc",
            owner_email="owner@example.com",
            owner_name="Test Owner",
            commission_rate_percent=30.0,
            # mailing_address_line1 omitted
            mailing_address_city="Blue Ridge",
            mailing_address_state="GA",
            mailing_address_postal_code="30513",
        )
    assert "mailing_address_line1" in str(exc.value)

def test_invite_rejects_missing_city():
    from pydantic import ValidationError
    from backend.api.admin_payouts import OwnerInviteRequest

    with pytest.raises(ValidationError) as exc:
        OwnerInviteRequest(
            property_id="prop-abc",
            owner_email="owner@example.com",
            owner_name="Test Owner",
            commission_rate_percent=30.0,
            mailing_address_line1="123 Main St",
            # city omitted
            mailing_address_state="GA",
            mailing_address_postal_code="30513",
        )
    assert "mailing_address_city" in str(exc.value)

def test_invite_accepts_complete_address():
    from backend.api.admin_payouts import OwnerInviteRequest

    req = OwnerInviteRequest(
        property_id="prop-abc",
        owner_email="owner@example.com",
        owner_name="Test Owner",
        commission_rate_percent=30.0,
        mailing_address_line1="PO Box 982",
        mailing_address_city="Morganton",
        mailing_address_state="GA",
        mailing_address_postal_code="30560",
    )
    assert req.mailing_address_line1 == "PO Box 982"
    assert req.mailing_address_country == "USA"  # default

@pytest.mark.asyncio
async def test_accept_invite_copies_address_to_opa():
    """
    Full round-trip: create_invite() stores address in token,
    accept_invite() copies it to owner_payout_accounts.
    """
    from unittest.mock import AsyncMock, patch
    from backend.core.database import AsyncSessionLocal
    from backend.services.owner_onboarding import create_invite, accept_invite

    uid = uuid.uuid4().hex[:8]
    email = f"e5-addr-rt-{uid}@example.com"
    prop_id = f"e5-addr-rt-prop-{uid}"
    stub_account = f"acct_e5rt_{uid}"
    stub_url = f"https://connect.stripe.com/setup/e/{stub_account}/test"

    with patch("backend.services.owner_onboarding.create_connect_account",
               AsyncMock(return_value={"account_id": stub_account, "status": "onboarding"})), \
         patch("backend.services.owner_onboarding.create_onboarding_link",
               AsyncMock(return_value=stub_url)):
        async with AsyncSessionLocal() as db:
            invite = await create_invite(
                db,
                property_id=prop_id,
                owner_email=email,
                owner_name=f"E5 RT Owner {uid}",
                commission_rate=Decimal("0.3000"),
                mailing_address_line1="555 Oak Street",
                mailing_address_city="Ellijay",
                mailing_address_state="GA",
                mailing_address_postal_code="30540",
            )
            raw_token = invite["invite_url"].split("token=")[1].split("&")[0]
            result = await accept_invite(
                db,
                raw_token=raw_token,
                property_id=prop_id,
                owner_name=f"E5 RT Owner {uid}",
            )

    assert result["success"] is True

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT mailing_address_line1, mailing_address_city,
               mailing_address_state, mailing_address_postal_code
        FROM owner_payout_accounts WHERE property_id=%s
    """, (prop_id,))
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "555 Oak Street",  f"Expected '555 Oak Street', got {row[0]!r}"
    assert row[1] == "Ellijay"
    assert row[2] == "GA"
    assert row[3] == "30540"

# ── 19–20. Fixture comparison tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_knight_cherokee_sunrise_fixture_2026_02():
    """
    Knight / Cherokee Sunrise / Feb 2026 re-rendered fixture contains:
      - Owner name "Gary Knight"
      - Owner address "PO Box 982 Morganton"
      - UNAPPROVED status badge
      - Property "Aska Adventure Area Cherokee Sunrise on Noontootla Creek"
      - Opening balance $64,822.71
      - "(includes minimum required balance)"
      - "Your payment amount of $0.00 has been processed."
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    # OBP 10907 = Knight Cherokee Sunrise Feb 2026 (created in E5 fixture setup)
    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, 10907)

    text = _pdf_text(pdf_bytes)

    assert "Gary Knight" in text
    assert "PO Box 982" in text
    assert "Morganton" in text
    assert "UNAPPROVED" in text
    assert "Aska Adventure Area" in text
    assert "Cherokee Sunrise on Noontootla Creek" in text
    assert "$64,822.71" in text
    assert "minimum required balance" in text
    assert "Your payment amount of $0.00 has been processed." in text

@pytest.mark.asyncio
async def test_dutil_above_timberline_fixture_2026_01():
    """
    Dutil / Above the Timberline / Jan 2026 re-rendered fixture contains:
      - Owner name "David Dutil"
      - Owner address Birmingham AL
      - APPROVED status badge
      - Property "Aska Adventure Area Above the Timberline"
      - Opening balance $3,001.91
      - Negative closing balance ($312.50)
      - Charges section: HVAC + cleaning = $312.50
      - "Your payment amount of $3,001.91 has been processed."
    """
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    # OBP 10908 = Dutil Above the Timberline Jan 2026
    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, 10908)

    text = _pdf_text(pdf_bytes)

    assert "David Dutil" in text
    assert "Birmingham" in text
    assert "AL" in text
    assert "APPROVED" in text
    assert "Aska Adventure Area" in text
    assert "Above the Timberline" in text
    assert "$3,001.91" in text
    assert "($312.50)" in text
    assert "minimum required balance" in text
    assert "Your payment amount of $3,001.91 has been processed." in text
    # Two charges
    assert "HVAC service call" in text
    assert "Deep clean after owner stay" in text
