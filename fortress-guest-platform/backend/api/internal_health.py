from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from backend.core.config import settings

router = APIRouter()


class InternalHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: Literal["fortress-prime-backend"] = "fortress-prime-backend"
    environment: str = Field(min_length=1)
    version: str = Field(min_length=1)
    timestamp_utc: datetime
    ingress: Literal["command_center"] = "command_center"
    request_host: str = Field(min_length=1)


def _secure_equals(presented: str | None, expected: str) -> bool:
    if not presented or not expected:
        return False
    return secrets.compare_digest(presented.strip(), expected.strip())


@router.get(
    "/internal/health",
    response_model=InternalHealthResponse,
    include_in_schema=False,
)
async def internal_health(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_fortress_ingress: Annotated[str | None, Header(alias="X-Fortress-Ingress")] = None,
    x_fortress_tunnel_signature: Annotated[
        str | None,
        Header(alias="X-Fortress-Tunnel-Signature"),
    ] = None,
) -> InternalHealthResponse:
    expected_secret = settings.internal_api_bearer_token

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    bearer_token = authorization[7:].strip()
    if not _secure_equals(bearer_token, expected_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
        )

    if x_fortress_ingress != "command_center":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid ingress boundary.",
        )

    if not _secure_equals(x_fortress_tunnel_signature, expected_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid tunnel signature.",
        )

    request_host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or "unknown"
    )

    return InternalHealthResponse(
        environment=settings.environment,
        version=str(request.app.version or "unknown"),
        timestamp_utc=datetime.now(timezone.utc),
        request_host=request_host,
    )
