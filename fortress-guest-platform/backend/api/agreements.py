"""
Agreements API — template management, e-signature, PDF generation.
Enterprise-grade rental agreement and e-sign system.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user, require_admin, require_manager_or_admin
from backend.models import (
    RentalAgreement, AgreementTemplate,
    Reservation, Guest, Property,
)
from backend.models.staff import StaffUser
from backend.services.agreement_renderer import (
    build_variable_context, render_template, extract_required_variables, extract_sections,
)
from backend.services.signing_token import generate_signing_token, validate_signing_token
from backend.services.pdf_generator import generate_agreement_pdf
from backend.services.email_service import send_email

logger = structlog.get_logger()
router = APIRouter()

VRS_URL = "http://192.168.0.100:3001"


# -----------------------------------------------------------------------
# Pydantic schemas
# -----------------------------------------------------------------------

class TemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    agreement_type: str = "rental_agreement"
    content_markdown: str
    requires_signature: bool = True
    requires_initials: bool = False
    auto_send: bool = True
    send_days_before_checkin: int = 7
    property_ids: Optional[list] = None


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content_markdown: Optional[str] = None
    requires_signature: Optional[bool] = None
    requires_initials: Optional[bool] = None
    auto_send: Optional[bool] = None
    send_days_before_checkin: Optional[int] = None
    property_ids: Optional[list] = None
    is_active: Optional[bool] = None


class AgreementCreate(BaseModel):
    template_id: UUID
    reservation_id: UUID


class SignatureSubmission(BaseModel):
    signer_name: str
    signer_email: str
    signature_type: str = Field(description="drawn | typed | click_to_sign")
    signature_data: str = Field(description="Base64 canvas PNG or typed name string")
    initials_data: Optional[str] = None
    initials_pages: Optional[list] = None
    consent_recorded: bool = False


# -----------------------------------------------------------------------
# Agreement Templates (admin)
# -----------------------------------------------------------------------

@router.get("/templates")
async def list_templates(
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(get_current_user),
):
    result = await db.execute(
        select(AgreementTemplate).where(AgreementTemplate.is_active == True).order_by(AgreementTemplate.name)
    )
    templates = result.scalars().all()
    return [_serialize_template(t) for t in templates]


@router.get("/templates/{template_id}")
async def get_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(get_current_user),
):
    t = await db.get(AgreementTemplate, template_id)
    if not t:
        raise HTTPException(404, "Template not found")
    data = _serialize_template(t)
    data["variables"] = extract_required_variables(t.content_markdown or "")
    return data


@router.post("/templates", status_code=201)
async def create_template(
    body: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_admin),
):
    t = AgreementTemplate(
        name=body.name,
        description=body.description,
        agreement_type=body.agreement_type,
        content_markdown=body.content_markdown,
        required_variables=extract_required_variables(body.content_markdown),
        requires_signature=body.requires_signature,
        requires_initials=body.requires_initials,
        auto_send=body.auto_send,
        send_days_before_checkin=body.send_days_before_checkin,
        property_ids=body.property_ids if body.property_ids else None,
        is_active=True,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    logger.info("template_created", id=str(t.id), name=t.name, by=str(user.id))
    return _serialize_template(t)


@router.patch("/templates/{template_id}")
async def update_template(
    template_id: UUID,
    body: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_admin),
):
    t = await db.get(AgreementTemplate, template_id)
    if not t:
        raise HTTPException(404, "Template not found")
    updates = body.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(t, k, v)
    if "content_markdown" in updates:
        t.required_variables = extract_required_variables(t.content_markdown)
    t.updated_at = datetime.utcnow()
    await db.commit()
    logger.info("template_updated", id=str(t.id), by=str(user.id))
    return _serialize_template(t)


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_admin),
):
    t = await db.get(AgreementTemplate, template_id)
    if not t:
        raise HTTPException(404, "Template not found")
    t.is_active = False
    t.updated_at = datetime.utcnow()
    await db.commit()
    logger.info("template_deactivated", id=str(t.id), by=str(user.id))
    return {"status": "deactivated"}


# -----------------------------------------------------------------------
# Agreements (admin CRUD)
# -----------------------------------------------------------------------

@router.get("/dashboard")
async def agreement_dashboard(
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(get_current_user),
):
    """Stats overview for the agreements page."""
    total = (await db.execute(select(func.count(RentalAgreement.id)))).scalar() or 0
    by_status = {}
    for s in ("draft", "sent", "viewed", "signed", "expired", "cancelled"):
        c = (await db.execute(
            select(func.count(RentalAgreement.id)).where(RentalAgreement.status == s)
        )).scalar() or 0
        by_status[s] = c

    expiring = (await db.execute(
        select(func.count(RentalAgreement.id)).where(
            RentalAgreement.status.in_(["sent", "viewed"]),
            RentalAgreement.expires_at <= datetime.utcnow() + timedelta(days=2),
        )
    )).scalar() or 0

    return {"total": total, "by_status": by_status, "expiring_soon": expiring}


@router.get("/")
async def list_agreements(
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(get_current_user),
    status_filter: Optional[str] = Query(None, alias="status"),
    property_id: Optional[UUID] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    q = select(RentalAgreement).order_by(RentalAgreement.created_at.desc())
    if status_filter:
        q = q.where(RentalAgreement.status == status_filter)
    if property_id:
        q = q.where(RentalAgreement.property_id == property_id)
    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    agreements = result.scalars().all()

    out = []
    for a in agreements:
        d = _serialize_agreement(a)
        guest = await db.get(Guest, a.guest_id)
        if guest:
            d["guest_name"] = f"{guest.first_name} {guest.last_name}"
        prop = await db.get(Property, a.property_id) if a.property_id else None
        if prop:
            d["property_name"] = prop.name
        res = await db.get(Reservation, a.reservation_id) if a.reservation_id else None
        if res:
            d["confirmation_code"] = res.confirmation_code
        out.append(d)
    return out


@router.get("/{agreement_id}")
async def get_agreement(
    agreement_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(get_current_user),
):
    a = await db.get(RentalAgreement, agreement_id)
    if not a:
        raise HTTPException(404, "Agreement not found")
    d = _serialize_agreement(a)
    d["rendered_content"] = a.rendered_content
    d["sections"] = extract_sections(a.rendered_content or "")
    guest = await db.get(Guest, a.guest_id)
    if guest:
        d["guest_name"] = f"{guest.first_name} {guest.last_name}"
        d["guest_email"] = guest.email
    return d


@router.post("/", status_code=201)
async def create_agreement(
    body: AgreementCreate,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    template = await db.get(AgreementTemplate, body.template_id)
    if not template:
        raise HTTPException(404, "Template not found")

    reservation = await db.get(Reservation, body.reservation_id)
    if not reservation:
        raise HTTPException(404, "Reservation not found")

    guest = await db.get(Guest, reservation.guest_id)
    prop = await db.get(Property, reservation.property_id)

    ctx = build_variable_context(reservation=reservation, guest=guest, prop=prop)
    rendered = render_template(template.content_markdown, ctx)

    expires = datetime.utcnow() + timedelta(days=7)

    agreement = RentalAgreement(
        guest_id=reservation.guest_id,
        reservation_id=reservation.id,
        property_id=reservation.property_id,
        template_id=template.id,
        agreement_type=template.agreement_type,
        rendered_content=rendered,
        status="draft",
        expires_at=expires,
    )
    db.add(agreement)
    await db.commit()
    await db.refresh(agreement)

    expires_tz = expires.replace(tzinfo=timezone.utc)
    token = generate_signing_token(str(agreement.id), expires_tz)
    agreement.agreement_url = f"{VRS_URL}/sign/{token}"
    await db.commit()

    logger.info("agreement_created",
                id=str(agreement.id),
                reservation=reservation.confirmation_code,
                template=template.name,
                by=str(user.id))
    return _serialize_agreement(agreement)


@router.post("/{agreement_id}/send")
async def send_agreement(
    agreement_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    a = await db.get(RentalAgreement, agreement_id)
    if not a:
        raise HTTPException(404, "Agreement not found")
    if a.status == "signed":
        raise HTTPException(400, "Agreement already signed")

    guest = await db.get(Guest, a.guest_id)
    if not guest or not guest.email:
        raise HTTPException(400, "Guest has no email address")

    if not a.agreement_url:
        raw_expires = a.expires_at or datetime.utcnow() + timedelta(days=7)
        expires_tz = raw_expires.replace(tzinfo=timezone.utc) if raw_expires.tzinfo is None else raw_expires
        token = generate_signing_token(str(a.id), expires_tz)
        a.agreement_url = f"{VRS_URL}/sign/{token}"

    prop = await db.get(Property, a.property_id) if a.property_id else None
    prop_name = prop.name if prop else "Your Rental"

    html = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
<div style="text-align:center;padding:20px 0;border-bottom:2px solid #2563eb;">
  <h1 style="color:#0f172a;margin:0;">Cabin Rentals of Georgia</h1>
  <p style="color:#64748b;margin:4px 0;">Rental Agreement</p>
</div>
<div style="padding:24px 0;">
  <p>Dear {guest.first_name},</p>
  <p>Your rental agreement for <strong>{prop_name}</strong> is ready for your review and signature.</p>
  <p>Please click the button below to review and sign your agreement electronically:</p>
  <div style="text-align:center;margin:30px 0;">
    <a href="{a.agreement_url}" style="background:#2563eb;color:white;padding:14px 36px;
       text-decoration:none;border-radius:8px;font-weight:600;font-size:16px;">
      Review &amp; Sign Agreement
    </a>
  </div>
  <p style="color:#64748b;font-size:13px;">
    This link expires on {a.expires_at.strftime('%B %d, %Y') if a.expires_at else 'in 7 days'}.
    If you have questions, please contact us.
  </p>
</div>
<div style="border-top:1px solid #e2e8f0;padding-top:12px;font-size:11px;color:#94a3b8;text-align:center;">
  Cabin Rentals of Georgia &bull; cabin-rentals-of-georgia.com
</div>
</body></html>"""

    sent = send_email(
        to=guest.email,
        subject=f"Rental Agreement for {prop_name} — Please Sign",
        html_body=html,
    )

    a.status = "sent"
    a.sent_at = datetime.utcnow()
    a.sent_via = "email"
    await db.commit()

    logger.info("agreement_sent",
                id=str(a.id),
                to=guest.email,
                email_delivered=sent,
                by=str(user.id))
    return {
        "status": "sent",
        "signing_url": a.agreement_url,
        "email_sent": sent,
        "sent_to": guest.email,
    }


