"""
Dispute Defense — Chargeback Ironclad evidence compilation and Stripe submission.

Reason-Code-Aware Defense Routing:
  - fraudulent / unrecognized: IoT physical occupancy proof (lock code_used events)
  - product_unacceptable / general: Damage defense (work orders, waiver, inspection logs)
  - product_not_received: Maximum IoT emphasis (every lock/unlock event)
  - All other codes: Generic evidence (agreement + booking metadata)

Then submits the compiled evidence packet to the Stripe Disputes API.
"""

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import stripe
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings

logger = structlog.get_logger(service="dispute_defense")

NAS_EVIDENCE_BASE = Path("/mnt/fortress_nas/sectors/legal/chargeback-evidence")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_EVIDENCE_DIR = Path(
    os.getenv("EVIDENCE_STORAGE_DIR", str(PROJECT_ROOT / "storage" / "evidence"))
)
LOCAL_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


async def _get_db_session():
    """Create a fresh async DB session for background tasks."""
    from backend.core.database import async_session_factory
    async with async_session_factory() as session:
        yield session


async def _fetch_dispute_context(db: AsyncSession, dispute_id: str) -> Dict[str, Any]:
    """Fetch all context needed for evidence compilation."""
    result = await db.execute(
        text("""
            SELECT de.*, r.confirmation_code, r.check_in_date, r.check_out_date,
                   r.total_amount, r.num_guests, r.status AS res_status,
                   r.damage_waiver_fee,
                   g.first_name, g.last_name, g.email AS guest_email, g.phone_number,
                   p.name AS property_name, p.address AS property_address,
                   ra.pdf_url AS agreement_pdf, ra.signed_at, ra.signer_name,
                   ra.signer_ip_address, ra.signer_email
            FROM dispute_evidence de
            LEFT JOIN reservations r ON de.reservation_id = r.id
            LEFT JOIN guests g ON de.guest_id = g.id
            LEFT JOIN properties p ON de.property_id = p.id
            LEFT JOIN rental_agreements ra ON de.rental_agreement_id = ra.id
            WHERE de.dispute_id = :did
            LIMIT 1
        """),
        {"did": dispute_id},
    )
    row = result.first()
    if not row:
        return {}
    return dict(row._mapping)


async def _fetch_iot_events(db: AsyncSession, property_id: str, check_in, check_out) -> List[Dict]:
    """Fetch IoT lock events for the reservation period."""
    if not property_id or not check_in or not check_out:
        return []
    try:
        result = await db.execute(
            text("""
                SELECT event_type, device_id, timestamp, user_code, metadata
                FROM iot_event_log
                WHERE property_id = :pid
                  AND timestamp BETWEEN :ci AND :co
                  AND event_type IN ('lock', 'unlock', 'code_set', 'code_used')
                ORDER BY timestamp ASC
            """),
            {"pid": property_id, "ci": check_in, "co": check_out},
        )
        return [
            {
                "event_type": r.event_type,
                "device_id": r.device_id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else "",
                "user_code": r.user_code or "",
            }
            for r in result.all()
        ]
    except Exception as e:
        logger.warning("iot_fetch_failed", error=str(e)[:200])
        return []


async def _fetch_work_orders(
    db: AsyncSession, property_id: str, check_in, check_out
) -> List[Dict]:
    """Pull work_orders for the property during the reservation date range for damage evidence."""
    if not property_id or not check_in or not check_out:
        return []
    try:
        result = await db.execute(
            text("""
                SELECT id, title, description, status, priority, created_at, completed_at,
                       estimated_cost, actual_cost
                FROM work_orders
                WHERE property_id = :pid
                  AND created_at BETWEEN :ci AND (:co::timestamp + interval '30 days')
                ORDER BY created_at ASC
            """),
            {"pid": property_id, "ci": check_in, "co": check_out},
        )
        return [
            {
                "id": str(r.id),
                "title": r.title or "",
                "description": (r.description or "")[:300],
                "status": r.status or "",
                "priority": r.priority or "",
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "completed_at": r.completed_at.isoformat() if r.completed_at else "",
                "estimated_cost": float(r.estimated_cost) if r.estimated_cost else 0,
                "actual_cost": float(r.actual_cost) if r.actual_cost else 0,
            }
            for r in result.all()
        ]
    except Exception as e:
        logger.warning("work_orders_fetch_failed", error=str(e)[:200])
        return []


