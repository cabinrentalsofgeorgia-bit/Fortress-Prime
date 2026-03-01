"""
HMAC-SHA256 signing tokens for public agreement signing URLs.
Tokens encode agreement_id + expiry timestamp and are verified server-side.
"""
import hashlib
import hmac
import time
from datetime import datetime, timezone

import structlog

from backend.core.config import settings

logger = structlog.get_logger()

_SECRET = (settings.jwt_secret_key + "-esign").encode()
_SEP = "|"


def generate_signing_token(agreement_id: str, expires_at: datetime) -> str:
    """Create HMAC-SHA256 token: base64url(agreement_id|expiry_ts|hmac)."""
    ts = str(int(expires_at.timestamp()))
    message = f"{agreement_id}{_SEP}{ts}"
    sig = hmac.new(_SECRET, message.encode(), hashlib.sha256).hexdigest()
    return f"{agreement_id}{_SEP}{ts}{_SEP}{sig}"


def validate_signing_token(token: str) -> str | None:
    """
    Validate token and return agreement_id if valid, None otherwise.
    Checks HMAC integrity and expiry.
    """
    parts = token.split(_SEP)
    if len(parts) != 3:
        logger.warning("signing_token_malformed")
        return None

    agreement_id, ts_str, sig = parts

    try:
        expires_ts = int(ts_str)
    except ValueError:
        logger.warning("signing_token_bad_timestamp")
        return None

    if time.time() > expires_ts:
        logger.info("signing_token_expired", agreement_id=agreement_id)
        return None

    expected_msg = f"{agreement_id}{_SEP}{ts_str}"
    expected_sig = hmac.new(_SECRET, expected_msg.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(sig, expected_sig):
        logger.warning("signing_token_invalid_sig", agreement_id=agreement_id)
        return None

    return agreement_id
