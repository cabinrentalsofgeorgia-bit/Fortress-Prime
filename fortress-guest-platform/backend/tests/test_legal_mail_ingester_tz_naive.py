"""
Tests for FLOS Phase 0a-8 tz-naive sent_at fix (INC-2026-04-28, Bug #2).

email_archive.sent_at is TIMESTAMP WITHOUT TIME ZONE. RFC 2822 Date headers
delivered by IMAP carry a UTC offset, so parsedate_to_datetime() returns an
aware datetime. asyncpg refuses to encode an aware datetime into a naive
column ("can't subtract offset-naive and offset-aware datetimes"), which
silently dropped every legal mail message during the INC-2026-04-28
incident. parse_message() now converts to UTC and strips tzinfo.
"""
from __future__ import annotations

from backend.services.legal_mail_ingester import parse_message


_SOURCE = {
    "uid": "1",
    "host": "h",
    "folder": "INBOX",
    "mailbox_alias": "test",
    "transport": "imap",
}


def test_parse_message_strips_tz_aware_sent_at():
    """RFC 2822 Date headers with TZ offset must produce naive UTC datetime."""
    raw = (
        b"Date: Tue, 28 Apr 2026 09:22:54 -0400\r\n"
        b"From: test@example.com\r\n"
        b"To: legal@example.com\r\n"
        b"Subject: Test\r\n"
        b"Message-ID: <abc@test>\r\n"
        b"\r\n"
        b"Body\r\n"
    )

    parsed = parse_message(raw, source=_SOURCE, routing_tag="legal")

    assert parsed is not None
    assert parsed.sent_at is not None
    assert parsed.sent_at.tzinfo is None
    # 09:22:54 -0400 == 13:22:54 UTC
    assert parsed.sent_at.hour == 13
    assert parsed.sent_at.minute == 22
    assert parsed.sent_at.second == 54


def test_parse_message_naive_utc_date_header_passes_through():
    """A Date header already in UTC (+0000) must also yield naive UTC."""
    raw = (
        b"Date: Mon, 01 Apr 2026 12:00:00 +0000\r\n"
        b"From: a@example.com\r\n"
        b"To: legal@example.com\r\n"
        b"Subject: Test\r\n"
        b"Message-ID: <utc@test>\r\n"
        b"\r\n"
        b"Body\r\n"
    )

    parsed = parse_message(raw, source=_SOURCE, routing_tag="legal")

    assert parsed is not None
    assert parsed.sent_at is not None
    assert parsed.sent_at.tzinfo is None
    assert parsed.sent_at.hour == 12


def test_parse_message_missing_date_yields_none_sent_at():
    """No Date header must not crash; sent_at is None."""
    raw = (
        b"From: a@example.com\r\n"
        b"To: legal@example.com\r\n"
        b"Subject: Test\r\n"
        b"Message-ID: <nodate@test>\r\n"
        b"\r\n"
        b"Body\r\n"
    )

    parsed = parse_message(raw, source=_SOURCE, routing_tag="legal")

    assert parsed is not None
    assert parsed.sent_at is None


def test_parse_message_unparseable_date_yields_none_sent_at():
    """Garbage in Date header must not crash; sent_at is None."""
    raw = (
        b"Date: not-a-real-date\r\n"
        b"From: a@example.com\r\n"
        b"To: legal@example.com\r\n"
        b"Subject: Test\r\n"
        b"Message-ID: <baddate@test>\r\n"
        b"\r\n"
        b"Body\r\n"
    )

    parsed = parse_message(raw, source=_SOURCE, routing_tag="legal")

    assert parsed is not None
    assert parsed.sent_at is None
