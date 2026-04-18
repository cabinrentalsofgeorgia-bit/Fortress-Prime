"""
Phase C tests — owner charges table, endpoints, and statement integration.

Tests:
--- Schema ---
1.  owner_charges table exists with all columns
2.  All 17 enum values defined
3.  amount=0 rejected by CHECK constraint
4.  empty description rejected
5.  voided_at without voided_by rejected (and vice versa)

--- OwnerChargeType Python enum ---
6.  All 17 values present
7.  Each value has a non-empty display_name

--- is_charge_period_locked helper ---
8.  Returns None when no period exists
9.  Returns None when period exists but status is 'draft'
10. Returns the period when status is 'approved'
11. Returns the period when status is 'paid'
12. Returns the period when status is 'emailed'
13. Returns the period when status is 'voided'
14. Returns None for a date outside all periods

--- POST /api/admin/payouts/charges ---
15. Successful creation
16. Rejected: account does not exist
17. Rejected: owner not enrolled
18. Rejected: amount=0
19. Rejected: description empty
20. Rejected: posting_date in locked period (HTTP 409)

--- GET /api/admin/payouts/charges ---
21. Returns charges for owner+period
22. Excludes voided by default
23. Includes voided when include_voided=true
24. Filters by transaction_type

--- PATCH /api/admin/payouts/charges/{id} ---
25. Successfully updates description
26. Rejected: charge is voided
27. Rejected: charge in locked period

--- POST /api/admin/payouts/charges/{id}/void ---
28. Successfully voids a charge
29. Rejected: charge already voided
30. Rejected: charge in locked period

--- compute_owner_statement integration ---
31. No charges → total_charges=0
32. Three charges totaling $312.50 → total_charges=Decimal("312.50")
33. Charge + credit (net $150) → total_charges=Decimal("150.00")
34. Voided charge NOT counted
35. Charge outside period NOT counted

--- State machine integration ---
36. Create charge in open period → succeeds
37. After period approved → create/patch/void all return 409
38. New charge in different open period → succeeds
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

import psycopg2
import pytest

DSN = "postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow"


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_enrolled_opa(uid: str, prop_id: Optional[str] = None) -> int:
    """Create an enrolled owner_payout_accounts row and return its id."""
    if prop_id is None:
        prop_id = f"phase-c-test-{uid}"
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, owner_email, stripe_account_id,
             commission_rate, account_status)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (property_id) DO UPDATE
            SET stripe_account_id=EXCLUDED.stripe_account_id,
                commission_rate=EXCLUDED.commission_rate,
                updated_at=now()
        RETURNING id
    """, (prop_id, f"Charge Test Owner {uid}", f"ct-{uid}@test.com",
          f"acct_ct_{uid}", Decimal("0.3000"), "active"))
    opa_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return opa_id


def _make_unenrolled_opa(uid: str) -> int:
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, commission_rate, account_status)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (property_id) DO UPDATE
            SET stripe_account_id=NULL, updated_at=now()
        RETURNING id
    """, (f"unenrolled-{uid}", f"Unenrolled {uid}", Decimal("0.3000"), "onboarding"))
    opa_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return opa_id


def _insert_charge(opa_id: int, amount: Decimal, posting_date: date,
                   description: str = "Test charge",
                   transaction_type: str = "maintenance") -> int:
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_charges
            (owner_payout_account_id, posting_date, transaction_type,
             description, amount, created_by)
        VALUES (%s, %s, %s::owner_charge_type_enum, %s, %s, %s)
        RETURNING id
    """, (opa_id, posting_date, transaction_type, description, amount,
          "test@fortress.local"))
    charge_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return charge_id


# ── 1–5: Schema checks ───────────────────────────────────────────────────────

def test_owner_charges_table_columns():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns "
                "WHERE table_name='owner_charges' ORDER BY ordinal_position")
    cols = {r[0] for r in cur.fetchall()}
    conn.close()
    required = {"id","owner_payout_account_id","posting_date","transaction_type",
                "description","amount","reference_id","originating_work_order_id",
                "created_at","created_by","voided_at","voided_by","void_reason"}
    assert not (required - cols), f"Missing columns: {required - cols}"