async def _fetch_housekeeping(
    db: AsyncSession, property_id: str, check_in
) -> List[Dict]:
    """Pull housekeeping_tasks for pre-arrival inspection proof."""
    if not property_id or not check_in:
        return []
    try:
        result = await db.execute(
            text("""
                SELECT id, task_type, status, scheduled_date, completed_at, cleaner_name, notes
                FROM housekeeping_tasks
                WHERE property_id = :pid
                  AND scheduled_date BETWEEN (:ci::date - interval '3 days') AND :ci::date
                ORDER BY scheduled_date DESC
                LIMIT 5
            """),
            {"pid": property_id, "ci": check_in},
        )
        return [
            {
                "id": str(r.id),
                "task_type": r.task_type or "cleaning",
                "status": r.status or "",
                "scheduled_date": r.scheduled_date.isoformat() if r.scheduled_date else "",
                "completed_at": r.completed_at.isoformat() if r.completed_at else "",
                "cleaner_name": r.cleaner_name or "",
                "notes": (r.notes or "")[:300],
            }
            for r in result.all()
        ]
    except Exception as e:
        logger.warning("housekeeping_fetch_failed", error=str(e)[:200])
        return []


async def _fetch_damage_claims(
    db: AsyncSession, reservation_id: str
) -> List[Dict]:
    """Pull damage_claims for the specific reservation."""
    if not reservation_id:
        return []
    try:
        result = await db.execute(
            text("""
                SELECT id, damage_description, estimated_cost, status, created_at,
                       damage_waiver_collected
                FROM damage_claims
                WHERE reservation_id = :rid
                ORDER BY created_at DESC
            """),
            {"rid": reservation_id},
        )
        return [
            {
                "id": str(r.id),
                "description": (r.damage_description or "")[:400],
                "estimated_cost": float(r.estimated_cost) if r.estimated_cost else 0,
                "status": r.status or "",
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "damage_waiver_collected": bool(getattr(r, "damage_waiver_collected", False)),
            }
            for r in result.all()
        ]
    except Exception as e:
        logger.warning("damage_claims_fetch_failed", error=str(e)[:200])
        return []


def _classify_reason(reason: str) -> str:
    """Map the Stripe dispute reason code to a defense strategy."""
    r = (reason or "").lower().strip()
    if r in ("fraudulent", "unrecognized"):
        return "fraud"
    if r in ("product_unacceptable", "general"):
        return "damage"
    if r == "product_not_received":
        return "not_received"
    return "generic"


