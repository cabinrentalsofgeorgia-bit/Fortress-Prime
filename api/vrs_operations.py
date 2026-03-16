import os
import time

import requests as http_client
from fastapi import APIRouter, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel, Field

router = APIRouter()

VRS_API = os.getenv("VRS_API_URL", "http://127.0.0.1:8100")
JWT_ALGORITHM = "HS256"
COOKIE_NAME = "fortress_session"
JWT_SECRET = os.getenv("JWT_SECRET", "")

_VRS_JWT_SECRET = os.getenv(
    "VRS_JWT_SECRET_KEY",
    "oyt1L9BhC-6P2G0qwaEZ4LjtNB7r628WeAVxuNME9ulrD3j-CIgAZFOZ5xLOwIku",
)
_VRS_SERVICE_USER_ID = os.getenv(
    "VRS_SERVICE_USER_ID", "69171062-62bf-4dd7-8478-61f748da78ef"
)
_vrs_service_token: str = ""
_vrs_token_exp: float = 0


class VRSQuoteBuildRequest(BaseModel):
    cabin_name: str = Field(min_length=1, max_length=255)
    guest_count: int = Field(ge=1, le=20)
    check_in: str = Field(min_length=8, max_length=32)
    check_out: str = Field(min_length=8, max_length=32)
    special_requests: str = Field(default="", max_length=2000)


def _verify_console_user(request: Request) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="JWT secret is not configured")
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


def _get_vrs_service_token() -> str:
    global _vrs_service_token, _vrs_token_exp
    now = time.time()
    if _vrs_service_token and now < _vrs_token_exp - 30:
        return _vrs_service_token

    exp = now + 3600
    payload = {
        "sub": _VRS_SERVICE_USER_ID,
        "role": "admin",
        "email": "service@fortress.local",
        "exp": exp,
        "iat": now,
    }
    _vrs_service_token = jwt.encode(payload, _VRS_JWT_SECRET, algorithm=JWT_ALGORITHM)
    _vrs_token_exp = exp
    return _vrs_service_token


@router.post("/api/vrs/leads/{lead_id}/quotes/build")
async def build_vrs_quote(lead_id: str, body: VRSQuoteBuildRequest, request: Request):
    _verify_console_user(request)
    upstream_url = f"{VRS_API}/api/vrs/leads/{lead_id}/quotes/build"
    headers = {"Authorization": f"Bearer {_get_vrs_service_token()}"}

    try:
        resp = http_client.post(upstream_url, json=body.model_dump(), headers=headers, timeout=15)
    except http_client.RequestException as exc:
        raise HTTPException(status_code=502, detail="VRS platform unavailable") from exc

    if resp.status_code >= 400:
        detail = resp.text[:500] if resp.text else "Quote build failed"
        raise HTTPException(status_code=resp.status_code, detail=detail)

    return resp.json()
