"""
Contracts API — Management agreement generation, prospectus engine, and e-signature dispatch.

Endpoints:
  POST /generate                     — Generate a management agreement PDF from Iron Dome data
  POST /prospectus                   — Generate a full SOTA prospectus PDF (pitch + agreement)
  GET  /prospectus/{property_id}/data — Return prospectus data as JSON for marketing pages
  GET  /{id}/pdf                     — Download the generated contract PDF
  POST /{id}/send                    — Email the signing link to the property owner
  GET  /                             — List generated management contracts
"""

import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import FileResponse

from backend.core.database import get_db
from backend.core.security import require_admin
from backend.models import RentalAgreement, Property, Guest
from backend.services.contract_generator import generate_management_contract
from backend.services.prospectus_engine import generate_prospectus_data, render_prospectus_pdf
from backend.services.signing_token import generate_signing_token
from backend.services.email_service import send_email

logger = structlog.get_logger(service="contracts_api")
router = APIRouter()

VRS_URL = os.getenv("VRS_URL", "http://192.168.0.100:3001")


class GenerateContractRequest(BaseModel):
    owner_id: str = Field(..., min_length=1)
    property_id: str = Field(..., min_length=1)
    term_years: int = Field(default=1, ge=1, le=10)
    effective_date: Optional[date] = None


class SendContractRequest(BaseModel):
    recipient_email: Optional[str] = Field(default=None, max_length=255)
    expires_days: int = Field(default=30, ge=1, le=90)


