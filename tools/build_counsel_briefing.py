#!/usr/bin/env python3
"""
Generali v. CROG — Counsel Briefing Packet Generator

Stitches 5 source documents from the Fortress Legal NAS into a single
professional PDF suitable for attorney intake review.

Source documents:
  1. Factual Timeline (generated inline)
  2. Eckles Issue Note (generated inline)
  3. FINAL_Answer_and_Defenses_20260302.txt
  4. E_Discovery_Report_20260302.txt
  5. audit_report_20260302_091240.txt (appendix)

Output:
  /mnt/fortress_nas/sectors/legal/fish-trap-suv2026000013/filings/outgoing/
      Generali_v_CROG_Counsel_Briefing.pdf

Usage:
  python3 tools/build_counsel_briefing.py
"""

import os
import shutil
from datetime import datetime
from pathlib import Path

from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    PageBreak,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib import colors

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
NAS_LEGAL = Path("/mnt/fortress_nas/sectors/legal/fish-trap-suv2026000013")

ANSWER_FILE = NAS_LEGAL / "filings" / "outgoing" / "FINAL_Answer_and_Defenses_20260302.txt"
EDISCOVERY_FILE = NAS_LEGAL / "evidence" / "E_Discovery_Report_20260302.txt"
AUDIT_FILE = PROJECT_ROOT / "audit_report_20260302_091240.txt"

