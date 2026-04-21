"""
Tests for EmailMessageService — inbound persistence and HITL workflow.

Parallel to (nonexistent) test_message_service.py for SMS.
Set TEST_DATABASE_URL to run against an isolated database; without it the tests
run against fortress_shadow (the dev DB) with a warning from conftest.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.email_inquirer import EmailInquirer
from backend.models.email_message import EmailMessage
from backend.services.email_message_service import EmailMessageService


# ── shared DB session fixture ─────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """
    Yield an async DB session backed by a savepoint so service commits land
    on the savepoint (not the outer transaction), allowing full rollback after
    each test.
    """
    from backend.core.database import async_session_factory
    async with async_session_factory() as session:
        await session.begin()
        nested = await session.begin_nested()
        yield session
        try:
            await nested.rollback()
        except Exception:
            pass
        try:
            await session.rollback()
        except Exception:
            pass


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def reviewer(db_session) -> UUID:
    """Create a minimal StaffUser and return its UUID for reviewer fields."""
    from backend.models.staff import StaffUser
    user = StaffUser(
        email=f"reviewer-{uuid4()}@crog.internal",
        password_hash="hashed",
        first_name="Test",
        last_name="Reviewer",
        role="admin",
    )
    db_session.add(user)
    await db_session.flush()
    return user.id


@pytest.fixture
def fake_imap_uid() -> int:
    import random
    return random.randint(100_000, 999_999)


@pytest.fixture
def fake_email_payload(fake_imap_uid):
    return {
        "email_from": "guest@example.com",
        "email_to": "reservations@cabin-rentals-of-georgia.com",
        "subject": "Weekend availability inquiry",
        "body_text": "Hi! Do you have any cabins available for Memorial Day weekend?",
        "imap_uid": fake_imap_uid,
        "message_id": f"<msg-{uuid4()}@example.com>",
        "received_at": datetime.now(tz=timezone.utc),
    }


# ── helpers ───────────────────────────────────────────────────────────────────

async def _make_svc(db: AsyncSession) -> EmailMessageService:
    return EmailMessageService(db)


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_receive_email_creates_inquirer_and_message(db_session, fake_email_payload):
    """receive_email creates a new EmailInquirer and EmailMessage row."""
    svc = await _make_svc(db_session)
    msg = await svc.receive_email(**fake_email_payload)

    assert isinstance(msg.id, UUID)
    assert msg.direction == "inbound"
    assert msg.email_from == fake_email_payload["email_from"]
    assert msg.imap_uid == fake_email_payload["imap_uid"]
    assert msg.approval_status == "pending_approval"
    assert msg.requires_human_review is True
    assert msg.inquirer_id is not None


@pytest.mark.asyncio
async def test_receive_email_idempotent(db_session, fake_email_payload):
    """Calling receive_email twice with the same imap_uid returns the same row."""
    svc = await _make_svc(db_session)
    msg1 = await svc.receive_email(**fake_email_payload)
    msg2 = await svc.receive_email(**fake_email_payload)

    assert msg1.id == msg2.id


@pytest.mark.asyncio
async def test_find_or_create_inquirer_deduplicates(db_session):
    """_find_or_create_inquirer returns the same inquirer for the same email."""
    svc = await _make_svc(db_session)
    email = f"testguest-{uuid4()}@example.com"
    i1 = await svc._find_or_create_inquirer(email, display_name=None)
    i2 = await svc._find_or_create_inquirer(email, display_name=None)
    assert i1.id == i2.id


@pytest.mark.asyncio
async def test_get_pending_drafts_empty(db_session):
    """get_pending_drafts returns an empty list when no drafts exist."""
    svc = await _make_svc(db_session)
    drafts = await svc.get_pending_drafts()
    assert isinstance(drafts, list)


@pytest.mark.asyncio
async def test_get_pending_drafts_shows_pending_approval(db_session, fake_email_payload):
    """A newly ingested email appears in get_pending_drafts."""
    svc = await _make_svc(db_session)
    msg = await svc.receive_email(**fake_email_payload)

    drafts = await svc.get_pending_drafts()
    msg_ids = [str(d["message_id"]) for d in drafts]
    assert str(msg.id) in msg_ids


@pytest.mark.asyncio
async def test_execute_rejection(db_session, fake_email_payload, reviewer):
    """execute_rejection marks the message rejected with reviewer metadata."""
    svc = await _make_svc(db_session)
    msg = await svc.receive_email(**fake_email_payload)

    reviewer_id = reviewer
    result = await svc.execute_rejection(msg.id, reviewer_id)

    assert result["status"] == "rejected"
    assert result["reviewer_id"] == reviewer_id
    assert result["smtp_message_id"] is None

    # Verify DB state
    refreshed = await db_session.get(EmailMessage, msg.id)
    assert refreshed.approval_status == "rejected"
    assert refreshed.human_reviewed_by == reviewer_id


@pytest.mark.asyncio
async def test_execute_rejection_wrong_status_raises(db_session, fake_email_payload, reviewer):
    """Cannot reject a message that's already been rejected."""
    svc = await _make_svc(db_session)
    msg = await svc.receive_email(**fake_email_payload)
    reviewer_id = reviewer

    await svc.execute_rejection(msg.id, reviewer_id)

    with pytest.raises(ValueError, match="Cannot reject"):
        await svc.execute_rejection(msg.id, reviewer_id)


