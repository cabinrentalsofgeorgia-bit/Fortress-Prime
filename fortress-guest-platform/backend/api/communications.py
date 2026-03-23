"""Omnichannel webhook receivers for the concierge communications swarm."""

from __future__ import annotations

import base64
import binascii
import re
import time
from email.utils import parseaddr

import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import FormData
from twilio.request_validator import RequestValidator

from backend.core.config import settings
from backend.core.database import get_db
from backend.services.communication_service import CommunicationService

router = APIRouter()
logger = structlog.get_logger()
communication_service = CommunicationService()
EMPTY_TWIML_RESPONSE = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


@router.post("/twilio/sms")
async def receive_twilio_sms(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    form_data = await request.form()
    payload = {key: str(value) for key, value in form_data.items()}
    _verify_twilio_signature(request, payload)

    sender_phone = payload.get("From", "")
    inbound_body = (payload.get("Body") or "").strip()
    message_sid = (payload.get("MessageSid") or "").strip()

    if not sender_phone or not inbound_body or not message_sid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Twilio SMS payload is missing From, Body, or MessageSid.",
        )

    context = await communication_service.resolve_guest_context(sender_phone, "sms", db)
    reply_text = await communication_service.build_response(
        db=db,
        context=context,
        inbound_message=inbound_body,
    )
    await communication_service.dispatch_sms_reply(
        db=db,
        context=context,
        to_phone=sender_phone,
        message_body=reply_text,
        inbound_message_sid=message_sid,
        inbound_metadata={
            "body": inbound_body,
            "channel": "sms",
            "from": sender_phone,
            "to": payload.get("To", ""),
            "account_sid": payload.get("AccountSid", ""),
            "num_media": payload.get("NumMedia", "0"),
        },
    )

    logger.info(
        "communications_twilio_sms_processed",
        from_phone=sender_phone,
        reservation_id=str(context.reservation_id) if context.reservation_id else None,
        property_id=str(context.property_id) if context.property_id else None,
    )
    return Response(content=EMPTY_TWIML_RESPONSE, media_type="application/xml")


@router.post("/sendgrid/email")
async def receive_sendgrid_email(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    raw_body = await request.body()
    _verify_sendgrid_signature(request, raw_body)

    form_data = await request.form()
    sender_email = _extract_email_address(str(form_data.get("from") or ""))
    subject = str(form_data.get("subject") or "").strip()
    inbound_body = _extract_email_body(form_data)

    if not sender_email or not inbound_body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SendGrid email payload is missing sender or message body.",
        )

    context = await communication_service.resolve_guest_context(sender_email, "email", db)
    reply_text = await communication_service.build_response(
        db=db,
        context=context,
        inbound_message=inbound_body,
    )
    await communication_service.dispatch_email_reply(
        to_email=sender_email,
        subject=subject,
        message_body=reply_text,
    )

    logger.info(
        "communications_sendgrid_email_processed",
        from_email=sender_email,
        reservation_id=str(context.reservation_id) if context.reservation_id else None,
        property_id=str(context.property_id) if context.property_id else None,
    )
    return JSONResponse({"status": "accepted"})


def _verify_twilio_signature(request: Request, payload: dict[str, str]) -> None:
    auth_token = (settings.twilio_auth_token or "").strip()
    if not auth_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Twilio webhook verification is not configured.",
        )

    signature = request.headers.get("X-Twilio-Signature", "").strip()
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing Twilio signature header.",
        )

    validator = RequestValidator(auth_token)
    if not validator.validate(str(request.url), payload, signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio signature.",
        )


def _verify_sendgrid_signature(request: Request, raw_body: bytes) -> None:
    public_key_value = (settings.sendgrid_inbound_public_key or "").strip()
    if not public_key_value:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SendGrid inbound signature verification is not configured.",
        )

    signature_header = request.headers.get("X-Twilio-Email-Event-Webhook-Signature", "").strip()
    timestamp_header = request.headers.get("X-Twilio-Email-Event-Webhook-Timestamp", "").strip()
    if not signature_header or not timestamp_header:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing SendGrid signature headers.",
        )

    try:
        request_timestamp = int(timestamp_header)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid SendGrid webhook timestamp.",
        ) from exc

    now = int(time.time())
    if abs(now - request_timestamp) > settings.sendgrid_inbound_max_age_seconds:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Expired SendGrid webhook timestamp.",
        )

    try:
        signature = base64.b64decode(signature_header, validate=True)
    except binascii.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Malformed SendGrid webhook signature.",
        ) from exc

    public_key = _load_sendgrid_public_key(public_key_value)
    try:
        public_key.verify(
            signature,
            timestamp_header.encode("utf-8") + raw_body,
            ec.ECDSA(hashes.SHA256()),
        )
    except InvalidSignature as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid SendGrid webhook signature.",
        ) from exc


def _load_sendgrid_public_key(public_key_value: str) -> EllipticCurvePublicKey:
    try:
        if public_key_value.startswith("-----BEGIN"):
            loaded_key = serialization.load_pem_public_key(public_key_value.encode("utf-8"))
        else:
            loaded_key = serialization.load_der_public_key(base64.b64decode(public_key_value))
    except (ValueError, TypeError, binascii.Error) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configured SendGrid public key is invalid.",
        ) from exc

    if not isinstance(loaded_key, EllipticCurvePublicKey):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configured SendGrid public key must be elliptic curve.",
        )
    return loaded_key


def _extract_email_address(value: str) -> str:
    _, email_address = parseaddr(value or "")
    return email_address.strip().lower()


def _extract_email_body(form_data: FormData) -> str:
    stripped_reply = str(form_data.get("text") or "").strip()
    if stripped_reply:
        return stripped_reply

    html_body = str(form_data.get("html") or "").strip()
    if not html_body:
        return ""

    without_tags = re.sub(r"<[^>]+>", " ", html_body)
    return re.sub(r"\s+", " ", without_tags).strip()
