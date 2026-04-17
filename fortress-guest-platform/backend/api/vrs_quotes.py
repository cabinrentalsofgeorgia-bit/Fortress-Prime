"""
Public quote endpoints for guest checkout flows.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.queue import get_arq_pool
from backend.models.media import PropertyImage
from backend.models.property import Property
from backend.models.taylor_quote import TaylorQuoteRequest, TaylorQuoteStatus
from backend.models.vrs_add_on import VRSAddOn, VRSAddOnPricingModel, VRSAddOnScope
from backend.models.vrs_quotes import GuestQuote, GuestQuoteStatus
from backend.services.email_service import is_email_configured, send_email
from backend.services.async_jobs import enqueue_async_job, extract_request_actor
from backend.services.quote_builder import calculate_property_quote
from backend.services.fast_quote_service import FastQuoteError, calculate_locked_fast_quote_breakdown
from backend.services.streamline_client import StreamlineClient

log = structlog.get_logger(__name__)

router = APIRouter()
LEGACY_PROPERTY_MAP = {
    "14": "f66def25-6b88-4a72-a023-efa575281a59",
}


class GuestQuoteGenerateRequest(BaseModel):
    property_id: str | UUID | None = None
    guest_name: str | None = None
    guest_email: str | None = None
    guest_phone: str | None = None
    check_in: date | None = None
    check_out: date | None = None
    adults: int = 2
    children: int = 0
    pets: int = 0
    base_rent: Decimal = Field(default=Decimal("0.00"))
    taxes: Decimal = Field(default=Decimal("0.00"))
    fees: Decimal = Field(default=Decimal("0.00"))
    campaign: str = "direct"
    target_keyword: str | None = None


class GuestQuoteSendRequest(BaseModel):
    guest_email: EmailStr
    property_name: str
    total_amount: Decimal
    checkout_url: str


class StreamlineQuoteRequest(BaseModel):
    property_id: str | UUID
    start_date: date | None = None
    end_date: date | None = None
    check_in: date | None = None
    check_out: date | None = None
    adults: int = Field(default=2, ge=1, le=24)
    children: int = Field(default=0, ge=0, le=24)
    pets: int = Field(default=0, ge=0, le=12)
    selected_add_on_ids: list[UUID] = Field(default_factory=list)
    force_refresh: bool = False

    @model_validator(mode="after")
    def _normalize_dates(self) -> "StreamlineQuoteRequest":
        start = self.start_date or self.check_in
        end = self.end_date or self.check_out
        if start is None or end is None:
            raise ValueError("start_date/end_date or check_in/check_out are required")
        self.start_date = start
        self.end_date = end
        self.check_in = start
        self.check_out = end
        return self


class StreamlineRefreshRequest(BaseModel):
    property_id: str | UUID
    start_date: date
    end_date: date


class TaylorQuoteCreateRequest(BaseModel):
    guest_email: EmailStr
    check_in: date
    check_out: date
    adults: int = Field(default=2, ge=1, le=24)
    children: int = Field(default=0, ge=0, le=24)
    pets: int = Field(default=0, ge=0, le=12)


async def resolve_quote_property(
    requested_property_id: str | UUID | None,
    db: AsyncSession,
) -> tuple[Property, str]:
    if requested_property_id is None:
        raise HTTPException(status_code=400, detail="property_id is required")

    raw_property_id = str(requested_property_id).strip()
    if not raw_property_id:
        raise HTTPException(status_code=400, detail="property_id is required")

    resolved_identifier = LEGACY_PROPERTY_MAP.get(raw_property_id, raw_property_id)

    property_uuid = None
    try:
        property_uuid = UUID(resolved_identifier)
    except ValueError:
        pass

    property_record = None
    if property_uuid is not None:
        result = await db.execute(select(Property).where(Property.id == property_uuid))
        property_record = result.scalar_one_or_none()

    if property_record is None:
        result = await db.execute(
            select(Property).where(Property.streamline_property_id == resolved_identifier)
        )
        property_record = result.scalar_one_or_none()

    if property_record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Property '{raw_property_id}' not found. "
                "Expected a mapped legacy ID, property UUID, or Streamline property ID."
            ),
        )

    return property_record, raw_property_id


@router.post("/generate")
async def generate_guest_quote(
    payload: GuestQuoteGenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
):
    property_record, requested_property_id = await resolve_quote_property(payload.property_id, db)

    nights = None
    if payload.check_in and payload.check_out:
        nights = (payload.check_out - payload.check_in).days
        if nights < 1:
            raise HTTPException(status_code=400, detail="check_out must be after check_in")

    should_calculate_quote = (
        payload.check_in is not None
        and payload.check_out is not None
        and payload.base_rent == Decimal("0.00")
        and payload.taxes == Decimal("0.00")
        and payload.fees == Decimal("0.00")
    )

    pricing_source = "manual_payload"
    nightly_breakdown = None
    base_rent = payload.base_rent
    taxes = payload.taxes
    fees = payload.fees

    if should_calculate_quote:
        pricing = await calculate_property_quote(
            property_id=property_record.id,
            check_in=payload.check_in,
            check_out=payload.check_out,
            db=db,
        )
        base_rent = Decimal(pricing["base_rent"])
        taxes = Decimal(pricing["taxes"])
        fees = Decimal(pricing["fees"])
        pricing_source = pricing["pricing_source"]
        nightly_breakdown = pricing["nightly_breakdown"]

    total_amount = base_rent + taxes + fees
    guest_name = payload.guest_name or "Manual Quote Request"
    guest_phone = payload.guest_phone or "manual-quote"

    quote = GuestQuote(
        target_property_id=str(property_record.id),
        property_id=property_record.id,
        guest_name=guest_name,
        guest_email=payload.guest_email,
        guest_phone=guest_phone,
        check_in=payload.check_in,
        check_out=payload.check_out,
        nights=nights,
        adults=payload.adults,
        children=payload.children,
        pets=payload.pets,
        base_rent=base_rent,
        taxes=taxes,
        fees=fees,
        total_amount=total_amount,
        base_price=float(base_rent),
        ai_adjusted_price=float(total_amount),
        sovereign_narrative="Autogenerated checkout quote",
        campaign=payload.campaign,
        target_keyword=payload.target_keyword,
        quote_breakdown={
            "base_rent": str(base_rent),
            "taxes": str(taxes),
            "fees": str(fees),
            "total": str(total_amount),
            "pricing_source": pricing_source,
            "nightly_breakdown": nightly_breakdown,
        },
        source_snapshot={
            "requested_property_id": requested_property_id,
            "resolved_property_id": str(property_record.id),
            "resolved_property_name": property_record.name,
            "legacy_id_mapped": requested_property_id in LEGACY_PROPERTY_MAP,
            "pricing_source": pricing_source,
        },
    )
    db.add(quote)
    await db.commit()
    await db.refresh(quote)

    response_payload = {
        "id": str(quote.id),
        "status": quote.status,
        "checkout_url": f"/api/quotes/{quote.id}/checkout",
        "property_id": str(property_record.id),
        "property_name": property_record.name,
        "base_rent": float(quote.base_rent),
        "taxes": float(quote.taxes),
        "fees": float(quote.fees),
        "total_amount": float(quote.total_amount),
        "pricing_source": pricing_source,
    }

    shadow_job = await enqueue_async_job(
        db,
        worker_name="run_shadow_audit_job",
        job_name="run_shadow_audit",
        payload={
            "payload": payload.model_dump(mode="json"),
            "legacy_result": response_payload,
            "metadata": {
                "quote_id": str(quote.id),
                "orchestrator": "spark-node-2-leader",
            },
        },
        requested_by=extract_request_actor(
            request.headers.get("x-user-id"),
            request.headers.get("x-user-email"),
        ),
        tenant_id=getattr(request.state, "tenant_id", None),
        request_id=request.headers.get("x-request-id"),
        redis=arq_redis,
    )
    response_payload["shadow_audit_job_id"] = str(shadow_job.id)

    return response_payload


@router.post("/send")
async def send_guest_quote_email(payload: GuestQuoteSendRequest):
    if not is_email_configured():
        raise HTTPException(
            status_code=503,
            detail="Email delivery is not configured for the quote dispatcher.",
        )

    absolute_checkout_url = payload.checkout_url
    if absolute_checkout_url.startswith("/"):
        absolute_checkout_url = f"https://crog-ai.com{absolute_checkout_url}"

    total_amount = f"${payload.total_amount.quantize(Decimal('0.01'))}"
    subject = f"Your custom quote for {payload.property_name}"
    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f4f4f5;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:40px auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1);">
    <tr>
      <td style="background:#18181b;padding:28px 32px;text-align:center;">
        <h1 style="margin:0;color:#ffffff;font-size:20px;font-weight:600;letter-spacing:-0.025em;">
          Cabin Rentals of Georgia
        </h1>
      </td>
    </tr>
    <tr>
      <td style="padding:32px;">
        <h2 style="margin:0 0 10px;color:#18181b;font-size:18px;">
          Your custom quote is ready
        </h2>
        <p style="margin:0 0 16px;color:#52525b;font-size:15px;line-height:1.6;">
          Here is your custom quote for <strong>{payload.property_name}</strong>.
        </p>
        <p style="margin:0 0 24px;color:#18181b;font-size:24px;font-weight:700;">
          {total_amount}
        </p>
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td align="center">
              <a href="{absolute_checkout_url}"
                 style="display:inline-block;background:#18181b;color:#ffffff;text-decoration:none;padding:12px 28px;border-radius:8px;font-size:15px;font-weight:600;">
                Complete Your Reservation
              </a>
            </td>
          </tr>
        </table>
        <p style="margin:24px 0 0;color:#52525b;font-size:14px;line-height:1.6;">
          If the button does not work, copy and paste this link into your browser:
        </p>
        <p style="margin:8px 0 0;font-size:13px;line-height:1.6;word-break:break-all;">
          <a href="{absolute_checkout_url}" style="color:#2563eb;">{absolute_checkout_url}</a>
        </p>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    text_body = (
        f"Here is your custom quote for {payload.property_name}.\n\n"
        f"Quoted total: {total_amount}\n\n"
        f"Complete your reservation here: {absolute_checkout_url}\n"
    )

    sent = send_email(
        to=str(payload.guest_email),
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )
    if not sent:
        raise HTTPException(
            status_code=502,
            detail="Quote email dispatch failed. Check SMTP configuration and delivery logs.",
        )

    return {"status": "sent", "guest_email": str(payload.guest_email)}


@router.get("/streamline/properties")
async def list_streamline_quote_properties(
    db: AsyncSession = Depends(get_db),
    force_refresh: bool = Query(default=False),
):
    client = StreamlineClient()
    try:
        return await client.get_property_catalog(db, force_refresh=force_refresh)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await client.close()


@router.get("/streamline/calendar/{property_id}")
async def get_streamline_master_calendar(
    property_id: str,
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    force_refresh: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    start_date = start or date.today()
    end_date = end or (start_date + timedelta(days=41))

    client = StreamlineClient()
    try:
        return await client.get_master_calendar(
            property_id,
            start_date,
            end_date,
            db,
            force_refresh=force_refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await client.close()


@router.post("/streamline/quote")
async def get_streamline_deterministic_quote(
    payload: StreamlineQuoteRequest,
    db: AsyncSession = Depends(get_db),
):
    client = StreamlineClient()
    try:
        quote_response = await client.get_deterministic_quote(
            payload.property_id,
            payload.start_date,
            payload.end_date,
            db,
            adults=payload.adults,
            children=payload.children,
            pets=payload.pets,
            force_refresh=payload.force_refresh,
        )
        streamline_total = Decimal(str(quote_response["total_amount"]))
        ancillary_total = Decimal("0.00")
        add_on_line_items: list[dict[str, Any]] = []

        if payload.selected_add_on_ids:
            resolved_property, _ = await resolve_quote_property(payload.property_id, db)
            add_on_result = await db.execute(
                select(VRSAddOn).where(
                    VRSAddOn.id.in_(payload.selected_add_on_ids),
                    VRSAddOn.is_active.is_(True),
                )
            )
            selected_add_ons = add_on_result.scalars().all()
            total_nights = (payload.end_date - payload.start_date).days
            total_guests = payload.adults + payload.children

            for add_on in selected_add_ons:
                if add_on.scope == VRSAddOnScope.PROPERTY_SPECIFIC and add_on.property_id != resolved_property.id:
                    continue

                unit_price = Decimal(str(add_on.price or "0.00"))
                item_price = Decimal("0.00")
                if add_on.pricing_model == VRSAddOnPricingModel.FLAT_FEE:
                    item_price = unit_price
                elif add_on.pricing_model == VRSAddOnPricingModel.PER_NIGHT:
                    item_price = unit_price * total_nights
                elif add_on.pricing_model == VRSAddOnPricingModel.PER_GUEST:
                    item_price = unit_price * total_guests

                item_price = item_price.quantize(Decimal("0.01"))
                ancillary_total += item_price
                add_on_line_items.append(
                    {
                        "id": str(add_on.id),
                        "name": add_on.name,
                        "description": add_on.description,
                        "pricing_model": add_on.pricing_model.value,
                        "amount": float(item_price),
                    }
                )

        grand_total = (streamline_total + ancillary_total).quantize(Decimal("0.01"))
        quote_response["selected_add_on_ids"] = [str(add_on_id) for add_on_id in payload.selected_add_on_ids]
        quote_response["add_ons"] = add_on_line_items
        quote_response["ancillary_total"] = float(ancillary_total)
        quote_response["streamline_total"] = float(streamline_total)
        quote_response["grand_total"] = float(grand_total)
        quote_response["total_amount"] = float(grand_total)
        return quote_response
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await client.close()


@router.post("/streamline/refresh")
async def refresh_streamline_quote_cache(
    payload: StreamlineRefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    client = StreamlineClient()
    try:
        return await client.refresh_property_cache(
            payload.property_id,
            db,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await client.close()


@router.get("/{quote_id}")
async def get_guest_quote_public(
    quote_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Public guest quote lookup — no auth required.
    The UUID itself is the unforgeable capability token.
    PII (guest email, phone) is never returned.
    """
    result = await db.execute(select(GuestQuote).where(GuestQuote.id == quote_id))
    quote = result.scalar_one_or_none()
    if quote is None:
        raise HTTPException(status_code=404, detail="Quote not found")

    # Derive effective status without mutating the row — expiry is caller-visible
    now = datetime.utcnow()
    effective_status = quote.status
    if quote.status == GuestQuoteStatus.PENDING and quote.expires_at < now:
        effective_status = GuestQuoteStatus.EXPIRED

    # Resolve property record and hero image in two targeted queries
    property_record: Property | None = None
    hero_image_url: str | None = None
    if quote.property_id:
        prop_res = await db.execute(
            select(Property).where(Property.id == quote.property_id)
        )
        property_record = prop_res.scalar_one_or_none()

        if property_record is not None:
            img_res = await db.execute(
                select(PropertyImage)
                .where(PropertyImage.property_id == property_record.id)
                .order_by(PropertyImage.is_hero.desc(), PropertyImage.display_order)
                .limit(1)
            )
            img = img_res.scalar_one_or_none()
            if img is not None:
                hero_image_url = img.sovereign_url or img.legacy_url

    source_snapshot: dict = quote.source_snapshot or {}
    return {
        "id": str(quote.id),
        "status": effective_status,
        "target_property_id": quote.target_property_id,
        "property_name": (
            property_record.name
            if property_record
            else source_snapshot.get("resolved_property_name", "Mountain Cabin")
        ),
        "property_slug": property_record.slug if property_record else None,
        "property_type": getattr(property_record, "property_type", None) if property_record else None,
        "property_bedrooms": property_record.bedrooms if property_record else None,
        "property_bathrooms": float(property_record.bathrooms) if property_record else None,
        "property_max_guests": property_record.max_guests if property_record else None,
        "property_hero_image": hero_image_url,
        "check_in": quote.check_in.isoformat() if quote.check_in else None,
        "check_out": quote.check_out.isoformat() if quote.check_out else None,
        "nights": quote.nights,
        "adults": quote.adults,
        "children": quote.children,
        "pets": quote.pets,
        "currency": quote.currency,
        "base_rent": float(quote.base_rent),
        "taxes": float(quote.taxes),
        "fees": float(quote.fees),
        "total_amount": float(quote.total_amount),
        "sovereign_narrative": quote.sovereign_narrative,
        "quote_breakdown": quote.quote_breakdown,
        "stripe_payment_link_url": quote.stripe_payment_link_url,
        "expires_at": quote.expires_at.isoformat(),
        "accepted_at": quote.accepted_at.isoformat() if quote.accepted_at else None,
        "created_at": quote.created_at.isoformat(),
    }