@router.post("/{agreement_id}/remind")
async def remind_agreement(
    agreement_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_manager_or_admin),
):
    a = await db.get(RentalAgreement, agreement_id)
    if not a:
        raise HTTPException(404, "Agreement not found")
    if a.status not in ("sent", "viewed"):
        raise HTTPException(400, f"Cannot remind — status is {a.status}")

    guest = await db.get(Guest, a.guest_id)
    if not guest or not guest.email:
        raise HTTPException(400, "Guest has no email")

    prop = await db.get(Property, a.property_id) if a.property_id else None
    prop_name = prop.name if prop else "Your Rental"

    html = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
<div style="padding:20px 0;">
  <p>Dear {guest.first_name},</p>
  <p>This is a friendly reminder to review and sign your rental agreement for <strong>{prop_name}</strong>.</p>
  <div style="text-align:center;margin:24px 0;">
    <a href="{a.agreement_url}" style="background:#f59e0b;color:white;padding:14px 36px;
       text-decoration:none;border-radius:8px;font-weight:600;">
      Sign Agreement Now
    </a>
  </div>
</div>
</body></html>"""

    sent = send_email(to=guest.email, subject=f"Reminder: Sign Your Agreement for {prop_name}", html_body=html)
    a.reminder_count = (a.reminder_count or 0) + 1
    a.last_reminder_at = datetime.utcnow()
    await db.commit()
    logger.info("agreement_reminder", id=str(a.id), reminder_count=a.reminder_count, by=str(user.id))
    return {"status": "reminded", "reminder_count": a.reminder_count, "email_sent": sent}


@router.get("/{agreement_id}/pdf")
async def download_pdf(
    agreement_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(get_current_user),
):
    a = await db.get(RentalAgreement, agreement_id)
    if not a:
        raise HTTPException(404, "Agreement not found")
    if not a.pdf_url:
        raise HTTPException(404, "PDF not yet generated — agreement may not be signed")
    import os
    if not os.path.exists(a.pdf_url):
        raise HTTPException(404, "PDF file missing from storage")
    return FileResponse(
        a.pdf_url,
        media_type="application/pdf",
        filename=f"agreement-{a.agreement_type}-{agreement_id}.pdf",
    )


@router.post("/bulk-send")
async def bulk_send_agreements(
    template_id: UUID,
    days_ahead: int = Query(7, le=30),
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_admin),
):
    """Send agreements for all reservations checking in within days_ahead."""
    from datetime import date
    template = await db.get(AgreementTemplate, template_id)
    if not template:
        raise HTTPException(404, "Template not found")

    cutoff = date.today() + timedelta(days=days_ahead)
    res_q = await db.execute(
        select(Reservation).where(
            Reservation.check_in_date >= date.today(),
            Reservation.check_in_date <= cutoff,
            Reservation.status.in_(["confirmed"]),
        )
    )
    reservations = res_q.scalars().all()

    created = 0
    skipped = 0
    for res in reservations:
        existing = await db.execute(
            select(RentalAgreement).where(
                RentalAgreement.reservation_id == res.id,
                RentalAgreement.agreement_type == template.agreement_type,
            )
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        guest = await db.get(Guest, res.guest_id)
        prop = await db.get(Property, res.property_id)
        ctx = build_variable_context(reservation=res, guest=guest, prop=prop)
        rendered = render_template(template.content_markdown, ctx)
        expires = datetime.utcnow() + timedelta(days=7)

        a = RentalAgreement(
            guest_id=res.guest_id,
            reservation_id=res.id,
            property_id=res.property_id,
            template_id=template.id,
            agreement_type=template.agreement_type,
            rendered_content=rendered,
            status="draft",
            expires_at=expires,
        )
        db.add(a)
        await db.flush()
        token = generate_signing_token(str(a.id), expires.replace(tzinfo=timezone.utc))
        a.agreement_url = f"{VRS_URL}/sign/{token}"
        created += 1

    await db.commit()
    logger.info("bulk_agreements_created", created=created, skipped=skipped, by=str(user.id))
    return {"created": created, "skipped": skipped, "total_reservations": len(reservations)}


# -----------------------------------------------------------------------
# Public signing endpoints (token-verified, no JWT)
# -----------------------------------------------------------------------

@router.get("/public/{token}")
async def public_view_agreement(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    agreement_id = validate_signing_token(token)
    if not agreement_id:
        raise HTTPException(403, "Invalid or expired signing link")

    a = await db.get(RentalAgreement, UUID(agreement_id))
    if not a:
        raise HTTPException(404, "Agreement not found")
    if a.status == "signed":
        raise HTTPException(400, "Agreement already signed")

    if not a.first_viewed_at:
        a.first_viewed_at = datetime.utcnow()
    a.view_count = (a.view_count or 0) + 1
    if a.status == "sent":
        a.status = "viewed"
    await db.commit()

    guest = await db.get(Guest, a.guest_id)
    prop = await db.get(Property, a.property_id) if a.property_id else None

    sections = extract_sections(a.rendered_content or "")

    template = await db.get(AgreementTemplate, a.template_id) if a.template_id else None

    logger.info("agreement_viewed",
                id=agreement_id,
                ip=request.client.host if request.client else "unknown",
                view_count=a.view_count)

    return {
        "agreement_id": str(a.id),
        "agreement_type": a.agreement_type,
        "status": a.status,
        "rendered_content": a.rendered_content,
        "sections": sections,
        "requires_signature": template.requires_signature if template else True,
        "requires_initials": template.requires_initials if template else False,
        "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "",
        "guest_email": guest.email if guest else "",
        "property_name": prop.name if prop else "",
        "expires_at": str(a.expires_at) if a.expires_at else None,
    }


@router.post("/public/{token}/sign")
async def public_sign_agreement(
    token: str,
    body: SignatureSubmission,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    agreement_id = validate_signing_token(token)
    if not agreement_id:
        raise HTTPException(403, "Invalid or expired signing link")

    a = await db.get(RentalAgreement, UUID(agreement_id))
    if not a:
        raise HTTPException(404, "Agreement not found")
    if a.status == "signed":
        raise HTTPException(400, "Agreement already signed")
    if not body.consent_recorded:
        raise HTTPException(422, "You must check the consent box to sign")

    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")

    a.signed_at = datetime.utcnow()
    a.signature_type = body.signature_type
    a.signature_data = body.signature_data
    a.signer_name = body.signer_name
    a.signer_email = body.signer_email
    a.initials_data = body.initials_data
    a.initials_pages = body.initials_pages
    a.signer_ip_address = client_ip
    a.signer_user_agent = user_agent
    a.consent_recorded = True
    a.status = "signed"
    await db.commit()

    prop = await db.get(Property, a.property_id) if a.property_id else None
    res = await db.get(Reservation, a.reservation_id) if a.reservation_id else None

    pdf_path = generate_agreement_pdf(
        agreement_id=str(a.id),
        rendered_content=a.rendered_content or "",
        signer_name=a.signer_name,
        signer_email=a.signer_email,
        signature_data=a.signature_data,
        signature_type=a.signature_type,
        initials_data=a.initials_data,
        initials_pages=a.initials_pages,
        signer_ip=client_ip,
        signer_user_agent=user_agent,
        signed_at=a.signed_at,
        agreement_type=a.agreement_type or "Rental Agreement",
        property_name=prop.name if prop else "",
        confirmation_code=res.confirmation_code if res else "",
    )

    if pdf_path:
        a.pdf_url = pdf_path
        a.pdf_generated_at = datetime.utcnow()
        await db.commit()

    if a.signer_email:
        send_email(
            to=a.signer_email,
            subject="Your Signed Rental Agreement — Cabin Rentals of Georgia",
            html_body=f"""<p>Dear {a.signer_name},</p>
