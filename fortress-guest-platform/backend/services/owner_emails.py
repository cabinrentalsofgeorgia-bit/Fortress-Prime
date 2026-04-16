"""
Owner Email Notifications
==========================
  1. booking_alert         — sent to the property owner when a new reservation is confirmed
  2. charge_notification   — sent when a charge is posted (I.1b, 2026-04-16)

The monthly statement email was removed in Phase 1.5 of the Area 2 gap remediation
(2026-04-14). It used a hardcoded 65% owner split which was incorrect — rates are
per-owner. The replacement is send_owner_statement() in
backend/services/owner_statement_service.py, built in Phase 4.

The old send_monthly_statement and send_all_monthly_statements functions are gone.
The trigger endpoint POST /api/admin/payouts/statements/send-all returns HTTP 501
until Phase 4 is complete.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.services.email_service import send_email, is_email_configured

logger = structlog.get_logger(service="owner_emails")

PORTAL_BASE_URL = settings.storefront_base_url.rstrip("/")


async def send_booking_alert(
    db: AsyncSession,
    *,
    reservation_id: str,
    property_id: str,
    confirmation_code: str,
    guest_name: str,
    check_in_date: date,
    check_out_date: date,
    total_amount: Decimal,
    nights: int,
) -> bool:
    """
    Send a booking alert email to the owner of the property.

    Called from the reservation confirmation webhook / finalization path.
    Returns True if email was sent, False if owner has no email or SMTP not configured.
    """
    if not is_email_configured():
        logger.warning("owner_booking_alert_skipped", reason="smtp_not_configured")
        return False

    # Look up owner email from owner_payout_accounts
    result = await db.execute(text("""
        SELECT owner_email, owner_name
        FROM owner_payout_accounts
        WHERE property_id = :pid
        LIMIT 1
    """), {"pid": property_id})
    row = result.fetchone()
    if not row or not row.owner_email:
        logger.info("owner_booking_alert_skipped", reason="no_owner_email", property_id=property_id)
        return False

    # Look up property name
    prop_result = await db.execute(text(
        "SELECT name FROM properties WHERE id = :pid LIMIT 1"
    ), {"pid": property_id})
    prop_row = prop_result.fetchone()
    property_name = prop_row.name if prop_row else "Your Property"

    owner_email = row.owner_email
    nights_label = f"{nights} night{'s' if nights != 1 else ''}"
    owner_share = total_amount * Decimal("0.65")  # 65/35 split

    subject = f"New Booking — {property_name} ({confirmation_code})"
    html_body = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;">
      <h2 style="color:#1e293b;">New Booking Confirmed</h2>
      <p>Great news — <strong>{property_name}</strong> has a new reservation.</p>
      <table style="width:100%;border-collapse:collapse;margin:16px 0;">
        <tr style="background:#f8fafc;">
          <td style="padding:10px 14px;font-weight:600;">Confirmation</td>
          <td style="padding:10px 14px;">{confirmation_code}</td>
        </tr>
        <tr>
          <td style="padding:10px 14px;font-weight:600;">Guest</td>
          <td style="padding:10px 14px;">{guest_name}</td>
        </tr>
        <tr style="background:#f8fafc;">
          <td style="padding:10px 14px;font-weight:600;">Check-in</td>
          <td style="padding:10px 14px;">{check_in_date.strftime('%B %-d, %Y')}</td>
        </tr>
        <tr>
          <td style="padding:10px 14px;font-weight:600;">Check-out</td>
          <td style="padding:10px 14px;">{check_out_date.strftime('%B %-d, %Y')} ({nights_label})</td>
        </tr>
        <tr style="background:#f8fafc;">
          <td style="padding:10px 14px;font-weight:600;">Total Revenue</td>
          <td style="padding:10px 14px;">${total_amount:,.2f}</td>
        </tr>
        <tr>
          <td style="padding:10px 14px;font-weight:600;">Your Share (65%)</td>
          <td style="padding:10px 14px;color:#16a34a;font-weight:600;">${owner_share:,.2f}</td>
        </tr>
      </table>
      <p style="margin-top:24px;">
        <a href="{PORTAL_BASE_URL}/owner"
           style="background:#1e293b;color:#fff;padding:12px 24px;border-radius:6px;
                  text-decoration:none;font-weight:600;">
          View Owner Portal
        </a>
      </p>
    </div>
    """
    text_body = (
        f"New Booking — {property_name}\n"
        f"Confirmation: {confirmation_code}\n"
        f"Guest: {guest_name}\n"
        f"Check-in: {check_in_date}\n"
        f"Check-out: {check_out_date} ({nights_label})\n"
        f"Total: ${total_amount:,.2f}  |  Your share: ${owner_share:,.2f}\n"
    )

    sent = send_email(owner_email, subject, html_body, text_body)
    logger.info(
        "owner_booking_alert_sent" if sent else "owner_booking_alert_failed",
        owner_email=owner_email,
        confirmation_code=confirmation_code,
        property_id=property_id,
    )
    return sent


