"""Unit-style tests for backend.api.integrations handlers."""

import pytest
from fastapi import HTTPException

from backend.api import integrations as api


class _FakeVRS:
    def __init__(self):
        self.closed = False
        self.is_configured = True

    async def health_check(self):
        return {"status": "connected"}

    def get_sync_status(self):
        return {"last_sync": "now"}

    async def close(self):
        self.closed = True

    async def fetch_properties(self):
        return [{"id": 1}]

    async def fetch_reservations(self):
        return [{"id": 1, "raw": {"x": 1}}]

    async def fetch_owners(self):
        return [{"owner_id": 10}]

    async def fetch_owner_statement(self, **_kwargs):
        return {"statement": "ok"}

    async def fetch_guest_by_email(self, _email):
        return {"reservations": [{"client_id": 42}]}

    async def fetch_guest_history(self, _client_id):
        return [{"stay": "A"}]

    async def fetch_reservation_info(self, _code):
        return {"info": "ok"}

    async def fetch_reservation_price(self, _code):
        return {"price": "ok"}

    async def fetch_reservation_notes(self, _code):
        return [{"note": "ok"}]

    async def sync_all(self, _db):
        return {"created": 1}

    async def fetch_housekeeping_report(self, unit_id=None):
        return {"reservations": {"reservation": []}, "unit_id": unit_id}

    async def fetch_all_feedback(self):
        return [{"id": "1", "comment": "nice"}]


@pytest.mark.asyncio
async def test_streamline_status_ok(monkeypatch):
    monkeypatch.setattr(api, "StreamlineVRS", _FakeVRS)
    resp = await api.streamline_status()
    assert resp["provider"] == "Streamline VRS"
    assert resp["health"]["status"] == "connected"
    assert "sync" in resp


@pytest.mark.asyncio
async def test_preview_properties_success(monkeypatch):
    monkeypatch.setattr(api, "StreamlineVRS", _FakeVRS)
    resp = await api.preview_streamline_properties()
    assert resp["count"] == 1
    assert resp["properties"][0]["id"] == 1


@pytest.mark.asyncio
async def test_preview_reservations_strips_raw(monkeypatch):
    monkeypatch.setattr(api, "StreamlineVRS", _FakeVRS)
    resp = await api.preview_streamline_reservations()
    assert resp["count"] == 1
    assert "raw" not in resp["reservations"][0]


@pytest.mark.asyncio
async def test_list_owners_success(monkeypatch):
    monkeypatch.setattr(api, "StreamlineVRS", _FakeVRS)
    resp = await api.list_owners()
    assert resp["count"] == 1
    assert resp["owners"][0]["owner_id"] == 10


@pytest.mark.asyncio
async def test_owner_statement_success(monkeypatch):
    monkeypatch.setattr(api, "StreamlineVRS", _FakeVRS)
    resp = await api.get_owner_statement(owner_id=10, unit_id=None, start=None, end=None, include_pdf=False)
    assert resp["statement"] == "ok"


@pytest.mark.asyncio
async def test_guest_history_success(monkeypatch):
    monkeypatch.setattr(api, "StreamlineVRS", _FakeVRS)
    resp = await api.get_guest_history_by_email("guest@example.com")
    assert resp["email"] == "guest@example.com"
    assert resp["client_id"] == "42"
    assert len(resp["history"]) == 1


@pytest.mark.asyncio
async def test_guest_history_not_found(monkeypatch):
    class _NoGuestVRS(_FakeVRS):
        async def fetch_guest_by_email(self, _email):
            return None

    monkeypatch.setattr(api, "StreamlineVRS", _NoGuestVRS)
    with pytest.raises(HTTPException) as exc:
        await api.get_guest_history_by_email("missing@example.com")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_reservation_detail_success(monkeypatch):
    monkeypatch.setattr(api, "StreamlineVRS", _FakeVRS)
    resp = await api.get_reservation_detail("ABC123")
    assert resp["confirmation_code"] == "ABC123"
    assert resp["info"]["info"] == "ok"


