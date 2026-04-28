"""
Tests for FLOS Phase 0a-7 UID watermark fix (INC-2026-04-28).

Each test below covers one failure mode of the prior `UNSEEN SINCE <date>`
SEARCH predicate, which silently dropped any message that anything
(webmail, Captain, operator) had marked \\Seen before the patrol fired.
The fix replaces it with a `UID <last+1>:*` watermark + bootstrap fallback.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

from backend.services.legal_mail_ingester import (
    LegalMailboxConfig,
    LegalMailIngesterTransport,
    _imap_date,
)


def _mailbox() -> LegalMailboxConfig:
    return LegalMailboxConfig(
        name="legal-cpanel",
        transport="imap",
        address="legal@cabin-rentals-of-georgia.com",
        routing_tag="legal",
        host="mail.example.com",
        port=993,
        credentials_ref="DUMMY_CRED_REF",
    )


def _conn_returning_uids(uid_list: list[bytes]) -> MagicMock:
    """Build a mock IMAP conn whose SEARCH returns the given UID bytes list,
    and whose FETCH returns a minimal RFC822 envelope per UID.
    """
    conn = MagicMock()
    captured = {"search_predicate": None}

    def uid_side_effect(*args):
        if not args:
            return ("BAD", [])
        verb = args[0]
        if verb == "SEARCH":
            captured["search_predicate"] = args[1]
            payload = b" ".join(uid_list) if uid_list else b""
            return ("OK", [payload])
        if verb == "FETCH":
            uid_arg = args[1]
            envelope = (
                b"From: sender@example.com\r\n"
                b"To: legal@cabin-rentals-of-georgia.com\r\n"
                b"Subject: test\r\n"
                b"Message-ID: <" + uid_arg.encode("ascii") + b"@test>\r\n"
                b"Date: Mon, 01 Apr 2026 12:00:00 +0000\r\n"
                b"\r\n"
                b"body\r\n"
            )
            return ("OK", [(b"1 (UID " + uid_arg.encode("ascii") + b" BODY[] {NN}", envelope), b")"])
        return ("BAD", [])

    conn.uid = MagicMock(side_effect=uid_side_effect)
    conn._captured = captured  # type: ignore[attr-defined]
    return conn


def test_fetch_recent_bootstrap_uses_since_band():
    """First patrol with NULL watermark uses SINCE date band, no UNSEEN."""
    transport = LegalMailIngesterTransport(_mailbox())
    conn = _conn_returning_uids([b"7"])

    records, new_uid = transport._fetch_with(conn, last_seen_uid=None)

    expected_since = _imap_date(date.today() - timedelta(days=transport.mailbox.search_band_days))
    predicate = conn._captured["search_predicate"]
    assert predicate == f"SINCE {expected_since}"
    assert "UNSEEN" not in predicate
    assert len(records) == 1
    assert new_uid == "7"


def test_fetch_recent_steady_state_uses_uid_watermark():
    """Subsequent patrol uses UID <last+1>:* predicate."""
    transport = LegalMailIngesterTransport(_mailbox())
    conn = _conn_returning_uids([b"43", b"44"])

    records, new_uid = transport._fetch_with(conn, last_seen_uid="42")

    assert conn._captured["search_predicate"] == "UID 43:*"
    assert "UNSEEN" not in conn._captured["search_predicate"]
    assert "SINCE" not in conn._captured["search_predicate"]
    assert len(records) == 2
    assert new_uid == "44"


def test_fetch_recent_filters_uid_quirk_at_or_below_watermark():
    """IMAP UID <next>:* may return a UID below next; filter it.

    The cPanel server returns the highest UID in the mailbox even when no
    messages have UID >= next. Without filtering we'd re-process old mail
    or set a phantom watermark.
    """
    transport = LegalMailIngesterTransport(_mailbox())
    # SEARCH UID 43:* returns [40, 50]: 40 must be dropped, 50 kept.
    conn = _conn_returning_uids([b"40", b"50"])

    records, new_uid = transport._fetch_with(conn, last_seen_uid="42")

    assert conn._captured["search_predicate"] == "UID 43:*"
    assert len(records) == 1
    assert records[0]["uid"] == "50"
    assert new_uid == "50"


def test_fetch_recent_no_new_messages_returns_unchanged_watermark():
    """When SEARCH returns empty, returned new_uid equals input."""
    transport = LegalMailIngesterTransport(_mailbox())
    conn = _conn_returning_uids([])

    records, new_uid = transport._fetch_with(conn, last_seen_uid="50")

    assert records == []
    # Watermark unchanged, NOT None — that would re-bootstrap next patrol.
    assert new_uid == "50"


def test_invalid_watermark_falls_back_to_bootstrap():
    """Garbage in the watermark column triggers bootstrap, not crash."""
    transport = LegalMailIngesterTransport(_mailbox())
    conn = _conn_returning_uids([b"5"])

    records, new_uid = transport._fetch_with(conn, last_seen_uid="NOT_A_NUMBER")

    expected_since = _imap_date(date.today() - timedelta(days=transport.mailbox.search_band_days))
    predicate = conn._captured["search_predicate"]
    assert predicate == f"SINCE {expected_since}"
    assert "UNSEEN" not in predicate
    assert len(records) == 1
    assert new_uid == "5"
