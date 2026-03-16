"""
Document Engine — PDF generation for receipts and rental agreements.

Uses reportlab to produce professional, branded PDFs entirely on local
hardware. All documents are generated in-memory (io.BytesIO) and returned
as bytes — no temp files touch the filesystem.
"""
from __future__ import annotations

import io
from datetime import datetime

import structlog
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

logger = structlog.get_logger(service="document_engine")

COMPANY_NAME = "Cabin Rentals of Georgia, LLC"
COMPANY_LINE = "Blue Ridge, GA  |  (706) 455-5555  |  www.crog-ai.com"


class DocumentEngine:
    """Generates branded PDF receipts and rental agreements."""

    @staticmethod
    def generate_receipt(quote_data: dict) -> bytes:
        """
        Generate a professional payment receipt PDF.

        Expected quote_data keys:
            guest_name, property_name, check_in, check_out, nights,
            base_rent, taxes, fees, total, payment_method, status, quote_id
        """
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        width, height = letter

        # ── Header band ──────────────────────────────────────────
        c.setFillColor(colors.HexColor("#065f46"))
        c.rect(0, height - 100, width, 100, fill=True, stroke=False)

        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 22)
        c.drawCentredString(width / 2, height - 45, COMPANY_NAME)
        c.setFont("Helvetica", 10)
        c.drawCentredString(width / 2, height - 65, COMPANY_LINE)
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(width / 2, height - 88, "PAYMENT RECEIPT")

        # ── Status watermark ─────────────────────────────────────
        status = quote_data.get("status", "paid")
        watermark = "PAID IN FULL" if status == "paid" else "PENDING VERIFICATION"
        c.saveState()
        c.setFillColor(colors.HexColor("#059669") if status == "paid" else colors.HexColor("#d97706"))
        c.setFillAlpha(0.08)
        c.setFont("Helvetica-Bold", 72)
        c.translate(width / 2, height / 2)
        c.rotate(35)
        c.drawCentredString(0, 0, watermark)
        c.restoreState()

        # ── Booking details ──────────────────────────────────────
        y = height - 140
        c.setFillColor(colors.black)

        def _label_value(label: str, value: str, ypos: float) -> float:
            c.setFont("Helvetica-Bold", 11)
            c.drawString(72, ypos, label)
            c.setFont("Helvetica", 11)
            c.drawString(220, ypos, str(value))
            return ypos - 22

        y = _label_value("Receipt #:", quote_data.get("quote_id", "N/A")[:18], y)
        y = _label_value("Date:", datetime.utcnow().strftime("%B %d, %Y"), y)
        y = _label_value("Guest:", quote_data.get("guest_name", "—"), y)
        y = _label_value("Property:", quote_data.get("property_name", "—"), y)
        y = _label_value("Check-In:", quote_data.get("check_in", "—"), y)
        y = _label_value("Check-Out:", quote_data.get("check_out", "—"), y)
        y = _label_value("Nights:", str(quote_data.get("nights", "—")), y)
        y = _label_value("Payment Method:", (quote_data.get("payment_method") or "—").title(), y)

        # ── Line items table ─────────────────────────────────────
        y -= 20
        c.setStrokeColor(colors.HexColor("#d1d5db"))
        c.line(72, y, width - 72, y)
        y -= 25

        def _line_item(desc: str, amount: str, ypos: float, bold: bool = False) -> float:
            font = "Helvetica-Bold" if bold else "Helvetica"
            c.setFont(font, 12 if bold else 11)
            c.drawString(72, ypos, desc)
            c.drawRightString(width - 72, ypos, f"${amount}")
            return ypos - 24

        y = _line_item("Base Rent", quote_data.get("base_rent", "0.00"), y)
        y = _line_item("Taxes", quote_data.get("taxes", "0.00"), y)
        y = _line_item("Fees", quote_data.get("fees", "0.00"), y)

        y -= 6
        c.setStrokeColor(colors.HexColor("#065f46"))
        c.setLineWidth(1.5)
        c.line(72, y, width - 72, y)
        y -= 28

        y = _line_item("TOTAL DUE", quote_data.get("total", "0.00"), y, bold=True)

        # ── Status badge ─────────────────────────────────────────
        y -= 20
        badge_color = colors.HexColor("#059669") if status == "paid" else colors.HexColor("#d97706")
        c.setFillColor(badge_color)
        badge_text = watermark
        c.setFont("Helvetica-Bold", 16)
        tw = c.stringWidth(badge_text, "Helvetica-Bold", 16)
        bx = (width - tw) / 2 - 16
        c.roundRect(bx, y - 8, tw + 32, 32, 6, fill=True, stroke=False)
        c.setFillColor(colors.white)
        c.drawCentredString(width / 2, y, badge_text)

        # ── Footer ───────────────────────────────────────────────
        c.setFillColor(colors.HexColor("#999999"))
        c.setFont("Helvetica", 8)
        c.drawCentredString(width / 2, 40, f"© {datetime.utcnow().year} {COMPANY_NAME}. All rights reserved.")
        c.drawCentredString(width / 2, 28, "This is an electronically generated receipt and is valid without signature.")

        c.showPage()
        c.save()
        return buf.getvalue()

    @staticmethod
    def generate_agreement(quote_data: dict) -> bytes:
        """
        Generate a 1-page placeholder rental agreement PDF.

        This is a standard-form agreement template. Full legal agreements
        with e-signatures are handled by the Agreements module.
        """
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        width, height = letter

        # ── Header ───────────────────────────────────────────────
        c.setFillColor(colors.HexColor("#065f46"))
        c.rect(0, height - 80, width, 80, fill=True, stroke=False)

        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(width / 2, height - 40, COMPANY_NAME)
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(width / 2, height - 62, "VACATION RENTAL AGREEMENT")

        # ── Agreement body ───────────────────────────────────────
        y = height - 120
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 11)
        line_h = 18
        left = 72
        max_w = width - 144

        prop = quote_data.get("property_name", "the Property")
        guest = quote_data.get("guest_name", "Guest")
        ci = quote_data.get("check_in", "TBD")
        co = quote_data.get("check_out", "TBD")
        total = quote_data.get("total", "0.00")

        preamble = (
            f"This Vacation Rental Agreement (\"Agreement\") is entered into between "
            f"{COMPANY_NAME} (\"Manager\") and {guest} (\"Guest\") for the rental "
            f"of {prop}."
        )

        from reportlab.lib.utils import simpleSplit
        for line in simpleSplit(preamble, "Helvetica", 11, max_w):
            c.drawString(left, y, line)
            y -= line_h

        y -= 10

        sections = [
            ("1. RENTAL PERIOD", f"Check-in: {ci}  |  Check-out: {co}"),
            ("2. TOTAL AMOUNT", f"${total} USD — inclusive of all taxes and fees."),
            ("3. CHECK-IN / CHECK-OUT",
             "Check-in time: 4:00 PM. Check-out time: 10:00 AM. "
             "Early arrivals and late departures are subject to availability."),
            ("4. OCCUPANCY",
             "Only registered guests may occupy the property. Maximum occupancy "
             "as listed on the property page must be respected at all times."),
            ("5. PETS",
             "Pets are allowed only in designated pet-friendly properties. "
             "An undisclosed pet will result in a $500 fee. All pet waste must be cleaned immediately."),
            ("6. SMOKING",
             "Smoking is strictly prohibited inside all properties. "
             "A $500 cleaning fee will be charged for violations."),
            ("7. DAMAGES",
             "Guest is responsible for any damages beyond normal wear and tear. "
             "Damages will be documented and deducted from the security deposit or billed separately."),
            ("8. NOISE & CONDUCT",
             "Quiet hours are 10:00 PM to 8:00 AM. Excessive noise or disruptive "
             "behavior may result in immediate eviction without refund."),
            ("9. CANCELLATION",
             "Cancellations made 30+ days prior to check-in receive a full refund minus "
             "a $100 processing fee. Cancellations within 30 days are non-refundable."),
            ("10. LIABILITY",
             "Manager is not liable for personal injury or loss of personal property. "
             "Guest assumes all risks associated with the use of amenities including hot tubs, "
             "fire pits, and hiking trails."),
        ]

        for title, body in sections:
            if y < 80:
                c.showPage()
                y = height - 60
                c.setFillColor(colors.black)

            c.setFont("Helvetica-Bold", 11)
            c.drawString(left, y, title)
            y -= line_h

            c.setFont("Helvetica", 10)
            for line in simpleSplit(body, "Helvetica", 10, max_w):
                if y < 60:
                    c.showPage()
                    y = height - 60
                    c.setFillColor(colors.black)
                    c.setFont("Helvetica", 10)
                c.drawString(left, y, line)
                y -= line_h - 2
            y -= 8

        # ── Signature block ──────────────────────────────────────
        y -= 10
        if y < 120:
            c.showPage()
            y = height - 80
            c.setFillColor(colors.black)

        c.setFont("Helvetica", 10)
        c.drawString(left, y, "Guest Signature: _________________________________")
        c.drawString(width / 2 + 20, y, f"Date: {datetime.utcnow().strftime('%m/%d/%Y')}")
        y -= 30
        c.drawString(left, y, f"Guest Name (printed): {guest}")

        # ── Footer ───────────────────────────────────────────────
        c.setFillColor(colors.HexColor("#999999"))
        c.setFont("Helvetica", 8)
        c.drawCentredString(width / 2, 40, f"© {datetime.utcnow().year} {COMPANY_NAME}. All rights reserved.")
        c.drawCentredString(width / 2, 28, "This agreement is subject to Georgia state law.")

        c.showPage()
        c.save()
        return buf.getvalue()
