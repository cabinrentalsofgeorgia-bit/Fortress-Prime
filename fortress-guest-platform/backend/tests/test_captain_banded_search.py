"""Issue #260 — Captain banded SEARCH for gary-gk overflow.

Unbounded UNSEEN SEARCH against gary-gk returned >1MB UID list, overflowing
the IMAP client buffer ('got more than 1000000 bytes'). Banded SEARCH
(UNSEEN + SINCE date) bounds the result set per FLOS Phase 0a v1.1 §3.2
(legal_mail_ingester precedent).
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from backend.services.captain_multi_mailbox import ImapTransport, MailboxConfig


@pytest.fixture
def imap_transport() -> ImapTransport:
    cfg = MailboxConfig(
        name="gary-gk",
        transport="imap",
        address="gary@garyknight.com",
        routing_tag="executive",
        host="imap.example.test",
        port=993,
        credentials_ref="MAILPLUS_PASSWORD_GARY",
        poll_interval_sec=120,
    )
    return ImapTransport(cfg, max_messages=25)


def test_banded_search_uses_since_clause(imap_transport: ImapTransport) -> None:
    """SEARCH command always pairs UNSEEN with SINCE."""
    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b""])

    imap_transport._search_unseen_banded(mock_conn)

    args = mock_conn.search.call_args[0]
    assert args[0] is None  # charset
    assert "UNSEEN" in args
    assert "SINCE" in args


def test_banded_search_cold_start_uses_30_day_floor(
    imap_transport: ImapTransport,
) -> None:
    """When no last_patrol_at state exists, SINCE = today - 30 days."""
    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b""])

    imap_transport._search_unseen_banded(mock_conn)

    args = mock_conn.search.call_args[0]
    since_idx = args.index("SINCE")
    since_str = args[since_idx + 1]
    since_dt = datetime.strptime(since_str, "%d-%b-%Y").replace(tzinfo=timezone.utc)
    expected_floor = datetime.now(timezone.utc) - timedelta(days=30)

    assert abs((since_dt - expected_floor).total_seconds()) < 86400


def test_banded_search_returns_empty_on_search_failure(
    imap_transport: ImapTransport,
) -> None:
    """If SEARCH returns non-OK, log warning and return []. Patrol continues."""
    mock_conn = MagicMock()
    mock_conn.search.return_value = ("NO", [b"some error"])

    result = imap_transport._search_unseen_banded(mock_conn)

    assert result == []


def test_banded_search_returns_empty_when_no_results(
    imap_transport: ImapTransport,
) -> None:
    """OK response with empty data returns empty list — no spurious fetches."""
    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b""])

    result = imap_transport._search_unseen_banded(mock_conn)

    assert result == []


def test_banded_search_parses_uid_list(imap_transport: ImapTransport) -> None:
    """OK response with whitespace-delimited UIDs returns parsed list."""
    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b"101 102 103"])

    result = imap_transport._search_unseen_banded(mock_conn)

    assert result == [b"101", b"102", b"103"]


def test_no_unbounded_search_path_remains() -> None:
    """Regression guard: no SEARCH call site issues UNSEEN without a SINCE clause."""
    import backend.services.captain_multi_mailbox as captain_module

    src = inspect.getsource(captain_module)
    assert "SEARCH ALL" not in src.upper()

    # Inspect every place where UNSEEN appears as a SEARCH argument.
    # Allowed forms: ("UNSEEN", "SINCE", ...) sequence, or "(UNSEEN SINCE ...)"
    upper = src.upper()
    idx = 0
    while True:
        idx = upper.find('"UNSEEN"', idx)
        if idx == -1:
            break
        window = upper[idx : idx + 200]
        assert "SINCE" in window, (
            f"'UNSEEN' arg found without nearby 'SINCE' clause near offset {idx}"
        )
        idx += len('"UNSEEN"')


def test_fetch_with_uses_banded_search(imap_transport: ImapTransport) -> None:
    """_fetch_with now routes through _search_unseen_banded."""
    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b""])

    imap_transport._fetch_with(mock_conn)

    # search() must have been called with SINCE in the criteria
    assert mock_conn.search.called
    args = mock_conn.search.call_args[0]
    assert "SINCE" in args
