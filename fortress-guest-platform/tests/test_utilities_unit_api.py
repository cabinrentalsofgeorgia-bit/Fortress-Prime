"""Unit tests for backend.api.utilities with strict mock isolation and zero IO."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import utilities as api


class _FakeScalars:
    """Scalar list adapter compatible with endpoint expectations."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeResult:
    """Fake SQL result supporting scalar_one/scalar_one_or_none/scalars/iteration."""

    def __init__(self, scalar_value=None, scalar_one_value=None, rows=None, iter_rows=None):
        self._scalar_value = scalar_value
        self._scalar_one_value = scalar_one_value
        self._rows = rows or []
        self._iter_rows = iter_rows or []

    def scalar_one(self):
        return self._scalar_one_value

    def scalar_one_or_none(self):
        return self._scalar_value

    def scalars(self):
        return _FakeScalars(self._rows)

    def __iter__(self):
        return iter(self._iter_rows)


class _FakeDB:
    """Async DB double with queued results and mutation tracking."""

    def __init__(self):
        self._results = []
        self._objects = {}
        self.added = []
        self.deleted = []
        self.commits = 0
        self.refreshes = 0

    def queue_result(self, result):
        self._results.append(result)

    def put(self, model, key, value):
        self._objects[(id(model), str(key))] = value

    async def execute(self, *_args, **_kwargs):
        if not self._results:
            return _FakeResult()
        return self._results.pop(0)

    async def get(self, model, key):
        return self._objects.get((id(model), str(key)))

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        self.refreshes += 1
        # Simulate DB-assigned defaults for pydantic response validation.
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        if getattr(obj, "is_active", None) is None:
            obj.is_active = True
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.utcnow()
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = datetime.utcnow()


