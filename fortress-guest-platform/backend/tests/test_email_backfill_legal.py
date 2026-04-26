"""Tests for backend.scripts.email_backfill_legal — PR I email backfill.

IMAP, Postgres, and Qdrant are mocked. The classifier is exercised against
synthetic ParsedEmail fixtures. The pipeline is exercised end-to-end with
a fake LegacySession + fake process_vault_upload.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

import run  # noqa: F401  registers backend.* path
from backend.scripts import email_backfill_legal as ebl


# ─── classifier helpers ──────────────────────────────────────────────────


def _mk(*, message_id="<msg-1@x>", sender="counsel@msp-lawfirm.com",
        sender_addr=None, to=("gary@cabin-rentals-of-georgia.com",),
        cc=(), subject="", body="", internaldate=date(2023, 6, 15)):
    sender_addr = sender_addr or (sender.split("<")[-1].rstrip(">").strip().lower()
                                    if "<" in sender else sender.lower())
    return ebl.ParsedEmail(
        message_id=message_id, sender=sender, sender_addr=sender_addr,
        to_addrs=list(to), cc_addrs=list(cc),
        subject=subject, body_snippet=body.lower(),
        internaldate=internaldate, raw_bytes=b"raw",
    )


# ─── 1. Classifier — explicit Case I docket ──────────────────────────────


def test_classifier_explicit_case_i_docket_routes_to_case_i():
    msg = _mk(subject="RE: 7IL Properties LLC v. Knight, 2:21-cv-00226-RWS",
              internaldate=date(2022, 5, 10))
    r = ebl.classify_email(msg)
    assert r.case_slug == "7il-v-knight-ndga-i"
    assert "2:21-cv-00226" in r.matched_terms
    assert r.privileged is True   # sender is msp-lawfirm.com (counsel domain)


# ─── 2. Classifier — explicit Case II docket ─────────────────────────────


def test_classifier_explicit_case_ii_docket_routes_to_case_ii():
    msg = _mk(subject="Re: 2:26-cv-00113 status",
              internaldate=date(2026, 3, 1))
    r = ebl.classify_email(msg)
    assert r.case_slug == "7il-v-knight-ndga-ii"
    assert "2:26-cv-00113" in r.matched_terms


# ─── 3. Classifier — Vanderburge keyword ─────────────────────────────────


def test_classifier_vanderburge_keyword_routes_to_vanderburge():
    msg = _mk(subject="Re: Vanderburge easement settlement draft",
              internaldate=date(2020, 8, 10))
    r = ebl.classify_email(msg)
    assert r.case_slug == "vanderburge-v-knight-fannin"
    assert any(t in r.matched_terms for t in ("vanderburge", "easement"))


# ─── 4. Classifier — Sanker 2019 with no other signal → quarantine ───────


def test_classifier_sanker_2019_no_other_signal_quarantines():
    """Sanker emails in 2019-2020 are ambiguous (Vanderburge active period
    overlaps with Case I pre-filing prep). Should land in quarantine."""
    msg = _mk(sender="jsank@msp-lawfirm.com",
              subject="checking in on the matter",
              body="please review the attached and let me know your thoughts.",
              internaldate=date(2019, 10, 20))
    r = ebl.classify_email(msg)
    assert r.case_slug is None
    assert "needs human review" in r.reason or "review" in r.reason


# ─── 5. Classifier — Sanker 2026+ no signal → Case II ────────────────────


def test_classifier_sanker_2026_routes_to_case_ii():
    msg = _mk(sender="jsank@msp-lawfirm.com",
              subject="status update",
              internaldate=date(2026, 4, 1))
    r = ebl.classify_email(msg)
    assert r.case_slug == "7il-v-knight-ndga-ii"


# ─── 6. Classifier — Sanker 2023 no signal → Case I ──────────────────────


def test_classifier_sanker_2023_routes_to_case_i():
    msg = _mk(sender="jsank@msp-lawfirm.com",
              subject="discovery responses",
              internaldate=date(2023, 6, 15))
    r = ebl.classify_email(msg)
    assert r.case_slug == "7il-v-knight-ndga-i"


# ─── 7. Classifier — Sanker with cc Podesta → Case I ─────────────────────


def test_classifier_sanker_with_cc_podesta_routes_to_case_i():
    msg = _mk(sender="jsank@msp-lawfirm.com",
              cc=("fpodesta@fgplaw.com",),
              subject="trial prep meeting",
              internaldate=date(2024, 3, 5))
    r = ebl.classify_email(msg)
    assert r.case_slug == "7il-v-knight-ndga-i"
    assert "fgplaw" in r.reason or "your-side" in r.reason


# ─── 8. Classifier — Sanker with cc Frank Moore → Vanderburge ────────────


def test_classifier_sanker_with_cc_frank_moore_routes_to_vanderburge():
    msg = _mk(sender="jsank@msp-lawfirm.com",
              cc=("frank.moore@somefirm.com",),
              subject="settlement terms",
              internaldate=date(2020, 7, 10))
    r = ebl.classify_email(msg)
    assert r.case_slug == "vanderburge-v-knight-fannin"
    assert "moore" in r.reason.lower()


# ─── 9. Classifier — opposing counsel routes to work-product ─────────────


def test_classifier_opposing_counsel_routes_to_work_product():
    msg = _mk(sender="bgoldberg@somefirm.com",
              sender_addr="bgoldberg@somefirm.com",
              subject="discovery response from plaintiff",
              body="please find attached the production",
              internaldate=date(2023, 4, 1))
    r = ebl.classify_email(msg)
    # Opposing counsel matches → 7IL case; not privileged
    assert r.case_slug in ("7il-v-knight-ndga-i", "7il-v-knight-ndga-ii")
    assert r.privileged is False


# ─── 10. Classifier — unmatched email → quarantine ───────────────────────


def test_classifier_unmatched_email_quarantines():
    msg = _mk(sender="newsletter@example.com",
              sender_addr="newsletter@example.com",
              subject="weekly newsletter",
              body="random marketing content",
              internaldate=date(2024, 1, 15),
              cc=(), to=("gary@cabin-rentals-of-georgia.com",))
    r = ebl.classify_email(msg)
    assert r.case_slug is None
    assert r.privileged is False


# ─── 11. message_file_hash uses Message-Id when available ────────────────


def test_message_file_hash_uses_message_id_when_present():
    msg_a = _mk(message_id="<unique@example.com>")
    msg_a.raw_bytes = b"different bytes"
    msg_b = _mk(message_id="<unique@example.com>")
    msg_b.raw_bytes = b"completely different bytes"
    assert ebl.message_file_hash(msg_a) == ebl.message_file_hash(msg_b)


def test_message_file_hash_falls_back_to_raw_bytes_when_no_msg_id():
    msg_a = ebl.ParsedEmail(message_id="", sender="", sender_addr="",
                              to_addrs=[], cc_addrs=[], subject="",
                              body_snippet="", internaldate=None,
                              raw_bytes=b"first content")
    msg_b = ebl.ParsedEmail(message_id="", sender="", sender_addr="",
                              to_addrs=[], cc_addrs=[], subject="",
                              body_snippet="", internaldate=None,
                              raw_bytes=b"second content")
    assert ebl.message_file_hash(msg_a) != ebl.message_file_hash(msg_b)


# ─── 12. email_file_name shape ──────────────────────────────────────────


def test_email_file_name_format():
    msg = _mk(sender="jsank@msp-lawfirm.com", sender_addr="jsank@msp-lawfirm.com",
              subject="Re: trial prep",
              internaldate=date(2024, 3, 5))
    name = ebl.email_file_name(msg)
    assert name.endswith(".eml")
    assert "20240305" in name
    assert "jsank" in name
    assert "trial-prep" in name or "trial" in name


# ─── 13. parse_email handles minimal RFC-822 ────────────────────────────


def test_parse_email_minimal():
    raw = (b"From: alice@dralaw.com\r\n"
            b"To: gary@cabin-rentals-of-georgia.com\r\n"
            b"Subject: closing docs\r\n"
            b"Message-ID: <abc-123@dralaw.com>\r\n"
            b"\r\n"
            b"please review attached\r\n")
    parsed = ebl.parse_email(raw, date(2025, 6, 1))
    assert parsed is not None
    assert parsed.sender_addr == "alice@dralaw.com"
    assert "gary@cabin-rentals-of-georgia.com" in parsed.to_addrs
    assert parsed.subject == "closing docs"
    assert parsed.message_id == "<abc-123@dralaw.com>"


# ─── 14. parse_email returns None on bad input ─────────────────────────


def test_parse_email_returns_none_on_bad_bytes():
    parsed = ebl.parse_email(b"\xff\xfe garbage \x00\x01", date(2020, 1, 1))
    # email_module is permissive — bad bytes still parse but yield empty fields.
    # Either None or a parsed-but-empty result is acceptable.
    assert parsed is None or parsed.sender_addr == ""


# ─── 15. classifier — username-only match falls under date window ───────


def test_classifier_username_match_with_date_window():
    msg = _mk(sender="general@some.com", sender_addr="general@some.com",
              subject="re: argo for closing", body="",
              internaldate=date(2024, 8, 1),
              to=("gary@cabin-rentals-of-georgia.com",))
    r = ebl.classify_email(msg)
    # 'argo' is in USERNAME_TERMS_BY_CASE for case_i; date 2024 within window
    assert r.case_slug == "7il-v-knight-ndga-i"


# ─── 16. classify rule precedence — docket beats domain ────────────────


def test_classifier_docket_beats_domain():
    """Even if Sanker is sender, an explicit Case II docket in subject wins."""
    msg = _mk(sender="jsank@msp-lawfirm.com",
              subject="2:26-cv-00113 motion to dismiss",
              internaldate=date(2023, 1, 1))  # weird date but explicit docket wins
    r = ebl.classify_email(msg)
    assert r.case_slug == "7il-v-knight-ndga-ii"


# ─── 17. classify — date_bands utility ─────────────────────────────────


def test_date_bands_6mo_stride():
    bands = ebl.date_bands(date(2018, 1, 1), date(2019, 1, 1), months=6)
    assert len(bands) == 2
    assert bands[0] == (date(2018, 1, 1), date(2018, 7, 1))
    assert bands[1] == (date(2018, 7, 1), date(2019, 1, 1))


# ─── 18. lock file — concurrent run rejected ────────────────────────────


def test_lock_file_prevents_concurrent_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(ebl, "_lock_path", lambda case: tmp_path / f"l-{case}.lock")
    (tmp_path / "l-c.lock").write_text("99999\nstamp\n")
    with pytest.raises(SystemExit) as ei:
        ebl.acquire_lock("c", force=False)
    assert "another backfill" in str(ei.value)


# ─── 19. lock file — force overrides stale lock ────────────────────────


def test_lock_file_force_overrides_stale_lock(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(ebl, "_lock_path", lambda case: tmp_path / f"l-{case}.lock")
    p = tmp_path / "l-c.lock"
    p.write_text("99999\nstamp\n")
    # Backdate to >6h ago
    old = ebl.LOCK_STALE_AFTER_S + 100
    os.utime(str(p), (p.stat().st_atime - old, p.stat().st_mtime - old))
    lock = ebl.acquire_lock("c", force=True)
    assert lock.exists()
    ebl.release_lock(lock)


# ─── 20. Mocked end-to-end — single email round-trip ─────────────────


@pytest.mark.asyncio
async def test_ingest_email_full_pipeline_mocked(monkeypatch, tmp_path):
    """Mock LegacySession + process_vault_upload; verify _ingest_email returns
    'ingested' and triggers mirror."""

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def _fake_upload(*, db, case_slug, file_bytes, file_name, mime_type):
        assert mime_type == "message/rfc822"
        assert file_name.endswith(".eml")
        return {"status": "completed", "document_id": "id-x",
                "chunks": 4, "vectors_indexed": 4}

    mirror_calls = []

    def _fake_mirror(case_slug, doc_id):
        mirror_calls.append((case_slug, doc_id))

    def _fake_check_existing(case_slug, file_hash):
        return None

    monkeypatch.setattr("backend.services.ediscovery_agent.LegacySession",
                        lambda: _FakeSession())
    monkeypatch.setattr("backend.services.legal_ediscovery.process_vault_upload",
                        _fake_upload)
    monkeypatch.setattr(ebl, "_check_existing_row", _fake_check_existing)
    monkeypatch.setattr(ebl, "_mirror_row_db_to_prod", _fake_mirror)

    parsed = _mk(sender="fpodesta@fgplaw.com",
                  sender_addr="fpodesta@fgplaw.com",
                  subject="case I trial prep notes",
                  internaldate=date(2024, 5, 15))
    cls = ebl.classify_email(parsed)
    outcome = await ebl._ingest_email(parsed, cls)
    assert outcome.status == "ingested"
    assert outcome.case_slug == "7il-v-knight-ndga-i"
    assert outcome.document_id == "id-x"
    assert mirror_calls == [("7il-v-knight-ndga-i", "id-x")]


# ─── 21. _ingest_email — quarantine returns 'quarantined' status ─────


@pytest.mark.asyncio
async def test_ingest_email_quarantine_returns_quarantined():
    parsed = _mk(sender="x@example.com", sender_addr="x@example.com",
                  subject="random unmatched", internaldate=date(2024, 1, 1))
    cls = ebl.ClassificationResult(case_slug=None, privileged=False,
                                     reason="no match", matched_terms=[])
    outcome = await ebl._ingest_email(parsed, cls)
    assert outcome.status == "quarantined"
    assert outcome.case_slug is None


# ─── 22. _ingest_email — duplicate skipped via _check_existing_row ──


@pytest.mark.asyncio
async def test_ingest_email_duplicate_skipped(monkeypatch):
    """If file_hash already exists with terminal status, skip without
    calling process_vault_upload."""
    upload_called = {"n": 0}

    async def _fake_upload(**kwargs):
        upload_called["n"] += 1
        return {"status": "completed", "document_id": "x"}

    monkeypatch.setattr(ebl, "_check_existing_row",
                        lambda case_slug, file_hash: "completed")
    monkeypatch.setattr("backend.services.ediscovery_agent.LegacySession",
                        lambda: object())
    monkeypatch.setattr("backend.services.legal_ediscovery.process_vault_upload",
                        _fake_upload)

    parsed = _mk(sender="fpodesta@fgplaw.com",
                  sender_addr="fpodesta@fgplaw.com",
                  subject="known email", internaldate=date(2024, 5, 15))
    cls = ebl.classify_email(parsed)
    outcome = await ebl._ingest_email(parsed, cls)
    assert outcome.status == "duplicate"
    assert upload_called["n"] == 0


# ─── 23. classify — Lissa Knight with vanderburge keyword → vanderburge


def test_classifier_lissa_with_vanderburge_keyword():
    msg = _mk(sender="someone@example.com",
              sender_addr="someone@example.com",
              subject="lissa knight + vanderburge property",
              internaldate=date(2020, 4, 1))
    r = ebl.classify_email(msg)
    assert r.case_slug == "vanderburge-v-knight-fannin"


# ─── 24. CLI — args parse with sane defaults ────────────────────────────


def test_cli_args_sane_defaults():
    args = ebl._parse_args(["--case-slug", "test"])
    assert args.case_slug == "test"
    assert args.mailbox == "gary-gk,gary-crog"
    assert args.since == "2018-01-01"
    assert args.until is not None  # set to today by default
    assert args.dry_run is False
    assert args.rollback is False
    assert args.jobs == 4


# ─── 25. CLI — rollback flag isolated path ──────────────────────────────


def test_cli_rollback_flag_present():
    args = ebl._parse_args(["--case-slug", "test", "--rollback", "--force"])
    assert args.rollback is True
    assert args.force is True


# ─── 26. classifier — empty subject + body still classifies on sender ──


def test_classifier_empty_subject_uses_sender_domain():
    msg = _mk(sender="alice@dralaw.com",
              sender_addr="alice@dralaw.com",
              subject="", body="",
              internaldate=date(2025, 6, 1))
    r = ebl.classify_email(msg)
    # dralaw.com is in case_i counsel domains; date 2025 within window
    assert r.case_slug == "7il-v-knight-ndga-i"
    assert r.privileged is True
