"""
Phase B tests — revenue-side bug fixes.

B1: CC processing fee removed
B2: is_owner_booking column and _map_reservation fix
B3: backfill verification
B5: allocate_reservation_to_period
B6: owner booking exclusion in compute_owner_statement
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import psycopg2
import pytest

DSN = "postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow"


# ── B1: No CC fee deduction ───────────────────────────────────────────────────

def test_owner_payout_no_processing_fee_deduction():
    """
    The named B1 confirmation test.
    $1,615 rent at 30% commission → exactly $1,130.50 net. NOT $1,063.23.
    CC processing fee must be $0.00 (Model A).
    """
    from backend.services.ledger import calculate_owner_payout, BucketedItem, TaxBucket
    D = Decimal
    items = [BucketedItem(name="Base Rent", amount=D("1615.00"),
                          item_type="rent", bucket=TaxBucket.LODGING)]
    result = calculate_owner_payout(items, commission_rate=D("30.00"))

    assert result.gross_revenue    == D("1615.00"), f"gross={result.gross_revenue}"
    assert result.commission_amount == D("484.50"),  f"commission={result.commission_amount}"
    assert result.cc_processing_fee == D("0.00"),    "CC fee must be $0.00 (Model A)"
    assert result.net_owner_payout  == D("1130.50"), f"net={result.net_owner_payout}"


def test_calculate_owner_payout_signature_no_cc_args():
    """
    calculate_owner_payout must NOT accept cc_processing_rate or cc_processing_flat.
    Callers that pass these deprecated args should get a TypeError.
    """
    import inspect
    from backend.services.ledger import calculate_owner_payout
    sig = inspect.signature(calculate_owner_payout)
    assert "cc_processing_rate" not in sig.parameters
    assert "cc_processing_flat" not in sig.parameters


# ── B2: is_owner_booking column and _map_reservation fix ─────────────────────

def test_is_owner_booking_column_exists():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name='reservations' AND column_name='is_owner_booking'
    """)
    row = cur.fetchone()
    conn.close()
    assert row is not None, "is_owner_booking column missing from reservations"
    assert row[1] == "NO", "is_owner_booking must be NOT NULL"
    assert "false" in str(row[2]).lower(), "is_owner_booking default must be false"


def test_map_reservation_sets_owner_booking_when_maketype_is_O():
    """
    Regression test: when maketype_name='O' AND hear_about_name='Ring Central',
    is_owner_booking must be True. The old code silently overwrote it with False.
    """
    from backend.integrations.streamline_vrs import StreamlineVRS

    # Simulate the exact raw data that was causing the bug
    fake_raw = {
        "maketype_name": "O",
        "hear_about_name": "Ring Central",
        "confirmation_id": "99999",
        "unit_id": "12345",
        "status_code": "1",
        "occupants": "2",
        "occupants_small": "0",
        "pets": "0",
        "price_total": "212",
        "price_paidsum": "212",
        "price_balance": "0",
        "price_nightly": None,
        "price_common": "212",
        "days_number": "6",
        "startdate": "06/04/2026",
        "enddate": "06/10/2026",
        "first_name": "Dale & Denise",
        "last_name": "Eby",
        "email": "daledeby@netscape.net",
    }

    vrs = StreamlineVRS()
    mapped = vrs._map_reservation(fake_raw)

    assert mapped["is_owner_booking"] is True, (
        f"Expected is_owner_booking=True for maketype_name='O', got {mapped['is_owner_booking']}"
    )
    assert mapped["source"] == "Ring Central", "source should still be hear_about_name"


def test_map_reservation_false_for_regular_guest():
    """Regular guest reservations must have is_owner_booking=False."""
    from backend.integrations.streamline_vrs import StreamlineVRS

    fake_raw = {
        "maketype_name": "T",
        "hear_about_name": "Airbnb",
        "confirmation_id": "77777",
        "unit_id": "12345",
        "status_code": "1",
        "occupants": "4",
        "occupants_small": "0",
        "pets": "0",
        "price_total": "2500",
        "price_paidsum": "2500",
        "price_balance": "0",
        "price_nightly": "500",
        "price_common": "2500",
        "days_number": "5",
        "startdate": "06/15/2026",
        "enddate": "06/20/2026",
        "first_name": "John",
        "last_name": "Smith",
        "email": "john@example.com",
    }

    vrs = StreamlineVRS()
    mapped = vrs._map_reservation(fake_raw)

    assert mapped["is_owner_booking"] is False


# ── B3: Backfill verification ─────────────────────────────────────────────────