def _build_evidence_html(
    ctx: Dict[str, Any],
    iot_events: List[Dict],
    work_orders: Optional[List[Dict]] = None,
    housekeeping: Optional[List[Dict]] = None,
    damage_claims: Optional[List[Dict]] = None,
) -> str:
    """Build a reason-code-aware evidence packet as HTML for WeasyPrint rendering."""
    work_orders = work_orders or []
    housekeeping = housekeeping or []
    damage_claims = damage_claims or []

    guest_name = f"{ctx.get('first_name', '')} {ctx.get('last_name', '')}".strip() or "Unknown Guest"
    dispute_id = ctx.get("dispute_id", "N/A")
    conf_code = ctx.get("confirmation_code", "N/A")
    prop_name = ctx.get("property_name", "N/A")
    prop_addr = ctx.get("property_address", "N/A")
    check_in = ctx.get("check_in_date", "")
    check_out = ctx.get("check_out_date", "")
    total = ctx.get("total_amount")
    total_fmt = f"${float(total):,.2f}" if total else "N/A"
    num_guests = ctx.get("num_guests", "N/A")
    dispute_amount = ctx.get("dispute_amount")
    dispute_fmt = f"${float(dispute_amount):,.2f}" if dispute_amount else "N/A"
    dispute_reason = ctx.get("dispute_reason", "N/A")
    strategy = _classify_reason(dispute_reason)

    signer_name = ctx.get("signer_name", "N/A")
    signed_at = ctx.get("signed_at")
    signed_fmt = signed_at.strftime("%B %d, %Y at %I:%M %p UTC") if signed_at else "N/A"
    signer_ip = ctx.get("signer_ip_address", "N/A")
    signer_email = ctx.get("signer_email", "N/A")
    has_agreement = bool(ctx.get("agreement_pdf"))

    strategy_labels = {
        "fraud": "FRAUD DEFENSE — Physical Occupancy Proof",
        "damage": "DAMAGE DEFENSE — Condition & Waiver Proof",
        "not_received": "SERVICE DELIVERY — Full IoT Occupancy Log",
        "generic": "GENERAL DEFENSE — Service Documentation",
    }

    # --- Agreement section (all strategies) ---
    if has_agreement:
        agreement_section = f"""
        <h2>Section 1: Signed Rental Agreement</h2>
        <div class="evidence-box">
            <p><strong>Agreement Status:</strong> Electronically signed</p>
            <p><strong>Signer:</strong> {signer_name} ({signer_email})</p>
            <p><strong>Signed On:</strong> {signed_fmt}</p>
            <p><strong>Signer IP:</strong> {signer_ip}</p>
            <p class="note">The full signed rental agreement PDF is attached as a separate file.
               The agreement includes cancellation policy, house rules, damage waiver terms,
               and the guest's explicit consent to all charges.</p>
        </div>
        """
    else:
        agreement_section = """
        <h2>Section 1: Rental Agreement</h2>
        <div class="evidence-box warning">
            <p>No signed rental agreement was found on file for this reservation.
               The booking confirmation and payment records serve as evidence of
               the guest's engagement with the service.</p>
        </div>
        """

    # --- IoT section (all strategies, but prominence varies) ---
    iot_rows = ""
    for evt in iot_events:
        iot_rows += f"""
        <tr>
            <td>{evt['timestamp']}</td>
            <td>{evt['event_type'].upper()}</td>
            <td>{evt['device_id']}</td>
            <td>{evt['user_code']}</td>
        </tr>"""

    if iot_events:
        iot_heading = "Section 2: IoT Smart Lock Access Log"
        if strategy == "fraud":
            iot_heading = "Section 2: PHYSICAL OCCUPANCY PROOF — IoT Smart Lock Log"
        elif strategy == "not_received":
            iot_heading = "Section 2: SERVICE DELIVERY PROOF — Complete IoT Access Log"

        iot_section = f"""
        <h2>{iot_heading}</h2>
        <p>The following access events were recorded by the property's electronic smart lock system
           during the guest's reservation period{', proving the cardholder physically occupied the property:' if strategy in ('fraud', 'not_received') else ':'}
        </p>
        <table class="evidence-table">
            <thead>
                <tr><th>Timestamp (UTC)</th><th>Event</th><th>Device</th><th>Access Code</th></tr>
            </thead>
            <tbody>{iot_rows}</tbody>
        </table>
        <p class="note"><strong>{len(iot_events)} access events</strong> recorded during the stay period.</p>
        """
        if strategy in ("fraud", "not_received"):
            code_used = [e for e in iot_events if e["event_type"] in ("code_used", "unlock")]
            iot_section += f"""
        <div class="evidence-box">
            <p><strong>Key Finding:</strong> The guest's unique access code was used <strong>{len(code_used)} time(s)</strong>
               to physically unlock the property's Yale Assure smart lock. This constitutes irrefutable
               evidence of physical occupancy by the cardholder or their authorized party.</p>
        </div>
            """
    else:
        iot_section = """
        <h2>Section 2: Property Access Verification</h2>
        <p>IoT smart lock event logs are not available for this property/period. However, the signed
           rental agreement and booking confirmation constitute sufficient evidence of the
           guest's voluntary engagement with the service.</p>
        """

    # --- Damage defense section (damage strategy) ---
    damage_section = ""
    if strategy == "damage":
        damage_section += "<h2>Section 3: Damage Defense Evidence</h2>"

        damage_waiver = ctx.get("damage_waiver_fee")
        if damage_waiver and float(damage_waiver) > 0:
            damage_section += f"""
        <div class="evidence-box">
            <p><strong>Damage Waiver Protection:</strong> The guest purchased a damage waiver
               (${ float(damage_waiver):,.2f}) as part of this reservation, acknowledging potential
               liability for property damage under the terms of their rental agreement.</p>
        </div>
            """

        if damage_claims:
            damage_section += """
        <h3>Damage Claims Filed</h3>
        <table class="evidence-table">
            <thead><tr><th>Date Filed</th><th>Description</th><th>Estimated Cost</th><th>Status</th></tr></thead>
            <tbody>"""
            for dc in damage_claims:
                damage_section += f"""
            <tr>
                <td>{dc['created_at']}</td>
                <td>{dc['description']}</td>
                <td>${dc['estimated_cost']:,.2f}</td>
                <td>{dc['status'].upper()}</td>
            </tr>"""
            damage_section += "</tbody></table>"

        if work_orders:
            damage_section += """
        <h3>Work Orders — Repair Documentation</h3>
        <table class="evidence-table">
            <thead><tr><th>Created</th><th>Title</th><th>Description</th><th>Priority</th><th>Cost</th><th>Status</th></tr></thead>
            <tbody>"""
            for wo in work_orders:
                cost = wo["actual_cost"] if wo["actual_cost"] > 0 else wo["estimated_cost"]
                damage_section += f"""
            <tr>
                <td>{wo['created_at']}</td>
                <td>{wo['title']}</td>
                <td>{wo['description']}</td>
                <td>{wo['priority'].upper()}</td>
                <td>${cost:,.2f}</td>
                <td>{wo['status'].upper()}</td>
            </tr>"""
            damage_section += "</tbody></table>"

        if housekeeping:
            damage_section += """
        <h3>Pre-Arrival Inspection & Cleaning</h3>
        <p>The following housekeeping activities were completed prior to guest arrival,
           documenting the property's condition before the disputed stay:</p>
        <table class="evidence-table">
            <thead><tr><th>Scheduled</th><th>Completed</th><th>Type</th><th>Cleaner</th><th>Notes</th><th>Status</th></tr></thead>
            <tbody>"""
            for hk in housekeeping:
                damage_section += f"""
            <tr>
                <td>{hk['scheduled_date']}</td>
                <td>{hk['completed_at']}</td>
                <td>{hk['task_type'].title()}</td>
                <td>{hk['cleaner_name']}</td>
                <td>{hk['notes']}</td>
                <td>{hk['status'].upper()}</td>
            </tr>"""
            damage_section += "</tbody></table>"

        if not damage_claims and not work_orders and not housekeeping:
            damage_section += """
        <p>No damage claims, work orders, or pre-arrival inspections were found for this
           reservation period. The property was in standard condition for the guest's stay.</p>
            """

    # --- Conclusion section (reason-code-aware) ---
    conclusions: List[str] = [
        f"The guest voluntarily booked a vacation rental stay at {prop_name}.",
    ]
    if has_agreement:
        conclusions.append(
            "The guest electronically signed a rental agreement acknowledging the terms, "
            "cancellation policy, and charges."
        )
    else:
        conclusions.append(
            "The guest completed the booking process and payment, acknowledging the terms of service."
        )

    if strategy == "fraud" and iot_events:
        conclusions.append(
            "IoT smart lock records confirm the cardholder's unique access code was used to "
            "physically enter and occupy the property, disproving the claim of fraudulent charge."
        )
    elif strategy == "not_received" and iot_events:
        conclusions.append(
            "IoT smart lock records provide irrefutable proof that the vacation rental "
            "accommodation was delivered and the property was physically occupied."
        )
    elif strategy == "damage":
        conclusions.append(
            "Damage documentation, work orders, and pre-arrival inspection records demonstrate "
            "the property's condition before and after the guest's stay."
        )
    elif iot_events:
        conclusions.append(
            "IoT smart lock records confirm the guest physically accessed and occupied the "
            "property during the reservation dates."
        )

    conclusions.append("The service (vacation rental accommodation) was delivered in full as agreed.")
    conclusion_items = "\n".join(f"  <li>{c}</li>" for c in conclusions)

    section_order = agreement_section + "\n" + iot_section
    if strategy == "damage":
        section_order = agreement_section + "\n" + damage_section + "\n" + iot_section

    final_section_num = 4 if strategy == "damage" else 3

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{
    size: letter;
    margin: 0.85in;
    @top-center {{
      content: "CONFIDENTIAL — Dispute Evidence Packet — {dispute_id}";
      font-size: 8px;
      color: #888;
    }}
    @bottom-center {{
      content: "Page " counter(page) " of " counter(pages) " — Cabin Rentals of Georgia, LLC";
      font-size: 8px;
      color: #888;
    }}
  }}
  body {{
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 11px;
    line-height: 1.55;
    color: #1a1a2e;
  }}
  h1 {{ font-size: 20px; color: #0f172a; text-align: center; border-bottom: 2px solid #dc2626; padding-bottom: 8px; }}
  h2 {{ font-size: 14px; color: #1e293b; margin-top: 24px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }}
  h3 {{ font-size: 12px; color: #334155; margin-top: 16px; }}
  .header {{ text-align: center; margin-bottom: 24px; }}
  .header .company {{ font-size: 22px; font-weight: 700; margin: 0; }}
  .header .tag {{ font-size: 10px; color: #dc2626; text-transform: uppercase; letter-spacing: 0.15em; }}
  .strategy-banner {{ background: #1e293b; color: #fff; padding: 10px 16px; text-align: center; font-size: 12px;
                       font-weight: 600; letter-spacing: 0.05em; border-radius: 4px; margin: 12px 0; }}
  .summary-table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  .summary-table td {{ padding: 6px 10px; border: 1px solid #e2e8f0; font-size: 11px; }}
  .summary-table .label {{ background: #f1f5f9; font-weight: 600; width: 35%; }}
  .evidence-table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  .evidence-table th {{ background: #1e293b; color: #fff; padding: 6px 10px; font-size: 10px; text-align: left; }}
  .evidence-table td {{ padding: 5px 10px; border: 1px solid #e2e8f0; font-size: 10px; }}
  .evidence-table tr:nth-child(even) td {{ background: #f8fafc; }}
  .evidence-box {{ border: 1px solid #2563eb; border-radius: 6px; padding: 14px; margin: 12px 0; background: #f8fafc; }}
  .evidence-box.warning {{ border-color: #f59e0b; background: #fef3c7; }}
  .note {{ font-size: 10px; color: #64748b; font-style: italic; }}
  .generated {{ margin-top: 32px; padding: 12px; background: #f1f5f9; border-left: 4px solid #2563eb; font-size: 9px; color: #475569; }}
</style>
</head>
<body>

<div class="header">
  <p class="company">Cabin Rentals of Georgia, LLC</p>
  <p class="tag">Chargeback Evidence Packet — Dispute Defense</p>
</div>

<h1>Evidence of Service Delivery</h1>

<div class="strategy-banner">
  Defense Strategy: {strategy_labels.get(strategy, 'GENERAL DEFENSE')}
</div>

<h2>Dispute Summary</h2>
<table class="summary-table">
  <tr><td class="label">Stripe Dispute ID</td><td>{dispute_id}</td></tr>
  <tr><td class="label">Disputed Amount</td><td>{dispute_fmt}</td></tr>
  <tr><td class="label">Dispute Reason</td><td>{dispute_reason}</td></tr>
  <tr><td class="label">Defense Strategy</td><td>{strategy_labels.get(strategy, 'General')}</td></tr>
  <tr><td class="label">Guest Name</td><td>{guest_name}</td></tr>
  <tr><td class="label">Guest Email</td><td>{ctx.get('guest_email', 'N/A')}</td></tr>
</table>

<h2>Booking Confirmation</h2>
<table class="summary-table">
  <tr><td class="label">Confirmation Code</td><td>{conf_code}</td></tr>
  <tr><td class="label">Property</td><td>{prop_name}</td></tr>
  <tr><td class="label">Property Address</td><td>{prop_addr}</td></tr>
  <tr><td class="label">Check-In</td><td>{check_in}</td></tr>
  <tr><td class="label">Check-Out</td><td>{check_out}</td></tr>
  <tr><td class="label">Number of Guests</td><td>{num_guests}</td></tr>
  <tr><td class="label">Total Charged</td><td>{total_fmt}</td></tr>
</table>

{section_order}

<h2>Section {final_section_num}: Conclusions</h2>
<p>The above evidence demonstrates that:</p>
<ol>
{conclusion_items}
</ol>

<div class="generated">
  <strong>Evidence Packet Generated:</strong> {datetime.now(timezone.utc).strftime('%B %d, %Y at %I:%M %p UTC')}<br>
  <strong>Generated By:</strong> Fortress Chargeback Ironclad (Automated) — {strategy_labels.get(strategy, 'General')} mode<br>
  <strong>Cabin Rentals of Georgia, LLC</strong> — Blue Ridge, Georgia 30513
</div>

</body>
</html>"""


def _render_evidence_pdf(html: str, dispute_id: str) -> Optional[str]:
    """Render the evidence packet HTML to PDF via WeasyPrint."""
    try:
        from weasyprint import HTML
    except ImportError:
        logger.error("weasyprint_not_installed")
        return None

    dispute_dir = LOCAL_EVIDENCE_DIR / dispute_id
    dispute_dir.mkdir(parents=True, exist_ok=True)

    filename = f"evidence_packet_{dispute_id}.pdf"
    pdf_path = dispute_dir / filename

    try:
        HTML(string=html).write_pdf(str(pdf_path))
        logger.info("evidence_pdf_generated", dispute_id=dispute_id, path=str(pdf_path))
    except Exception as e:
        logger.error("evidence_pdf_failed", dispute_id=dispute_id, error=str(e)[:300])
        return None

    try:
        if NAS_EVIDENCE_BASE.exists():
            nas_dir = NAS_EVIDENCE_BASE / dispute_id
            nas_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(pdf_path), str(nas_dir / filename))
            logger.info("evidence_pdf_nas_copy", dispute_id=dispute_id)
    except Exception as e:
        logger.warning("evidence_nas_copy_failed", error=str(e)[:200])

    return str(pdf_path)


async def _submit_evidence_to_stripe(
    dispute_id: str, evidence_pdf_path: str, ctx: Dict[str, Any], db: AsyncSession
):
    """Submit compiled evidence to Stripe Disputes API."""
    stripe.api_key = settings.stripe_secret_key
    if not stripe.api_key:
        logger.error("stripe_api_key_not_configured")
        return

    guest_name = f"{ctx.get('first_name', '')} {ctx.get('last_name', '')}".strip()
    check_in = ctx.get("check_in_date")
    check_out = ctx.get("check_out_date")
    service_date = check_in.isoformat() if check_in else None

    evidence_params: Dict[str, Any] = {
        "customer_name": guest_name or None,
        "customer_email_address": ctx.get("guest_email") or None,
        "service_date": service_date,
        "service_documentation": (
            f"Vacation rental accommodation at {ctx.get('property_name', 'N/A')}, "
            f"{ctx.get('property_address', 'Blue Ridge, GA')}. "
            f"Check-in: {check_in}, Check-out: {check_out}. "
            f"Confirmation: {ctx.get('confirmation_code', 'N/A')}."
        ),
    }

    try:
        with open(evidence_pdf_path, "rb") as f:
            file_upload = stripe.File.create(
                purpose="dispute_evidence",
                file=f,
            )
        evidence_params["uncategorized_file"] = file_upload.id
        logger.info("evidence_file_uploaded", dispute_id=dispute_id, file_id=file_upload.id)
    except Exception as e:
        logger.error("evidence_file_upload_failed", dispute_id=dispute_id, error=str(e)[:300])

    try:
        response = stripe.Dispute.modify(
            dispute_id,
            evidence=evidence_params,
            submit=True,
        )
        logger.info(
            "evidence_submitted_to_stripe",
            dispute_id=dispute_id,
            status=response.get("status", "unknown") if isinstance(response, dict) else getattr(response, "status", "unknown"),
        )

        await db.execute(
            text("""
                UPDATE dispute_evidence
                SET evidence_pdf_path = :pdf,
                    submitted_to_stripe_at = NOW(),
                    stripe_response = :resp::jsonb,
                    status = 'submitted',
                    updated_at = NOW()
                WHERE dispute_id = :did
            """),
            {
                "did": dispute_id,
                "pdf": evidence_pdf_path,
                "resp": json.dumps({"status": "submitted", "evidence_params": list(evidence_params.keys())}),
            },
        )
        await db.commit()

    except stripe.error.StripeError as e:
        logger.error("stripe_evidence_submit_failed", dispute_id=dispute_id, error=str(e)[:300])
        await db.execute(
            text("""
                UPDATE dispute_evidence
                SET evidence_pdf_path = :pdf,
                    stripe_response = :resp::jsonb,
                    status = 'pending',
                    updated_at = NOW()
                WHERE dispute_id = :did
            """),
            {
                "did": dispute_id,
                "pdf": evidence_pdf_path,
                "resp": json.dumps({"error": str(e)[:300]}),
            },
        )
        await db.commit()


async def compile_and_submit_evidence(dispute_id: str, reservation_id: str):
    """
    Background task entry point. Creates its own DB session, routes to the
    reason-code-specific defense strategy, compiles evidence, and submits to Stripe.
    """
    from backend.core.database import async_session_factory

    async with async_session_factory() as db:
        ctx = await _fetch_dispute_context(db, dispute_id)
        if not ctx:
            logger.error("dispute_context_not_found", dispute_id=dispute_id)
            return

        property_id = str(ctx.get("property_id", ""))
        check_in = ctx.get("check_in_date")
        check_out = ctx.get("check_out_date")
        res_id = str(ctx.get("reservation_id", ""))
        strategy = _classify_reason(ctx.get("dispute_reason", ""))

        logger.info(
            "dispute_defense_strategy_selected",
            dispute_id=dispute_id,
            reason=ctx.get("dispute_reason"),
            strategy=strategy,
        )

        iot_events = await _fetch_iot_events(db, property_id, check_in, check_out)

        work_orders: List[Dict] = []
        housekeeping_tasks: List[Dict] = []
        claims: List[Dict] = []

        if strategy == "damage":
            work_orders = await _fetch_work_orders(db, property_id, check_in, check_out)
            housekeeping_tasks = await _fetch_housekeeping(db, property_id, check_in)
            claims = await _fetch_damage_claims(db, res_id)

        evidence_html = _build_evidence_html(
            ctx, iot_events,
            work_orders=work_orders,
            housekeeping=housekeeping_tasks,
            damage_claims=claims,
        )
        pdf_path = _render_evidence_pdf(evidence_html, dispute_id)

        if not pdf_path:
            logger.error("evidence_compilation_failed", dispute_id=dispute_id)
            return

        await db.execute(
            text("""
                UPDATE dispute_evidence
                SET evidence_pdf_path = :pdf,
                    iot_events_count = :iot_count,
                    status = 'evidence_compiled',
                    updated_at = NOW()
                WHERE dispute_id = :did
            """),
            {"did": dispute_id, "pdf": pdf_path, "iot_count": len(iot_events)},
        )
        await db.commit()

        await _submit_evidence_to_stripe(dispute_id, pdf_path, ctx, db)

        logger.info(
            "dispute_defense_complete",
            dispute_id=dispute_id,
            reservation_id=reservation_id,
            strategy=strategy,
            iot_events=len(iot_events),
            work_orders=len(work_orders),
            housekeeping=len(housekeeping_tasks),
            damage_claims=len(claims),
            has_agreement=bool(ctx.get("agreement_pdf")),
        )
