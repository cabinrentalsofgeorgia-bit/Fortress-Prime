"""
Statement PDF Renderer
=======================
Produces owner statement PDFs matching Streamline's format.

Entry point:
    render_owner_statement_pdf(db, period_id) -> bytes

Uses reportlab Platypus (SimpleDocTemplate + Table) for precise tabular layout,
keeping the same io.BytesIO-in-memory approach as document_engine.py.
"""
from __future__ import annotations

import io
import uuid as _uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.owner_balance_period import OwnerBalancePeriod, StatementPeriodStatus
from backend.models.owner_charge import OwnerCharge
from backend.models.owner_payout import OwnerPayoutAccount
from backend.models.property import Property
from backend.services.statement_computation import StatementResult, compute_owner_statement

logger = structlog.get_logger(service="statement_pdf")

# Company headquarters address — appears at the top of every owner statement
# below the owner address. Matches Streamline's format exactly including the
# "Ga" capitalization (not "GA") for visual parity at cutover.
COMPANY_HQ_ADDRESS = "86 Huntington Way Blue Ridge Ga 30513"

# Colours matching CROG branding
_HEADER_BG   = colors.HexColor("#1e293b")  # dark slate
_SECTION_BG  = colors.HexColor("#f1f5f9")  # light grey
_APPROVED_BG = colors.HexColor("#16a34a")  # green
_UNAPPROVED_BG = colors.HexColor("#d97706")  # amber
_VOIDED_BG   = colors.HexColor("#dc2626")  # red
_DRAFT_BG    = colors.HexColor("#64748b")  # grey
_WHITE       = colors.white
_BLACK       = colors.black
_LIGHT_GREY  = colors.HexColor("#e2e8f0")


# ── Currency formatting ───────────────────────────────────────────────────────

def _fmt(amount: Decimal, parens: bool = True) -> str:
    """Format a Decimal as currency. Negative shown as ($X.XX) if parens=True."""
    if amount is None:
        amount = Decimal("0.00")
    amount = Decimal(str(amount))
    abs_val = abs(amount)
    formatted = f"${abs_val:,.2f}"
    if amount < 0 and parens:
        return f"({formatted})"
    elif amount < 0:
        return f"-{formatted}"
    return formatted


# ── Status badge ──────────────────────────────────────────────────────────────

def _status_badge(status: str) -> tuple[str, object]:
    """Return (badge_text, badge_bg_color) for the given period status."""
    mapping = {
        "draft":            ("DRAFT",       _DRAFT_BG),
        "pending_approval": ("UNAPPROVED",  _UNAPPROVED_BG),
        "approved":         ("APPROVED",    _APPROVED_BG),
        "paid":             ("APPROVED",    _APPROVED_BG),
        "emailed":          ("APPROVED",    _APPROVED_BG),
        "voided":           ("VOIDED",      _VOIDED_BG),
    }
    return mapping.get(status, ("UNKNOWN", _DRAFT_BG))


# ── YTD totals ────────────────────────────────────────────────────────────────

async def _get_ytd_totals(
    db: AsyncSession,
    owner_payout_account_id: int,
    year: int,
    period_end: date,
) -> dict:
    """Sum all non-voided period totals from Jan 1 of year through period_end."""
    result = await db.execute(
        select(OwnerBalancePeriod)
        .where(
            OwnerBalancePeriod.owner_payout_account_id == owner_payout_account_id,
            OwnerBalancePeriod.period_start >= date(year, 1, 1),
            OwnerBalancePeriod.period_end <= period_end,
            OwnerBalancePeriod.status.notin_(["voided"]),
        )
    )
    periods = result.scalars().all()

    ytd = {
        "revenue":       Decimal("0.00"),
        "commission":    Decimal("0.00"),
        "charges":       Decimal("0.00"),
        "payments":      Decimal("0.00"),
        "owner_income":  Decimal("0.00"),
    }
    for p in periods:
        ytd["revenue"]      += Decimal(str(p.total_revenue      or 0))
        ytd["commission"]   += Decimal(str(p.total_commission   or 0))
        ytd["charges"]      += Decimal(str(p.total_charges      or 0))
        ytd["payments"]     += Decimal(str(p.total_payments     or 0))
        ytd["owner_income"] += Decimal(str(p.total_owner_income or 0))
    return ytd


# ── Style helpers ─────────────────────────────────────────────────────────────