def _utility_obj(**overrides):
    """Build fake utility row object with fields used by API responses."""
    base = {
        "id": uuid4(),
        "property_id": uuid4(),
        "service_type": "internet",
        "provider_name": "ISP Co",
        "account_number": "A-1",
        "account_holder": "Owner",
        "portal_url": "https://portal",
        "portal_username": "user",
        "portal_password_enc": "enc",
        "contact_phone": "555-1111",
        "contact_email": "owner@example.com",
        "notes": "note",
        "monthly_budget": Decimal("100.00"),
        "is_active": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _reading_obj(**overrides):
    """Build fake reading row object for list/reading endpoints."""
    base = {
        "id": uuid4(),
        "utility_id": uuid4(),
        "reading_date": date.today(),
        "cost": Decimal("45.10"),
        "usage_amount": Decimal("10.5"),
        "usage_unit": "kwh",
        "notes": None,
        "created_at": datetime.utcnow(),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_encrypt_decrypt_and_masking_paths(monkeypatch):
    """Validates encryption/decryption helper behavior including masking on decrypt failure."""
    api._fernet_key = None
    cipher = api._encrypt("secret-value")
    assert cipher != "secret-value"
    assert api._decrypt(cipher) == "secret-value"
    assert api._decrypt("") == ""
    assert api._encrypt("") == ""
    assert api._decrypt("definitely-not-valid-ciphertext") == "********"


@pytest.mark.asyncio
async def test_list_service_types_and_property_utilities():
    """Validates utility listing and cost aggregation logic with mocked SQL responses only."""
    out_types = await api.list_service_types(_user=SimpleNamespace(id="u"))
    assert "internet" in out_types

    db = _FakeDB()
    utility = _utility_obj()
    db.queue_result(_FakeResult(rows=[utility]))  # utility list
    db.queue_result(_FakeResult(scalar_one_value=Decimal("12.50")))  # mtd
    db.queue_result(_FakeResult(scalar_one_value=Decimal("55.00")))  # ytd
    db.queue_result(_FakeResult(scalar_one_value=date(2026, 2, 20)))  # latest

    rows = await api.list_property_utilities(
        property_id=utility.property_id,
        is_active=True,
        db=db,
        _user=SimpleNamespace(id="u"),
    )
    assert len(rows) == 1
    assert rows[0].provider_name == "ISP Co"
    assert rows[0].total_cost_mtd == 12.5
    assert rows[0].total_cost_ytd == 55.0
    assert rows[0].latest_reading_date == "2026-02-20"


@pytest.mark.asyncio
async def test_create_update_delete_and_reveal_password(monkeypatch):
    """Validates utility CRUD plus password reveal using mocked encryption and DB primitives."""
    db = _FakeDB()
    monkeypatch.setattr(api, "_encrypt", lambda plaintext: f"enc::{plaintext}")
    monkeypatch.setattr(api, "_decrypt", lambda ciphertext: "revealed-password")

    payload = api.UtilityCreate(
        property_id=uuid4(),
        service_type="water",
        provider_name="Water Co",
        portal_password="raw-secret",
    )
    created = await api.create_utility(payload, db=db, _user=SimpleNamespace(id="mgr"))
    assert created.provider_name == "Water Co"
    assert created.has_portal_password is True
    assert db.commits == 1
    assert db.refreshes == 1

    utility_id = db.added[0].id
    db.put(api.PropertyUtility, utility_id, db.added[0])

    updated = await api.update_utility(
        utility_id=utility_id,
        body=api.UtilityUpdate(provider_name="Updated Water", portal_password="new-secret"),
        db=db,
        _user=SimpleNamespace(id="mgr"),
    )
    assert updated.provider_name == "Updated Water"
    assert db.added[0].portal_password_enc == "enc::new-secret"

    reveal = await api.reveal_password(
        utility_id=utility_id,
        db=db,
        user=SimpleNamespace(id="mgr"),
    )
    assert reveal["password"] == "revealed-password"

    removed = await api.delete_utility(utility_id=utility_id, db=db, _user=SimpleNamespace(id="mgr"))
    assert removed["status"] == "deleted"
    assert len(db.deleted) == 1


@pytest.mark.asyncio
async def test_utility_not_found_edges():
    """Validates 404 branches for missing utility and reading records."""
    db = _FakeDB()
    missing_utility = uuid4()
    with pytest.raises(HTTPException) as up_exc:
        await api.update_utility(
            utility_id=missing_utility,
            body=api.UtilityUpdate(provider_name="x"),
            db=db,
            _user=SimpleNamespace(id="mgr"),
        )
    assert up_exc.value.status_code == 404

    with pytest.raises(HTTPException) as pw_exc:
        await api.reveal_password(missing_utility, db=db, user=SimpleNamespace(id="mgr"))
    assert pw_exc.value.status_code == 404

    missing_reading = uuid4()
    with pytest.raises(HTTPException) as rd_exc:
        await api.delete_reading(missing_reading, db=db, _user=SimpleNamespace(id="mgr"))
    assert rd_exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_and_list_readings(monkeypatch):
    """Validates reading create/list flow with no filesystem or network access."""
    db = _FakeDB()
    util = _utility_obj()
    db.put(api.PropertyUtility, util.id, util)

    reading_payload = api.ReadingCreate(
        reading_date=date(2026, 2, 1),
        cost=80.5,
        usage_amount=200.0,
        usage_unit="kwh",
    )
    created = await api.add_reading(util.id, reading_payload, db=db, _user=SimpleNamespace(id="staff"))
    assert created.cost == 80.5
    assert created.usage_unit == "kwh"
    assert db.commits == 1

    db.queue_result(_FakeResult(rows=[_reading_obj(utility_id=util.id)]))
    rows = await api.list_readings(
        utility_id=util.id,
        start=date(2026, 1, 1),
        end=date(2026, 12, 31),
        limit=10,
        db=db,
        _user=SimpleNamespace(id="staff"),
    )
    assert len(rows) == 1
    assert rows[0].utility_id == util.id


@pytest.mark.asyncio
async def test_add_reading_missing_dependency_branch():
    """Validates add_reading fails cleanly when target utility dependency is absent."""
    db = _FakeDB()
    with pytest.raises(HTTPException) as exc:
        await api.add_reading(
            utility_id=uuid4(),
            data=api.ReadingCreate(cost=10.0),
            db=db,
            _user=SimpleNamespace(id="staff"),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_analytics_paths_and_period_branches():
    """Validates per-property and portfolio analytics aggregation over mocked query result rows."""
    property_id = uuid4()
    db = _FakeDB()

    db.queue_result(
        _FakeResult(
            iter_rows=[
                SimpleNamespace(service_type="internet", total=Decimal("100.0")),
                SimpleNamespace(service_type="water", total=Decimal("50.0")),
            ]
        )
    )
    db.queue_result(
        _FakeResult(
            iter_rows=[
                SimpleNamespace(reading_date=date(2026, 2, 1), service_type="internet", cost=Decimal("20.0")),
                SimpleNamespace(reading_date=date(2026, 2, 2), service_type="water", cost=Decimal("10.0")),
            ]
        )
    )
    monkey_property = SimpleNamespace(name="Cabin A")
    # Property class is imported inside utility_cost_analytics; this fake is keyed by id(model), key.
    from backend.models import Property
    db.put(Property, property_id, monkey_property)

    out = await api.utility_cost_analytics(
        property_id=property_id,
        period="last30",
        db=db,
        _user=SimpleNamespace(id="staff"),
    )
    assert out.total == 150.0
    assert out.by_service["internet"] == 100.0
    assert len(out.daily_breakdown) == 2

    db2 = _FakeDB()
    db2.queue_result(
        _FakeResult(
            iter_rows=[
                SimpleNamespace(id=uuid4(), name="Cabin A", service_type="internet", total=Decimal("25.0")),
                SimpleNamespace(id=uuid4(), name="Cabin B", service_type="water", total=Decimal("15.0")),
            ]
        )
    )
    portfolio = await api.portfolio_cost_summary(
        period="last90",
        db=db2,
        _user=SimpleNamespace(id="staff"),
    )
    assert portfolio["period"] == "last90"
    assert portfolio["grand_total"] == 40.0
    assert len(portfolio["properties"]) == 2