def test_confirmed_owner_bookings_are_flagged():
    """The 5 confirmed owner bookings must have is_owner_booking=True."""
    CONFIRMED = ['54048', '54049', '54047', '53887', '53868']
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT confirmation_code, is_owner_booking
        FROM reservations
        WHERE confirmation_code = ANY(%s)
    """, ([CONFIRMED],))
    rows = {r[0]: r[1] for r in cur.fetchall()}
    conn.close()

    for conf in CONFIRMED:
        assert rows.get(conf) is True, (
            f"Reservation {conf} should be is_owner_booking=True, got {rows.get(conf)}"
        )


def test_regular_guest_cancellations_not_flagged():
    """The 4 regular-guest cancelled reservations must remain is_owner_booking=False."""
    REGULAR = ['53482', '53483', '53876', '53614']
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT confirmation_code, is_owner_booking
        FROM reservations
        WHERE confirmation_code = ANY(%s)
    """, ([REGULAR],))
    rows = {r[0]: r[1] for r in cur.fetchall()}
    conn.close()

    for conf in REGULAR:
        assert rows.get(conf) is False, (
            f"Reservation {conf} should be is_owner_booking=False, got {rows.get(conf)}"
        )


# ── B5: allocate_reservation_to_period ───────────────────────────────────────

def _make_res(check_in: date, check_out: date):
    """Build a minimal mock reservation object for allocation tests."""
    class FakeRes:
        check_in_date = check_in
        check_out_date = check_out
        nights_count = None
    return FakeRes()


def test_allocation_entirely_within_period():
    from backend.services.statement_computation import allocate_reservation_to_period
    res = _make_res(date(2026, 3, 5), date(2026, 3, 10))
    frac, crosses = allocate_reservation_to_period(res, date(2026, 3, 1), date(2026, 3, 31))
    assert frac == Decimal("1"), f"Expected 1, got {frac}"
    assert crosses is False


def test_allocation_spanning_two_periods():
    from backend.services.statement_computation import allocate_reservation_to_period
    # Jan 29 – Feb 3 (5 nights): 3 in Jan, 2 in Feb
    res = _make_res(date(2026, 1, 29), date(2026, 2, 3))
    jan_frac, jan_crosses = allocate_reservation_to_period(res, date(2026, 1, 1), date(2026, 1, 31))
    feb_frac, feb_crosses = allocate_reservation_to_period(res, date(2026, 2, 1), date(2026, 2, 28))

    assert jan_frac == Decimal("3") / Decimal("5"), f"Jan frac={jan_frac}"
    assert feb_frac == Decimal("2") / Decimal("5"), f"Feb frac={feb_frac}"
    assert jan_crosses is True
    assert feb_crosses is True
    # Fractions must sum to exactly 1
    assert (jan_frac + feb_frac) == Decimal("1")


def test_allocation_checkin_last_day_checkout_next():
    """Check-in on Jan 31, check-out Feb 1 → 1 night, fully in January."""
    from backend.services.statement_computation import allocate_reservation_to_period
    res = _make_res(date(2026, 1, 31), date(2026, 2, 1))
    jan_frac, _ = allocate_reservation_to_period(res, date(2026, 1, 1), date(2026, 1, 31))
    feb_frac, _ = allocate_reservation_to_period(res, date(2026, 2, 1), date(2026, 2, 28))
    assert jan_frac == Decimal("1"), f"Should be 1 night in Jan, got {jan_frac}"
    assert feb_frac == Decimal("0"), f"Should be 0 nights in Feb, got {feb_frac}"


def test_allocation_checkin_first_day_of_period():
    """Check-in on March 1 → fully inside March."""
    from backend.services.statement_computation import allocate_reservation_to_period
    res = _make_res(date(2026, 3, 1), date(2026, 3, 5))
    frac, crosses = allocate_reservation_to_period(res, date(2026, 3, 1), date(2026, 3, 31))
    assert frac == Decimal("1")
    assert crosses is False


def test_allocation_zero_night_stay():
    """check_in == check_out → zero nights → fraction is 0, no crash."""
    from backend.services.statement_computation import allocate_reservation_to_period
    res = _make_res(date(2026, 3, 5), date(2026, 3, 5))
    frac, _ = allocate_reservation_to_period(res, date(2026, 3, 1), date(2026, 3, 31))
    assert frac == Decimal("0")


