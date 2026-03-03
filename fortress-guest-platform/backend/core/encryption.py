"""
Shared Fernet encryption utilities.

Used by:
  - backend/api/system_sensors.py  (FastAPI endpoints)
  - backend/api/utilities.py       (utility credential encryption)
  - src/email_bridge.py            (decrypt sensor passwords at sweep time)

Key derivation uses SECRET_KEY from the FGP .env, truncated and padded
to 32 bytes, then base64url-encoded for Fernet compatibility.
"""

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet

_fernet_instance: Optional[Fernet] = None


def _derive_key(secret: str) -> bytes:
    raw = secret.encode()[:32].ljust(32, b"\0")
    return base64.urlsafe_b64encode(raw)


def get_fernet(secret_key: Optional[str] = None) -> Fernet:
    """Return a Fernet instance derived from the given secret or SECRET_KEY env var."""
    global _fernet_instance
    if secret_key is not None:
        return Fernet(_derive_key(secret_key))
    if _fernet_instance is None:
        sk = os.getenv("SECRET_KEY", "change-me-fortress-secret")
        _fernet_instance = Fernet(_derive_key(sk))
    return _fernet_instance


def encrypt(plaintext: str, secret_key: Optional[str] = None) -> str:
    if not plaintext:
        return ""
    return get_fernet(secret_key).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str, secret_key: Optional[str] = None) -> str:
    if not ciphertext:
        return ""
    try:
        return get_fernet(secret_key).decrypt(ciphertext.encode()).decode()
    except Exception:
        return ""
