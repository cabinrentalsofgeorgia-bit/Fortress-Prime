"""Omnichannel concierge communication orchestration."""

from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any, Literal
from uuid import UUID

import structlog
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.rest import Client

from backend.agents.concierge_agent import ConciergeAgent
from backend.core.config import settings
from backend.models.guest import Guest
from backend.models.message import Message
from backend.models.property import Property
from backend.models.reservation import Reservation
from backend.services.email_service import send_email

logger = structlog.get_logger()

CommunicationType = Literal["sms", "email"]
ACTIVE_RESERVATION_STATUSES = ("confirmed", "checked_in")
STRANGER_FALLBACK_RESPONSE = (
    "For verified guest support, please call the main office so we can confirm your reservation and help you directly."
)


@dataclass(slots=True)
class ResolvedGuestContext:
    """Guest identity resolved against an active or upcoming reservation."""

    identifier: str
    type: CommunicationType
    property_id: UUID | None
    property_name: str | None
    guest_id: UUID | None
    guest_name: str
    reservation_id: UUID | None
    reservation_confirmation_code: str | None
    fallback_response: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.property_id is not None


class CommunicationService:
    """Resolve sender identity, run concierge RAG, and dispatch the reply."""

    def __init__(self, concierge_agent: ConciergeAgent | None = None) -> None:
        self._concierge_agent = concierge_agent or ConciergeAgent()
        self._logger = logger.bind(service="communication_service")

    async def resolve_guest_context(
        self,
        identifier: str,
        type: CommunicationType,
        db: AsyncSession,
    ) -> ResolvedGuestContext:
        normalized_identifier = _normalize_identifier(identifier, type)
        today = datetime.now(timezone.utc).date()

        stmt = (
            select(Reservation, Guest, Property)
            .join(Guest, Reservation.guest_id == Guest.id)
            .join(Property, Reservation.property_id == Property.id)
            .where(
                Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
                Reservation.check_out_date >= today,
                _contact_match_clause(normalized_identifier, type),
            )
            .order_by(
                case(
                    (
                        and_(
                            Reservation.check_in_date <= today,
                            Reservation.check_out_date >= today,
                        ),
                        0,
                    ),
                    else_=1,
                ),
                Reservation.check_in_date.asc(),
                Reservation.created_at.desc(),
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        row = result.first()
        if row is None:
            return ResolvedGuestContext(
                identifier=normalized_identifier,
                type=type,
                property_id=None,
                property_name=None,
                guest_id=None,
                guest_name="Guest",
                reservation_id=None,
                reservation_confirmation_code=None,
                fallback_response=STRANGER_FALLBACK_RESPONSE,
            )

        reservation, guest, property_record = row
        guest_name = " ".join(
            part.strip()
            for part in (guest.first_name or "", guest.last_name or "")
            if part and part.strip()
        ).strip() or "Guest"
        return ResolvedGuestContext(
            identifier=normalized_identifier,
            type=type,
            property_id=property_record.id,
            property_name=property_record.name,
            guest_id=guest.id,
            guest_name=guest_name,
            reservation_id=reservation.id,
            reservation_confirmation_code=reservation.confirmation_code,
            fallback_response=None,
        )

    async def build_response(
        self,
        *,
        db: AsyncSession,
        context: ResolvedGuestContext,
        inbound_message: str,
    ) -> str:
        if not context.is_resolved:
            return context.fallback_response or STRANGER_FALLBACK_RESPONSE

        answer = await self._concierge_agent.answer_query(
            db,
            property_id=context.property_id,
            guest_message=inbound_message,
        )
        return answer.response

    async def dispatch_sms_reply(
        self,
        *,
        db: AsyncSession,
        context: ResolvedGuestContext,
        to_phone: str,
        message_body: str,
        inbound_message_sid: str,
        inbound_metadata: dict[str, Any],
    ) -> str:
        normalized_to_phone = _normalize_phone(to_phone)
        self._ensure_twilio_configured()
        inbound_message, created = await self._record_inbound_sms(
            db=db,
            context=context,
            from_phone=normalized_to_phone,
            external_id=inbound_message_sid,
            body=inbound_metadata.get("body", ""),
            extra_data=inbound_metadata,
        )
        if not created:
            self._logger.info(
                "twilio_inbound_duplicate_ignored",
                message_sid=inbound_message_sid,
                reservation_id=str(context.reservation_id) if context.reservation_id else None,
            )
            return ""

        message = await asyncio.to_thread(
            self._send_sms_sync,
            normalized_to_phone,
            message_body,
        )
        await self._record_outbound_sms(
            db=db,
            context=context,
            to_phone=normalized_to_phone,
            external_id=message.sid,
            body=message_body,
            extra_data={
                "channel": "sms",
                "inbound_message_id": str(inbound_message.id),
                "provider_status": message.status,
                "num_segments": message.num_segments,
            },
        )
        return str(message.sid)

    async def dispatch_email_reply(
        self,
        *,
        to_email: str,
        subject: str,
        message_body: str,
    ) -> None:
        normalized_to_email = _normalize_email(to_email)
        rendered_html = (
            "<html><body><p>"
            + html.escape(message_body).replace("\n", "<br>")
            + "</p></body></html>"
        )
        sent = await asyncio.to_thread(
            send_email,
            normalized_to_email,
            _reply_subject(subject),
            rendered_html,
            message_body,
            None,
        )
        if not sent:
            raise RuntimeError("SMTP reply dispatch failed.")

    def _send_sms_sync(self, to_phone: str, message_body: str) -> Any:
        self._ensure_twilio_configured()
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        return client.messages.create(
            from_=settings.twilio_phone_number,
            to=to_phone,
            body=message_body,
        )

    @staticmethod
    def _ensure_twilio_configured() -> None:
        if not settings.twilio_account_sid or not settings.twilio_auth_token or not settings.twilio_phone_number:
            raise RuntimeError("Twilio credentials are not fully configured.")

    async def _record_inbound_sms(
        self,
        *,
        db: AsyncSession,
        context: ResolvedGuestContext,
        from_phone: str,
        external_id: str,
        body: str,
        extra_data: dict[str, Any],
    ) -> tuple[Message, bool]:
        existing = await db.execute(
            select(Message).where(
                Message.external_id == external_id,
                Message.direction == "inbound",
                Message.provider == "twilio",
            )
        )
        existing_message = existing.scalar_one_or_none()
        if existing_message is not None:
            return existing_message, False

        message = Message(
            external_id=external_id,
            guest_id=context.guest_id,
            reservation_id=context.reservation_id,
            direction="inbound",
            phone_from=from_phone,
            phone_to=settings.twilio_phone_number,
            body=body,
            status="received",
            sent_at=datetime.utcnow(),
            provider="twilio",
            extra_data={"channel": "sms", **extra_data},
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        return message, True

    async def _record_outbound_sms(
        self,
        *,
        db: AsyncSession,
        context: ResolvedGuestContext,
        to_phone: str,
        external_id: str,
        body: str,
        extra_data: dict[str, Any],
    ) -> Message:
        message = Message(
            external_id=external_id,
            guest_id=context.guest_id,
            reservation_id=context.reservation_id,
            direction="outbound",
            phone_from=settings.twilio_phone_number,
            phone_to=to_phone,
            body=body,
            status="sent",
            sent_at=datetime.utcnow(),
            provider="twilio",
            is_auto_response=True,
            extra_data=extra_data,
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        return message


def _contact_match_clause(identifier: str, type: CommunicationType) -> Any:
    if type == "sms":
        digits = _normalize_phone_digits(identifier)
        candidates = {digits}
        if len(digits) == 11 and digits.startswith("1"):
            candidates.add(digits[1:])
        if len(digits) == 10:
            candidates.add(f"1{digits}")
        sanitized_candidates = tuple(value for value in candidates if value)
        guest_phone = func.regexp_replace(func.coalesce(Guest.phone, ""), r"\D", "", "g")
        reservation_phone = func.regexp_replace(func.coalesce(Reservation.guest_phone, ""), r"\D", "", "g")
        return or_(
            guest_phone.in_(sanitized_candidates),
            reservation_phone.in_(sanitized_candidates),
        )

    normalized_email = _normalize_email(identifier)
    return or_(
        func.lower(func.coalesce(Guest.email, "")) == normalized_email,
        func.lower(func.coalesce(Reservation.guest_email, "")) == normalized_email,
    )


def _normalize_identifier(identifier: str, type: CommunicationType) -> str:
    if type == "sms":
        return _normalize_phone(identifier)
    return _normalize_email(identifier)


def _normalize_phone(value: str) -> str:
    digits = _normalize_phone_digits(value)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return value.strip()


def _normalize_phone_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _normalize_email(value: str) -> str:
    _, email_address = parseaddr(value or "")
    return email_address.strip().lower()


def _reply_subject(subject: str) -> str:
    clean_subject = (subject or "").strip()
    if not clean_subject:
        return "Re: Your stay with Cabin Rentals of Georgia"
    if clean_subject.lower().startswith("re:"):
        return clean_subject
    return f"Re: {clean_subject}"
