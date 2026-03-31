"""
Integrations API — PMS sync management and status

Endpoints:
  - Streamline status, sync, preview
  - Backfill: notes, agreements, financial detail, housekeeping, feedback
  - Owner balances and statements
  - Guest history lookup
"""
from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, text, desc
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from backend.core.database import get_db
from backend.core.security import RoleChecker, require_admin
from backend.integrations.streamline_vrs import (
    StreamlineVRS,
    is_streamline_circuit_placeholder,
)
from backend.models.staff import StaffRole, StaffUser

router = APIRouter(dependencies=[Depends(require_admin)])
logger = structlog.get_logger()


@router.get("/streamline/status")
async def streamline_status():
    """Get Streamline VRS connection status and sync info."""
    vrs = StreamlineVRS()
    health = await vrs.health_check()
    sync_status = vrs.get_sync_status()
    await vrs.close()
    return {
        "provider": "Streamline VRS",
        "health": health,
        "sync": sync_status,
    }


@router.post("/streamline/sync")
async def trigger_streamline_sync(db: AsyncSession = Depends(get_db)):
    """
    Manually trigger a full Streamline VRS sync.
    
    Syncs: Properties -> Reservations -> Guests
    Returns a summary of created/updated/error counts.
    """
    log = logger.bind(endpoint="streamline_sync")
    log.info("manual_sync_triggered")

    vrs = StreamlineVRS()
    try:
        summary = await vrs.sync_all(db)
        return {"status": "ok", "summary": summary}
    except Exception as e:
        log.error("manual_sync_failed", error=str(e))
        return {"status": "error", "message": str(e)}
    finally:
        await vrs.close()