def _styles():
    base = getSampleStyleSheet()
    return {
        "normal": ParagraphStyle("normal", fontName="Helvetica", fontSize=9, leading=12),
        "bold":   ParagraphStyle("bold",   fontName="Helvetica-Bold", fontSize=9, leading=12),
        "title":  ParagraphStyle("title",  fontName="Helvetica-Bold", fontSize=14, leading=18,
                                 textColor=_WHITE),
        "co":     ParagraphStyle("co",     fontName="Helvetica", fontSize=8, leading=11,
                                 textColor=_WHITE),
        "section":ParagraphStyle("section",fontName="Helvetica-Bold", fontSize=9, leading=12,
                                 textColor=_BLACK),
        "small":  ParagraphStyle("small",  fontName="Helvetica", fontSize=8, leading=10),
        "badge":  ParagraphStyle("badge",  fontName="Helvetica-Bold", fontSize=11, leading=14,
                                 textColor=_WHITE),
    }


def _tbl_style(header_cols: int = None, data_rows: int = 0) -> TableStyle:
    """Standard table style with header row, grid, alternating rows."""
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), _SECTION_BG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_WHITE, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    return TableStyle(cmds)


def _total_row_style() -> TableStyle:
    return TableStyle([
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), _SECTION_BG),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, _BLACK),
    ])


# ── Name formatting ──────────────────────────────────────────────────────────

def _streamline_name(owner_name: str, owner_middle_name: str | None) -> str:
    """Format owner name in Streamline's last-middle-first format.

    Streamline renders "Knight Mitchell Gary" (last middle first, no comma).
    Policy: Streamline is source of truth for name format (G.6, 2026-04-15).

    Inputs:
      owner_name        — stored as "First Last" (e.g., "Gary Knight")
      owner_middle_name — stored separately, nullable (e.g., "Mitchell")

    Parsing: splits owner_name on whitespace, treats first token as first name
    and last token as last name. Names with 3+ words (compound first names,
    suffixes) are handled by index — middle component is silently ignored from
    the stored field; middle_name column carries the authoritative middle.
    """
    parts = owner_name.strip().split()
    if len(parts) < 2:
        # Fallback: single-word name — return as-is
        return owner_name
    first = parts[0]
    last = parts[-1]
    if owner_middle_name and owner_middle_name.strip():
        return f"{last} {owner_middle_name.strip()} {first}"
    return f"{last} {first}"


# ── Main renderer ─────────────────────────────────────────────────────────────

