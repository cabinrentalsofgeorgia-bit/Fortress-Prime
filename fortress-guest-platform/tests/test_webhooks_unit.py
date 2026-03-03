"""Unit tests for webhook handlers with mocked dependencies."""

from types import SimpleNamespace

import pytest

from backend.api import webhooks as wh


class _FakeRequest:
    def __init__(self, form_payload):
        self._form_payload = form_payload

    async def form(self):
        return self._form_payload


class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeDB:
    def __init__(self):
        self.added = []
        self.committed = False
        self.message_for_status = None

    async def get(self, *_args, **_kwargs):
        return None

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self.message_for_status)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_handle_incoming_sms_success_queues_for_review(monkeypatch):
    fake_db = _FakeDB()
    request = _FakeRequest(
        {
            "From": "+17065551234",
            "Body": "Need late checkout",
            "MessageSid": "SM_TEST_IN_001",
        }
    )

    class _FakeTwilioClient:
        def parse_webhook(self, form_data):
            assert "From" in form_data
            return {"from": form_data["From"], "body": form_data["Body"], "message_sid": form_data["MessageSid"]}

    class _FakeMessageService:
        def __init__(self, _db, _twilio):
            pass

        async def receive_sms(self, **_kwargs):
            return SimpleNamespace(
                id="msg1",
                guest_id=None,
                reservation_id=None,
                intent=None,
                sentiment=None,
                category=None,
                requires_human_review=False,
            )

        async def send_sms(self, **_kwargs):
            return SimpleNamespace(id="out1")

    class _FakeDecision:
        intent = SimpleNamespace(value="request")
        sentiment = SimpleNamespace(label="neutral", score=0.5, urgency_level=1)
        action = "queue"
        requires_human = True
        should_auto_send = False
        response_text = "We can help with that."
        confidence = 0.71
        escalation_reason = "manual_review"
        metadata = {"source": "unit-test"}

    class _FakeOrchestrator:
        async def process_incoming_message(self, **_kwargs):
            return _FakeDecision()

    monkeypatch.setattr(wh, "TwilioClient", _FakeTwilioClient)
    monkeypatch.setattr(wh, "MessageService", _FakeMessageService)
    monkeypatch.setattr(wh, "AgenticOrchestrator", _FakeOrchestrator)

    resp = await wh.handle_incoming_sms(request=request, db=fake_db)
    assert resp.status_code == 200
    assert fake_db.committed is True
    assert len(fake_db.added) == 1


@pytest.mark.asyncio
async def test_handle_sms_status_updates_message(monkeypatch):
    fake_db = _FakeDB()
    fake_db.message_for_status = SimpleNamespace(
        id="m1",
        status="sent",
        error_code=None,
        error_message=None,
        delivered_at=None,
    )
    request = _FakeRequest(
        {
            "MessageSid": "SM_TEST_OUT_001",
            "MessageStatus": "delivered",
            "ErrorCode": "",
            "ErrorMessage": "",
        }
    )

    resp = await wh.handle_sms_status(request=request, db=fake_db)
    assert resp.status_code == 200
    assert fake_db.committed is True
    assert fake_db.message_for_status.status == "delivered"


@pytest.mark.asyncio
async def test_handle_sms_status_exception_returns_200():
    class _BadRequest:
        async def form(self):
            raise RuntimeError("boom")

    fake_db = _FakeDB()
    resp = await wh.handle_sms_status(request=_BadRequest(), db=fake_db)
    assert resp.status_code == 200