OUTPUT_NAS = NAS_LEGAL / "filings" / "outgoing" / "Generali_v_CROG_Counsel_Briefing.pdf"
OUTPUT_LOCAL = PROJECT_ROOT / "Generali_v_CROG_Counsel_Briefing.pdf"


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def build_styles():
    ss = getSampleStyleSheet()

    ss.add(ParagraphStyle(
        "Confidential",
        parent=ss["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#880000"),
        spaceAfter=6,
    ))
    ss.add(ParagraphStyle(
        "CoverTitle",
        parent=ss["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        alignment=TA_CENTER,
        spaceAfter=12,
    ))
    ss.add(ParagraphStyle(
        "CoverCaption",
        parent=ss["Normal"],
        fontName="Helvetica",
        fontSize=13,
        alignment=TA_CENTER,
        spaceAfter=8,
        leading=18,
    ))
    ss.add(ParagraphStyle(
        "CoverSub",
        parent=ss["Normal"],
        fontName="Helvetica",
        fontSize=11,
        alignment=TA_CENTER,
        spaceAfter=6,
        leading=15,
    ))
    ss.add(ParagraphStyle(
        "SectionHeader",
        parent=ss["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        spaceBefore=18,
        spaceAfter=10,
        textColor=colors.HexColor("#111111"),
        borderWidth=1,
        borderColor=colors.HexColor("#333333"),
        borderPadding=4,
    ))
    ss.add(ParagraphStyle(
        "SubHeader",
        parent=ss["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        spaceBefore=12,
        spaceAfter=6,
    ))
    ss.add(ParagraphStyle(
        "LegalBody",
        parent=ss["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        alignment=TA_JUSTIFY,
        leading=14,
        spaceAfter=6,
    ))
    ss.add(ParagraphStyle(
        "LegalBodyBold",
        parent=ss["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        alignment=TA_LEFT,
        leading=14,
        spaceBefore=10,
        spaceAfter=4,
    ))
    ss.add(ParagraphStyle(
        "TimelineDate",
        parent=ss["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        spaceAfter=2,
    ))
    ss.add(ParagraphStyle(
        "TimelineDesc",
        parent=ss["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        leftIndent=18,
        spaceAfter=8,
    ))
    ss.add(ParagraphStyle(
        "MonoAppendix",
        parent=ss["Code"],
        fontName="Courier",
        fontSize=6.5,
        leading=8,
        alignment=TA_LEFT,
    ))
    ss.add(ParagraphStyle(
        "AppendixNote",
        parent=ss["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=9,
        alignment=TA_LEFT,
        spaceAfter=12,
        textColor=colors.HexColor("#444444"),
    ))
    ss.add(ParagraphStyle(
        "FooterStyle",
        parent=ss["Normal"],
        fontName="Helvetica",
        fontSize=7,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#888888"),
    ))
    return ss


# ---------------------------------------------------------------------------
# Page template callbacks
# ---------------------------------------------------------------------------
CONF_TEXT = "PRIVILEGED AND CONFIDENTIAL \u2014 ATTORNEY WORK PRODUCT"


def header_footer(canvas, doc):
    canvas.saveState()
    # Header
    canvas.setFont("Helvetica-Bold", 7)
    canvas.setFillColor(colors.HexColor("#880000"))
    canvas.drawCentredString(
        letter[0] / 2, letter[1] - 0.4 * inch, CONF_TEXT
    )
    # Footer
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#888888"))
    canvas.drawCentredString(
        letter[0] / 2,
        0.4 * inch,
        f"Generali v. CROG \u2014 Counsel Briefing Packet  |  Page {doc.page}",
    )
    canvas.restoreState()


def cover_page_template(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 7)
    canvas.setFillColor(colors.HexColor("#880000"))
    canvas.drawCentredString(
        letter[0] / 2, letter[1] - 0.4 * inch, CONF_TEXT
    )
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Content builders
# ---------------------------------------------------------------------------
def build_cover(ss):
    elements = []
    elements.append(Spacer(1, 2.0 * inch))
    elements.append(Paragraph(CONF_TEXT, ss["Confidential"]))
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph(
        "COUNSEL BRIEFING PACKET", ss["CoverTitle"]
    ))
    elements.append(Spacer(1, 0.2 * inch))

    caption = (
        "IN THE SUPERIOR COURT OF FANNIN COUNTY<br/>"
        "STATE OF GEORGIA<br/><br/>"
        "GENERALI GLOBAL ASSISTANCE, INC.<br/>"
        "<i>Plaintiff,</i><br/><br/>"
        "v.<br/><br/>"
        "CABIN RENTALS OF GEORGIA, LLC<br/>"
        "<i>Defendant.</i><br/><br/>"
        "<b>Civil Action No. SUV2026000013</b>"
    )
    elements.append(Paragraph(caption, ss["CoverCaption"]))
    elements.append(Spacer(1, 0.5 * inch))

    today = datetime.now().strftime("%B %d, %Y")
    elements.append(Paragraph(f"Prepared: {today}", ss["CoverSub"]))
    elements.append(Paragraph(
        "Prepared by: Cabin Rentals of Georgia, LLC<br/>"
        "Gary M. Knight, Owner &amp; Managing Member",
        ss["CoverSub"],
    ))
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph(
        "<i>This packet contains a factual timeline, the Eckles pro se analysis, "
        "drafted Answer with 9 Affirmative Defenses, a forensic E-Discovery report "
        "from 57,236+ emails, and a sovereign infrastructure audit verifying "
        "chain of custody.</i>",
        ss["CoverSub"],
    ))
    elements.append(PageBreak())
    return elements


def build_toc(ss):
    elements = []
    elements.append(Paragraph("TABLE OF CONTENTS", ss["SectionHeader"]))
    toc_items = [
        ("Section 1", "Factual Timeline"),
        ("Section 2", "The Eckles Issue \u2014 LLC Pro Se Bar"),
        ("Section 3", "Defendant\u2019s Answer and Affirmative Defenses"),
        ("Section 4", "E-Discovery Forensic Report"),
        ("Appendix A", "Sovereign Infrastructure Audit"),
    ]
    for label, title in toc_items:
        elements.append(Paragraph(
            f"<b>{label}:</b>  {title}", ss["LegalBody"]
        ))
    elements.append(PageBreak())
    return elements


def build_timeline(ss):
    elements = []
    elements.append(Paragraph(
        "SECTION 1: FACTUAL TIMELINE", ss["SectionHeader"]
    ))
    elements.append(Paragraph(
        "The following chronology summarizes the material events giving rise to "
        "this dispute, drawn from internal records, the Streamline VRS booking "
        "system, and a forensic review of 57,236+ archived emails.",
        ss["LegalBody"],
    ))
    elements.append(Spacer(1, 0.15 * inch))

    events = [
        ("August 14, 2018",
         "Cabin Rentals of Georgia, LLC (\u201cCROG\u201d) executes a Vacation "
         "Rental Participation Agreement with CSA Travel Protection (now Generali "
         "Global Assistance, Inc.) for travel insurance products offered to guests."),

        ("Date Unknown (Pre-2019)",
         "An \u201cUpdated Compensation Schedule\u201d (Exhibit B to the Complaint) "
         "is purportedly signed by <b>Colleen Blackman</b> of <b>Vickery Resort</b> "
         "(238 Tina St, Hollister MO 65672). Blackman is <u>not</u> an officer, "
         "authorized agent, or managing member of CROG LLC. Gary M. Knight, the sole "
         "owner and managing member, did not authorize or ratify this signature."),

        ("November 2019 \u2013 January 2024",
         "Generali issues monthly invoices to CROG. The invoices consistently reflect "
         "a frozen balance of approximately $7,500. The same amount appears month "
         "after month with no reduction, suggesting the balance was disputed and "
         "never accepted by CROG."),

        ("March 3\u20134, 2021",
         "Joan Cassidy, CROG\u2019s bookkeeper, identifies discrepancies between "
         "the CSA/Generali invoice and CROG\u2019s internal Streamline booking records. "
         "A three-email chain between Joan Cassidy and Gary Knight documents active "
         "questioning of the invoice accuracy. (E-Discovery Finding 2.)"),

        ("January 2024",
         "CROG makes a $2,000 partial payment toward the disputed balance."),

        ("September 5, 2024",
         "RTS Financial (collection agent) sends demand for <b>$7,600</b> on behalf "
         "of Generali. (Note: amount does not match the $7,500 claimed in the "
         "Complaint.)"),

        ("September 22, 2024",
         "RTS Financial sends a \u201cpre-litigation\u201d letter now claiming "
         "<b>$7,500</b> (reduced from $7,600 two weeks earlier) plus $2,508 in "
         "\u201capplicable fees\u201d and threatening 1.5% monthly interest."),

        ("January 2026",
         "Generali Global Assistance, Inc. files suit in the Superior Court of "
         "Fannin County, Georgia. Civil Action No. SUV2026000013."),

        ("February 13, 2026",
         "Original deadline for Defendant to file Answer."),

        ("February 2026",
         "Judge Sosebee recuses herself from the case. CROG files a Motion for "
         "Extension of Time to file the Answer."),

        ("February 16, 2026",
         "J. David Stuart (Plaintiff\u2019s counsel) files opposition to the "
         "extension motion and emails Judge Sosebee\u2019s clerk. Stuart raises "
         "the <i>Eckles</i> corporate pro se issue, stating: \u201cA nonlawyer "
         "cannot represent a company in court.\u201d"),

        ("March 2, 2026",
         "Extension status <b>unconfirmed</b>. No replacement judge assigned as "
         "of this date. CROG seeking licensed Georgia counsel to file the Answer "
         "and defend the action."),
    ]

    for date, desc in events:
        elements.append(Paragraph(date, ss["TimelineDate"]))
        elements.append(Paragraph(desc, ss["TimelineDesc"]))

    elements.append(PageBreak())
    return elements


def build_eckles(ss):
    elements = []
    elements.append(Paragraph(
        "SECTION 2: THE ECKLES ISSUE \u2014 LLC PRO SE BAR",
        ss["SectionHeader"],
    ))

    paras = [
        "Under Georgia law, a limited liability company cannot represent itself "
        "in court proceedings without a licensed attorney. The controlling authority "
        "is <b><i>Eckles v. Atlanta Technology Group, Inc.</i></b>, 267 Ga. 801, "
        "803 (1997), in which the Georgia Supreme Court held that a corporation "
        "(and by extension, an LLC) cannot appear <i>pro se</i> through a "
        "non-attorney officer or representative.",

        "Cabin Rentals of Georgia, LLC is a Georgia limited liability company. "
        "Gary M. Knight is the sole owner, registered agent, and managing member. "
        "Despite Mr. Knight\u2019s complete authority over CROG\u2019s business "
        "affairs, he is not a licensed attorney and therefore <b>cannot file "
        "pleadings or appear on behalf of CROG</b> in the Superior Court of "
        "Fannin County.",

        "Plaintiff\u2019s counsel, J. David Stuart, explicitly raised this issue "
        "in his February 16, 2026 opposition to CROG\u2019s Motion for Extension "
        "of Time. Stuart wrote to Judge Sosebee\u2019s clerk: \u201cA nonlawyer "
        "cannot represent a company in court, and may be the unauthorized practice "
        "of law.\u201d",

        "<b>This is why CROG is seeking immediate retention of licensed Georgia "
        "counsel.</b> The Answer and Affirmative Defenses in Section 3 have been "
        "drafted and are ready for counsel\u2019s review, revision, and filing. "
        "CROG has the factual record, the e-discovery evidence, and the legal "
        "framework prepared. Counsel\u2019s role is to review, adopt, and execute "
        "the filing under their Georgia Bar number.",

        "<i>See also</i>: O.C.G.A. \u00a7 15-19-51 (unauthorized practice of law); "
        "<i>Lawler v. State</i>, 280 Ga. 555 (2006) (reaffirming the prohibition "
        "on non-attorney representation of entities).",
    ]
    for p in paras:
        elements.append(Paragraph(p, ss["LegalBody"]))

    elements.append(PageBreak())
    return elements


def _escape_xml(text: str) -> str:
    """Escape characters that conflict with ReportLab XML paragraph markup."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def build_answer_section(ss):
    elements = []
    elements.append(Paragraph(
        "SECTION 3: DEFENDANT\u2019S ANSWER AND AFFIRMATIVE DEFENSES",
        ss["SectionHeader"],
    ))
    elements.append(Paragraph(
        "<i>The following is the complete drafted Answer prepared by CROG\u2019s "
        "internal legal analysis system. It is presented for counsel\u2019s review, "
        "revision, and filing under counsel\u2019s Georgia Bar number.</i>",
        ss["LegalBody"],
    ))
    elements.append(Spacer(1, 0.1 * inch))

    raw = ANSWER_FILE.read_text(encoding="utf-8")
    # Strip the trailing metadata block
    if "---" in raw:
        raw = raw[:raw.rfind("---")]

    for line in raw.strip().split("\n"):
        stripped = line.strip()
        if not stripped:
            elements.append(Spacer(1, 0.08 * inch))
            continue

        # Detect defense headers (all-caps lines with "DEFENSE" or key headings)
        upper = stripped.upper()
        is_heading = (
            "DEFENSE" in upper
            or upper.startswith("RESPONSE TO COUNT")
            or upper.startswith("JURISDICTIONAL")
            or upper.startswith("AFFIRMATIVE DEFENSES")
            or upper.startswith("PRAYER FOR RELIEF")
            or upper.startswith("JURY TRIAL DEMAND")
            or upper.startswith("CERTIFICATE OF SERVICE")
            or upper == "DEFENDANT'S ANSWER AND DEFENSES"
            or upper.startswith("COMES NOW")
        )

        # Case caption at the top (centered lines)
        is_caption = (
            upper.startswith("IN THE SUPERIOR COURT")
            or upper.startswith("GENERALI GLOBAL")
            or upper.startswith("CABIN RENTALS")
            or stripped.startswith("v.")
            or "PLAINTIFF" in upper
            or "DEFENDANT" in upper and len(stripped) < 30
            or "CIVIL ACTION" in upper
        )

        escaped = _escape_xml(stripped)

        if is_caption:
            elements.append(Paragraph(escaped, ParagraphStyle(
                "caption_line",
                parent=ss["LegalBody"],
                alignment=TA_CENTER,
                fontName="Helvetica-Bold" if "GENERALI" in upper or "CABIN RENTALS" in upper else "Helvetica",
            )))
        elif is_heading:
            elements.append(Paragraph(escaped, ss["LegalBodyBold"]))
        else:
            elements.append(Paragraph(escaped, ss["LegalBody"]))

    elements.append(PageBreak())
    return elements


def build_ediscovery_section(ss):
    elements = []
    elements.append(Paragraph(
        "SECTION 4: E-DISCOVERY FORENSIC REPORT", ss["SectionHeader"]
    ))
    elements.append(Paragraph(
        "<i>This report was generated by the Fortress Prime E-Discovery engine, "
        "which performed a comprehensive forensic search of 57,236+ archived emails "
        "in the CROG enterprise database. All searches were executed against the "
        "fortress_db.email_archive table with full-text matching.</i>",
        ss["LegalBody"],
    ))
    elements.append(Spacer(1, 0.1 * inch))

    raw = EDISCOVERY_FILE.read_text(encoding="utf-8")

    for line in raw.strip().split("\n"):
        stripped = line.strip()
        if not stripped:
            elements.append(Spacer(1, 0.06 * inch))
            continue

        # Separator lines
        if stripped.startswith("====") or stripped.startswith("----"):
            continue

        escaped = _escape_xml(stripped)
        upper = stripped.upper()

        # Section headings (Roman numeral headers)
        if (upper.startswith("I.") or upper.startswith("II.") or
                upper.startswith("III.") or upper.startswith("IV.")):
            elements.append(Paragraph(escaped, ss["SubHeader"]))
        elif upper.startswith("FINDING"):
            elements.append(Paragraph(escaped, ss["LegalBodyBold"]))
        elif upper.startswith("SIGNIFICANCE:"):
            elements.append(Paragraph(
                f"<b>SIGNIFICANCE:</b> {escaped[14:]}", ss["LegalBody"]
            ))
        elif upper.startswith("INTEGRITY HASH"):
            elements.append(Spacer(1, 0.1 * inch))
            elements.append(Paragraph(
                f"<font size='8'>{escaped}</font>", ss["LegalBody"]
            ))
        elif stripped.startswith("|"):
            # Table rows — render as preformatted
            elements.append(Preformatted(stripped, ss["MonoAppendix"]))
        elif stripped.startswith("E-DISCOVERY FORENSIC REPORT"):
            elements.append(Paragraph(escaped, ss["SubHeader"]))
        elif "Generali Global Assistance" in stripped and "v." in stripped:
            elements.append(Paragraph(
                f"<i>{escaped}</i>",
                ParagraphStyle("edis_sub", parent=ss["LegalBody"], alignment=TA_CENTER),
            ))
        elif stripped.startswith("Report Generated:") or stripped.startswith("Searched Archive:") or stripped.startswith("Case Reference:"):
            elements.append(Paragraph(
                f"<font size='9'>{escaped}</font>", ss["LegalBody"]
            ))
        else:
            elements.append(Paragraph(escaped, ss["LegalBody"]))

    elements.append(PageBreak())
    return elements


def build_audit_appendix(ss):
    elements = []
    elements.append(Paragraph(
        "APPENDIX A: SOVEREIGN INFRASTRUCTURE AUDIT", ss["SectionHeader"]
    ))
    elements.append(Paragraph(
        "This appendix contains the complete output of the Fortress Prime Master "
        "Sovereign Audit, executed on March 2, 2026. It documents the 4-node DGX "
        "Spark compute cluster, PostgreSQL database infrastructure, and data "
        "architecture that powers the E-Discovery engine. Its inclusion "
        "demonstrates that the forensic email search was conducted on a "
        "comprehensive, production-grade system with verifiable chain of custody.",
        ss["AppendixNote"],
    ))

    raw = AUDIT_FILE.read_text(encoding="utf-8")
    # Split into chunks of ~120 lines to avoid oversized flowables
    lines = raw.split("\n")
    chunk_size = 100
    for i in range(0, len(lines), chunk_size):
        chunk = "\n".join(lines[i:i + chunk_size])
        elements.append(Preformatted(chunk, ss["MonoAppendix"]))

    return elements


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ss = build_styles()

    # Ensure output directory
    OUTPUT_NAS.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(OUTPUT_NAS),
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=1.0 * inch,
        rightMargin=1.0 * inch,
        title="Generali v. CROG — Counsel Briefing Packet",
        author="Cabin Rentals of Georgia, LLC",
        subject="Case SUV2026000013 — Attorney Intake Materials",
    )

    story = []
    story.extend(build_cover(ss))
    story.extend(build_toc(ss))
    story.extend(build_timeline(ss))
    story.extend(build_eckles(ss))
    story.extend(build_answer_section(ss))
    story.extend(build_ediscovery_section(ss))
    story.extend(build_audit_appendix(ss))

    doc.build(story, onFirstPage=cover_page_template, onLaterPages=header_footer)

    # Copy to local project root
    shutil.copy2(str(OUTPUT_NAS), str(OUTPUT_LOCAL))

    nas_size = OUTPUT_NAS.stat().st_size
    local_size = OUTPUT_LOCAL.stat().st_size

    print("=" * 70)
    print("  COUNSEL BRIEFING PACKET — BUILD COMPLETE")
    print("=" * 70)
    print(f"  NAS:   {OUTPUT_NAS}  ({nas_size:,} bytes)")
    print(f"  Local: {OUTPUT_LOCAL}  ({local_size:,} bytes)")
    print(f"  Pages: (open PDF to verify)")
    print("=" * 70)


if __name__ == "__main__":
    main()