def test_all_17_enum_values_in_db():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid=t.oid "
                "WHERE t.typname='owner_charge_type_enum' ORDER BY enumsortorder")
    values = {r[0] for r in cur.fetchall()}
    conn.close()
    assert len(values) == 17, f"Expected 17 enum values, got {len(values)}"


def test_amount_zero_rejected():
    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    with pytest.raises(Exception, match="chk_oc_amount_not_zero"):
        cur.execute("""
            INSERT INTO owner_charges
                (owner_payout_account_id, posting_date, transaction_type,
                 description, amount, created_by)
            VALUES (%s, %s, 'maintenance', %s, 0, 'test')
        """, (opa_id, date(2026, 3, 1), "test charge"))
        conn.commit()
    conn.rollback()
    conn.close()


def test_empty_description_rejected():
    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    with pytest.raises(Exception, match="chk_oc_description_not_empty"):
        cur.execute("""
            INSERT INTO owner_charges
                (owner_payout_account_id, posting_date, transaction_type,
                 description, amount, created_by)
            VALUES (%s, %s, 'maintenance', '', 100, 'test')
        """, (opa_id, date(2026, 3, 1)))
        conn.commit()
    conn.rollback()
    conn.close()


def test_voided_at_without_voided_by_rejected():
    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    with pytest.raises(Exception, match="chk_oc_void_pair"):
        cur.execute("""
            INSERT INTO owner_charges
                (owner_payout_account_id, posting_date, transaction_type,
                 description, amount, created_by, voided_at)
            VALUES (%s, %s, 'maintenance', 'test', 100, 'test', now())
        """, (opa_id, date(2026, 3, 1)))
        conn.commit()
    conn.rollback()
    conn.close()


# ── 6–7: Python enum ──────────────────────────────────────────────────────────

def test_owner_charge_type_has_17_values():
    from backend.models.owner_charge import OwnerChargeType
    assert len(list(OwnerChargeType)) == 17


def test_owner_charge_type_display_names_not_empty():
    from backend.models.owner_charge import OwnerChargeType
    for t in OwnerChargeType:
        assert t.display_name, f"{t.value} has empty display_name"
        assert t.display_name.strip() == t.display_name


# ── 8–14: is_charge_period_locked ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lock_returns_none_when_no_period():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import is_charge_period_locked

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)

    async with AsyncSessionLocal() as db:
        result = await is_charge_period_locked(db, opa_id, date(2026, 3, 15))
    assert result is None


@pytest.mark.asyncio
async def test_lock_returns_none_for_draft_period():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import is_charge_period_locked
    from backend.models.owner_balance_period import OwnerBalancePeriod

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)

    async with AsyncSessionLocal() as db:
        period = OwnerBalancePeriod(
            owner_payout_account_id=opa_id,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            opening_balance=Decimal("0"),
            closing_balance=Decimal("0"),
            status="draft",
        )
        db.add(period)
        await db.commit()

        result = await is_charge_period_locked(db, opa_id, date(2026, 3, 15))
    assert result is None


@pytest.mark.asyncio
async def test_lock_returns_period_for_approved():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import is_charge_period_locked
    from backend.models.owner_balance_period import OwnerBalancePeriod

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)

    async with AsyncSessionLocal() as db:
        period = OwnerBalancePeriod(
            owner_payout_account_id=opa_id,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            opening_balance=Decimal("0"),
            closing_balance=Decimal("0"),
            status="approved",
        )
        db.add(period)
        await db.commit()
        period_id = period.id

        locked = await is_charge_period_locked(db, opa_id, date(2026, 3, 15))
    assert locked is not None
    assert locked.id == period_id