<p>Thank you for signing your rental agreement for <strong>{prop.name if prop else 'your rental'}</strong>.</p>
<p>A signed copy is attached to this email for your records. If you have any questions, please don't hesitate to contact us.</p>
<p>We look forward to hosting you!</p>
<p style="color:#64748b;font-size:12px;">— Cabin Rentals of Georgia</p>""",
        )

    logger.info("agreement_signed",
                id=agreement_id,
                signer=a.signer_name,
                ip=client_ip,
                pdf_generated=bool(pdf_path))

    return {
        "status": "signed",
        "agreement_id": str(a.id),
        "signed_at": str(a.signed_at),
        "pdf_generated": bool(pdf_path),
    }


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _serialize_template(t: AgreementTemplate) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "description": t.description,
        "agreement_type": t.agreement_type,
        "content_markdown": t.content_markdown,
        "required_variables": t.required_variables,
        "is_active": t.is_active,
        "requires_signature": t.requires_signature,
        "requires_initials": t.requires_initials,
        "auto_send": t.auto_send,
        "send_days_before_checkin": t.send_days_before_checkin,
        "property_ids": t.property_ids,
        "created_at": str(t.created_at) if t.created_at else None,
        "updated_at": str(t.updated_at) if t.updated_at else None,
    }


def _serialize_agreement(a: RentalAgreement) -> dict:
    return {
        "id": str(a.id),
        "guest_id": str(a.guest_id),
        "reservation_id": str(a.reservation_id) if a.reservation_id else None,
        "property_id": str(a.property_id) if a.property_id else None,
        "template_id": str(a.template_id) if a.template_id else None,
        "agreement_type": a.agreement_type,
        "status": a.status,
        "sent_at": str(a.sent_at) if a.sent_at else None,
        "sent_via": a.sent_via,
        "agreement_url": a.agreement_url,
        "expires_at": str(a.expires_at) if a.expires_at else None,
        "first_viewed_at": str(a.first_viewed_at) if a.first_viewed_at else None,
        "view_count": a.view_count or 0,
        "signed_at": str(a.signed_at) if a.signed_at else None,
        "signature_type": a.signature_type,
        "signer_name": a.signer_name,
        "signer_email": a.signer_email,
        "signer_ip_address": a.signer_ip_address,
        "consent_recorded": a.consent_recorded,
        "pdf_url": bool(a.pdf_url),
        "reminder_count": a.reminder_count or 0,
        "created_at": str(a.created_at) if a.created_at else None,
    }