def _build_pdf_bytes(
    *,
    # Period dates and status
    period_start: date,
    period_end: date,
    status: str,
    # Balance figures (Decimal)
    opening_balance: Decimal,
    closing_balance: Decimal,
    total_revenue: Decimal,
    total_commission: Decimal,
    total_charges: Decimal,
    total_payments: Decimal,
    total_owner_income: Decimal,
    # Owner display data
    owner_name: str,
    owner_address: str,        # "" → shows [address missing] placeholder
    # Property display data
    prop_display_name: str,    # already has group prefix applied
    prop_address: str,
    # Statement content (reservations + charges)
    stmt: StatementResult,
    # YTD dict with keys: revenue, commission, charges, payments, owner_income
    ytd: dict,
) -> bytes:
    """
    Pure function — no database access.
    Builds the PDF story from pre-resolved data and returns bytes.

    Called by render_owner_statement_pdf (DB path) and by the regeneration
    script (in-memory path). Both callers are responsible for computing the
    input values; this function only handles the reportlab rendering.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.4 * inch,
        bottomMargin=0.5 * inch,
    )
    W = letter[0] - 1.2 * inch  # usable width

    S = _styles()
    story = []

    # ── 1. Header ─────────────────────────────────────────────────────────────
    badge_text, badge_color = _status_badge(status)
    _owner_name = owner_name or "(unknown owner)"

    if owner_address:
        owner_addr_html = owner_address  # single line — no <br/> replacement needed
    else:
        owner_addr_html = "<font color='#ef4444'>[address missing]</font>"
    header_left = (
        f"<b>OWNER STATEMENT</b><br/>"
        f"{_owner_name}<br/>"
        f"{owner_addr_html}<br/>"
        f"{COMPANY_HQ_ADDRESS}"
    )

    header_data = [[
        Paragraph(header_left, S["title"]),
        Paragraph(badge_text, S["badge"]),
    ]]
    header_tbl = Table(header_data, colWidths=[W * 0.75, W * 0.25])
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, -1), _WHITE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (1, 0), (1, 0), badge_color),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("ROUNDEDCORNERS", [5, 5, 5, 5]),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 0.15 * inch))

    # ── 2. Property + Period ──────────────────────────────────────────────────
    prop_data = [[
        Paragraph(f"<b>{prop_display_name}</b>", S["bold"]),
        Paragraph(
            f"{prop_address}<br/>Year: {period_start.year}  "
            f"Period: {period_start.month}",
            S["small"]
        ),
    ]]
    prop_tbl = Table(prop_data, colWidths=[W * 0.55, W * 0.45])
    prop_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _SECTION_BG),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(prop_tbl)
    story.append(Spacer(1, 0.1 * inch))

    # ── 3. Account Summary ────────────────────────────────────────────────────
    opening    = Decimal(str(opening_balance))
    closing    = Decimal(str(closing_balance))
    revenue    = Decimal(str(total_revenue))
    commission = Decimal(str(total_commission))
    charges    = Decimal(str(total_charges))
    payments   = Decimal(str(total_payments))
    owner_inc  = Decimal(str(total_owner_income))
    # Total balance due = opening + revenue - commission + owner_income - charges
    total_due = opening + revenue - commission + owner_inc - charges

    story.append(Paragraph("Account Summary", S["section"]))
    story.append(Spacer(1, 0.05 * inch))

    def _row(label, period_val, ytd_val=None, bold=False):
        fn = "Helvetica-Bold" if bold else "Helvetica"
        return [
            Paragraph(f"<font name='{fn}'>{label}</font>", S["normal"]),
            Paragraph(f"<font name='{fn}'>{_fmt(period_val)}</font>", S["normal"]),
            Paragraph(f"<font name='{fn}'>{_fmt(ytd_val) if ytd_val is not None else ''}</font>",
                      S["normal"]),
        ]

    summary_data = [
        [Paragraph(f"Activity: From {period_start.strftime('%m/%d/%Y')} to "
                   f"{period_end.strftime('%m/%d/%Y')}", S["bold"]),
         Paragraph("<b>Period</b>", S["bold"]),
         Paragraph("<b>YTD</b>", S["bold"])],
        _row(f"Balance as of {period_start.strftime('%m/%d/%Y')}", opening),
        _row("Payment Received",           payments,   ytd["payments"]),
        _row("Gross Reservation Revenue",  revenue,    ytd["revenue"]),
        _row("Less Management Commission", -commission, -ytd["commission"]),
        _row("Additional Owner Income",    owner_inc,  ytd["owner_income"]),
        _row("Owner Charges/Expenses",     -charges,   -ytd["charges"]),
        _row("Total Balance Due",          total_due),
        _row("Payments to Owner",          -payments,  -ytd["payments"]),
        _row(
            f"Balance as of {period_end.strftime('%m/%d/%Y')} "
            "(includes minimum required balance)",
            closing, bold=True,
        ),
    ]
    summary_tbl = Table(summary_data, colWidths=[W * 0.55, W * 0.22, W * 0.23])
    summary_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _SECTION_BG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, _LIGHT_GREY),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        # Bold closing balance row
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, _BLACK),
    ]))
    story.append(summary_tbl)
    story.append(Spacer(1, 0.08 * inch))

    # "Your payment amount of $X has been processed." — always rendered (matches Streamline)
    story.append(Paragraph(
        f"Your payment amount of {_fmt(payments)} has been processed.",
        S["small"],
    ))
    story.append(Spacer(1, 0.10 * inch))

    # ── 4. Reservations table ─────────────────────────────────────────────────
    story.append(Paragraph("Reservations", S["section"]))
    story.append(Spacer(1, 0.04 * inch))

    has_crossover = any(li.crosses_period_boundary for li in stmt.line_items)
    # H.1: "Type" column added between Res # and Guest to match Streamline layout.
    # Values come from StatementLineItem.reservation_type (STA, POS, …).
    res_header = ["Res #", "Type", "Guest", "Start", "End", "Nights",
                  "Gross Rent", "Mgmt Comm", "Net Amount"]
    res_rows = [res_header]

    for li in stmt.line_items:
        mark = "*" if li.crosses_period_boundary else ""
        guest = li.description.split("—")[-1].strip() if "—" in li.description else li.description
        res_rows.append([
            li.confirmation_code + mark,
            getattr(li, "reservation_type", ""),   # H.1: STA / POS / ""
            guest[:22],
            li.check_in.strftime("%m/%d/%y"),
            li.check_out.strftime("%m/%d/%y"),
            str(li.nights),
            _fmt(li.gross_amount),
            _fmt(li.commission_amount),
            _fmt(li.net_to_owner),
        ])

    # Total row
    res_rows.append([
        "Total:", "", "", "", "",
        str(sum(li.nights for li in stmt.line_items)),
        _fmt(stmt.total_gross),
        _fmt(stmt.total_commission),
        _fmt(stmt.total_net_to_owner),
    ])

    # Column widths adjusted to accommodate "Type" column (sum = 1.0).
    res_cw = [W * w for w in [0.12, 0.06, 0.17, 0.10, 0.10, 0.07, 0.13, 0.13, 0.12]]
    res_tbl = Table(res_rows, colWidths=res_cw)
    res_tbl.setStyle(_tbl_style())
    res_tbl.setStyle(_total_row_style())
    story.append(res_tbl)

    # Footnote always rendered (matches Streamline format).
    # Explains the asterisk on cross-period reservation line items.
    story.append(Spacer(1, 0.04 * inch))
    story.append(Paragraph(
        "* - This reservation carries over into the next statement or "
        "carried over from a previous statement.", S["small"]))

    story.append(Spacer(1, 0.12 * inch))

    # ── 5. Owner Payments / Additional Owner Income ───────────────────────────
    story.append(Paragraph("Owner Payments / Additional Owner Income", S["section"]))
    story.append(Spacer(1, 0.04 * inch))

    oi_rows = [["Date", "Description", "Amount"]]
    # Currently total_owner_income is always 0 (not yet implemented)
    oi_rows.append(["TOTAL:", "", _fmt(owner_inc)])

    oi_tbl = Table(oi_rows, colWidths=[W * 0.18, W * 0.62, W * 0.20])
    oi_tbl.setStyle(_tbl_style())
    oi_tbl.setStyle(_total_row_style())
    story.append(oi_tbl)
    story.append(Spacer(1, 0.12 * inch))

    # ── 6. Owner Charges/Expenses ─────────────────────────────────────────────
    story.append(Paragraph("Owner Charges/Expenses", S["section"]))
    story.append(Spacer(1, 0.04 * inch))

    ch_header = ["Posted Date", "Type", "Description", "W.O./REF#", "Expense"]
    ch_rows = [ch_header]
    for ch in stmt.owner_charges:
        ch_rows.append([
            ch.posting_date.strftime("%m/%d/%Y"),
            ch.transaction_type_display[:20],
            ch.description[:35],
            ch.reference_id or "",
            _fmt(ch.amount),
        ])
    ch_rows.append(["TOTAL:", "", "", "", _fmt(-charges)])

    ch_cw = [W * w for w in [0.15, 0.18, 0.35, 0.13, 0.19]]
    ch_tbl = Table(ch_rows, colWidths=ch_cw)
    ch_tbl.setStyle(_tbl_style())
    ch_tbl.setStyle(_total_row_style())
    story.append(ch_tbl)
    story.append(Spacer(1, 0.12 * inch))

    # ── 7. Payments To Owner ──────────────────────────────────────────────────
    story.append(Paragraph("Payments To Owner", S["section"]))
    story.append(Spacer(1, 0.04 * inch))

    pt_rows = [["Date", "Description", "ACH #", "CK #", "Amount"]]
    # Payments are not yet tracked as line items (Phase D mark_statement_paid
    # stores a reference in notes but not in a structured table).
    # Display the total from total_payments if non-zero.
    pt_rows.append(["TOTAL:", "", "", "", _fmt(-payments)])
    pt_rows.append(["Scheduled Payments:", "", "", "", _fmt(Decimal("0.00"))])

    pt_cw = [W * w for w in [0.15, 0.38, 0.16, 0.12, 0.19]]
    pt_tbl = Table(pt_rows, colWidths=pt_cw)
    pt_tbl.setStyle(_tbl_style())
    pt_tbl.setStyle(_total_row_style())
    story.append(pt_tbl)
    story.append(Spacer(1, 0.12 * inch))

    # ── 8. Owner Reserve ──────────────────────────────────────────────────────
    story.append(Paragraph("Owner Reserve", S["section"]))
    story.append(Spacer(1, 0.04 * inch))

    or_rows = [
        ["Date", "Type", "Description", "Amount"],
        [f"Balance as of {period_start.strftime('%m/%d/%Y')}:", "", "", _fmt(Decimal("0.00"))],
        [f"Balance as of {period_end.strftime('%m/%d/%Y')}:",   "", "", _fmt(Decimal("0.00"))],
    ]
    or_cw = [W * w for w in [0.20, 0.18, 0.42, 0.20]]
    or_tbl = Table(or_rows, colWidths=or_cw)
    or_tbl.setStyle(_tbl_style())
    story.append(or_tbl)
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph(
        "(Owner Reserve sub-account not yet implemented — displayed as zero.)",
        S["small"]))

    # ── Build ─────────────────────────────────────────────────────────────────
    doc.build(story)
    return buf.getvalue()


# ── DB entry point ────────────────────────────────────────────────────────────

async def render_owner_statement_pdf(
    db: AsyncSession,
    period_id: int,
) -> bytes:
    """
    Render an owner statement PDF for the given OwnerBalancePeriod.id.
    Returns the PDF as bytes (produced entirely in memory, no temp files).

    Fetches all data from the database, then delegates to _build_pdf_bytes().
    For in-memory rendering (no DB), call _build_pdf_bytes() directly.
    """
    period = await db.get(OwnerBalancePeriod, period_id)
    if period is None:
        raise ValueError(f"Statement period {period_id} not found")

    opa = await db.get(OwnerPayoutAccount, period.owner_payout_account_id)
    if opa is None:
        raise ValueError(f"Owner payout account not found for period {period_id}")

    # Resolve property name, full address, and group
    prop_name = opa.property_id
    prop_address = ""
    prop_group = ""
    try:
        prop_uuid = _uuid.UUID(opa.property_id)
        prop = await db.get(Property, prop_uuid)
        if prop:
            prop_name = prop.name
            prop_group = prop.property_group or ""
            # Assemble full one-line address: "street city STATE postal"
            # Format matches Streamline: space-separated, no comma before state
            addr_parts = [
                prop.address or "",
                prop.city or "",
                (f"{prop.state or ''} {prop.postal_code or ''}").strip(),
            ]
            prop_address = " ".join(p for p in addr_parts if p).strip()
    except ValueError:
        pass  # fake / non-UUID test property_id

    prop_display_name = f"{prop_group} {prop_name}".strip() if prop_group else prop_name
    owner_address = opa.mailing_address_display

    # Compute live statement (reservations + charges).
    # require_stripe_enrollment=False: multi-property owners may have stripe_account_id
    # NULL on secondary OPAs (single Stripe account shared; primary OPA holds the link).
    stmt = await compute_owner_statement(
        db,
        owner_payout_account_id=period.owner_payout_account_id,
        period_start=period.period_start,
        period_end=period.period_end,
        require_stripe_enrollment=False,
    )

    # YTD totals
    ytd = await _get_ytd_totals(
        db,
        owner_payout_account_id=period.owner_payout_account_id,
        year=period.period_start.year,
        period_end=period.period_end,
    )

    pdf_bytes = _build_pdf_bytes(
        period_start=period.period_start,
        period_end=period.period_end,
        status=period.status,
        opening_balance=Decimal(str(period.opening_balance)),
        closing_balance=Decimal(str(period.closing_balance)),
        total_revenue=Decimal(str(period.total_revenue)),
        total_commission=Decimal(str(period.total_commission)),
        total_charges=Decimal(str(period.total_charges)),
        total_payments=Decimal(str(period.total_payments)),
        total_owner_income=Decimal(str(period.total_owner_income)),
        owner_name=_streamline_name(opa.owner_name or "", getattr(opa, "owner_middle_name", None)),
        owner_address=owner_address,
        prop_display_name=prop_display_name,
        prop_address=prop_address,
        stmt=stmt,
        ytd=ytd,
    )

    logger.info(
        "statement_pdf_rendered",
        period_id=period_id,
        owner=opa.owner_name,
        property=prop_name,
        size_bytes=len(pdf_bytes),
    )
    return pdf_bytes
