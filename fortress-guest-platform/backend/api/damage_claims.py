"""
Damage Claims API — Post-checkout damage reporting + legal draft workflow
"""
from typing import List, Optional
from uuid import UUID
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, or_
from pydantic import BaseModel, Field

from backend.core.database import get_db
from backend.core.security import require_manager_or_admin
from backend.models import DamageClaim, Reservation, Property, Guest

router = APIRouter(dependencies=[Depends(require_manager_or_admin)])


class DamageClaimCreate(BaseModel):
    reservation_id: UUID
    damage_description: str = Field(..., min_length=10)
    policy_violations: Optional[str] = None
    damage_areas: Optional[List[str]] = None
    estimated_cost: Optional[float] = None
    photo_urls: Optional[List[str]] = None
    reported_by: str = Field(default="staff")
    inspection_date: Optional[date] = None
    inspection_notes: Optional[str] = None


class DamageClaimUpdate(BaseModel):
    damage_description: Optional[str] = None
    policy_violations: Optional[str] = None
    damage_areas: Optional[List[str]] = None
    estimated_cost: Optional[float] = None
    photo_urls: Optional[List[str]] = None
    inspection_notes: Optional[str] = None
    status: Optional[str] = None
    final_response: Optional[str] = None
    resolution: Optional[str] = None
    resolution_amount: Optional[float] = None


class DamageClaimResponse(BaseModel):
    id: UUID
    claim_number: str
    reservation_id: UUID
    property_id: UUID
    guest_id: UUID
    damage_description: str
    policy_violations: Optional[str]
    damage_areas: Optional[List[str]]
    estimated_cost: Optional[float]
    photo_urls: Optional[List[str]]
    reported_by: str
    inspection_date: date
    inspection_notes: Optional[str]
    legal_draft: Optional[str]
    legal_draft_model: Optional[str]
    legal_draft_at: Optional[datetime]
    agreement_clauses: Optional[dict]
    status: str
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    final_response: Optional[str]
    sent_at: Optional[datetime]
    sent_via: Optional[str]
    resolution: Optional[str]
    resolution_amount: Optional[float]
    resolved_at: Optional[datetime]
    created_at: Optional[datetime]
    guest_name: Optional[str] = None
    guest_email: Optional[str] = None
    guest_phone: Optional[str] = None
    property_name: Optional[str] = None
    confirmation_code: Optional[str] = None
    check_in_date: Optional[date] = None
    check_out_date: Optional[date] = None
    streamline_notes: Optional[list] = None

    class Config:
        from_attributes = True


def _enrich(claim: DamageClaim, guest: Guest = None, prop: Property = None, res: Reservation = None) -> DamageClaimResponse:
    data = {c.name: getattr(claim, c.name) for c in claim.__table__.columns}
    if guest:
        data["guest_name"] = f"{guest.first_name} {guest.last_name}"
        data["guest_email"] = guest.email
        data["guest_phone"] = guest.phone_number
    if prop:
        data["property_name"] = prop.name
    if res:
        data["confirmation_code"] = res.confirmation_code
        data["check_in_date"] = res.check_in_date
        data["check_out_date"] = res.check_out_date
        data["streamline_notes"] = res.streamline_notes or []
    return DamageClaimResponse(**data)


async def _fetch_enriched(db: AsyncSession, claim_id) -> DamageClaimResponse:
    """Re-fetch a claim with its related records after a mutation."""
    result = await db.execute(
        select(DamageClaim, Guest, Property, Reservation)
        .join(Guest, DamageClaim.guest_id == Guest.id)
        .join(Property, DamageClaim.property_id == Property.id)
        .join(Reservation, DamageClaim.reservation_id == Reservation.id)
        .where(DamageClaim.id == claim_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(404, "Claim not found")
    c, g, p, r = row
    return _enrich(c, g, p, r)


@router.get("/reservation-options")
async def reservation_options(
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
):
    """Return recent reservations enriched with guest/property names for the claim form."""
    result = await db.execute(
        select(Reservation, Guest, Property)
        .join(Guest, Reservation.guest_id == Guest.id)
        .join(Property, Reservation.property_id == Property.id)
        .order_by(desc(Reservation.check_in_date))
        .limit(limit)
    )
    rows = result.all()
    return [
        {
            "id": str(r.id),
            "confirmation_code": r.confirmation_code,
            "guest_name": f"{g.first_name} {g.last_name}",
            "property_name": p.name,
            "check_in_date": str(r.check_in_date),
            "check_out_date": str(r.check_out_date),
            "status": r.status,
        }
        for r, g, p in rows
    ]


@router.get("/", response_model=List[DamageClaimResponse])
async def list_claims(
    status: Optional[str] = None,
    property_id: Optional[UUID] = None,
    search: Optional[str] = Query(None, description="Search by guest name, property, claim#, or description"),
    year: Optional[int] = Query(None, description="Filter by check-in year"),
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(DamageClaim, Guest, Property, Reservation)
        .join(Guest, DamageClaim.guest_id == Guest.id)
        .join(Property, DamageClaim.property_id == Property.id)
        .join(Reservation, DamageClaim.reservation_id == Reservation.id)
    )
    if status and status != "all":
        query = query.where(DamageClaim.status == status)
    if property_id:
        query = query.where(DamageClaim.property_id == property_id)
    if year:
        query = query.where(func.extract("year", Reservation.check_in_date) == year)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Guest.first_name.ilike(term),
                Guest.last_name.ilike(term),
                func.concat(Guest.first_name, ' ', Guest.last_name).ilike(term),
                Guest.email.ilike(term),
                Property.name.ilike(term),
                DamageClaim.claim_number.ilike(term),
                DamageClaim.damage_description.ilike(term),
                Reservation.confirmation_code.ilike(term),
            )
        )
    query = query.order_by(desc(DamageClaim.created_at)).limit(limit)
    result = await db.execute(query)
    return [_enrich(c, g, p, r) for c, g, p, r in result.all()]


