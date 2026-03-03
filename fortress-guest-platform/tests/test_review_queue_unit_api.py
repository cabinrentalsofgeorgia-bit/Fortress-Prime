"""Unit tests for backend.api.review_queue handlers."""

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import review_queue as api


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeResult:
    def __init__(self, scalar_value=None, rows=None):
        self._scalar_value = scalar_value
        self._rows = rows or []

    def scalar(self):
        return self._scalar_value

    def scalar_one_or_none(self):
        return self._scalar_value

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeDB:
    def __init__(self):
        self._results = []
        self._objects = {}
        self.commits = 0

    def queue_result(self, result):
        self._results.append(result)

    def put(self, _model, key, value):
        self._objects[(id(_model), str(key))] = value

    async def get(self, model, key):
        return self._objects.get((id(model), str(key)))

    async def execute(self, *_args, **_kwargs):
        if not self._results:
            return _FakeResult()
        return self._results.pop(0)

    async def commit(self):
        self.commits += 1


def _mk_entry(status="pending"):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        created_at=now,
        intent="intent",
        sentiment_label="neutral",
        urgency_level=1,
        confidence=0.75,
        action="reply",
        escalation_reason=None,
        proposed_response="Hello there",
        final_response=None,
        reviewed_by=None,
        reviewed_at=None,
        decision_metadata={},
        message_id=uuid4(),
        guest_id=uuid4(),
        reservation_id=uuid4(),
        inbound_message=SimpleNamespace(phone_from="+1", body="in", created_at=now),
        guest=SimpleNamespace(full_name="Guest", phone_number="+1", total_stays=2),
        reservation=SimpleNamespace(id=uuid4()),
        sent_message_id=None,
    )


@pytest.mark.asyncio
async def test_list_queue_and_stats():
    db = _FakeDB()
    db.queue_result(_FakeResult(scalar_value=1))  # total
    db.queue_result(_FakeResult(rows=[_mk_entry()]))  # rows

    out = await api.list_queue(status="pending", limit=10, offset=0, db=db)
    assert out["total"] == 1
    assert len(out["items"]) == 1

    db.queue_result(_FakeResult(scalar_value=1))  # pending
    db.queue_result(_FakeResult(scalar_value=2))  # approved/sent
    db.queue_result(_FakeResult(scalar_value=1))  # rejected
    db.queue_result(_FakeResult(scalar_value=0))  # edited
    db.queue_result(_FakeResult(scalar_value=0.5))  # avg
    stats = await api.queue_stats(db=db)
    assert stats["pending"] == 1
    assert stats["approved"] == 2
    assert stats["total_reviewed"] == 3


@pytest.mark.asyncio
async def test_get_queue_entry_not_found():
    db = _FakeDB()
    with pytest.raises(HTTPException) as exc:
        await api.get_queue_entry(entry_id=uuid4(), db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_queue_entry_with_thread():
    db = _FakeDB()
    entry = _mk_entry()
    db.put(api.AgentResponseQueue, entry.id, entry)
    db.put(api.Message, entry.message_id, SimpleNamespace(body="msg", phone_from="+1", created_at=datetime.utcnow()))
    db.put(api.Guest, entry.guest_id, SimpleNamespace(id=entry.guest_id, full_name="Guest", phone_number="+1", total_stays=2))
    db.queue_result(_FakeResult(rows=[SimpleNamespace(direction="in", body="hello", created_at=datetime.utcnow(), is_auto_response=False)]))
    payload = await api.get_queue_entry(entry_id=entry.id, db=db)
    assert payload["entry"]["id"] == str(entry.id)
    assert payload["guest"]["name"] == "Guest"
    assert len(payload["conversation_thread"]) == 1


@pytest.mark.asyncio
async def test_approve_edit_reject_paths(monkeypatch):
    db = _FakeDB()
    entry = _mk_entry()
    db.put(api.AgentResponseQueue, entry.id, entry)

    async def _fake_send_response(db, entry, text):
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(api, "_send_response", _fake_send_response)
    approved = await api.approve_and_send(entry_id=entry.id, body=api.ApproveBody(reviewed_by="qa"), db=db)
    assert approved["status"] == "approved"

    entry2 = _mk_entry()
    db.put(api.AgentResponseQueue, entry2.id, entry2)
    edited = await api.edit_and_send(entry_id=entry2.id, body=api.EditBody(final_response="Updated", reviewed_by="qa"), db=db)
    assert edited["status"] == "edited"

    entry3 = _mk_entry()
    db.put(api.AgentResponseQueue, entry3.id, entry3)
    rejected = await api.reject_response(entry_id=entry3.id, body=api.RejectBody(reviewed_by="qa", reason="bad"), db=db)
    assert rejected["status"] == "rejected"
    assert entry3.decision_metadata["rejection_reason"] == "bad"


@pytest.mark.asyncio
async def test_send_response_missing_inbound():
    db = _FakeDB()
    entry = _mk_entry()
    entry.message_id = uuid4()
    with pytest.raises(HTTPException) as exc:
        await api._send_response(db=db, entry=entry, text="x")
    assert exc.value.status_code == 400