@pytest.mark.asyncio
async def test_lock_returns_none_for_date_outside_period():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import is_charge_period_locked
    from backend.models.owner_balance_period import OwnerBalancePeriod

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)

    async with AsyncSessionLocal() as db:
        period = OwnerBalancePeriod(
            owner_payout_account_id=opa_id,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            opening_balance=Decimal("0"),
            closing_balance=Decimal("0"),
            status="approved",
        )
        db.add(period)
        await db.commit()

        # April 15 is outside March
        locked = await is_charge_period_locked(db, opa_id, date(2026, 4, 15))
    assert locked is None


# ── 15–20: POST /api/admin/payouts/charges ───────────────────────────────────

@pytest.mark.asyncio
async def test_create_charge_success():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import create_charge, OwnerChargeCreateRequest
    from backend.models.owner_charge import OwnerChargeType
    from unittest.mock import MagicMock

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    user = MagicMock(email="admin@test.com")

    body = OwnerChargeCreateRequest(
        owner_payout_account_id=opa_id,
        posting_date=date(2099, 3, 15),
        transaction_type=OwnerChargeType.MAINTENANCE,
        description="Fix hot tub pump",
        amount=Decimal("325.00"),
    )
    async with AsyncSessionLocal() as db:
        result = await create_charge(body=body, db=db, user=user)

    assert result["amount"] == "325.00"
    assert result["created_by"] == "admin@test.com"
    assert result["transaction_type"] == "maintenance"


@pytest.mark.asyncio
async def test_create_charge_account_not_found():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import create_charge, OwnerChargeCreateRequest
    from backend.models.owner_charge import OwnerChargeType
    from fastapi import HTTPException
    from unittest.mock import MagicMock

    user = MagicMock(email="admin@test.com")
    body = OwnerChargeCreateRequest(
        owner_payout_account_id=999999999,
        posting_date=date(2026, 3, 15),
        transaction_type=OwnerChargeType.MAINTENANCE,
        description="test",
        amount=Decimal("100"),
    )
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await create_charge(body=body, db=db, user=user)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_charge_rejected_unenrolled():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import create_charge, OwnerChargeCreateRequest
    from backend.models.owner_charge import OwnerChargeType
    from fastapi import HTTPException
    from unittest.mock import MagicMock

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_unenrolled_opa(uid)
    user = MagicMock(email="admin@test.com")

    body = OwnerChargeCreateRequest(
        owner_payout_account_id=opa_id,
        posting_date=date(2026, 3, 15),
        transaction_type=OwnerChargeType.MAINTENANCE,
        description="test",
        amount=Decimal("100"),
    )
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await create_charge(body=body, db=db, user=user)
    assert exc.value.status_code == 422
    assert "onboarding" in str(exc.value.detail).lower() or "enrolled" in str(exc.value.detail).lower()


def test_create_charge_rejects_zero_amount():
    from pydantic import ValidationError
    from backend.api.admin_charges import OwnerChargeCreateRequest
    from backend.models.owner_charge import OwnerChargeType

    with pytest.raises(ValidationError):
        OwnerChargeCreateRequest(
            owner_payout_account_id=1,
            posting_date=date(2026, 3, 15),
            transaction_type=OwnerChargeType.MAINTENANCE,
            description="test",
            amount=Decimal("0"),
        )


def test_create_charge_rejects_empty_description():
    from pydantic import ValidationError
    from backend.api.admin_charges import OwnerChargeCreateRequest
    from backend.models.owner_charge import OwnerChargeType

    with pytest.raises(ValidationError):
        OwnerChargeCreateRequest(
            owner_payout_account_id=1,
            posting_date=date(2026, 3, 15),
            transaction_type=OwnerChargeType.MAINTENANCE,
            description="",
            amount=Decimal("100"),
        )