@pytest.mark.asyncio
async def test_execute_approval_sends_via_smtp(db_session, fake_email_payload, reviewer):
    """execute_approval_and_dispatch calls SMTPDispatcher and marks sent."""
    svc = await _make_svc(db_session)
    msg = await svc.receive_email(**fake_email_payload)

    # Manually set ai_draft so there's something to send
    msg.ai_draft = "Thank you for your inquiry! We'll get back to you shortly."
    await db_session.flush()

    reviewer_id = reviewer

    smtp_mock = AsyncMock(return_value={"success": True, "smtp_message_id": "mock-smtp-id"})
    with patch(
        "backend.services.email_message_service.SMTPDispatcher.send_quote",
        smtp_mock,
    ):
        result = await svc.execute_approval_and_dispatch(msg.id, reviewer_id)

    assert result["status"] == "sent"
    assert result["smtp_message_id"] == "mock-smtp-id"

    refreshed = await db_session.get(EmailMessage, msg.id)
    assert refreshed.approval_status == "sent"
    assert refreshed.sent_at is not None


@pytest.mark.asyncio
async def test_execute_approval_smtp_failure_marks_send_failed(db_session, fake_email_payload, reviewer):
    """If SMTP fails, approval_status becomes send_failed (no exception raised)."""
    svc = await _make_svc(db_session)
    msg = await svc.receive_email(**fake_email_payload)
    msg.ai_draft = "Draft reply text."
    await db_session.flush()

    reviewer_id = reviewer
    smtp_mock = AsyncMock(return_value={"success": False, "error": "smtp_not_configured"})
    with patch(
        "backend.services.email_message_service.SMTPDispatcher.send_quote",
        smtp_mock,
    ):
        result = await svc.execute_approval_and_dispatch(msg.id, reviewer_id)

    assert result["status"] == "send_failed"

    refreshed = await db_session.get(EmailMessage, msg.id)
    assert refreshed.approval_status == "send_failed"
    assert refreshed.error_code == "smtp_failed"


@pytest.mark.asyncio
async def test_link_inquirer_to_guest(db_session, fake_email_payload):
    """link_inquirer_to_guest back-fills guest_id on all linked messages."""
    svc = await _make_svc(db_session)
    msg = await svc.receive_email(**fake_email_payload)

    # Simulate a guest being created
    from backend.models.guest import Guest
    fake_guest = Guest(phone_number=f"+1555{uuid4().int % 10_000_000:07d}")
    db_session.add(fake_guest)
    await db_session.flush()
    await db_session.refresh(fake_guest)

    await svc.link_inquirer_to_guest(msg.inquirer_id, fake_guest.id)

    refreshed_msg = await db_session.get(EmailMessage, msg.id)
    assert refreshed_msg.guest_id == fake_guest.id

    refreshed_inquirer = await db_session.get(EmailInquirer, msg.inquirer_id)
    assert refreshed_inquirer.guest_id == fake_guest.id
