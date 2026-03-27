"""Storefront intent meta sanitization (no PII in meta)."""

from uuid import uuid4

from backend.api.storefront_intent import _sanitize_meta, _session_fingerprint


def test_sanitize_drops_banned_keys() -> None:
    assert _sanitize_meta({"email": "a@b.com"}) == {}
    assert _sanitize_meta({"nested": {"phone": "123"}}) == {}


def test_sanitize_drops_email_like_strings() -> None:
    assert _sanitize_meta({"note": "x@y.co"}) == {}


def test_sanitize_keeps_safe_meta() -> None:
    assert _sanitize_meta({"section": "hero", "depth": 1}) == {"section": "hero", "depth": 1}


def test_session_fingerprint_stable() -> None:
    sid = uuid4()
    a = _session_fingerprint(sid)
    b = _session_fingerprint(sid)
    assert a == b
    assert len(a) == 64