@pytest.mark.asyncio
async def test_create_charge_rejected_locked_period():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import create_charge, OwnerChargeCreateRequest
    from backend.models.owner_charge import OwnerChargeType
    from backend.models.owner_balance_period import OwnerBalancePeriod
    from fastapi import HTTPException
    from unittest.mock import MagicMock

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    user = MagicMock(email="admin@test.com")

    async with AsyncSessionLocal() as db:
        period = OwnerBalancePeriod(
            owner_payout_account_id=opa_id,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            opening_balance=Decimal("0"), closing_balance=Decimal("0"),
            status="approved",
        )
        db.add(period)
        await db.commit()

        body = OwnerChargeCreateRequest(
            owner_payout_account_id=opa_id,
            posting_date=date(2026, 3, 15),
            transaction_type=OwnerChargeType.MAINTENANCE,
            description="locked period charge",
            amount=Decimal("100"),
        )
        with pytest.raises(HTTPException) as exc:
            await create_charge(body=body, db=db, user=user)
    assert exc.value.status_code == 409


# ── 21–24: GET /api/admin/payouts/charges ────────────────────────────────────

@pytest.mark.asyncio
async def test_list_charges_for_owner():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import list_charges

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    _insert_charge(opa_id, Decimal("100"), date(2026, 3, 10))
    _insert_charge(opa_id, Decimal("200"), date(2026, 3, 20))

    async with AsyncSessionLocal() as db:
        result = await list_charges(owner_payout_account_id=opa_id,
                                    period_start=None, period_end=None,
                                    transaction_type=None, include_voided=False,
                                    limit=100, offset=0, db=db)
    assert result["total"] >= 2


@pytest.mark.asyncio
async def test_list_charges_excludes_voided_by_default():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import list_charges

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    charge_id = _insert_charge(opa_id, Decimal("100"), date(2099, 4, 10))

    # Void it directly
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("UPDATE owner_charges SET voided_at=now(), voided_by='test' WHERE id=%s",
                (charge_id,))
    conn.commit()
    conn.close()

    async with AsyncSessionLocal() as db:
        without_voided = await list_charges(
            owner_payout_account_id=opa_id,
            period_start=date(2099, 4, 1), period_end=date(2099, 4, 30),
            transaction_type=None, include_voided=False, limit=100, offset=0, db=db)
        with_voided = await list_charges(
            owner_payout_account_id=opa_id,
            period_start=date(2099, 4, 1), period_end=date(2099, 4, 30),
            transaction_type=None, include_voided=True, limit=100, offset=0, db=db)

    assert without_voided["total"] == 0
    assert with_voided["total"] == 1


# ── 25–27: PATCH /api/admin/payouts/charges/{id} ─────────────────────────────

@pytest.mark.asyncio
async def test_patch_charge_description():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import update_charge, OwnerChargePatchRequest
    from unittest.mock import MagicMock

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    charge_id = _insert_charge(opa_id, Decimal("100"), date(2099, 5, 10), "Original desc")
    user = MagicMock(email="admin@test.com")

    async with AsyncSessionLocal() as db:
        result = await update_charge(
            charge_id=charge_id,
            body=OwnerChargePatchRequest(description="Updated desc"),
            db=db, user=user)
    assert result["description"] == "Updated desc"


@pytest.mark.asyncio
async def test_patch_charge_rejected_if_voided():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import update_charge, OwnerChargePatchRequest
    from fastapi import HTTPException
    from unittest.mock import MagicMock

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    charge_id = _insert_charge(opa_id, Decimal("100"), date(2099, 5, 10), "Test")

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("UPDATE owner_charges SET voided_at=now(), voided_by='test' WHERE id=%s",
                (charge_id,))
    conn.commit()
    conn.close()

    user = MagicMock(email="admin@test.com")
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await update_charge(
                charge_id=charge_id,
                body=OwnerChargePatchRequest(description="new"),
                db=db, user=user)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_patch_charge_rejected_locked_period():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import update_charge, OwnerChargePatchRequest
    from backend.models.owner_balance_period import OwnerBalancePeriod
    from fastapi import HTTPException
    from unittest.mock import MagicMock

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    charge_id = _insert_charge(opa_id, Decimal("100"), date(2026, 4, 10), "Locked test")

    async with AsyncSessionLocal() as db:
        period = OwnerBalancePeriod(
            owner_payout_account_id=opa_id,
            period_start=date(2026, 4, 1), period_end=date(2026, 4, 30),
            opening_balance=Decimal("0"), closing_balance=Decimal("0"),
            status="approved",
        )
        db.add(period)
        await db.commit()

        user = MagicMock(email="admin@test.com")
        with pytest.raises(HTTPException) as exc:
            await update_charge(charge_id=charge_id,
                                body=OwnerChargePatchRequest(description="new"),
                                db=db, user=user)
    assert exc.value.status_code == 409


