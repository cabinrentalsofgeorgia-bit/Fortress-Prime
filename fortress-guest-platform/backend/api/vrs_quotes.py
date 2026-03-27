"""
Public quote endpoints for guest checkout flows.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.queue import get_arq_pool
from backend.models.property import Property
from backend.models.vrs_add_on import VRSAddOn, VRSAddOnPricingModel, VRSAddOnScope
from backend.models.vrs_quotes import GuestQuote, GuestQuoteStatus
from backend.services.email_service import is_email_configured, send_email
from backend.services.async_jobs import enqueue_async_job, extract_request_actor
from backend.services.quote_builder import calculate_property_quote
from backend.services.streamline_client import StreamlineClient


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
