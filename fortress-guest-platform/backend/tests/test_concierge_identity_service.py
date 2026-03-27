"""Strike 11 — concierge identity normalization (unit)."""

import pytest

from backend.core.config import settings
from backend.services.concierge_identity_service import _norm_email, _norm_phone
from backend.services.enticer_swarm_service import render_recovery_sms_body


def test_norm_email() -> None:
    assert _norm_email("  User@Example.COM ") == "user@example.com"
    assert _norm_email("not-an-email") is None
    assert _norm_email("") is None


def test_norm_phone_us_ten_digit() -> None:
    assert _norm_phone("(404) 555-0199") == "4045550199"
    assert _norm_phone("+1 404 555 0199") == "4045550199"
    assert _norm_phone("123") is None


def test_render_recovery_sms_body_interpolates_default_url() -> None:
    body = render_recovery_sms_body(first_name="Alex", book_url="https://example.com/book")
    assert "https://example.com/book" in body


def test_render_recovery_sms_body_interpolates_first_name_when_template_requests_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "concierge_recovery_sms_body_template",
        "Hi {first_name}, finish your booking here: {book_url}",
        raising=False,
    )
    body = render_recovery_sms_body(first_name="Alex", book_url="https://example.com/book")
    assert "Alex" in body
    assert "https://example.com/book" in body
