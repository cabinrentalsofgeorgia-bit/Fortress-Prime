from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import decode_token, _decode_if_base64_pem
from backend.models.property import Property
from backend.models.reservation import Reservation

bearer_scheme = HTTPBearer(auto_error=False)
GUEST_PORTAL_TOKEN_TYPE = "guest_portal"
CONVERTED_RESERVATION_STATUSES = frozenset({"confirmed", "checked_in", "checked_out", "no_show"})


@dataclass(slots=True)
class AuthenticatedGuest:
    reservation: Reservation

    @property
    def property(self) -> Property:
        return self.reservation.prop


def create_guest_token(
    reservation_id: str,
    expires_delta: timedelta = timedelta(days=7),
) -> str:
    normalized_reservation_id = reservation_id.strip()
    if not normalized_reservation_id:
        raise ValueError("reservation_id must not be empty")

    private_key = _decode_if_base64_pem(settings.jwt_rsa_private_key)
    if not private_key:
        raise RuntimeError("JWT RSA private key is not configured")

    issued_at = datetime.now(timezone.utc)
    expire = issued_at + expires_delta
    payload = {
        "sub": normalized_reservation_id,
        "reservation_id": normalized_reservation_id,
        "role": "guest",
        "typ": GUEST_PORTAL_TOKEN_TYPE,
        "exp": expire,
        "iat": issued_at,
    }
    headers = {"kid": settings.jwt_key_id}
    return jwt.encode(payload, private_key, algorithm=settings.jwt_algorithm, headers=headers)


def _extract_guest_token(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials],
) -> str:
    cookie_token = (request.cookies.get("fgp_guest_token") or "").strip()
    if cookie_token:
        return cookie_token
    if creds is not None and creds.credentials.strip():
        return creds.credentials.strip()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Guest authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_guest(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedGuest:
    token = _extract_guest_token(request, creds)

    try:
        payload = decode_token(token)
        reservation_id = str(payload.get("reservation_id") or payload.get("sub") or "").strip()
        role = str(payload.get("role") or "").strip().lower()
        token_type = str(payload.get("typ") or "").strip().lower()
        if not reservation_id:
            raise JWTError("Missing reservation_id claim")
        if role != "guest" or token_type != GUEST_PORTAL_TOKEN_TYPE:
            raise JWTError("Guest token claims are invalid")
        parsed_reservation_id = UUID(reservation_id)
    except (JWTError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired guest token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    result = await db.execute(
        select(Reservation)
        .options(
            joinedload(Reservation.guest),
            joinedload(Reservation.prop).selectinload(Property.images),
            joinedload(Reservation.prop).selectinload(Property.guestbook_guides),
        )
        .where(Reservation.id == parsed_reservation_id)
    )
    reservation = result.scalar_one_or_none()
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    if reservation.status not in CONVERTED_RESERVATION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guest portal is unavailable for this reservation",
        )
    if reservation.prop is None or reservation.guest is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reservation is missing required guest or property context",
        )

    return AuthenticatedGuest(reservation=reservation)