@pytest.mark.asyncio
async def test_owner_statement_error_is_502(monkeypatch):
    class _ErrVRS(_FakeVRS):
        async def fetch_owner_statement(self, **_kwargs):
            raise RuntimeError("upstream fail")

    monkeypatch.setattr(api, "StreamlineVRS", _ErrVRS)
    with pytest.raises(HTTPException) as exc:
        await api.get_owner_statement(owner_id=1, unit_id=None, start=None, end=None, include_pdf=False)
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_trigger_sync_success(monkeypatch):
    monkeypatch.setattr(api, "StreamlineVRS", _FakeVRS)
    resp = await api.trigger_streamline_sync(db=object())
    assert resp["status"] == "ok"
    assert resp["summary"]["created"] == 1


@pytest.mark.asyncio
async def test_trigger_sync_error(monkeypatch):
    class _ErrVRS(_FakeVRS):
        async def sync_all(self, _db):
            raise RuntimeError("sync failed")

    monkeypatch.setattr(api, "StreamlineVRS", _ErrVRS)
    resp = await api.trigger_streamline_sync(db=object())
    assert resp["status"] == "error"
    assert "sync failed" in resp["message"]


@pytest.mark.asyncio
async def test_preview_properties_error(monkeypatch):
    class _ErrVRS(_FakeVRS):
        async def fetch_properties(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(api, "StreamlineVRS", _ErrVRS)
    resp = await api.preview_streamline_properties()
    assert "error" in resp


@pytest.mark.asyncio
async def test_preview_reservations_error(monkeypatch):
    class _ErrVRS(_FakeVRS):
        async def fetch_reservations(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(api, "StreamlineVRS", _ErrVRS)
    resp = await api.preview_streamline_reservations()
    assert "error" in resp


@pytest.mark.asyncio
async def test_list_owners_error(monkeypatch):
    class _ErrVRS(_FakeVRS):
        async def fetch_owners(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(api, "StreamlineVRS", _ErrVRS)
    resp = await api.list_owners()
    assert "error" in resp


@pytest.mark.asyncio
async def test_owner_statement_empty_message(monkeypatch):
    class _NoneVRS(_FakeVRS):
        async def fetch_owner_statement(self, **_kwargs):
            return None

    monkeypatch.setattr(api, "StreamlineVRS", _NoneVRS)
    resp = await api.get_owner_statement(owner_id=9, unit_id=1, start="2026-01-01", end="2026-01-31", include_pdf=True)
    assert resp["message"] == "No statement data returned"


@pytest.mark.asyncio
async def test_housekeeping_preview(monkeypatch):
    monkeypatch.setattr(api, "StreamlineVRS", _FakeVRS)
    resp = await api.preview_housekeeping_report(unit_id=7)
    assert "reservations" in resp
    assert resp["unit_id"] == 7


@pytest.mark.asyncio
async def test_housekeeping_preview_error(monkeypatch):
    class _ErrVRS(_FakeVRS):
        async def fetch_housekeeping_report(self, unit_id=None):
            raise RuntimeError("hk failed")

    monkeypatch.setattr(api, "StreamlineVRS", _ErrVRS)
    resp = await api.preview_housekeeping_report(unit_id=None)
    assert "error" in resp


@pytest.mark.asyncio
async def test_feedback_preview(monkeypatch):
    monkeypatch.setattr(api, "StreamlineVRS", _FakeVRS)
    resp = await api.preview_feedback()
    assert resp["count"] == 1


@pytest.mark.asyncio
async def test_feedback_preview_error(monkeypatch):
    class _ErrVRS(_FakeVRS):
        async def fetch_all_feedback(self):
            raise RuntimeError("fb failed")

    monkeypatch.setattr(api, "StreamlineVRS", _ErrVRS)
    resp = await api.preview_feedback()
    assert "error" in resp


@pytest.mark.asyncio
async def test_guest_history_upstream_error(monkeypatch):
    class _ErrVRS(_FakeVRS):
        async def fetch_guest_by_email(self, _email):
            raise RuntimeError("upstream")

    monkeypatch.setattr(api, "StreamlineVRS", _ErrVRS)
    with pytest.raises(HTTPException) as exc:
        await api.get_guest_history_by_email("guest@example.com")
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_reservation_detail_error(monkeypatch):
    class _ErrVRS(_FakeVRS):
        async def fetch_reservation_info(self, _code):
            raise RuntimeError("fail")

    monkeypatch.setattr(api, "StreamlineVRS", _ErrVRS)
    with pytest.raises(HTTPException) as exc:
        await api.get_reservation_detail("A1")
    assert exc.value.status_code == 502