def test_allocation_decimal_precision():
    """
    $1,000 / 7 nights split 4/3 across two periods must sum exactly to $1,000.
    """
    from backend.services.statement_computation import allocate_reservation_to_period
    # Jan 29 – Feb 5 = 7 nights: 3 in Jan, 4 in Feb
    res = _make_res(date(2026, 1, 29), date(2026, 2, 5))
    jan_frac, _ = allocate_reservation_to_period(res, date(2026, 1, 1), date(2026, 1, 31))
    feb_frac, _ = allocate_reservation_to_period(res, date(2026, 2, 1), date(2026, 2, 28))

    gross = Decimal("1000.00")
    jan_amt = (gross * jan_frac).quantize(Decimal("0.01"))
    feb_amt = (gross * feb_frac).quantize(Decimal("0.01"))

    # Exact fractions: jan=3/7, feb=4/7
    assert jan_frac == Decimal(3) / Decimal(7)
    assert feb_frac == Decimal(4) / Decimal(7)
    # Amounts must sum to exactly $1,000.00 (within 1 cent rounding)
    total = jan_amt + feb_amt
    assert abs(total - gross) <= Decimal("0.01"), (
        f"Split amounts {jan_amt} + {feb_amt} = {total} ≠ {gross}"
    )


# ── B6: Owner booking exclusion in compute_owner_statement ───────────────────

@pytest.mark.asyncio
async def test_owner_bookings_excluded_from_statement():
    """
    A property with one regular reservation and one owner-booking reservation
    in the same period produces a statement with only the regular one.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.models.reservation import Reservation
    from backend.services.statement_computation import compute_owner_statement
    from sqlalchemy import select

    uid = uuid.uuid4().hex[:8]

    # Use a real property (not an owner-booking one)
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM properties WHERE renting_state='active' AND name='High Hopes'"
    )
    prop_id = str(cur.fetchone()[0])
    cur.execute("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, commission_rate, account_status, stripe_account_id)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (property_id) DO UPDATE
            SET stripe_account_id=EXCLUDED.stripe_account_id,
                commission_rate=EXCLUDED.commission_rate, updated_at=now()
        RETURNING id
    """, (prop_id, f"B6 Test Owner {uid}", Decimal("0.3000"), "active",
          f"acct_b6_{uid}"))
    opa_id = cur.fetchone()[0]
    conn.commit()
    conn.close()

    # Clean up any stale B6REG-*/B6OWN-* test reservations at this property
    # left over from previous test runs to avoid count collisions.
    conn = psycopg2.connect(DSN)
    cur2 = conn.cursor()
    cur2.execute(
        "DELETE FROM reservations WHERE property_id = %s "
        "AND (confirmation_code LIKE 'B6REG-%%' OR confirmation_code LIKE 'B6OWN-%%')",
        (prop_id,)
    )
    conn.commit()
    conn.close()

    async with AsyncSessionLocal() as db:
        # Find a guest and create two reservations: one regular, one owner-booking
        from backend.models.guest import Guest
        guest = Guest(email=f"b6test{uid}@test.com", first_name="B6", last_name="Test",
                      phone=f"555-{uid[:4]}")
        db.add(guest)
        await db.flush()

        import uuid as _uuid
        # Use far-future dates to avoid real reservations that exist in the DB
        regular_res = Reservation(
            confirmation_code=f"B6REG-{uid}",
            guest_id=guest.id,
            property_id=_uuid.UUID(prop_id),
            guest_email=f"b6test{uid}@test.com",
            guest_name="B6 Test Guest",
            check_in_date=date(2099, 3, 10),
            check_out_date=date(2099, 3, 15),
            num_guests=2,
            status="confirmed",
            nightly_rate=Decimal("500.00"),
            nights_count=5,
            total_amount=Decimal("2500.00"),
            is_owner_booking=False,
            booking_source="direct",
        )
        owner_res = Reservation(
            confirmation_code=f"B6OWN-{uid}",
            guest_id=guest.id,
            property_id=_uuid.UUID(prop_id),
            guest_email=f"b6test{uid}@test.com",
            guest_name="B6 Owner Guest",
            check_in_date=date(2099, 3, 20),
            check_out_date=date(2099, 3, 23),
            num_guests=2,
            status="confirmed",
            nightly_rate=Decimal("0.00"),
            nights_count=3,
            total_amount=Decimal("212.00"),
            is_owner_booking=True,
            booking_source="Ring Central",
        )
        db.add_all([regular_res, owner_res])
        await db.commit()

        result = await compute_owner_statement(
            db, opa_id,
            period_start=date(2099, 3, 1),
            period_end=date(2099, 3, 31),
        )

    assert result.reservation_count == 1, (
        f"Expected 1 reservation (regular only), got {result.reservation_count}"
    )
    assert len(result.line_items) == 1
    assert result.line_items[0].confirmation_code == f"B6REG-{uid}"
    # The owner-booking reservation must NOT appear
    owner_codes = [li.confirmation_code for li in result.line_items]
    assert f"B6OWN-{uid}" not in owner_codes