async def send_owner_charge_notification(
    db: AsyncSession,
    *,
    charge_id: int,
) -> bool:
    """
    Send a plain-text notification to the owner when a charge is posted.

    Returns True if email was dispatched.
    Returns False (never raises) if:
      - OPA has no email
      - SMTP not configured
      - send_email fails

    I.1b, 2026-04-16. No portal link (portal has no statement view yet).
    """
    if not is_email_configured():
        logger.warning("owner_charge_notification_skipped", reason="smtp_not_configured", charge_id=charge_id)
        return False

    # Load charge + OPA + property + optional vendor via raw SQL (async-safe)
    charge_result = await db.execute(text("""
        SELECT
            oc.id,
            oc.posting_date,
            oc.transaction_type,
            oc.description,
            oc.amount,
            oc.reference_id,
            oc.vendor_id,
            oc.vendor_amount,
            oc.markup_percentage,
            opa.owner_name,
            opa.owner_email,
            opa.property_id
        FROM owner_charges oc
        JOIN owner_payout_accounts opa ON opa.id = oc.owner_payout_account_id
        WHERE oc.id = :charge_id
    """), {"charge_id": charge_id})
    row = charge_result.fetchone()

    if row is None:
        logger.warning("owner_charge_notification_skipped", reason="charge_not_found", charge_id=charge_id)
        return False

    if not row.owner_email:
        logger.info("owner_charge_notification_skipped", reason="no_owner_email", charge_id=charge_id)
        return False

    # Resolve property name
    prop_result = await db.execute(text(
        "SELECT name FROM properties WHERE id::text = :pid LIMIT 1"
    ), {"pid": str(row.property_id)})
    prop_row = prop_result.fetchone()
    property_name = prop_row.name if prop_row else "Your Property"

    # Resolve vendor name (if linked)
    vendor_name: str = ""
    if row.vendor_id:
        v_result = await db.execute(text(
            "SELECT name FROM vendors WHERE id = :vid LIMIT 1"
        ), {"vid": row.vendor_id})
        v_row = v_result.fetchone()
        if v_row:
            vendor_name = v_row.name

    # Format transaction type for display
    try:
        from backend.models.owner_charge import OwnerChargeType
        tx_display = OwnerChargeType(row.transaction_type).display_name
    except ValueError:
        tx_display = str(row.transaction_type).replace("_", " ").title()

    vendor_line = f"Vendor: {vendor_name}\n" if vendor_name else ""
    ref_line = f"Reference: {row.reference_id}\n" if row.reference_id else ""

    subject = f"Owner Charge Posted — {property_name}"

    text_body = (
        f"A new charge has been posted to your owner account.\n\n"
        f"Property:          {property_name}\n"
        f"Posted Date:       {row.posting_date.strftime('%B %d, %Y')}\n"
        f"Transaction Type:  {tx_display}\n"
        f"Description:       {row.description}\n"
        f"{vendor_line}"
        f"{ref_line}"
        f"Amount:            ${float(row.amount):,.2f}\n\n"
        f"This charge will appear on your next owner statement.\n"
        f"If you have questions, please contact us.\n\n"
        f"—\nCabin Rentals of Georgia\n"
    )

    # Plain-text HTML (preserves formatting in most email clients)
    html_body = (
        f"<pre style=\"font-family:monospace,monospace;font-size:14px;"
        f"line-height:1.6;max-width:520px;\">{text_body}</pre>"
    )

    sent = send_email(row.owner_email, subject, html_body, text_body)

    if sent:
        logger.info(
            "owner_charge_notification_sent",
            charge_id=charge_id,
            to=row.owner_email,
            subject=subject,
            property=property_name,
        )
    else:
        logger.warning(
            "owner_charge_notification_failed",
            charge_id=charge_id,
            to=row.owner_email,
        )

    return sent


async def send_monthly_statement(  # type: ignore[return]  # noqa: F811
    db: AsyncSession,
    *,
    property_id: str,
    year: int,
    month: int,
) -> bool:
    """
    DELETED in Phase 1.5 (2026-04-14). Used a hardcoded 65% split.

    Replaced by send_owner_statement() in
    backend/services/owner_statement_service.py (Phase 4).
    This stub is kept only so that existing import sites do not crash before
    they are updated. It always raises NotImplementedError.
    """
    raise NotImplementedError(
        "send_monthly_statement was removed because it used a hardcoded 65% "
        "commission split. Use send_owner_statement() from "
        "backend/services/owner_statement_service.py instead."
    )
    # (old body removed — see NotImplementedError above)