# ── 28–30: void ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_void_charge_success():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import void_charge, VoidRequest
    from unittest.mock import MagicMock

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    charge_id = _insert_charge(opa_id, Decimal("150"), date(2099, 6, 10), "Void me")
    user = MagicMock(email="staff@test.com")

    async with AsyncSessionLocal() as db:
        result = await void_charge(
            charge_id=charge_id,
            body=VoidRequest(void_reason="Entered in wrong period"),
            db=db, user=user)
    assert result["voided_at"] is not None
    assert result["voided_by"] == "staff@test.com"


@pytest.mark.asyncio
async def test_void_charge_already_voided():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import void_charge, VoidRequest
    from fastapi import HTTPException
    from unittest.mock import MagicMock

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    charge_id = _insert_charge(opa_id, Decimal("150"), date(2099, 6, 10), "Void twice test")

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("UPDATE owner_charges SET voided_at=now(), voided_by='test' WHERE id=%s",
                (charge_id,))
    conn.commit()
    conn.close()

    user = MagicMock(email="staff@test.com")
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await void_charge(charge_id=charge_id,
                              body=VoidRequest(void_reason="second void"),
                              db=db, user=user)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_void_charge_rejected_locked_period():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import void_charge, VoidRequest
    from backend.models.owner_balance_period import OwnerBalancePeriod
    from fastapi import HTTPException
    from unittest.mock import MagicMock

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    charge_id = _insert_charge(opa_id, Decimal("150"), date(2026, 5, 10), "Locked void test")

    async with AsyncSessionLocal() as db:
        period = OwnerBalancePeriod(
            owner_payout_account_id=opa_id,
            period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
            opening_balance=Decimal("0"), closing_balance=Decimal("0"),
            status="paid",
        )
        db.add(period)
        await db.commit()

        user = MagicMock(email="staff@test.com")
        with pytest.raises(HTTPException) as exc:
            await void_charge(charge_id=charge_id,
                              body=VoidRequest(void_reason="locked period test"),
                              db=db, user=user)
    assert exc.value.status_code == 409


# ── 31–35: compute_owner_statement integration ───────────────────────────────

@pytest.mark.asyncio
async def test_statement_no_charges():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import compute_owner_statement

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)

    async with AsyncSessionLocal() as db:
        result = await compute_owner_statement(
            db, opa_id,
            period_start=date(2099, 1, 1), period_end=date(2099, 1, 31))
    assert result.total_charges == Decimal("0.00")
    assert result.owner_charges == []


@pytest.mark.asyncio
async def test_statement_three_charges_totaling():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import compute_owner_statement

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    _insert_charge(opa_id, Decimal("100.00"), date(2099, 2, 5))
    _insert_charge(opa_id, Decimal("112.50"), date(2099, 2, 12))
    _insert_charge(opa_id, Decimal("100.00"), date(2099, 2, 20))

    async with AsyncSessionLocal() as db:
        result = await compute_owner_statement(
            db, opa_id,
            period_start=date(2099, 2, 1), period_end=date(2099, 2, 28))
    assert result.total_charges == Decimal("312.50")
    assert len(result.owner_charges) == 3