# ── Phase B.5: detect_owner_booking() helper ─────────────────────────────────

def test_detect_owner_booking_maketype_O():
    from backend.integrations.streamline_vrs import StreamlineVRS
    assert StreamlineVRS.detect_owner_booking({"maketype_name": "O"}) is True


def test_detect_owner_booking_type_name_OWN():
    from backend.integrations.streamline_vrs import StreamlineVRS
    assert StreamlineVRS.detect_owner_booking({"type_name": "OWN"}) is True


def test_detect_owner_booking_owner_res_flag():
    from backend.integrations.streamline_vrs import StreamlineVRS
    r = {"flags": {"flag": [{"name": "OWNER RES", "id": 2635}]}}
    assert StreamlineVRS.detect_owner_booking(r) is True


def test_detect_owner_booking_owner_res_flag_lowercase():
    """Flag name matching must be case-insensitive."""
    from backend.integrations.streamline_vrs import StreamlineVRS
    r = {"flags": {"flag": [{"name": "owner res", "id": 2635}]}}
    assert StreamlineVRS.detect_owner_booking(r) is True


def test_detect_owner_booking_all_three_signals():
    from backend.integrations.streamline_vrs import StreamlineVRS
    r = {
        "maketype_name": "O",
        "type_name": "OWN",
        "flags": {"flag": [{"name": "OWNER RES"}]},
    }
    assert StreamlineVRS.detect_owner_booking(r) is True


def test_detect_owner_booking_none_of_three_signals():
    from backend.integrations.streamline_vrs import StreamlineVRS
    r = {
        "maketype_name": "T",
        "type_name": "POS",
        "hear_about_name": "Airbnb",
        "flags": {"flag": [{"name": "R"}, {"name": "StreamSign"}]},
    }
    assert StreamlineVRS.detect_owner_booking(r) is False


def test_detect_owner_booking_exact_54029_pattern():
    """
    The exact raw data from reservation 54029 (Patrick M Rooke).
    maketype_name='A', type_name='OWN', flags=['OWNER RES'].
    Phase B missed this because it only checked maketype_name=='O'.
    """
    from backend.integrations.streamline_vrs import StreamlineVRS
    r = {
        "maketype_name": "A",     # NOT 'O' — this was the missed signal
        "type_name": "OWN",       # catches it
        "hear_about_name": "Ring Central",
        "flags": {"flag": [
            {"id": 2, "name": "R", "description": "Repeat Reservation"},
            {"id": 2635, "name": "OWNER RES", "description": "Owner Reservation"},
        ]},
    }
    assert StreamlineVRS.detect_owner_booking(r) is True, (
        "detect_owner_booking must return True for 54029's pattern "
        "(type_name='OWN' + OWNER RES flag, even though maketype_name!='O')"
    )


def test_map_reservation_uses_detect_owner_booking():
    """
    _map_reservation must call detect_owner_booking, not inline the logic.
    Verified by passing the 54029 pattern and checking is_owner_booking=True.
    """
    from backend.integrations.streamline_vrs import StreamlineVRS
    vrs = StreamlineVRS()
    fake_raw = {
        "maketype_name": "A",
        "type_name": "OWN",
        "hear_about_name": "Ring Central",
        "flags": {"flag": [{"id": 2635, "name": "OWNER RES"}]},
        "confirmation_id": "54029",
        "unit_id": "70206",
        "status_code": "4",   # cancelled
        "occupants": "2",
        "occupants_small": "0",
        "pets": "0",
        "price_total": "238.50",
        "price_paidsum": "238.50",
        "price_balance": "0",
        "price_nightly": "0",
        "price_common": "238.50",
        "days_number": "214",
        "startdate": "05/31/2026",
        "enddate": "12/31/2026",
        "first_name": "Patrick M",
        "last_name": "Rooke",
        "email": "",
    }
    mapped = vrs._map_reservation(fake_raw)
    assert mapped["is_owner_booking"] is True, (
        f"_map_reservation should set is_owner_booking=True for 54029 pattern, "
        f"got {mapped['is_owner_booking']}"
    )


# ── B5.2: reservation 54029 is flagged ───────────────────────────────────────

def test_reservation_54029_is_owner_booking():
    """
    Reservation 54029 (Patrick M Rooke / Cohutta Sunset departure hold) must
    have is_owner_booking=True after the Phase B.5 fix.
    """
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT is_owner_booking, status, total_amount FROM reservations "
        "WHERE confirmation_code = '54029'"
    )
    row = cur.fetchone()
    conn.close()
    assert row is not None, "Reservation 54029 not found"
    assert row[0] is True, f"Expected is_owner_booking=True for 54029, got {row[0]}"