@router.get("/stats")
async def claim_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DamageClaim.status, func.count(DamageClaim.id))
        .group_by(DamageClaim.status)
    )
    counts = {row[0]: row[1] for row in result.all()}
    total_cost = await db.execute(
        select(func.sum(DamageClaim.estimated_cost))
        .where(DamageClaim.status != "closed")
    )
    return {
        "total": sum(counts.values()),
        "by_status": counts,
        "open_estimated_cost": float(total_cost.scalar() or 0),
    }


@router.get("/{claim_id}", response_model=DamageClaimResponse)
async def get_claim(claim_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DamageClaim, Guest, Property, Reservation)
        .join(Guest, DamageClaim.guest_id == Guest.id)
        .join(Property, DamageClaim.property_id == Property.id)
        .join(Reservation, DamageClaim.reservation_id == Reservation.id)
        .where(DamageClaim.id == claim_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(404, "Claim not found")
    c, g, p, r = row
    return _enrich(c, g, p, r)


@router.post("/", response_model=DamageClaimResponse)
async def create_claim(
    body: DamageClaimCreate,
    db: AsyncSession = Depends(get_db),
):
    reservation = await db.get(Reservation, body.reservation_id)
    if not reservation:
        raise HTTPException(404, "Reservation not found")

    claim = DamageClaim(
        claim_number="",
        reservation_id=reservation.id,
        property_id=reservation.property_id,
        guest_id=reservation.guest_id,
        damage_description=body.damage_description,
        policy_violations=body.policy_violations,
        damage_areas=body.damage_areas,
        estimated_cost=body.estimated_cost,
        photo_urls=body.photo_urls,
        reported_by=body.reported_by,
        inspection_date=body.inspection_date or date.today(),
        inspection_notes=body.inspection_notes,
        status="reported",
    )
    db.add(claim)
    await db.commit()
    await db.refresh(claim)
    return await _fetch_enriched(db, claim.id)


@router.patch("/{claim_id}", response_model=DamageClaimResponse)
async def update_claim(
    claim_id: UUID,
    body: DamageClaimUpdate,
    db: AsyncSession = Depends(get_db),
):
    claim = await db.get(DamageClaim, claim_id)
    if not claim:
        raise HTTPException(404, "Claim not found")

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(claim, field, value)

    if body.status == "resolved" and not claim.resolved_at:
        claim.resolved_at = datetime.utcnow()

    await db.commit()
    await db.refresh(claim)
    return await _fetch_enriched(db, claim.id)


@router.post("/{claim_id}/generate-legal-draft", response_model=DamageClaimResponse)
async def generate_legal_draft(
    claim_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Trigger the full Damage Command Center 6-step workflow:
    Investigator → Golden Memory → Contract Auditor (NIM FP8) →
    Legal Drafter (Anthropic Opus) → Council Review → Persist.
    """
    claim = await db.get(DamageClaim, claim_id)
    if not claim:
        raise HTTPException(404, "Claim not found")

    import structlog
    log = structlog.get_logger()
    log.info(
        "legal_draft_generate_via_workflow",
        claim_number=claim.claim_number,
        claim_id=str(claim.id),
        reservation_id=str(claim.reservation_id),
    )

    from backend.services.damage_workflow import process_damage_claim

    workflow_result = await process_damage_claim(
        reservation_id=claim.reservation_id,
        staff_notes=claim.damage_description or "",
        db=db,
        reported_by=claim.reported_by or "staff",
        damage_areas=claim.damage_areas,
        estimated_cost=float(claim.estimated_cost) if claim.estimated_cost else None,
        photo_urls=claim.photo_urls,
    )

    log.info(
        "legal_draft_workflow_complete",
        claim_number=claim.claim_number,
        workflow_status=workflow_result.get("status"),
        steps=list(workflow_result.get("steps", {}).keys()),
        elapsed_ms=workflow_result.get("elapsed_ms"),
    )

    await db.refresh(claim)
    return await _fetch_enriched(db, claim.id)


@router.post("/{claim_id}/approve")
async def approve_claim(
    claim_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Approve the legal draft — marks ready to send, then embeds into Golden Memory."""
    claim = await db.get(DamageClaim, claim_id)
    if not claim:
        raise HTTPException(404, "Claim not found")

    claim.final_response = claim.final_response or claim.legal_draft
    claim.status = "approved"
    claim.reviewed_by = "management"
    claim.reviewed_at = datetime.utcnow()
    await db.commit()

    # Embed into Golden Memory (Qdrant fgp_golden_claims) — non-blocking
    qdrant_ok = False
    try:
        qdrant_ok = await _embed_claim_to_golden_memory(claim, db)
    except Exception as e:
        import structlog
        structlog.get_logger().warning(
            "golden_memory_embed_failed",
            claim_id=str(claim_id),
            error=str(e)[:200],
        )

    return {
        "ok": True,
        "claim_number": claim.claim_number,
        "status": "approved",
        "golden_memory_embedded": qdrant_ok,
    }


async def _embed_claim_to_golden_memory(claim: DamageClaim, db) -> bool:
    """Embed an approved claim into the fgp_golden_claims Qdrant collection.

    Combines the damage evidence + approved legal draft into a single
    embedding for RAG retrieval on future claims.

    Returns True on success, False on failure. Never raises — Constitution Rule 5.
    """
    import hashlib, uuid as _uuid
    import httpx
    import structlog

    from backend.core.config import settings
    from backend.core.vector_db import embed_text as embed_text_vector

    logger = structlog.get_logger()
    COLLECTION = "fgp_golden_claims"
    VECTOR_DIM = 768

    evidence = (claim.damage_description or "").strip()
    draft = (claim.final_response or claim.legal_draft or "").strip()
    if not evidence and not draft:
        return False

    combined = f"Damage: {evidence}. Response: {draft[:1000]}"

    qdrant_url = settings.qdrant_url.rstrip("/")
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}

    try:
        vec = await embed_text_vector(combined[:8000])
        if len(vec) != VECTOR_DIM:
            logger.warning("golden_embed_dim_mismatch", expected=VECTOR_DIM, got=len(vec))
            return False

        async with httpx.AsyncClient(timeout=30) as client:
            # Ensure collection exists
            check = await client.get(f"{qdrant_url}/collections/{COLLECTION}", headers=headers)
            if check.status_code != 200:
                await client.put(
                    f"{qdrant_url}/collections/{COLLECTION}",
                    json={"vectors": {"size": VECTOR_DIM, "distance": "Cosine"}},
                    headers=headers,
                )

            # Deterministic point ID
            seed = f"golden_claim:{claim.id}"
            point_id = str(_uuid.UUID(hashlib.md5(seed.encode()).hexdigest()))

            # Build payload
            reservation = await db.get(Reservation, claim.reservation_id) if claim.reservation_id else None
            prop = await db.get(Property, claim.property_id) if claim.property_id else None
            guest = await db.get(Guest, claim.guest_id) if claim.guest_id else None

            payload = {
                "claim_id": str(claim.id),
                "claim_number": claim.claim_number or "",
                "text": combined[:2000],
                "damage_description": evidence[:500],
                "legal_draft": draft[:1000],
                "resolution": (claim.resolution or "")[:500],
                "status": claim.status or "",
                "property_name": prop.name if prop else "",
                "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "",
                "confirmation_code": reservation.confirmation_code if reservation else "",
                "damage_areas": claim.damage_areas or [],
                "estimated_cost": float(claim.estimated_cost) if claim.estimated_cost else None,
                "embedded_at": datetime.utcnow().isoformat(),
            }

            # Upsert to Qdrant
            resp = await client.put(
                f"{qdrant_url}/collections/{COLLECTION}/points",
                json={"points": [{"id": point_id, "vector": vec, "payload": payload}]},
                headers=headers,
            )
            resp.raise_for_status()

            # Save point ID back to PostgreSQL
            claim.qdrant_point_id = point_id
            await db.commit()

            logger.info(
                "golden_memory_embedded",
                claim_number=claim.claim_number,
                point_id=point_id,
                collection=COLLECTION,
            )
            return True

    except Exception as e:
        logger.warning("golden_memory_embed_error", claim_id=str(claim.id), error=str(e)[:200])
        return False


@router.post("/{claim_id}/send")
async def send_claim_response(
    claim_id: UUID,
    via: str = "email",
    db: AsyncSession = Depends(get_db),
):
    """Send the approved response to the guest via SMS/email."""
    claim = await db.get(DamageClaim, claim_id)
    if not claim:
        raise HTTPException(404, "Claim not found")
    if claim.status not in ("approved", "draft_ready"):
        raise HTTPException(400, f"Claim must be approved before sending (current: {claim.status})")

    guest = await db.get(Guest, claim.guest_id)
    response_text = claim.final_response or claim.legal_draft

    if via in ("sms", "both") and guest.phone_number:
        from backend.services.message_service import MessageService
        svc = MessageService()
        await svc.send_sms(guest.phone_number, response_text[:1600])

    claim.sent_at = datetime.utcnow()
    claim.sent_via = via
    claim.status = "sent"
    await db.commit()
    return {"ok": True, "sent_via": via, "claim_number": claim.claim_number}


class DamageChargeRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Amount to charge in dollars")
    note: Optional[str] = None


@router.post("/{claim_id}/charge")
async def charge_damage_claim(
    claim_id: UUID,
    body: DamageChargeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_manager_or_admin),
):
    """
    Execute an off-session Stripe charge against the guest for a damage claim.
    Requires the guest to have a stripe_customer_id with a saved default payment method.
    If no saved method exists, returns moto_fallback=true so staff can use the MOTO terminal.
    """
    import stripe as stripe_lib
    from backend.integrations.stripe_payments import StripePayments

    claim = await db.get(DamageClaim, claim_id)
    if not claim:
        raise HTTPException(404, "Claim not found")
    if claim.status not in ("approved", "sent", "resolved"):
        raise HTTPException(400, f"Claim must be approved/sent/resolved before charging (current: {claim.status})")
    if claim.stripe_charge_id:
        raise HTTPException(400, f"Claim already charged: {claim.stripe_charge_id}")

    guest = await db.get(Guest, claim.guest_id)
    if not guest or not guest.stripe_customer_id:
        return {
            "charged": False,
            "moto_fallback": True,
            "reason": "no_saved_payment_method",
            "message": "Guest has no saved payment method — use the MOTO terminal to collect card details.",
        }

    amount_cents = int(round(body.amount * 100))
    reservation = await db.get(Reservation, claim.reservation_id) if claim.reservation_id else None
    conf_code = reservation.confirmation_code if reservation else str(claim_id)[:8]

    try:
        stripe = StripePayments()
        result = await stripe.charge_off_session(
            customer_id=guest.stripe_customer_id,
            amount_cents=amount_cents,
            description=f"Damage claim {claim.claim_number} — {conf_code}",
            metadata={
                "claim_id": str(claim.id),
                "claim_number": claim.claim_number or "",
                "reservation_id": str(claim.reservation_id or ""),
                "source": "fortress_damage_charge",
            },
        )
    except stripe_lib.error.CardError as e:
        raise HTTPException(402, f"Card declined: {e.user_message or str(e)}")
    except stripe_lib.error.InvalidRequestError as e:
        if "no attached payment source" in str(e).lower() or "no default payment method" in str(e).lower():
            return {
                "charged": False,
                "moto_fallback": True,
                "reason": "no_default_payment_method",
                "message": "Guest has no default payment method on file — use the MOTO terminal.",
            }
        raise HTTPException(400, f"Stripe error: {str(e)}")

    staff_email = (current_user or {}).get("email") or (current_user or {}).get("sub") or "staff"
    claim.stripe_charge_id = result["payment_intent_id"]
    claim.amount_charged = body.amount
    claim.charge_payment_method_id = result.get("payment_method_id") or ""
    claim.charge_executed_at = datetime.utcnow()
    claim.charge_executed_by = staff_email
    claim.status = "resolved"
    claim.resolution_amount = body.amount
    if body.note:
        claim.resolution = body.note
    claim.resolved_at = datetime.utcnow()
    await db.commit()

    logger.info(
        "damage_claim_charged",
        claim_id=str(claim.id),
        claim_number=claim.claim_number,
        stripe_charge_id=result["payment_intent_id"],
        amount=body.amount,
        staff=staff_email,
    )
    return {
        "charged": True,
        "stripe_charge_id": result["payment_intent_id"],
        "amount_charged": body.amount,
        "claim_number": claim.claim_number,
    }
