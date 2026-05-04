from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services.legal.email_intake_foundation import (
    EmailSourceDropSafetyError,
    build_source_drop_plan,
    normalize_subject,
    parse_email_bytes,
    validate_source_root,
    write_manifest,
)


def _raw_email(
    *,
    subject: str,
    sender: str = "Alicia Argo <alicia@dralaw.com>",
    cc: str = "Terry Wilson <twilson@wilsonpruittlaw.com>",
    body: str = "Please review the attached legal correspondence.",
) -> bytes:
    cc_header = f"Cc: {cc}\r\n" if cc else ""
    return (
        f"From: {sender}\r\n"
        "To: Gary Knight <gary@cabin-rentals-of-georgia.com>\r\n"
        f"{cc_header}"
        f"Subject: {subject}\r\n"
        "Message-ID: <msg-1@example.com>\r\n"
        "In-Reply-To: <root@example.com>\r\n"
        "References: <root@example.com> <prior@example.com>\r\n"
        "Date: Fri, 17 Apr 2026 14:30:00 -0400\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: multipart/mixed; boundary=frontier\r\n"
        "\r\n"
        "--frontier\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        f"{body}\r\n"
        "--frontier\r\n"
        "Content-Type: application/pdf\r\n"
        "Content-Disposition: attachment; filename=\"draft-easement.pdf\"\r\n"
        "\r\n"
        "PDFBYTES\r\n"
        "--frontier--\r\n"
    ).encode()


def test_parse_email_bytes_extracts_metadata_thread_and_attachment():
    candidate = parse_email_bytes(
        _raw_email(
            subject="[External] Re: 2:26-cv-00113 easement draft",
            body="Please review the attached easement and 2:26-cv-00113 strategy notes.",
        ),
        source_path=Path("/tmp/source/email.eml"),
        source_root=Path("/tmp/source"),
    )

    assert candidate.source_relative_path == "email.eml"
    assert candidate.message_id == "<msg-1@example.com>"
    assert candidate.thread_key == "ref:<root@example.com>"
    assert candidate.normalized_subject == "2:26-cv-00113 easement draft"
    assert candidate.sender_email == "alicia@dralaw.com"
    assert candidate.case_slug_guess == "7il-v-knight-ndga-ii"
    assert candidate.privilege_risk == "likely_privileged"
    assert candidate.attachments[0].file_name == "draft-easement.pdf"
    assert candidate.attachments[0].size_bytes > 0
    assert candidate.intake_decision == "manifest_only"


def test_parse_email_bytes_routes_opposing_fish_trap_as_work_product():
    candidate = parse_email_bytes(
        _raw_email(
            subject="Fish Trap SUV2026000013 Goldberg inspection issue",
            sender="Brian Goldberg <bgoldberg@fmglaw.com>",
            cc="",
        ),
        source_path=Path("/tmp/fish/email.eml"),
    )

    assert candidate.case_slug_guess == "fish-trap-suv2026000013"
    assert candidate.privilege_risk == "work_product_or_opposing_party"


def test_build_source_drop_plan_is_manifest_only(tmp_path):
    (tmp_path / "a.eml").write_bytes(_raw_email(subject="2:21-cv-00226 trial prep"))
    (tmp_path / "notes.txt").write_text("operator note")

    plan = build_source_drop_plan(tmp_path)

    assert plan.dry_run is True
    assert plan.candidate_count == 1
    assert plan.attachment_count == 1
    assert len(plan.skipped) == 1
    assert plan.candidates[0].case_slug_guess == "7il-v-knight-ndga-i"


def test_write_manifest_includes_summary_counts(tmp_path):
    (tmp_path / "a.eml").write_bytes(_raw_email(subject="Vanderburge easement thread"))
    plan = build_source_drop_plan(tmp_path)
    output = write_manifest(plan, tmp_path / "manifest.json")
    data = json.loads(output.read_text())

    assert data["candidate_count"] == 1
    assert data["attachment_count"] == 1
    assert data["candidates"][0]["case_slug_guess"] == "vanderburge-v-knight-fannin"


def test_legacy_mixed_dump_is_blocked_by_default():
    with pytest.raises(EmailSourceDropSafetyError):
        validate_source_root(Path("/mnt/fortress_nas/legal_vault/7il-v-knight-ndga/emails"))


def test_normalize_subject_strips_external_and_reply_prefixes():
    assert normalize_subject("[External] Fwd: Re: 7IL update") == "7IL update"