@router.get("/streamline/properties")
async def preview_streamline_properties():
    """
    Preview properties from Streamline without writing to database.
    Useful for verifying the connection before running a full sync.
    """
    vrs = StreamlineVRS()
    try:
        properties = await vrs.fetch_properties()
        return {
            "count": len(properties),
            "properties": properties,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        await vrs.close()


@router.get("/streamline/reservations")
async def preview_streamline_reservations():
    """
    Preview upcoming reservations from Streamline without writing to database.
    """
    vrs = StreamlineVRS()
    try:
        reservations = await vrs.fetch_reservations()
        return {
            "count": len(reservations),
            "reservations": [
                {k: v for k, v in r.items() if k != "raw"}
                for r in reservations
            ],
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        await vrs.close()


@router.post("/notes/backfill")
async def backfill_reservation_notes(db: AsyncSession = Depends(get_db)):
    """
    Pull notes from Streamline for all reservations that don't have them yet.
    Uses GetReservationNotes per reservation.
    """
    from backend.models import Reservation

    log = logger.bind(endpoint="notes_backfill")
    log.info("notes_backfill_started")

    from sqlalchemy import or_, cast, String
    res_q = await db.execute(
        select(Reservation)
        .where(or_(
            Reservation.streamline_notes.is_(None),
            cast(Reservation.streamline_notes, String) == "[]",
        ))
        .where(Reservation.confirmation_code.isnot(None))
    )
    missing = res_q.scalars().all()

    vrs = StreamlineVRS()
    synced = 0
    empty = 0
    errors = []

    for res in missing:
        try:
            notes = await vrs.fetch_reservation_notes(res.confirmation_code)
            res.streamline_notes = notes if notes else []
            if notes:
                synced += 1
            else:
                empty += 1
        except Exception as e:
            res.streamline_notes = []
            errors.append(f"{res.confirmation_code}: {e}")

    await db.commit()
    await vrs.close()

    log.info("notes_backfill_complete", synced=synced, empty=empty, errors=len(errors))
    return {
        "status": "ok",
        "reservations_checked": len(missing),
        "with_notes": synced,
        "empty": empty,
        "errors": errors[:10],
    }


@router.post("/agreements/backfill")
async def backfill_agreements(db: AsyncSession = Depends(get_db)):
    """
    Generate rental agreements for all reservations that don't have one.

    For each reservation without a 'rental_agreement':
      1. Try to pull from Streamline (if document API permissions granted)
      2. Fall back to rendering the Standard Rental Agreement template
    """
    from backend.models import (
        Reservation, Guest, Property,
        RentalAgreement, AgreementTemplate,
    )
    from backend.services.agreement_renderer import (
        build_variable_context, render_template,
    )

    log = logger.bind(endpoint="agreements_backfill")
    log.info("backfill_started")

    tmpl_q = await db.execute(
        select(AgreementTemplate).where(
            AgreementTemplate.agreement_type == "rental_agreement",
            AgreementTemplate.is_active == True,
        ).limit(1)
    )
    template = tmpl_q.scalar_one_or_none()
    if not template:
        return {"status": "error", "message": "No active rental_agreement template found"}

    res_q = await db.execute(
        select(Reservation)
        .outerjoin(
            RentalAgreement,
            (RentalAgreement.reservation_id == Reservation.id)
            & (RentalAgreement.agreement_type == "rental_agreement"),
        )
        .where(
            RentalAgreement.id.is_(None),
            Reservation.status.notin_(["cancelled"]),
        )
    )
    missing = res_q.scalars().all()

    vrs = StreamlineVRS()
    generated = 0
    from_streamline = 0
    skipped = 0
    errors = []

    sl_docs_available = False
    if vrs.is_configured:
        try:
            probe = await vrs.fetch_all_documents()
            sl_docs_available = len(probe) > 0
        except Exception:
            pass

    for res in missing:
        try:
            if sl_docs_available:
                sl_docs = await vrs.fetch_reservation_documents(res.confirmation_code)
                if sl_docs:
                    for doc in sl_docs:
                        doc_content = doc.get("content") or doc.get("body") or doc.get("text", "")
                        signed_str = doc.get("signed_at") or doc.get("date_signed")
                        signed_at = None
                        if signed_str:
                            try:
                                signed_at = datetime.strptime(str(signed_str), "%m/%d/%Y")
                            except ValueError:
                                try:
                                    signed_at = datetime.fromisoformat(str(signed_str))
                                except ValueError:
                                    pass
                        ra = RentalAgreement(
                            guest_id=res.guest_id,
                            reservation_id=res.id,
                            property_id=res.property_id,
                            template_id=template.id,
                            agreement_type=(doc.get("type") or "rental_agreement").lower(),
                            rendered_content=doc_content,
                            status="signed" if signed_at else "viewed",
                            signed_at=signed_at,
                            signer_name=doc.get("signer_name", ""),
                        )
                        db.add(ra)
                        from_streamline += 1
                    continue

            guest = await db.get(Guest, res.guest_id)
            prop = await db.get(Property, res.property_id)
            if not guest or not prop:
                skipped += 1
                continue

            ctx = build_variable_context(reservation=res, guest=guest, prop=prop)
            rendered = render_template(template.content_markdown, ctx)

            ra = RentalAgreement(
                guest_id=res.guest_id,
                reservation_id=res.id,
                property_id=res.property_id,
                template_id=template.id,
                agreement_type="rental_agreement",
                rendered_content=rendered,
                status="signed",
                signed_at=res.check_in_date if hasattr(res.check_in_date, "isoformat") else None,
                signer_name=f"{guest.first_name} {guest.last_name}",
            )
            db.add(ra)
            generated += 1
        except Exception as e:
            errors.append(f"Res {res.confirmation_code}: {e}")

    await db.commit()
    await vrs.close()

    log.info("backfill_complete", generated=generated,
             from_streamline=from_streamline, skipped=skipped, errors=len(errors))

    return {
        "status": "ok",
        "reservations_missing_agreements": len(missing),
        "generated_from_template": generated,
        "from_streamline": from_streamline,
        "skipped": skipped,
        "errors": errors[:10],
    }


# ============================================================================
# Financial Enrichment — GetReservationPrice per reservation
# ============================================================================

@router.post("/prices/backfill")
async def backfill_reservation_prices(db: AsyncSession = Depends(get_db)):
    """
    Enrich reservations with detailed financial data from GetReservationPrice.
    Populates: cleaning_fee, pet_fee, damage_waiver_fee, service_fee,
    tax_amount, and the full streamline_financial_detail JSONB.
    """
    from backend.models import Reservation

    log = logger.bind(endpoint="prices_backfill")
    log.info("prices_backfill_started")

    res_q = await db.execute(
        select(Reservation)
        .where(
            Reservation.streamline_financial_detail.is_(None),
            Reservation.confirmation_code.isnot(None),
            Reservation.status.notin_(["cancelled"]),
        )
        .order_by(desc(Reservation.check_in_date))
    )
    missing = res_q.scalars().all()

    vrs = StreamlineVRS()
    enriched = 0
    errors = []

    for res in missing:
        try:
            price_data = await vrs.fetch_reservation_price(res.confirmation_code)
            if price_data:
                res.streamline_financial_detail = price_data
                vrs._apply_financial_detail(res, price_data)
                enriched += 1
        except Exception as e:
            if enriched == 0 and "E0014" in str(e):
                errors.append(f"GetReservationPrice not allowed — token upgrade needed")
                break
            errors.append(f"{res.confirmation_code}: {e}")

    await db.commit()
    await vrs.close()

    log.info("prices_backfill_complete", enriched=enriched, errors=len(errors))
    return {
        "status": "ok",
        "reservations_checked": len(missing),
        "enriched": enriched,
        "errors": errors[:10],
    }


# ============================================================================
# Owner Balances — GetUnitOwnerBalance per property
# ============================================================================

@router.post("/owners/sync")
async def sync_owner_balances(db: AsyncSession = Depends(get_db)):
    """
    Pull current owner balance for every property from Streamline,
    update properties.owner_balance JSONB and trust_balance table.
    """
    from backend.models import Property

    log = logger.bind(endpoint="owners_sync")
    log.info("owner_sync_started")

    vrs = StreamlineVRS()
    synced = 0
    errors = []

    try:
        owners_data = await vrs.fetch_owners()
        owner_map = {str(o.get("owner_id", "")): o for o in owners_data}
    except Exception as e:
        owner_map = {}
        errors.append(f"GetOwnerList: {e}")
    try:
        live_streamline_ids = {
            str(prop["streamline_property_id"])
            for prop in await vrs.fetch_properties()
            if str(prop.get("streamline_property_id", "")).strip()
        }
    except Exception as e:
        live_streamline_ids = set()
        errors.append(f"GetPropertyList: {e}")

    props_q = await db.execute(
        select(Property).where(Property.streamline_property_id.isnot(None))
    )
    props = props_q.scalars().all()

    for prop in props:
        try:
            streamline_id = str(prop.streamline_property_id or "").strip()
            if streamline_id not in live_streamline_ids:
                continue
            unit_id = int(streamline_id)
            bal = await vrs.fetch_unit_owner_balance(unit_id)
            if not bal or is_streamline_circuit_placeholder(bal):
                continue

            prop.owner_balance = bal
            ow_id = str(bal.get("owner_id", ""))
            if ow_id and ow_id in owner_map:
                ow = owner_map[ow_id]
                prop.owner_id = ow_id
                prop.owner_name = f"{ow.get('first_name', '')} {ow.get('last_name', '')}".strip()

            from decimal import Decimal
            owner_funds = Decimal(str(bal.get("owner_balance", 0) or 0))
            await db.execute(
                text("""
                    INSERT INTO trust_balance (property_id, owner_funds, last_updated)
                    VALUES (:pid, :funds, NOW())
                    ON CONFLICT (property_id) DO UPDATE
                    SET owner_funds = :funds, last_updated = NOW()
                """),
                {"pid": prop.streamline_property_id, "funds": float(owner_funds)},
            )
            synced += 1
        except Exception as e:
            if synced == 0 and "E0014" in str(e):
                errors.append("GetUnitOwnerBalance not allowed — token upgrade needed")
                break
            errors.append(f"{prop.name}: {e}")

    await db.commit()
    await vrs.close()

    log.info("owner_sync_complete", synced=synced, owners=len(owner_map))
    return {
        "status": "ok",
        "properties_checked": len(props),
        "balances_synced": synced,
        "owners_found": len(owner_map),
        "errors": errors[:10],
    }


@router.get("/owners/list")
async def list_owners():
    """Fetch the owner directory from Streamline (live)."""
    vrs = StreamlineVRS()
    try:
        owners = await vrs.fetch_owners()
        return {"count": len(owners), "owners": owners}
    except Exception as e:
        return {"error": str(e)}
    finally:
        await vrs.close()


@router.get("/owners/{owner_id}/statement")
async def get_owner_statement(
    owner_id: int,
    unit_id: Optional[int] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    include_pdf: bool = Query(False),
):
    """Fetch a monthly owner statement from Streamline (live)."""
    vrs = StreamlineVRS()
    try:
        start_date = date.fromisoformat(start) if start else None
        end_date = date.fromisoformat(end) if end else None
        data = await vrs.fetch_owner_statement(
            owner_id=owner_id, unit_id=unit_id,
            start_date=start_date, end_date=end_date,
            include_pdf=include_pdf,
        )
        return data if data else {"message": "No statement data returned"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        await vrs.close()


# ============================================================================
# Housekeeping — GetHousekeepingCleaningReport
# ============================================================================

@router.post("/housekeeping/sync")
async def sync_housekeeping(db: AsyncSession = Depends(get_db)):
    """
    Pull the full housekeeping/cleaning schedule from Streamline and
    create or update HousekeepingTask records.
    """
    from backend.models import Property, Reservation
    from backend.services.housekeeping_service import HousekeepingTask

    log = logger.bind(endpoint="housekeeping_sync")
    log.info("housekeeping_sync_started")

    vrs = StreamlineVRS()
    created = 0
    updated = 0
    errors = []

    try:
        hk_data = await vrs.fetch_housekeeping_report()

        raw_cleanings = []
        res_block = hk_data.get("reservations", {})
        if isinstance(res_block, dict):
            items = res_block.get("reservation", [])
            if isinstance(items, dict):
                items = [items]
            raw_cleanings = items

        for cl in raw_cleanings:
            unit_id = str(cl.get("unit_id", ""))
            prop_q = await db.execute(
                select(Property).where(Property.streamline_property_id == unit_id)
            )
            prop = prop_q.scalar_one_or_none()
            if not prop:
                continue

            clean_date = vrs._parse_streamline_date(
                cl.get("cleaning_date") or cl.get("date")
            )
            if not clean_date:
                continue

            existing_q = await db.execute(
                select(HousekeepingTask).where(
                    HousekeepingTask.property_id == prop.id,
                    HousekeepingTask.scheduled_date == clean_date,
                )
            )
            existing_hk = existing_q.scalar_one_or_none()

            ev_status = (cl.get("event_status_name") or "").lower()
            hk_status_name = (cl.get("housekeeping_status_name") or "").lower()
            if "complete" in ev_status or "clean" == hk_status_name:
                mapped_status = "completed"
            elif "progress" in ev_status or "cleaning" in hk_status_name:
                mapped_status = "in_progress"
            else:
                mapped_status = "pending"

            cleaner = cl.get("processor_name", "")

            if existing_hk:
                existing_hk.status = mapped_status
                existing_hk.assigned_to = cleaner or existing_hk.assigned_to
                existing_hk.streamline_source = cl
                existing_hk.streamline_synced_at = datetime.utcnow()
                updated += 1
            else:
                conf_id = cl.get("confirmation_id")
                res_id = None
                if conf_id:
                    res_q = await db.execute(
                        select(Reservation.id).where(
                            Reservation.confirmation_code == str(conf_id)
                        )
                    )
                    row = res_q.first()
                    if row:
                        res_id = row[0]

                hk = HousekeepingTask(
                    property_id=prop.id,
                    reservation_id=res_id,
                    scheduled_date=clean_date,
                    status=mapped_status,
                    assigned_to=cleaner or None,
                    cleaning_type="turnover",
                    streamline_source=cl,
                    streamline_synced_at=datetime.utcnow(),
                )
                db.add(hk)
                created += 1

        await db.commit()
    except Exception as e:
        errors.append(str(e))

    await vrs.close()

    log.info("housekeeping_sync_complete", created=created, updated=updated)
    return {
        "status": "ok",
        "created": created,
        "updated": updated,
        "errors": errors[:10],
    }


@router.get("/housekeeping/report")
async def preview_housekeeping_report(unit_id: Optional[int] = Query(None)):
    """Preview Streamline housekeeping report (live, no DB write)."""
    vrs = StreamlineVRS()
    try:
        data = await vrs.fetch_housekeeping_report(unit_id=unit_id)
        return data
    except Exception as e:
        return {"error": str(e)}
    finally:
        await vrs.close()


# ============================================================================
# Guest Feedback — GetAllFeedback
# ============================================================================

@router.post("/feedback/sync")
async def sync_guest_feedback(db: AsyncSession = Depends(get_db)):
    """
    Pull all guest feedback from Streamline and insert as GuestReview records.
    Skips feedback already imported (by streamline_feedback_id).
    """
    from backend.models import Property, Reservation, Guest, GuestReview

    log = logger.bind(endpoint="feedback_sync")
    log.info("feedback_sync_started")

    vrs = StreamlineVRS()
    imported = 0
    skipped = 0
    errors = []

    try:
        feedback = await vrs.fetch_all_feedback()

        for fb in feedback:
            fb_id = str(fb.get("id", fb.get("comment_id", "")))
            if not fb_id:
                skipped += 1
                continue

            existing = await db.execute(
                select(GuestReview).where(GuestReview.streamline_feedback_id == fb_id)
            )
            if existing.scalar_one_or_none():
                skipped += 1
                continue

            unit_id = str(fb.get("unit_id", ""))
            prop_q = await db.execute(
                select(Property).where(Property.streamline_property_id == unit_id)
            )
            prop = prop_q.scalar_one_or_none()
            if not prop:
                skipped += 1
                continue

            res = None
            guest_id = None
            conf_id = fb.get("reservation_id")
            if conf_id:
                res_q = await db.execute(
                    select(Reservation).where(Reservation.confirmation_code == str(conf_id))
                )
                res = res_q.scalar_one_or_none()
                if res:
                    guest_id = res.guest_id

            if not guest_id:
                sl_client_id = fb.get("client_id")
                if sl_client_id:
                    guest_q = await db.execute(
                        select(Guest).where(Guest.streamline_guest_id == str(sl_client_id))
                    )
                    g = guest_q.scalar_one_or_none()
                    if g:
                        guest_id = g.id

            if not guest_id:
                fb_email = (fb.get("email") or "").strip()
                if fb_email:
                    guest_q = await db.execute(
                        select(Guest).where(Guest.email == fb_email)
                    )
                    g = guest_q.scalar_one_or_none()
                    if g:
                        guest_id = g.id

            if not guest_id:
                skipped += 1
                continue

            points = int(fb.get("points", 0) or 0)
            overall = points if 1 <= points <= 5 else 5

            review = GuestReview(
                guest_id=guest_id,
                reservation_id=res.id if res else None,
                property_id=prop.id,
                direction="guest_to_property",
                overall_rating=overall,
                title=fb.get("title", ""),
                body=fb.get("comments") or fb.get("comment") or "",
                streamline_feedback_id=fb_id,
                source="streamline_feedback",
                is_published=bool(fb.get("show_in_site")),
            )
            db.add(review)
            imported += 1

        await db.commit()
    except Exception as e:
        errors.append(str(e))

    await vrs.close()

    log.info("feedback_sync_complete", imported=imported, skipped=skipped)
    return {
        "status": "ok",
        "total_feedback": len(feedback) if 'feedback' in dir() else 0,
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:10],
    }


@router.get("/feedback/preview")
async def preview_feedback():
    """Preview all guest feedback from Streamline (live, no DB write)."""
    vrs = StreamlineVRS()
    try:
        data = await vrs.fetch_all_feedback()
        return {"count": len(data), "feedback": data[:50]}
    except Exception as e:
        return {"error": str(e)}
    finally:
        await vrs.close()


# ============================================================================
# Guest History — GetClientReservationsHistory
# ============================================================================

@router.get("/guests/{guest_email}/history")
async def get_guest_history_by_email(guest_email: str):
    """
    Look up a guest by email and return their full reservation history
    from Streamline.
    """
    vrs = StreamlineVRS()
    try:
        lookup = await vrs.fetch_guest_by_email(guest_email)
        if not lookup:
            raise HTTPException(status_code=404, detail="Guest not found in Streamline")

        client_id = None
        if isinstance(lookup, dict):
            reservations = lookup.get("reservations", lookup.get("reservation", []))
            if isinstance(reservations, dict):
                reservations = [reservations]
            if reservations:
                client_id = str(reservations[0].get("client_id", ""))

        result = {"email": guest_email, "streamline_data": lookup, "history": []}

        if client_id:
            history = await vrs.fetch_guest_history(client_id)
            result["client_id"] = client_id
            result["history"] = history

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        await vrs.close()


@router.get("/reservation/{confirmation_code}/detail")
async def get_reservation_detail(confirmation_code: str):
    """
    Fetch full reservation detail from Streamline including
    taxes, fees, commissions, payment folio, and housekeeping.
    """
    vrs = StreamlineVRS()
    try:
        info = await vrs.fetch_reservation_info(confirmation_code)
        price = await vrs.fetch_reservation_price(confirmation_code)
        notes = await vrs.fetch_reservation_notes(confirmation_code)
        return {
            "confirmation_code": confirmation_code,
            "info": info,
            "price": price,
            "notes": notes,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        await vrs.close()
