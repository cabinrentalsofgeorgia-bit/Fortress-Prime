"""
Shared swarm authentication dependencies for M2M ingestion routes.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, Security, status
from fastapi.security.api_key import APIKeyHeader
from jose import JWTError

from backend.core.config import settings
from backend.core.security import decode_token

api_key_header = APIKeyHeader(name="X-Swarm-Token", auto_error=False)


def _load_valid_swarm_tokens() -> list[str]:
    return [key for key in [settings.swarm_seo_api_key, settings.swarm_api_key] if key]


async def verify_swarm_token(api_key: str | None = Security(api_key_header)) -> str:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Swarm-Token header",
        )

    valid_keys = _load_valid_swarm_tokens()
    if not valid_keys:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfiguration: Swarm auth keys not loaded",
        )

    if not any(hmac.compare_digest(api_key, valid_key) for valid_key in valid_keys):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Swarm Token",
        )

    return api_key


async def require_swarm_or_jwt(
    request: Request,
    api_key: str | None = Security(api_key_header),
) -> dict[str, str]:
    """Legacy dual-mode dependency. Do not use on strict M2M routes."""
    if api_key:
        await verify_swarm_token(api_key)
        return {"auth_mode": "swarm", "subject": "swarm"}

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing valid Bearer token or X-Swarm-Token",
        )

    try:
        payload = decode_token(auth_header[7:])
        subject = payload.get("sub")
        if not subject:
            raise JWTError("Missing sub claim")
        return {"auth_mode": "jwt", "subject": str(subject)}
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc
