from __future__ import annotations

from backend.core.security import hash_password, verify_password


def test_hash_password_round_trips_with_bcrypt() -> None:
    password = "Fortress-Prime-Test-Password-123!"
    hashed = hash_password(password)

    assert hashed.startswith("$2")
    assert verify_password(password, hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_verify_password_rejects_unsupported_hash_scheme() -> None:
    assert verify_password("secret", "plain-text-not-a-hash") is False
