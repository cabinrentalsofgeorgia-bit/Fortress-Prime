"""
Tests for the multi-mailbox Captain.

All tests avoid prod DB mutations — writes are captured by an in-memory
FakeSession. Transports (IMAP / Gmail API) are stubbed so the suite runs
without network or credentials.
"""
from __future__ import annotations

import asyncio
import imaplib
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.services.captain_multi_mailbox import (
    FetchedEmail,
    GmailApiTransport,
    ImapTransport,
    MailboxConfig,
    MailboxConfigError,
    classify_email,
    load_mailbox_configs,
    process_email,
    run_patrol,
)
from backend.services.privilege_filter import CaptureRoute


# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────

class FakeSession:
    """Captures SQL + params without hitting a real database."""

    def __init__(self, recorder: list[tuple[str, dict]]) -> None:
        self._recorder = recorder
        self.commits = 0

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def execute(self, stmt, params: dict | None = None) -> None:
        # stmt is a sqlalchemy TextClause — its str() contains the SQL text.
        self._recorder.append((str(stmt), dict(params or {})))

    async def commit(self) -> None:
        self.commits += 1


def make_fake_factory(recorder: list[tuple[str, dict]]):
    def _factory() -> FakeSession:
        return FakeSession(recorder)
    return _factory


def _mailbox(
    name: str = "mb",
    transport: str = "imap",
    address: str = "x@example.com",
    routing_tag: str = "operations",
    host: str = "mail.example.com",
    credentials_ref: str = "FAKE_PASSWORD",
) -> MailboxConfig:
    return MailboxConfig(
        name=name,
        transport=transport,
        address=address,
        routing_tag=routing_tag,
        host=host,
        port=993,
        credentials_ref=credentials_ref,
        poll_interval_sec=120,
    )