@router.post("/generate")
async def generate_contract(
    req: GenerateContractRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Generate a management agreement PDF from Iron Dome financial data."""
    result = await generate_management_contract(
        owner_id=req.owner_id,
        property_id=req.property_id,
        db=db,
        term_years=req.term_years,
        effective_date=req.effective_date,
    )

    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])

    if not result.get("pdf_path"):
        raise HTTPException(status_code=500, detail="PDF generation failed")

    prop_result = await db.execute(
        text("SELECT id, name, owner_id FROM properties WHERE id::text = :pid OR streamline_property_id = :pid LIMIT 1"),
        {"pid": req.property_id},
    )
    prop_row = prop_result.first()
    prop_uuid = str(prop_row.id) if prop_row else None

    owner_result = await db.execute(
        text("SELECT email FROM owner_property_map WHERE sl_owner_id = :oid LIMIT 1"),
        {"oid": req.owner_id},
    )
    owner_row = owner_result.first()
    owner_email = owner_row.email if owner_row else None

    guest_row = None
    if owner_email:
        guest_result = await db.execute(
            select(Guest).where(Guest.email == owner_email).limit(1)
        )
        guest_row = guest_result.scalar_one_or_none()

    if not guest_row and owner_email:
        guest_row = Guest(
            email=owner_email,
            first_name=result["variables_used"].get("owner_name", "Owner").split()[0],
            last_name=" ".join(result["variables_used"].get("owner_name", "").split()[1:]),
            phone_number=result["variables_used"].get("owner_phone", ""),
        )
        db.add(guest_row)
        await db.flush()

    agreement = RentalAgreement(
        guest_id=guest_row.id if guest_row else uuid4(),
        property_id=UUID(prop_uuid) if prop_uuid else None,
        agreement_type="management_contract",
        rendered_content=result["rendered_html"],
        status="draft",
        pdf_url=result["pdf_path"],
        pdf_generated_at=datetime.utcnow(),
    )
    db.add(agreement)
    await db.commit()
    await db.refresh(agreement)

    logger.info(
        "management_contract_created",
        agreement_id=str(agreement.id),
        owner_id=req.owner_id,
        property_id=req.property_id,
    )

    return {
        "agreement_id": str(agreement.id),
        "pdf_path": result["pdf_path"],
        "nas_path": result.get("nas_path"),
        "variables_used": result["variables_used"],
        "status": "draft",
    }


class GenerateProspectusRequest(BaseModel):
    owner_id: str = Field(..., min_length=1)
    property_id: str = Field(..., min_length=1)
    term_years: int = Field(default=1, ge=1, le=10)
    effective_date: Optional[date] = None


@router.post("/prospectus")
async def generate_prospectus(
    req: GenerateProspectusRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Generate a full SOTA prospectus PDF (pitch deck + management agreement)."""
    result = await render_prospectus_pdf(
        owner_id=req.owner_id,
        property_id=req.property_id,
        db=db,
        term_years=req.term_years,
        effective_date=req.effective_date,
    )

    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    if not result.get("pdf_path"):
        raise HTTPException(status_code=500, detail="PDF generation failed")

    prop_result = await db.execute(
        text("SELECT id, name, owner_id FROM properties WHERE id::text = :pid OR streamline_property_id = :pid LIMIT 1"),
        {"pid": req.property_id},
    )
    prop_row = prop_result.first()
    prop_uuid = str(prop_row.id) if prop_row else None

    owner_result = await db.execute(
        text("SELECT email FROM owner_property_map WHERE sl_owner_id = :oid LIMIT 1"),
        {"oid": req.owner_id},
    )
    owner_row = owner_result.first()
    owner_email = owner_row.email if owner_row else None

    guest_row = None
    if owner_email:
        guest_result = await db.execute(
            select(Guest).where(Guest.email == owner_email).limit(1)
        )
        guest_row = guest_result.scalar_one_or_none()

    if not guest_row and owner_email:
        payload = result.get("payload", {})
        owner_info = payload.get("owner", {})
        guest_row = Guest(
            email=owner_email,
            first_name=owner_info.get("owner_name", "Owner").split()[0],
            last_name=" ".join(owner_info.get("owner_name", "").split()[1:]),
            phone_number=owner_info.get("owner_phone", ""),
        )
        db.add(guest_row)
        await db.flush()

    agreement = RentalAgreement(
        guest_id=guest_row.id if guest_row else uuid4(),
        property_id=UUID(prop_uuid) if prop_uuid else None,
        agreement_type="prospectus",
        rendered_content=result["rendered_html"],
        status="draft",
        pdf_url=result["pdf_path"],
        pdf_generated_at=datetime.utcnow(),
    )
    db.add(agreement)
    await db.commit()
    await db.refresh(agreement)

    logger.info(
        "prospectus_created",
        agreement_id=str(agreement.id),
        owner_id=req.owner_id,
        property_id=req.property_id,
    )

    return {
        "prospectus_id": str(agreement.id),
        "pdf_path": result["pdf_path"],
        "nas_path": result.get("nas_path"),
        "status": "draft",
        "pro_forma_summary": {
            "annual_gross": result["payload"]["pro_forma"]["annual_gross"],
            "annual_net_to_owner": result["payload"]["pro_forma"]["annual_net_to_owner"],
            "adr_used": result["payload"]["pro_forma"]["adr_used"],
            "occupancy_used": result["payload"]["pro_forma"]["occupancy_used"],
        },
    }


@router.get("/prospectus/{property_id}/data")
async def get_prospectus_data(
    property_id: str,
    owner_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Return the prospectus payload as JSON for website rendering."""
    payload = await generate_prospectus_data(
        owner_id=owner_id,
        property_id=property_id,
        db=db,
    )
    return payload


@router.get("/{agreement_id}/pdf")
async def download_contract_pdf(
    agreement_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Download the generated management contract PDF."""
    agreement = await db.get(RentalAgreement, agreement_id)
    if not agreement:
        raise HTTPException(404, "Contract not found")
    if not agreement.pdf_url:
        raise HTTPException(404, "PDF not yet generated")

    from pathlib import Path
    pdf_file = Path(agreement.pdf_url)
    if not pdf_file.exists():
        raise HTTPException(404, "PDF file not found on disk")

    return FileResponse(
        str(pdf_file),
        media_type="application/pdf",
        filename=pdf_file.name,
    )


@router.post("/{agreement_id}/send")
async def send_contract_for_signing(
    agreement_id: UUID,
    req: SendContractRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Email a signing link to the property owner."""
    agreement = await db.get(RentalAgreement, agreement_id)
    if not agreement:
        raise HTTPException(404, "Contract not found")
    if agreement.status == "signed":
        raise HTTPException(400, "Contract already signed")

    recipient = req.recipient_email
    if not recipient and agreement.guest_id:
        guest = await db.get(Guest, agreement.guest_id)
        if guest:
            recipient = guest.email

    if not recipient:
        raise HTTPException(422, "No recipient email provided or found")

    expires = datetime.now(timezone.utc) + timedelta(days=req.expires_days)
    token = generate_signing_token(str(agreement.id), expires)
    signing_url = f"{VRS_URL}/sign/{token}"

    agreement.agreement_url = signing_url
    agreement.expires_at = expires
    agreement.status = "sent"
    agreement.sent_at = datetime.utcnow()
    agreement.sent_via = "email"
    await db.commit()

    prop = await db.get(Property, agreement.property_id) if agreement.property_id else None
    prop_name = prop.name if prop else "your property"

    send_email(
        to=recipient,
        subject=f"Management Agreement for Review & Signature — {prop_name}",
        html_body=f"""<p>Dear Property Owner,</p>
<p>Your Property Management Agreement for <strong>{prop_name}</strong> is ready for your review and signature.</p>
<p>Please click the link below to review the agreement and provide your electronic signature:</p>
<p style="margin:24px 0;"><a href="{signing_url}" style="background-color:#2563eb;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:bold;">Review &amp; Sign Agreement &rarr;</a></p>
<p style="color:#64748b;font-size:13px;">This link expires on {expires.strftime('%B %d, %Y')}.</p>
<p>If you have any questions about the agreement terms, please contact us at any time.</p>
<p style="color:#64748b;font-size:12px;">&mdash; Cabin Rentals of Georgia</p>""",
    )

    logger.info(
        "management_contract_sent",
        agreement_id=str(agreement.id),
        recipient=recipient,
        signing_url=signing_url,
    )

    return {
        "status": "sent",
        "agreement_id": str(agreement.id),
        "recipient": recipient,
        "signing_url": signing_url,
        "expires_at": expires.isoformat(),
    }


@router.get("/")
async def list_management_contracts(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """List management contracts and prospectuses with optional status filter."""
    query = select(RentalAgreement).where(
        RentalAgreement.agreement_type.in_(["management_contract", "prospectus"])
    ).order_by(RentalAgreement.created_at.desc())

    if status:
        query = query.where(RentalAgreement.status == status)

    result = await db.execute(query.limit(100))
    agreements = result.scalars().all()

    return {
        "contracts": [
            {
                "id": str(a.id),
                "property_id": str(a.property_id) if a.property_id else None,
                "agreement_type": a.agreement_type or "management_contract",
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "sent_at": a.sent_at.isoformat() if a.sent_at else None,
                "signed_at": a.signed_at.isoformat() if a.signed_at else None,
                "signer_name": a.signer_name,
                "pdf_url": a.pdf_url,
            }
            for a in agreements
        ],
        "total": len(agreements),
    }
