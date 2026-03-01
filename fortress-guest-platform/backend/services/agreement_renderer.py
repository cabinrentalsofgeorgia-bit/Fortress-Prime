"""
Agreement template renderer — variable substitution engine.
Fills {{variable}} placeholders from reservation + guest + property data.
"""
import re
from datetime import date, datetime
from typing import Dict, Any, Optional

import structlog

logger = structlog.get_logger()

VARIABLE_PATTERN = re.compile(r"\{\{(\w+)\}\}")


def build_variable_context(
    reservation: Any = None,
    guest: Any = None,
    prop: Any = None,
) -> Dict[str, str]:
    """Build a dict of all template variables from domain objects."""
    ctx: Dict[str, str] = {
        "today_date": date.today().strftime("%B %d, %Y"),
        "current_year": str(date.today().year),
    }

    if guest:
        ctx["guest_name"] = f"{guest.first_name or ''} {guest.last_name or ''}".strip()
        ctx["guest_first_name"] = guest.first_name or ""
        ctx["guest_last_name"] = guest.last_name or ""
        ctx["guest_email"] = guest.email or ""
        ctx["guest_phone"] = guest.phone_number or ""
        addr_parts = [
            getattr(guest, "address_line1", "") or "",
            getattr(guest, "city", "") or "",
            getattr(guest, "state", "") or "",
            getattr(guest, "postal_code", "") or "",
        ]
        ctx["guest_address"] = ", ".join(p for p in addr_parts if p)

    if prop:
        ctx["property_name"] = prop.name or ""
        ctx["property_address"] = prop.address or ""
        ctx["wifi_ssid"] = prop.wifi_ssid or ""
        ctx["wifi_password"] = prop.wifi_password or ""
        ctx["max_guests"] = str(prop.max_guests or "")
        ctx["bedrooms"] = str(prop.bedrooms or "")
        ctx["bathrooms"] = str(prop.bathrooms or "")
        ctx["owner_name"] = "Cabin Rentals of Georgia"

    if reservation:
        ctx["confirmation_code"] = reservation.confirmation_code or ""
        if reservation.check_in_date:
            ctx["check_in_date"] = reservation.check_in_date.strftime("%B %d, %Y")
        if reservation.check_out_date:
            ctx["check_out_date"] = reservation.check_out_date.strftime("%B %d, %Y")
        nights = 0
        if reservation.check_in_date and reservation.check_out_date:
            nights = (reservation.check_out_date - reservation.check_in_date).days
        ctx["num_nights"] = str(reservation.nights_count or nights)
        ctx["num_guests"] = str(reservation.num_guests or "")

        def _fmt(val):
            return f"${float(val):,.2f}" if val else "$0.00"

        ctx["total_amount"] = _fmt(reservation.total_amount)
        ctx["paid_amount"] = _fmt(reservation.paid_amount)
        ctx["balance_due"] = _fmt(reservation.balance_due)
        ctx["nightly_rate"] = _fmt(reservation.nightly_rate)
        ctx["access_code"] = reservation.access_code or "Provided at check-in"

    return ctx


def render_template(template_content: str, context: Dict[str, str]) -> str:
    """Replace all {{variable}} placeholders with context values."""
    def replacer(match):
        key = match.group(1)
        return context.get(key, f"[{key}]")

    rendered = VARIABLE_PATTERN.sub(replacer, template_content)
    return rendered


def extract_required_variables(template_content: str) -> list[str]:
    """Return all unique variable names found in a template."""
    return sorted(set(VARIABLE_PATTERN.findall(template_content)))


def extract_sections(rendered_content: str) -> list[Dict[str, Any]]:
    """
    Split rendered markdown into sections for the initials workflow.
    Sections are delimited by markdown ## headings.
    """
    lines = rendered_content.split("\n")
    sections: list[Dict[str, Any]] = []
    current: Dict[str, Any] = {"title": "Introduction", "content": [], "index": 0}

    for line in lines:
        if line.startswith("## "):
            if current["content"]:
                current["content"] = "\n".join(current["content"])
                sections.append(current)
            current = {
                "title": line.lstrip("# ").strip(),
                "content": [],
                "index": len(sections),
            }
        else:
            current["content"].append(line)

    if current["content"]:
        current["content"] = "\n".join(current["content"])
        sections.append(current)

    return sections