def _email(
    subject: str = "hello",
    body: str = "",
    sender: str = "sender@example.com",
    recipients: list[str] | None = None,
    attachments: list[str] | None = None,
) -> FetchedEmail:
    return FetchedEmail(
        subject=subject,
        body=body,
        sender_email=sender,
        recipient_emails=recipients or [],
        attachment_filenames=attachments or [],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Config parsing
# ─────────────────────────────────────────────────────────────────────────────

class TestMailboxConfigLoading:
    def test_empty_config_returns_empty_list(self):
        assert load_mailbox_configs("") == []
        assert load_mailbox_configs("[]") == []

    def test_invalid_json_raises(self):
        with pytest.raises(MailboxConfigError):
            load_mailbox_configs("not-json")

    def test_invalid_transport_raises(self):
        raw = json.dumps([{
            "name": "x", "transport": "smtp", "address": "a@b.c",
            "routing_tag": "legal",
        }])
        with pytest.raises(MailboxConfigError):
            load_mailbox_configs(raw)

    def test_invalid_routing_tag_raises(self):
        raw = json.dumps([{
            "name": "x", "transport": "imap", "address": "a@b.c",
            "routing_tag": "random", "host": "h",
            "credentials_ref": "SOME_ENV",
        }])
        with pytest.raises(MailboxConfigError):
            load_mailbox_configs(raw)

    def test_duplicate_address_raises(self):
        raw = json.dumps([
            {"name": "a", "transport": "imap", "address": "x@y.z",
             "routing_tag": "legal", "host": "h", "credentials_ref": "E1"},
            {"name": "b", "transport": "imap", "address": "X@y.z",
             "routing_tag": "legal", "host": "h", "credentials_ref": "E2"},
        ])
        with pytest.raises(MailboxConfigError):
            load_mailbox_configs(raw)


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — routing tag recorded on every capture
# ─────────────────────────────────────────────────────────────────────────────

class TestCaptainRoutesByTag:
    @pytest.mark.asyncio
    async def test_captain_routes_by_tag(self):
        mailboxes = [
            _mailbox("legal-cpanel", address="legal@c.com",
                     routing_tag="legal"),
            _mailbox("gary-crog", address="gary@c.com",
                     routing_tag="executive"),
            _mailbox("info-crog", address="info@c.com",
                     routing_tag="operations"),
            _mailbox("gary-gk", address="gary@gk.com",
                     routing_tag="executive"),
        ]
        recorder: list[tuple[str, dict]] = []
        factory = make_fake_factory(recorder)

        for mb in mailboxes:
            em = _email(
                subject=f"note for {mb.name}",
                body="routine checkin",
                sender="guest@example.com",
            )
            result = await process_email(em, mb, session_factory=factory)
            assert result["routing_tag"] == mb.routing_tag
            assert result["route"] == CaptureRoute.ALLOW.value

        # Every write stashes routing_tag inside the meta JSON payload.
        tags_seen: list[str] = []
        for sql, params in recorder:
            assert "INSERT INTO llm_training_captures" in sql
            meta = json.loads(params["meta"])
            tags_seen.append(meta["routing_tag"])
            assert meta["source_mailbox"]
            # source_module carries the tag too — test harness can check either.
            assert params["module"].startswith("captain_")

        assert tags_seen == ["legal", "executive", "operations", "executive"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — privilege filter sends privileged mail to restricted_captures
# ─────────────────────────────────────────────────────────────────────────────

class TestPrivilegeFilterHook:
    @pytest.mark.asyncio
    async def test_captain_privilege_filter_hook_restricted(self, monkeypatch):
        monkeypatch.setenv("ATTORNEY_DOMAINS", "jonesfirm.law")
        mb = _mailbox("legal-cpanel", address="legal@c.com", routing_tag="legal")
        em = _email(
            subject="Discovery update",
            body="Please review — ATTORNEY-CLIENT PRIVILEGED work product.",
            sender="partner@jonesfirm.law",
            attachments=["motion.pdf"],
        )

        decision = classify_email(em, mb)
        assert decision.route == CaptureRoute.RESTRICTED
        assert any("attorney_domain" in p or "keyword:" in p
                   for p in decision.matched_patterns)

        recorder: list[tuple[str, dict]] = []
        factory = make_fake_factory(recorder)
        result = await process_email(em, mb, session_factory=factory)

        assert result["route"] == CaptureRoute.RESTRICTED.value
        assert len(recorder) == 1
        sql, params = recorder[0]
        assert "INSERT INTO restricted_captures" in sql
        assert "INSERT INTO llm_training_captures" not in sql
        assert "jonesfirm.law" in params["reason"] \
            or "keyword:" in params["reason"] \
            or "text_marker:" in params["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — Gmail API pagination
# ─────────────────────────────────────────────────────────────────────────────

class TestGmailApiPagination:
    def test_captain_gmail_api_pagination(self):
        """
        Stub the Gmail API `messages().list()` to return 3 pages, each with a
        pageToken pointing at the next. The transport must chain through all
        of them and fetch every message.
        """
        pages = [
            {"messages": [{"id": "m1"}, {"id": "m2"}], "nextPageToken": "tok1"},
            {"messages": [{"id": "m3"}, {"id": "m4"}], "nextPageToken": "tok2"},
            {"messages": [{"id": "m5"}]},  # no nextPageToken → last page
        ]
        list_calls: list[dict] = []
        get_calls: list[str] = []

        def _mk_raw(mid: str) -> str:
            import base64
            body = (
                f"Subject: msg-{mid}\r\n"
                f"From: s@e.com\r\n"
                f"To: r@e.com\r\n\r\n"
                f"body-{mid}"
            ).encode()
            return base64.urlsafe_b64encode(body).decode()

        class FakeList:
            def __init__(self, params: dict) -> None:
                self.params = params

            def execute(self) -> dict:
                list_calls.append(self.params)
                token = self.params.get("pageToken")
                if token is None:
                    return pages[0]
                if token == "tok1":
                    return pages[1]
                if token == "tok2":
                    return pages[2]
                return {"messages": []}

        class FakeGet:
            def __init__(self, mid: str) -> None:
                self.mid = mid

            def execute(self) -> dict:
                get_calls.append(self.mid)
                return {"raw": _mk_raw(self.mid)}

        class FakeModify:
            def execute(self) -> dict:
                return {}

        class FakeMessages:
            def list(self, **kwargs) -> FakeList:
                return FakeList(kwargs)

            def get(self, userId: str, id: str, format: str) -> FakeGet:
                return FakeGet(id)

            def modify(self, userId: str, id: str, body: dict) -> FakeModify:
                return FakeModify()

        class FakeUsers:
            def messages(self) -> FakeMessages:
                return FakeMessages()

        class FakeService:
            def users(self) -> FakeUsers:
                return FakeUsers()

        mb = MailboxConfig(
            name="gmail-test", transport="gmail_api",
            address="x@gmail.com", routing_tag="operations",
        )
        transport = GmailApiTransport(mb, client_factory=lambda: FakeService())
        emails = transport.fetch_unseen()

        # 3 list calls → covers all pages.
        assert len(list_calls) == 3
        # First call: no pageToken; subsequent calls carry the token.
        assert list_calls[0].get("pageToken") is None
        assert list_calls[1]["pageToken"] == "tok1"
        assert list_calls[2]["pageToken"] == "tok2"

        # All 5 messages were fetched.
        assert get_calls == ["m1", "m2", "m3", "m4", "m5"]
        assert len(emails) == 5
        assert [e.subject for e in emails] == [
            "msg-m1", "msg-m2", "msg-m3", "msg-m4", "msg-m5"
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — four IMAP mailboxes on one host each get polled
# ─────────────────────────────────────────────────────────────────────────────

class TestImapMultiMailboxSingleHost:
    @pytest.mark.asyncio
    async def test_captain_imap_multi_mailbox_single_host(self, monkeypatch):
        """
        Four IMAP mailboxes on the same host. Each opens its own connection
        (cPanel does not pool reliably). run_patrol must iterate all four and
        produce one capture per mailbox.
        """
        host = "mail.cabin-rentals-of-georgia.com"
        mailboxes = [
            _mailbox("legal",  address="legal@crog.com",
                     routing_tag="legal",     host=host,
                     credentials_ref="PW_LEGAL"),
            _mailbox("gary",   address="gary@crog.com",
                     routing_tag="executive", host=host,
                     credentials_ref="PW_GARY"),
            _mailbox("info",   address="info@crog.com",
                     routing_tag="operations", host=host,
                     credentials_ref="PW_INFO"),
            _mailbox("gary_gk", address="gary@gk.com",
                     routing_tag="executive", host=host,
                     credentials_ref="PW_GARY_GK"),
        ]
        for ref in ("PW_LEGAL", "PW_GARY", "PW_INFO", "PW_GARY_GK"):
            monkeypatch.setenv(ref, "dummy-pass")

        connections_opened: list[tuple[str, int]] = []

        # Stub ImapTransport.fetch_unseen to record one connection per call
        # and return one fake email per mailbox.
        def fake_fetch(self: ImapTransport) -> list[FetchedEmail]:
            connections_opened.append((self.mailbox.host, self.mailbox.port))
            return [_email(
                subject=f"msg-for-{self.mailbox.name}",
                body="hello",
                sender=f"sender-{self.mailbox.name}@outside.com",
            )]

        monkeypatch.setattr(ImapTransport, "fetch_unseen", fake_fetch)

        recorder: list[tuple[str, dict]] = []
        factory = make_fake_factory(recorder)

        result = await run_patrol(
            mailboxes=mailboxes,
            session_factory=factory,
        )

        assert result["mailboxes"] == 4
        assert result["processed"] == 4
        assert len(connections_opened) == 4
        # All four calls targeted the same host.
        assert {h for (h, _) in connections_opened} == {host}
        # Routing tags recorded in the write metadata.
        tags = sorted(
            json.loads(params["meta"])["routing_tag"]
            for _, params in recorder
        )
        assert tags == ["executive", "executive", "legal", "operations"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — IMAP reconnect after disconnect
# ─────────────────────────────────────────────────────────────────────────────

class TestImapIdleReconnect:
    def test_captain_imap_idle_reconnect(self, monkeypatch):
        """
        First `_connect` call raises an IMAP4.abort (simulates cPanel dropping
        the idle connection). The transport must reconnect once and succeed.
        """
        mb = _mailbox(
            "legal", address="legal@crog.com", routing_tag="legal",
            host="mail.example.com", credentials_ref="FAKE_PW",
        )
        monkeypatch.setenv("FAKE_PW", "x")

        attempts: list[int] = []

        def fake_connect(self: ImapTransport) -> Any:
            attempts.append(len(attempts) + 1)
            if len(attempts) == 1:
                raise imaplib.IMAP4.abort("connection dropped")
            # Second attempt: return a mock connection that returns no unseen.
            conn = MagicMock(spec=imaplib.IMAP4_SSL)
            conn.search.return_value = ("OK", [b""])
            return conn

        monkeypatch.setattr(ImapTransport, "_connect", fake_connect)

        transport = ImapTransport(mb)
        emails = transport.fetch_unseen()

        assert emails == []
        assert len(attempts) == 2, "expected one reconnect after initial abort"
        assert transport.reconnect_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — worker startup respects the flag
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkerStartupRespectsFlag:
    def test_captain_worker_startup_respects_flag(self, monkeypatch):
        """
        When LEGAL_EMAIL_INTAKE_ENABLED=False, worker.startup must NOT spawn
        the captain_multi_mailbox_task.
        """
        from backend.core import worker

        # Neutralize every other conditional path in startup so we can focus
        # on the captain spawn gate. Only flags relevant to that gate matter.
        monkeypatch.setenv("SEO_GRADING_CONSUMER_ENABLED", "0")
        monkeypatch.setenv("SEO_REWRITE_CONSUMER_ENABLED", "0")
        monkeypatch.setenv("SEO_DEPLOY_CONSUMER_ENABLED", "0")

        # Flip everything off; set legal_email_intake_enabled=False.
        for attr, val in [
            ("semrush_shadow_observer_enabled", False),
            ("research_scout_enabled", False),
            ("concierge_shadow_draft_enabled", False),
            ("hunter_queue_sweep_enabled", False),
            ("async_job_watchdog_enabled", False),
            ("legal_email_intake_enabled", False),
        ]:
            monkeypatch.setattr(worker.settings, attr, val, raising=False)

        async def _fake_noop_async(*args, **kwargs):
            return None

        class _FakeStreamlineVRS:
            def __init__(self) -> None:
                self.is_configured = False

        monkeypatch.setattr(worker, "enforce_sovereign_boundary", _fake_noop_async)
        monkeypatch.setattr(worker, "StreamlineVRS", _FakeStreamlineVRS)

        ctx: dict[str, Any] = {}
        asyncio.run(worker.startup(ctx))

        assert "captain_multi_mailbox_task" not in ctx
        assert "legal_intake_task" not in ctx
