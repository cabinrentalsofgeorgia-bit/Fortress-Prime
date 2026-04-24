"""
Tests for the Captain junk filter — three-tier classifier that gates
access to the privilege filter + capture writes.

All LLM calls are stubbed; no real Ollama / network traffic.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from backend.services import captain_junk_filter as junk_mod
from backend.services import captain_multi_mailbox as captain_mod
from backend.services.captain_junk_filter import (
    JunkDecision,
    classify_junk,
)
from backend.services.captain_multi_mailbox import (
    FetchedEmail,
    MailboxConfig,
    process_email,
    run_patrol,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mailbox(
    name: str = "legal-cpanel",
    address: str = "legal@cabin-rentals-of-georgia.com",
    routing_tag: str = "legal",
) -> MailboxConfig:
    return MailboxConfig(
        name=name,
        transport="imap",
        address=address,
        routing_tag=routing_tag,
        host="mail.cabin-rentals-of-georgia.com",
        port=993,
        credentials_ref="MAILPLUS_PASSWORD_TEST",
        poll_interval_sec=120,
    )


def _email(
    subject: str = "hello",
    body: str = "routine message body",
    sender: str = "jane@example.com",
    headers: dict[str, list[str]] | None = None,
) -> FetchedEmail:
    return FetchedEmail(
        subject=subject, body=body, sender_email=sender,
        headers=headers or {},
    )


def _force_llm_returning(monkeypatch, decision: JunkDecision) -> dict[str, int]:
    """Replace _check_llm with a fake. Returns a counter of calls."""
    calls = {"count": 0}

    async def fake(em: FetchedEmail) -> JunkDecision:
        calls["count"] += 1
        return decision

    monkeypatch.setattr(junk_mod, "_check_llm", fake)
    return calls


# ─────────────────────────────────────────────────────────────────────────────
# 1. test_junk_header_list_unsubscribe_routes_junk
# ─────────────────────────────────────────────────────────────────────────────

class TestJunkHeaderListUnsubscribeRoutesJunk:
    def test_junk_header_list_unsubscribe_routes_junk(self, monkeypatch):
        monkeypatch.setattr(junk_mod, "_check_llm", None)  # must not be called
        em = _email(
            sender="analyst@bloomberg.net",
            headers={"list-unsubscribe": ["<mailto:u@bb.net>"]},
        )
        decision = asyncio.run(classify_junk(em))
        assert decision.is_junk is True
        assert decision.category == "newsletter"
        assert decision.reason == "header_list_unsubscribe"
        assert decision.confidence == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. test_junk_header_precedence_bulk_routes_junk
# ─────────────────────────────────────────────────────────────────────────────

class TestJunkHeaderPrecedenceBulkRoutesJunk:
    @pytest.mark.parametrize("value", ["bulk", "list", "junk", "BULK", "  Bulk  "])
    def test_junk_header_precedence_bulk_routes_junk(self, monkeypatch, value):
        monkeypatch.setattr(junk_mod, "_check_llm", None)
        em = _email(headers={"precedence": [value]})
        decision = asyncio.run(classify_junk(em))
        assert decision.is_junk is True
        assert decision.reason == "header_precedence_bulk"
        assert decision.category == "newsletter"


# ─────────────────────────────────────────────────────────────────────────────
# 3. test_junk_sender_noreply_routes_junk
# ─────────────────────────────────────────────────────────────────────────────

class TestJunkSenderNoreplyRoutesJunk:
    @pytest.mark.parametrize("addr", [
        "noreply@stripe.com",
        "no-reply@amazonaws.com",
        "donotreply@airbnb.com",
        "do-not-reply@somewhere.com",
        "NoReply@mixedcase.com",
    ])
    def test_junk_sender_noreply_routes_junk(self, monkeypatch, addr):
        monkeypatch.setattr(junk_mod, "_check_llm", None)
        em = _email(sender=addr)
        decision = asyncio.run(classify_junk(em))
        assert decision.is_junk is True
        assert decision.category == "notification"
        assert decision.reason == "sender_noreply"


# ─────────────────────────────────────────────────────────────────────────────
# 4. test_junk_sender_mailchimp_domain_routes_junk
# ─────────────────────────────────────────────────────────────────────────────

class TestJunkSenderMailchimpDomainRoutesJunk:
    @pytest.mark.parametrize("addr", [
        "newsletter@mcsv.net",
        "campaign@rsgsv.net",
        "sender@sendgrid.net",
        "foo@amazonses.com",
        "bar@mailgun.net",
    ])
    def test_junk_sender_mailchimp_domain_routes_junk(self, monkeypatch, addr):
        monkeypatch.setattr(junk_mod, "_check_llm", None)
        em = _email(sender=addr)
        decision = asyncio.run(classify_junk(em))
        assert decision.is_junk is True
        assert decision.category in {"marketing", "newsletter"}
        assert decision.reason in {
            "sender_esp_relay_domain",
            "sender_newsletter_localpart",
        }


# ─────────────────────────────────────────────────────────────────────────────
# 5. test_junk_legal_email_with_no_junk_signals_passes_through
# ─────────────────────────────────────────────────────────────────────────────

class TestJunkLegalEmailWithNoJunkSignalsPassesThrough:
    def test_junk_legal_email_with_no_junk_signals_passes_through(self, monkeypatch):
        """
        Realistic opposing-counsel email: no bulk headers, a personal
        sender address. Tier-3 LLM says is_junk=False. Must reach the
        downstream privilege filter (i.e. classify_junk returns is_junk=False).
        """
        _force_llm_returning(monkeypatch, JunkDecision(
            is_junk=False, category="legal",
            reason="llm_legal_correspondence", confidence=0.92,
        ))
        em = _email(
            subject="RE: Johnson v CROG — Rule 26 disclosures",
            body="Counsel — see attached the plaintiff's Rule 26 disclosures.",
            sender="jdoe@opposingfirm.com",
        )
        decision = asyncio.run(classify_junk(em))
        assert decision.is_junk is False


# ─────────────────────────────────────────────────────────────────────────────
# 6. test_junk_llm_timeout_fails_open
# ─────────────────────────────────────────────────────────────────────────────

class TestJunkLlmTimeoutFailsOpen:
    def test_junk_llm_timeout_fails_open(self, monkeypatch):
        """
        httpx.TimeoutException during the tier-3 call must NOT raise and
        must NOT route to junk. Email falls through to the privilege
        filter as if junk filtering were disabled for this message.
        """
        import httpx

        class _FakeClient:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *args, **kwargs):
                raise httpx.TimeoutException("timed out")

        monkeypatch.setattr(junk_mod.httpx, "AsyncClient", _FakeClient)
        monkeypatch.setenv("TASK_CLASSIFIER_OLLAMA_URL", "http://stub:11434")

        em = _email(
            subject="quick question",
            body="Hi Gary — any chance we can chat tomorrow?",
            sender="normal@person.com",
        )
        decision = asyncio.run(classify_junk(em))
        assert decision.is_junk is False
        assert decision.category == "unknown"
        assert decision.reason == "llm_timeout"
        assert decision.confidence == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 7. test_junk_ordering_header_before_sender_before_llm
# ─────────────────────────────────────────────────────────────────────────────

class TestJunkOrderingHeaderBeforeSenderBeforeLlm:
    def test_junk_ordering_header_before_sender_before_llm(self, monkeypatch):
        """
        If all three tiers would fire, the header tier must win (=> LLM
        never called). We plant an exploding LLM stub: any call fails
        the test.
        """
        def _boom_llm(*_args, **_kwargs):
            raise AssertionError("LLM must not be consulted when headers match")

        monkeypatch.setattr(junk_mod, "_check_llm", _boom_llm)

        # Noreply sender (tier 2 would match) + List-Unsubscribe header
        # (tier 1 matches) — expect tier-1 verdict.
        em = _email(
            sender="noreply@news.bloomberg.net",
            headers={"list-unsubscribe": ["<mailto:u@bb.net>"]},
        )
        decision = asyncio.run(classify_junk(em))
        assert decision.reason == "header_list_unsubscribe"

    def test_sender_before_llm(self, monkeypatch):
        """Tier 2 matches, no headers → LLM must not fire."""
        def _boom_llm(*_args, **_kwargs):
            raise AssertionError("LLM must not be consulted when sender matches")

        monkeypatch.setattr(junk_mod, "_check_llm", _boom_llm)
        em = _email(sender="noreply@stripe.com")
        decision = asyncio.run(classify_junk(em))
        assert decision.reason == "sender_noreply"


# ─────────────────────────────────────────────────────────────────────────────
# 8. test_patrol_report_includes_junk_counters
# ─────────────────────────────────────────────────────────────────────────────

class TestPatrolReportIncludesJunkCounters:
    @pytest.mark.asyncio
    async def test_patrol_report_includes_junk_counters(self, monkeypatch):
        """
        Feed 3 emails to a mocked mailbox: 1 newsletter (junk), 1 marketing
        (junk), 1 legitimate (allow). Patrol report must reflect
        junk=2, allow=1, and the by_junk_category breakdown.
        """
        monkeypatch.setattr(
            captain_mod.settings, "captain_junk_filter_enabled", True,
            raising=False,
        )

        emails_to_deliver = [
            _email(
                subject="Bloomberg morning briefing",
                sender="news@bloomberg.net",
                headers={"list-unsubscribe": ["<mailto:u@bb.net>"]},
            ),
            _email(
                subject="Big sale this weekend",
                sender="promo@amazonses.com",
            ),
            _email(
                subject="Re: contract revision",
                sender="counsel@firm.example",
                body="Please review the attached contract changes.",
            ),
        ]

        def fake_fetch(self) -> list[FetchedEmail]:
            return list(emails_to_deliver)

        monkeypatch.setattr(
            captain_mod.ImapTransport, "fetch_unseen", fake_fetch,
        )

        # The non-junk email reaches write_capture — stub the DB writer.
        writes: list[str] = []

        async def fake_write(em, mailbox, decision, session_factory=None):
            writes.append(decision.route.value)
            return decision.route.value

        monkeypatch.setattr(captain_mod, "write_capture", fake_write)

        result = await run_patrol(mailboxes=[_mailbox()])

        assert result["processed"] == 3
        assert result["junk"] == 2
        assert result["allow"] == 1
        assert result["restricted"] == 0
        assert result["block"] == 0
        assert result["by_junk_category"] == {"newsletter": 1, "marketing": 1}
        assert result["by_tag"] == {"legal": 3}
        # Only the non-junk email hit the write path.
        assert writes == ["allow"]


# ─────────────────────────────────────────────────────────────────────────────
# 9. test_privilege_filter_not_called_when_email_is_junk
# ─────────────────────────────────────────────────────────────────────────────

class TestPrivilegeFilterNotCalledWhenEmailIsJunk:
    @pytest.mark.asyncio
    async def test_privilege_filter_not_called_when_email_is_junk(
        self, monkeypatch,
    ):
        """
        Efficiency: a junk email must short-circuit before classify_email
        (which calls privilege_filter.classify_for_capture) is touched.
        Also asserts write_capture is never reached.
        """
        monkeypatch.setattr(
            captain_mod.settings, "captain_junk_filter_enabled", True,
            raising=False,
        )

        classify_spy = MagicMock(side_effect=AssertionError(
            "classify_email must not be called for junk mail"
        ))
        monkeypatch.setattr(captain_mod, "classify_email", classify_spy)

        async def explode_write(*args, **kwargs):
            raise AssertionError("write_capture must not be called for junk mail")
        monkeypatch.setattr(captain_mod, "write_capture", explode_write)

        em = _email(
            sender="newsletter@mailgun.net",  # tier-2 ESP relay domain
            headers={"list-unsubscribe": ["<https://u.mailgun.net/x>"]},
        )

        result = await process_email(em, _mailbox())
        assert result["route"] == "junk"
        assert result["junk_category"] == "newsletter"
        classify_spy.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Bonus — flag-off passthrough (ensures rollback works without revert)
# ─────────────────────────────────────────────────────────────────────────────

class TestJunkFilterDisabledSkipsEntirely:
    @pytest.mark.asyncio
    async def test_flag_false_bypasses_junk_classifier(self, monkeypatch):
        monkeypatch.setattr(
            captain_mod.settings, "captain_junk_filter_enabled", False,
            raising=False,
        )

        # If junk classifier were called, this would fire.
        async def _boom(em):
            raise AssertionError("classify_junk must not be called when flag is off")

        monkeypatch.setattr(junk_mod, "classify_junk", _boom)

        # The path therefore runs straight to classify_email + write_capture.
        class _FakeDecision:
            route = type("_R", (), {"value": "allow"})()
            reason = "ok"
            matched_patterns: tuple[str, ...] = ()
        monkeypatch.setattr(
            captain_mod, "classify_email", lambda *_: _FakeDecision(),
        )

        async def fake_write(em, mailbox, decision, session_factory=None):
            return decision.route.value
        monkeypatch.setattr(captain_mod, "write_capture", fake_write)

        em = _email(
            sender="noreply@stripe.com",                  # tier-2 match, ignored
            headers={"list-unsubscribe": ["<u@x.com>"]},  # tier-1 match, ignored
        )
        result = await process_email(em, _mailbox())
        assert result["route"] == "allow"