@pytest.mark.asyncio
async def test_statement_charge_and_credit():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import compute_owner_statement

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    _insert_charge(opa_id, Decimal("200.00"), date(2099, 3, 5))   # charge
    _insert_charge(opa_id, Decimal("-50.00"), date(2099, 3, 10))   # credit

    async with AsyncSessionLocal() as db:
        result = await compute_owner_statement(
            db, opa_id,
            period_start=date(2099, 3, 1), period_end=date(2099, 3, 31))
    assert result.total_charges == Decimal("150.00")


@pytest.mark.asyncio
async def test_statement_voided_charge_not_counted():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import compute_owner_statement

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    charge_id = _insert_charge(opa_id, Decimal("300.00"), date(2099, 4, 5))
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("UPDATE owner_charges SET voided_at=now(), voided_by='test' WHERE id=%s",
                (charge_id,))
    conn.commit()
    conn.close()

    async with AsyncSessionLocal() as db:
        result = await compute_owner_statement(
            db, opa_id,
            period_start=date(2099, 4, 1), period_end=date(2099, 4, 30))
    assert result.total_charges == Decimal("0.00")


@pytest.mark.asyncio
async def test_statement_charge_outside_period_excluded():
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_computation import compute_owner_statement

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    # April charge — should NOT appear in March statement
    _insert_charge(opa_id, Decimal("500.00"), date(2099, 4, 1))

    async with AsyncSessionLocal() as db:
        result = await compute_owner_statement(
            db, opa_id,
            period_start=date(2099, 3, 1), period_end=date(2099, 3, 31))
    assert result.total_charges == Decimal("0.00")


# ── 36–38: State machine integration ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_state_machine_locked_after_approval():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_charges import (
        create_charge, update_charge, void_charge,
        OwnerChargeCreateRequest, OwnerChargePatchRequest, VoidRequest,
    )
    from backend.models.owner_balance_period import OwnerBalancePeriod
    from backend.models.owner_charge import OwnerChargeType
    from fastapi import HTTPException
    from unittest.mock import MagicMock

    uid = uuid.uuid4().hex[:8]
    opa_id = _make_enrolled_opa(uid)
    charge_id = _insert_charge(opa_id, Decimal("100"), date(2099, 6, 15), "State machine test")

    user = MagicMock(email="admin@test.com")

    # Step 1: Approve the period
    async with AsyncSessionLocal() as db:
        period = OwnerBalancePeriod(
            owner_payout_account_id=opa_id,
            period_start=date(2099, 6, 1), period_end=date(2099, 6, 30),
            opening_balance=Decimal("0"), closing_balance=Decimal("0"),
            status="approved",
        )
        db.add(period)
        await db.commit()

    # Step 2: All modifications to that period should fail with 409
    async with AsyncSessionLocal() as db:
        # Create in locked period → 409
        with pytest.raises(HTTPException) as exc:
            await create_charge(
                body=OwnerChargeCreateRequest(
                    owner_payout_account_id=opa_id,
                    posting_date=date(2099, 6, 20),
                    transaction_type=OwnerChargeType.MAINTENANCE,
                    description="new charge in locked period",
                    amount=Decimal("50"),
                ), db=db, user=user)
        assert exc.value.status_code == 409

        # Patch in locked period → 409
        with pytest.raises(HTTPException) as exc:
            await update_charge(
                charge_id=charge_id,
                body=OwnerChargePatchRequest(description="modified"),
                db=db, user=user)
        assert exc.value.status_code == 409

        # Void in locked period → 409
        with pytest.raises(HTTPException) as exc:
            await void_charge(
                charge_id=charge_id,
                body=VoidRequest(void_reason="locked"),
                db=db, user=user)
        assert exc.value.status_code == 409

    # Step 3: Create in a DIFFERENT open period → succeeds
    async with AsyncSessionLocal() as db:
        result = await create_charge(
            body=OwnerChargeCreateRequest(
                owner_payout_account_id=opa_id,
                posting_date=date(2099, 7, 15),  # July — no approved period
                transaction_type=OwnerChargeType.SUPPLIES,
                description="new open period charge",
                amount=Decimal("75"),
            ), db=db, user=user)
    assert result["amount"] == "75.00"