def _fmt(amount: float) -> str:
    return f"${amount:,.2f}"


def _fmt_date(d: date) -> str:
    return d.strftime("%B %-d, %Y")


def _build_taylor_email_html(
    req: TaylorQuoteRequest,
    quote_url_map: dict[str, str] | None = None,
) -> str:
    """Render the multi-property quote email for a TaylorQuoteRequest."""
    options: list[dict] = req.property_options or []
    nights = req.nights
    check_in_str = _fmt_date(req.check_in)
    check_out_str = _fmt_date(req.check_out)
    guest_summary = f"{req.adults} adult{'s' if req.adults != 1 else ''}"
    if req.children:
        guest_summary += f", {req.children} child{'ren' if req.children != 1 else ''}"
    if req.pets:
        guest_summary += f", {req.pets} pet{'s' if req.pets != 1 else ''}"

    property_cards_html = ""
    for opt in options:
        hero_url: str | None = opt.get("hero_image_url")
        hero_block = ""
        if hero_url:
            alt = opt.get("property_name", "Cabin")
            hero_block = (
                f'<tr><td style="padding:0;line-height:0;">'
                f'<img src="{hero_url}" alt="{alt}" width="576" '
                f'style="display:block;width:100%;max-height:240px;object-fit:cover;border-radius:10px 10px 0 0;">'
                f"</td></tr>"
            )

        beds = opt.get("bedrooms", 0)
        baths = opt.get("bathrooms", 0)
        max_g = opt.get("max_guests", 0)
        specs = f"{beds} bed &middot; {baths} bath &middot; up to {max_g} guests"

        base_rent = float(opt.get("base_rent", 0))
        fees = float(opt.get("fees", 0))
        taxes = float(opt.get("taxes", 0))
        total = float(opt.get("total_amount", 0))
        booking_url = (quote_url_map or {}).get(
            opt.get("property_id", ""), opt.get("booking_url", "#")
        )
        property_name = opt.get("property_name", "Cabin")

        property_cards_html += f"""
    <tr>
      <td style="padding:0 32px 28px;">
        <table width="100%" cellpadding="0" cellspacing="0"
               style="border:1px solid #e4e4e7;border-radius:10px;overflow:hidden;background:#fafafa;">
          {hero_block}
          <tr>
            <td style="padding:20px 20px 0;">
              <h3 style="margin:0 0 4px;color:#18181b;font-size:17px;font-weight:700;line-height:1.3;">
                {property_name}
              </h3>
              <p style="margin:0 0 16px;color:#71717a;font-size:13px;">{specs}</p>
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="font-size:14px;color:#52525b;border-top:1px solid #f4f4f5;">
                <tr>
                  <td style="padding:8px 0 6px;border-bottom:1px solid #f4f4f5;">Base rent</td>
                  <td align="right" style="padding:8px 0 6px;border-bottom:1px solid #f4f4f5;">{_fmt(base_rent)}</td>
                </tr>
                <tr>
                  <td style="padding:6px 0;border-bottom:1px solid #f4f4f5;">Fees</td>
                  <td align="right" style="padding:6px 0;border-bottom:1px solid #f4f4f5;">{_fmt(fees)}</td>
                </tr>
                <tr>
                  <td style="padding:6px 0 10px;border-bottom:1px solid #f4f4f5;">Taxes</td>
                  <td align="right" style="padding:6px 0 10px;border-bottom:1px solid #f4f4f5;">{_fmt(taxes)}</td>
                </tr>
                <tr>
                  <td style="padding:10px 0 0;font-weight:700;color:#18181b;font-size:16px;">Total</td>
                  <td align="right" style="padding:10px 0 0;font-weight:700;color:#18181b;font-size:16px;">
                    {_fmt(total)}
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:18px 20px 20px;" align="center">
              <a href="{booking_url}"
                 style="display:inline-block;background:#18181b;color:#ffffff;text-decoration:none;
                        padding:12px 32px;border-radius:8px;font-size:14px;font-weight:600;">
                Book This Cabin &rarr;
              </a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f4f4f5;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="max-width:640px;margin:40px auto;background:#ffffff;border-radius:12px;
                overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1);">
    <tr>
      <td style="background:#18181b;padding:28px 32px;text-align:center;">
        <h1 style="margin:0;color:#ffffff;font-size:20px;font-weight:700;letter-spacing:-0.025em;">
          Cabin Rentals of Georgia
        </h1>
      </td>
    </tr>
    <tr>
      <td style="padding:32px 32px 24px;">
        <h2 style="margin:0 0 8px;color:#18181b;font-size:22px;font-weight:700;line-height:1.3;">
          Your cabin quote is ready
        </h2>
        <p style="margin:0 0 6px;color:#52525b;font-size:15px;line-height:1.6;">
          We found <strong>{len(options)} available cabin{'s' if len(options) != 1 else ''}</strong>
          for your stay:
        </p>
        <p style="margin:0 0 0;color:#18181b;font-size:15px;font-weight:600;line-height:1.6;">
          {check_in_str} &rarr; {check_out_str}
          &nbsp;&middot;&nbsp; {nights} night{'s' if nights != 1 else ''}
          &nbsp;&middot;&nbsp; {guest_summary}
        </p>
      </td>
    </tr>
    {property_cards_html}
    <tr>
      <td style="padding:24px 32px;border-top:1px solid #f4f4f5;text-align:center;">
        <p style="margin:0;color:#a1a1aa;font-size:12px;line-height:1.8;">
          Questions? Reply to this email or call us at (706) 832-3231.<br>
          Cabin Rentals of Georgia &middot; Blue Ridge, GA
        </p>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _build_taylor_email_text(
    req: TaylorQuoteRequest,
    quote_url_map: dict[str, str] | None = None,
) -> str:
    lines = [
        "Your cabin quote is ready — Cabin Rentals of Georgia",
        "",
        f"Dates: {req.check_in} to {req.check_out} ({req.nights} nights)",
        f"Guests: {req.adults} adults, {req.children} children, {req.pets} pets",
        "",
    ]
    for opt in (req.property_options or []):
        book_link = (quote_url_map or {}).get(
            opt.get("property_id", ""), opt.get("booking_url", "")
        )
        lines += [
            opt.get("property_name", "Cabin"),
            f"  {opt.get('bedrooms', 0)} bed · {opt.get('bathrooms', 0)} bath",
            f"  Base rent: {_fmt(float(opt.get('base_rent', 0)))}",
            f"  Fees:      {_fmt(float(opt.get('fees', 0)))}",
            f"  Taxes:     {_fmt(float(opt.get('taxes', 0)))}",
            f"  Total:     {_fmt(float(opt.get('total_amount', 0)))}",
            f"  Book here: {book_link}",
            "",
        ]
    lines.append("Reply to this email or call (706) 832-3231 with questions.")
    return "\n".join(lines)


@router.post("/taylor/request")
async def create_taylor_quote_request(
    payload: TaylorQuoteCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Check availability across all active properties for the requested dates,
    price each available one via Streamline, and save a pending quote request
    for Taylor to review and approve.
    """
    today = date.today()
    if payload.check_in < today:
        raise HTTPException(status_code=400, detail="check_in must be today or later")
    if payload.check_out <= payload.check_in:
        raise HTTPException(status_code=400, detail="check_out must be after check_in")
    nights = (payload.check_out - payload.check_in).days
    if nights > 30:
        raise HTTPException(status_code=400, detail="Stay window cannot exceed 30 nights")

    # Load all active properties with Streamline IDs
    props_result = await db.execute(
        select(Property).where(
            Property.is_active.is_(True),
            Property.streamline_property_id.isnot(None),
        )
    )
    properties = list(props_result.scalars().all())

    # Build hero image lookup: property_id → URL
    hero_result = await db.execute(
        select(PropertyImage).where(
            PropertyImage.property_id.in_([p.id for p in properties]),
            PropertyImage.status == "ingested",
        ).order_by(PropertyImage.is_hero.desc(), PropertyImage.display_order)
    )
    all_images = list(hero_result.scalars().all())
    # Keep only the best image per property
    hero_map: dict[str, str] = {}
    for img in all_images:
        key = str(img.property_id)
        if key not in hero_map:
            hero_map[key] = img.sovereign_url or img.legacy_url

    # Quote each property.  Primary path: sovereign fast-quote service (SQL ledger, same engine
    # as /api/direct-booking/quote).  Fallback path: deterministic quote (Streamline rate card)
    # for properties whose SQL ledger is not yet fully configured.
    property_options: list[dict[str, Any]] = []
    storefront_base = settings.storefront_base_url.rstrip("/")
    sl_client = StreamlineClient()
    try:
        for prop in properties:
            guests = (payload.adults or 2) + (payload.children or 0)
            slug = prop.slug or ""
            booking_url = (
                f"{storefront_base}/cabins/{slug}"
                f"?checkin={payload.check_in.isoformat()}"
                f"&checkout={payload.check_out.isoformat()}"
                f"&adults={payload.adults}"
            )

            # --- Primary: sovereign fast-quote (SQL ledger) ---
            try:
                breakdown = await calculate_locked_fast_quote_breakdown(
                    db,
                    prop.id,
                    payload.check_in,
                    payload.check_out,
                    guests,
                    adults=payload.adults,
                    children=payload.children,
                    pets=payload.pets,
                )
                fees_total = float(breakdown.cleaning + breakdown.admin_fee + breakdown.pet_fee)
                property_options.append({
                    "property_id": str(prop.id),
                    "property_name": prop.name,
                    "slug": slug,
                    "bedrooms": prop.bedrooms or 0,
                    "bathrooms": float(prop.bathrooms or 0),
                    "max_guests": prop.max_guests or 0,
                    "hero_image_url": hero_map.get(str(prop.id)),
                    "base_rent": float(breakdown.rent),
                    "fees": fees_total,
                    "taxes": float(breakdown.taxes),
                    "total_amount": float(breakdown.total),
                    "nights": nights,
                    "pricing_source": breakdown.pricing_source,
                    "line_items": list(breakdown.line_items),
                    "booking_url": booking_url,
                })
                continue

            except FastQuoteError as exc:
                if exc.code != "pricing_ledger_incomplete":
                    # Genuine availability / capacity block — property is unavailable.
                    log.info(
                        "taylor_property_unavailable",
                        property_name=prop.name,
                        property_id=str(prop.id),
                        code=exc.code,
                        detail=exc.message,
                    )
                    continue
                # SQL ledger not yet configured for this property — fall through to
                # the deterministic Streamline rate-card path below.
                log.info(
                    "taylor_property_pricing_fallback",
                    property_name=prop.name,
                    property_id=str(prop.id),
                    reason=exc.code,
                )

            except Exception as exc:
                log.warning(
                    "taylor_property_fast_quote_error",
                    property_name=prop.name,
                    property_id=str(prop.id),
                    error=str(exc)[:300],
                )
                continue

            # --- Fallback: deterministic quote via Streamline rate card ---
            try:
                det = await sl_client.get_deterministic_quote(
                    str(prop.id),
                    payload.check_in,
                    payload.check_out,
                    db,
                    adults=payload.adults,
                    children=payload.children,
                    pets=payload.pets,
                )
            except Exception as exc:
                log.warning(
                    "taylor_property_fallback_error",
                    property_name=prop.name,
                    property_id=str(prop.id),
                    error=str(exc)[:300],
                )
                continue

            if det.get("availability_status") != "available":
                log.info(
                    "taylor_property_unavailable",
                    property_name=prop.name,
                    property_id=str(prop.id),
                    code="streamline_unavailable",
                    detail=str(det.get("unavailable_dates", [])),
                )
                continue

            property_options.append({
                "property_id": str(prop.id),
                "property_name": prop.name,
                "slug": slug,
                "bedrooms": prop.bedrooms or 0,
                "bathrooms": float(prop.bathrooms or 0),
                "max_guests": prop.max_guests or 0,
                "hero_image_url": hero_map.get(str(prop.id)),
                "base_rent": det["base_rent"],
                "fees": det["fees"],
                "taxes": det["taxes"],
                "total_amount": det["total_amount"],
                "nights": nights,
                "pricing_source": det.get("pricing_source", "streamline_live"),
                "line_items": [],
                "booking_url": booking_url,
            })
    finally:
        await sl_client.close()

    req = TaylorQuoteRequest(
        guest_email=str(payload.guest_email),
        check_in=payload.check_in,
        check_out=payload.check_out,
        nights=nights,
        adults=payload.adults,
        children=payload.children,
        pets=payload.pets,
        status=TaylorQuoteStatus.PENDING_APPROVAL.value,
        property_options=property_options,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    return {
        "id": str(req.id),
        "status": req.status,
        "guest_email": req.guest_email,
        "check_in": str(req.check_in),
        "check_out": str(req.check_out),
        "nights": req.nights,
        "adults": req.adults,
        "children": req.children,
        "pets": req.pets,
        "available_property_count": len(property_options),
        "property_options": property_options,
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }


@router.get("/taylor/pending")
async def list_taylor_quote_requests(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """List pending and recently sent Taylor quote requests."""
    from sqlalchemy import desc
    result = await db.execute(
        select(TaylorQuoteRequest)
        .order_by(desc(TaylorQuoteRequest.created_at))
        .limit(limit)
    )
    rows = list(result.scalars().all())
    return {
        "requests": [
            {
                "id": str(r.id),
                "status": r.status,
                "guest_email": r.guest_email,
                "check_in": str(r.check_in),
                "check_out": str(r.check_out),
                "nights": r.nights,
                "adults": r.adults,
                "children": r.children,
                "pets": r.pets,
                "available_property_count": len(r.property_options or []),
                "property_options": r.property_options or [],
                "approved_by": r.approved_by,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/taylor/{request_id}")
async def get_taylor_quote_request(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(
        select(TaylorQuoteRequest).where(TaylorQuoteRequest.id == request_id)
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Taylor quote request not found")
    return {
        "id": str(req.id),
        "status": req.status,
        "guest_email": req.guest_email,
        "check_in": str(req.check_in),
        "check_out": str(req.check_out),
        "nights": req.nights,
        "adults": req.adults,
        "children": req.children,
        "pets": req.pets,
        "available_property_count": len(req.property_options or []),
        "property_options": req.property_options or [],
        "approved_by": req.approved_by,
        "sent_at": req.sent_at.isoformat() if req.sent_at else None,
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }


@router.post("/taylor/{request_id}/approve")
async def approve_taylor_quote_request(
    request_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Approve and send the multi-property quote email to the guest."""
    result = await db.execute(
        select(TaylorQuoteRequest).where(TaylorQuoteRequest.id == request_id)
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Taylor quote request not found")
    if req.status != TaylorQuoteStatus.PENDING_APPROVAL.value:
        raise HTTPException(
            status_code=409,
            detail=f"Request is already '{req.status}' — cannot approve again",
        )
    if not req.property_options:
        raise HTTPException(
            status_code=422,
            detail="No available properties to quote — cannot send an empty quote",
        )
    if not is_email_configured():
        raise HTTPException(status_code=503, detail="Email delivery is not configured")

    # ── Step A: mint one GuestQuote per property option ──────────────────
    # Pricing is frozen from the stored JSONB — guests see exactly what Taylor
    # reviewed.  48-hour TTL gives guests overnight to decide.
    TAYLOR_TTL_HOURS = 48
    storefront_base = settings.storefront_base_url.rstrip("/")

    # Build property_name lookup alongside the quote objects so we can include
    # human-readable names in the response without re-querying the options list.
    property_name_map: dict[str, str] = {}
    quotes: list[GuestQuote] = []

    for opt in req.property_options:
        prop_id_str: str = opt["property_id"]
        property_name_map[prop_id_str] = opt.get("property_name", "")

        base_rent  = Decimal(str(opt.get("base_rent", "0")))
        taxes      = Decimal(str(opt.get("taxes",     "0")))
        fees       = Decimal(str(opt.get("fees",      "0")))
        total      = base_rent + taxes + fees

        q = GuestQuote(
            target_property_id      = prop_id_str,
            property_id             = UUID(prop_id_str),
            guest_email             = req.guest_email,
            check_in                = req.check_in,
            check_out               = req.check_out,
            nights                  = req.nights,
            adults                  = req.adults,
            children                = req.children,
            pets                    = req.pets,
            base_rent               = base_rent,
            taxes                   = taxes,
            fees                    = fees,
            total_amount            = total,
            base_price              = float(base_rent),
            ai_adjusted_price       = float(total),
            sovereign_narrative     = "",
            campaign                = "taylor",
            quote_breakdown         = {
                "base_rent":        str(base_rent),
                "taxes":            str(taxes),
                "fees":             str(fees),
                "total":            str(total),
                "pricing_source":   opt.get("pricing_source", "taylor"),
                "nightly_breakdown": None,
            },
            source_snapshot         = {
                "resolved_property_id":   prop_id_str,
                "resolved_property_name": opt.get("property_name", ""),
                "pricing_source":         opt.get("pricing_source", "taylor"),
                "taylor_request_id":      str(req.id),
            },
            stripe_payment_link_url = opt.get("stripe_payment_link_url"),
            expires_at              = datetime.utcnow() + timedelta(hours=TAYLOR_TTL_HOURS),
            status                  = GuestQuoteStatus.PENDING,
        )
        db.add(q)
        quotes.append(q)

    # Flush to get auto-generated UUIDs without committing — if email fails we
    # rollback cleanly and no orphaned GuestQuote rows are persisted.
    await db.flush()

    # ── Step B: build per-property quote URL map ──────────────────────────
    quote_url_map: dict[str, str] = {
        str(q.property_id): f"{storefront_base}/quote/{q.id}"
        for q in quotes
    }

    # ── Step C: build and send the email ─────────────────────────────────
    nights = req.nights
    subject = (
        f"Your cabin quote: {req.check_in.strftime('%b %-d')} – "
        f"{req.check_out.strftime('%b %-d, %Y')} "
        f"({nights} night{'s' if nights != 1 else ''})"
    )
    html_body = _build_taylor_email_html(req, quote_url_map=quote_url_map)
    text_body = _build_taylor_email_text(req, quote_url_map=quote_url_map)

    sent = send_email(
        to=req.guest_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )
    if not sent:
        # HTTPException causes the session context manager to rollback — the
        # flushed GuestQuote rows are never committed.
        raise HTTPException(
            status_code=502,
            detail="Quote email dispatch failed. Check SMTP configuration and delivery logs.",
        )

    # ── Step D: commit everything atomically ──────────────────────────────
    actor = (
        request.headers.get("x-user-email")
        or request.headers.get("x-user-id")
        or "taylor"
    )
    req.status      = TaylorQuoteStatus.SENT.value
    req.approved_by = actor
    req.sent_at     = datetime.utcnow()
    await db.commit()

    # ── Step E: return quote URLs for logging / command-center display ────
    return {
        "status":         "sent",
        "request_id":     str(req.id),
        "guest_email":    req.guest_email,
        "approved_by":    req.approved_by,
        "sent_at":        req.sent_at.isoformat() if req.sent_at else None,
        "property_count": len(req.property_options),
        "guest_quotes": [
            {
                "property_id":   str(q.property_id),
                "property_name": property_name_map.get(str(q.property_id), ""),
                "quote_id":      str(q.id),
                "quote_url":     quote_url_map[str(q.property_id)],
                "expires_at":    q.expires_at.isoformat(),
            }
            for q in quotes
        ],
    }


@router.get("/{quote_id}")
async def get_guest_quote(quote_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GuestQuote).where(GuestQuote.id == quote_id))
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    return {
        "id": str(quote.id),
        "status": quote.status,
        "property_id": str(quote.property_id) if quote.property_id else None,
        "guest_name": quote.guest_name,
        "guest_email": quote.guest_email,
        "check_in": str(quote.check_in) if quote.check_in else None,
        "check_out": str(quote.check_out) if quote.check_out else None,
        "nights": quote.nights,
        "total_amount": float(quote.total_amount or 0),
        "stripe_payment_link_url": quote.stripe_payment_link_url,
        "expires_at": str(quote.expires_at) if quote.expires_at else None,
    }


@router.get("/{quote_id}/checkout")
async def quote_checkout_status(quote_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GuestQuote).where(GuestQuote.id == quote_id))
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    return {
        "quote_id": str(quote.id),
        "status": quote.status,
        "is_payable": quote.status == GuestQuoteStatus.PENDING,
        "payment_link_url": quote.stripe_payment_link_url,
        "total_amount": float(quote.total_amount or 0),
    }
