#!/usr/bin/env python3
"""
FORTRESS PRIME — Legal Case Manager
======================================
Multi-case legal command center. Manages cases, evidence, watchdog alerts,
action timelines, and automated forensic scanning.

Architecture:
    - PostgreSQL schema: legal.cases, legal.case_actions, legal.case_watchdog, legal.case_evidence
    - Golden rules: finance.classification_rules (LITIGATION_RECOVERY)
    - Email archive: public.email_archive (57K+ emails, forensic evidence)
    - NAS storage: /mnt/fortress_nas/sectors/legal/{case_slug}/

Usage:
    # Standalone (port 9878)
    ./venv/bin/python tools/legal_case_manager.py

    # Or import endpoints into batch_classifier.py

Cron Integration:
    # KYC Watchdog scans ALL active cases every 2 hours
    tools/kyc_watchdog.py (reads from legal.case_watchdog)
"""

import csv
import io
import json
import logging
import os
import sys
import hashlib
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional

# Ensure project root and tools dir are on Python path
_PROJECT_ROOT = Path(__file__).parent.parent
_TOOLS_DIR = Path(__file__).parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_TOOLS_DIR))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

import psycopg2
import psycopg2.extras
import psycopg2.pool
import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import smtplib

from fortress_auth import apply_fortress_security, require_auth
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText as MIMETextPart
from email import encoders
from xml.sax.saxutils import escape as xml_escape
import uuid
import time
import traceback

logging.basicConfig(level=logging.INFO, format="%(asctime)s [LEGAL] %(levelname)s  %(message)s")
log = logging.getLogger("legal_case_manager")

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "fortress_db"),
    "user": os.getenv("LEGAL_DB_USER", "admin"),
}
_db_host = os.getenv("LEGAL_DB_HOST", "")
if _db_host:
    DB_CONFIG["host"] = _db_host
    DB_CONFIG["port"] = int(os.getenv("LEGAL_DB_PORT", os.getenv("DB_PORT", "5432")))
_db_pass = os.getenv("LEGAL_DB_PASS", "")
if _db_pass:
    DB_CONFIG["password"] = _db_pass
NAS_LEGAL = Path("/mnt/fortress_nas/sectors/legal")
PORT = 9878

# Email configuration (Gmail SMTP — same pattern as watchtower/sentinel)
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
LEGAL_DEFAULT_EMAIL = os.getenv("LEGAL_DEFAULT_EMAIL", "cabin.rentals.of.georgia@gmail.com")

# ── App with production middleware ────────────────────────────────────
app = FastAPI(title="Fortress Prime — Legal Case Manager", version="2.1")

# Fortress enterprise security: JWT auth, CORS whitelist, rate limiting, security headers
apply_fortress_security(app)

# ── Connection Pool (production-grade) ────────────────────────────────
_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_start_time = time.time()

def _init_pool():
    global _pool
    if _pool is None:
        log.info(f"Connecting to DB: {DB_CONFIG}")
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2, maxconn=10, **DB_CONFIG
        )
        log.info("Database connection pool initialized (2-10 connections)")

def _get_pooled_conn():
    if _pool is None:
        _init_pool()
    return _pool.getconn()

def _put_conn(conn):
    if _pool and conn:
        try:
            conn.rollback()
        except Exception:
            pass
        _pool.putconn(conn)

# ── Request lifecycle middleware ──────────────────────────────────────

@app.middleware("http")
async def request_lifecycle(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    start = time.time()
    request.state.request_id = request_id
    try:
        response = await call_next(request)
        elapsed = (time.time() - start) * 1000
        if elapsed > 500:
            log.warning(f"[{request_id}] SLOW {request.method} {request.url.path} {elapsed:.0f}ms")
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed:.0f}ms"
        return response
    except Exception as e:
        log.error(f"[{request_id}] Unhandled error: {e}\n{traceback.format_exc()}")
        return JSONResponse(
            {"error": "Internal server error", "request_id": request_id},
            status_code=500,
        )

@app.on_event("startup")
async def startup():
    _init_pool()
    log.info("Legal CRM v2.0 ready")

@app.on_event("shutdown")
async def shutdown():
    if _pool:
        _pool.closeall()
        log.info("Database pool closed")

# ── Health endpoint ──────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    """Production health check — verifies DB, NAS, email config."""
    checks = {}
    conn = None
    try:
        conn = _get_pooled_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
    finally:
        if conn:
            _put_conn(conn)

    checks["nas"] = "ok" if NAS_LEGAL.exists() else "unreachable"
    checks["email"] = "configured" if GMAIL_ADDRESS and GMAIL_APP_PASSWORD else "not_configured"
    checks["uptime_seconds"] = int(time.time() - _start_time)
    checks["pool_size"] = _pool.maxconn if _pool else 0

    db_ok = checks["database"] == "ok"
    checks["status"] = "healthy" if db_ok else "unhealthy"
    return JSONResponse(checks, status_code=200 if db_ok else 503)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def get_conn():
    """Get a connection from the pool. ALWAYS return via _put_conn() in finally block."""
    return _get_pooled_conn()


def days_until(d):
    """Calculate days until a date."""
    if not d:
        return None
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return (d - date.today()).days


# ═══════════════════════════════════════════════════════════════════════════════
# PDF GENERATION (reportlab — camera-ready legal filings)
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_legal_pdf(text: str, case_number: str = "", title: str = "") -> bytes:
    """
    Render plain-text legal document to a professional PDF.

    Uses 1-inch margins, Times New Roman, and structured formatting that
    matches Georgia Superior Court filing expectations.
    """
    import io
    import re as _re
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, PageBreak,
    )
    from reportlab.lib.units import inch
    from reportlab.lib import colors

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=0.75 * inch,
        title=title or "Legal Document",
        author="Fortress Prime Legal CRM",
    )

    # ── Styles ────────────────────────────────────────────────────────
    s_court = ParagraphStyle(
        "CourtHeader",
        fontName="Times-Bold",
        fontSize=11,
        leading=14,
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    s_heading = ParagraphStyle(
        "DocHeading",
        fontName="Times-Bold",
        fontSize=13,
        leading=17,
        alignment=TA_CENTER,
        spaceAfter=14,
        spaceBefore=18,
    )
    s_section = ParagraphStyle(
        "SectionTitle",
        fontName="Times-Bold",
        fontSize=12,
        leading=15,
        alignment=TA_LEFT,
        spaceBefore=14,
        spaceAfter=6,
    )
    s_defense = ParagraphStyle(
        "DefenseTitle",
        fontName="Times-Bold",
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
        spaceBefore=10,
        spaceAfter=4,
    )
    s_body = ParagraphStyle(
        "BodyText",
        fontName="Times-Roman",
        fontSize=12,
        leading=17,
        alignment=TA_JUSTIFY,
        firstLineIndent=36,
    )
    s_body_plain = ParagraphStyle(
        "BodyPlain",
        fontName="Times-Roman",
        fontSize=12,
        leading=17,
        alignment=TA_LEFT,
    )
    s_indent = ParagraphStyle(
        "IndentedText",
        fontName="Times-Roman",
        fontSize=12,
        leading=17,
        alignment=TA_LEFT,
        leftIndent=36,
    )
    s_sig = ParagraphStyle(
        "SigText",
        fontName="Times-Roman",
        fontSize=12,
        leading=15,
        alignment=TA_LEFT,
    )
    s_meta = ParagraphStyle(
        "MetaText",
        fontName="Helvetica",
        fontSize=7,
        leading=10,
        textColor=colors.Color(0.6, 0.6, 0.6),
    )

    # ── Parse & Build Story ───────────────────────────────────────────
    story = []
    lines = text.split("\n")
    in_court_header = False
    court_lines: list[str] = []
    found_body = False
    in_sig_block = False

    for i, line in enumerate(lines):
        trimmed = line.strip()

        # Court header block (IN THE ... through Defendant.)
        if not found_body and trimmed.startswith("IN THE "):
            in_court_header = True
            court_lines = []

        if in_court_header:
            court_lines.append(xml_escape(trimmed))
            if trimmed.endswith("Defendant.") or trimmed.endswith("Defendant"):
                story.append(
                    Paragraph("<br/>".join(court_lines), s_court)
                )
                story.append(Spacer(1, 4))
                story.append(
                    HRFlowable(
                        width="100%", thickness=2,
                        color=colors.black, spaceAfter=12,
                    )
                )
                in_court_header = False
                found_body = True
            continue

        # Document title (DEFENDANT'S MOTION..., ANSWER TO..., etc.)
        if _re.match(
            r"^(DEFENDANT'S|MOTION FOR|ANSWER TO|ATTORNEY BRIEFING)", trimmed
        ):
            story.append(
                Paragraph(f"<u>{xml_escape(trimmed)}</u>", s_heading)
            )
            in_sig_block = False
            continue

        # Section headers
        if _re.match(
            r"^(I+V?I*\.\s+|JURISDICTIONAL|RESPONSE TO|AFFIRMATIVE DEFENSES"
            r"|PRAYER FOR RELIEF|JURY TRIAL|CERTIFICATE OF SERVICE"
            r"|PROPOSED ORDER|ORDER$|CASE OVERVIEW|CLAIMS SUMMARY"
            r"|OPPOSING COUNSEL|CASE NOTES|EVIDENCE INVENTORY"
            r"|COMES NOW|WHEREFORE|IT IS HEREBY)",
            trimmed,
        ):
            story.append(Paragraph(xml_escape(trimmed), s_section))
            in_sig_block = False
            continue

        # Defense titles
        if _re.match(
            r"^(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH"
            r"|NINTH|TENTH|ELEVENTH|TWELFTH) DEFENSE",
            trimmed,
        ):
            story.append(
                Paragraph(f"<u>{xml_escape(trimmed)}</u>", s_defense)
            )
            continue

        # Signature lines (_____)
        if _re.match(r"^_{4,}", trimmed):
            story.append(Spacer(1, 24))
            story.append(
                HRFlowable(
                    width="45%", thickness=1,
                    color=colors.black, spaceAfter=4,
                )
            )
            in_sig_block = True
            continue

        # Metadata footer (--- near end)
        if trimmed.startswith("---") and i > len(lines) - 8:
            story.append(Spacer(1, 18))
            story.append(
                HRFlowable(
                    width="100%", thickness=0.5,
                    color=colors.Color(0.7, 0.7, 0.7), spaceAfter=4,
                )
            )
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    story.append(
                        Paragraph(xml_escape(lines[j].strip()), s_meta)
                    )
            break

        # PROPOSED ORDER page break
        if trimmed == "PROPOSED ORDER":
            story.append(PageBreak())
            story.append(Paragraph(xml_escape(trimmed), s_section))
            continue

        # Blank lines
        if not trimmed:
            story.append(Spacer(1, 6))
            in_sig_block = False
            continue

        # Signature block text (after _____)
        if in_sig_block:
            story.append(Paragraph(xml_escape(trimmed), s_sig))
            continue

        # Indented address/counsel blocks (4+ leading spaces)
        if line.startswith("    "):
            story.append(Paragraph(xml_escape(trimmed), s_indent))
            continue

        # Numbered paragraphs
        if _re.match(r"^\d+\.", trimmed) or _re.match(r"^[a-z]\.\s", trimmed):
            story.append(Paragraph(xml_escape(trimmed), s_body_plain))
            continue

        # Regular body text
        story.append(Paragraph(xml_escape(trimmed), s_body))

    doc.build(story)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL DELIVERY (Gmail SMTP)
# ═══════════════════════════════════════════════════════════════════════════════

def _send_legal_email(
    pdf_bytes: bytes,
    filename: str,
    to_email: str,
    case_name: str = "",
    case_number: str = "",
) -> dict:
    """Attach a PDF to a professional legal email and deliver via Gmail SMTP."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return {
            "error": (
                "Email not configured. Set GMAIL_ADDRESS and "
                "GMAIL_APP_PASSWORD in your .env file."
            )
        }

    msg = MIMEMultipart()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_email
    msg["Subject"] = f"Legal Filing — {case_number} — {filename.replace('.pdf','')}"

    body = (
        f"Attached is the legal document for:\n\n"
        f"  Case:   {case_name}\n"
        f"  Number: {case_number}\n"
        f"  File:   {filename}\n\n"
        f"Generated by Fortress Prime Legal CRM.\n\n"
        f"— Cabin Rentals of Georgia, LLC\n"
        f"  PO Box 982, Morganton, GA 30560\n"
        f"  (678) 549-3680\n"
    )
    msg.attach(MIMETextPart(body, "plain"))

    part = MIMEBase("application", "pdf")
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition", f'attachment; filename="{filename}"'
    )
    msg.attach(part)

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        log.info(f"Legal PDF emailed: {filename} -> {to_email}")
        return {"sent": True, "to": to_email, "filename": filename}
    except Exception as e:
        log.error(f"Email send failed: {e}")
        return {"error": f"Failed to send: {str(e)}"}


# ═══════════════════════════════════════════════════════════════════════════════
# API: CASE MANAGEMENT (CRUD)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/cases")
async def list_cases():
    """List all legal cases with status and countdown."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT c.*,
               (SELECT COUNT(*) FROM legal.case_actions a WHERE a.case_id = c.id AND a.status = 'pending') as pending_actions,
               (SELECT COUNT(*) FROM legal.case_actions a WHERE a.case_id = c.id AND a.status = 'completed') as completed_actions,
               (SELECT COUNT(*) FROM legal.case_evidence e WHERE e.case_id = c.id) as evidence_count,
               (SELECT COUNT(*) FROM legal.case_watchdog w WHERE w.case_id = c.id AND w.is_active) as watchdog_terms
        FROM legal.cases c
        ORDER BY c.critical_date ASC NULLS LAST, c.created_at DESC
    """)
    cases = []
    for row in cur.fetchall():
        c = dict(row)
        c["days_remaining"] = days_until(c.get("critical_date"))
        for k in ("created_at", "updated_at", "critical_date", "petition_date"):
            if c.get(k):
                c[k] = str(c[k])
        cases.append(c)
    cur.close()
    _put_conn(conn)
    return {"cases": cases, "total": len(cases)}


@app.get("/api/cases/{case_slug}")
async def get_case(case_slug: str):
    """Get full case detail with actions, evidence, and watchdog terms."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT * FROM legal.cases WHERE case_slug = %s", (case_slug,))
    case = cur.fetchone()
    if not case:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "Case not found"}, status_code=404)
    case = dict(case)
    case["days_remaining"] = days_until(case.get("critical_date"))
    for k in ("created_at", "updated_at", "critical_date", "petition_date"):
        if case.get(k):
            case[k] = str(case[k])

    # Actions
    cur.execute("""
        SELECT * FROM legal.case_actions WHERE case_id = %s ORDER BY action_date DESC
    """, (case["id"],))
    actions = [dict(r) for r in cur.fetchall()]
    for a in actions:
        for k in ("action_date", "created_at"):
            if a.get(k): a[k] = str(a[k])

    # Evidence
    cur.execute("""
        SELECT * FROM legal.case_evidence WHERE case_id = %s ORDER BY is_critical DESC, discovered_at DESC
    """, (case["id"],))
    evidence = [dict(r) for r in cur.fetchall()]
    for e in evidence:
        if e.get("discovered_at"): e["discovered_at"] = str(e["discovered_at"])

    # Watchdog
    cur.execute("""
        SELECT * FROM legal.case_watchdog WHERE case_id = %s ORDER BY priority, search_type
    """, (case["id"],))
    watchdog = [dict(r) for r in cur.fetchall()]
    for w in watchdog:
        if w.get("created_at"): w["created_at"] = str(w["created_at"])

    cur.close()
    _put_conn(conn)
    return {"case": case, "actions": actions, "evidence": evidence, "watchdog": watchdog}


@app.post("/api/cases")
async def create_case(request: dict):
    """Create a new legal case."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    required = ["case_slug", "case_number", "case_name"]
    for r in required:
        if r not in request:
            cur.close(); _put_conn(conn)
            return JSONResponse({"error": f"Missing required field: {r}"}, status_code=400)

    # Create NAS directory structure
    case_dir = NAS_LEGAL / request["case_slug"]
    for sub in ["evidence", "correspondence", "certified_mail", "filings"]:
        (case_dir / sub).mkdir(parents=True, exist_ok=True)

    cur.execute("""
        INSERT INTO legal.cases (
            case_slug, case_number, case_name, court, judge, case_type, our_role,
            critical_date, critical_note, plan_admin, plan_admin_email, plan_admin_address,
            fiduciary, opposing_counsel, our_claim_basis, petition_date, notes
        ) VALUES (
            %(case_slug)s, %(case_number)s, %(case_name)s, %(court)s, %(judge)s,
            %(case_type)s, %(our_role)s, %(critical_date)s, %(critical_note)s,
            %(plan_admin)s, %(plan_admin_email)s, %(plan_admin_address)s,
            %(fiduciary)s, %(opposing_counsel)s, %(our_claim_basis)s,
            %(petition_date)s, %(notes)s
        ) RETURNING id, case_slug
    """, {
        "case_slug": request["case_slug"],
        "case_number": request["case_number"],
        "case_name": request["case_name"],
        "court": request.get("court"),
        "judge": request.get("judge"),
        "case_type": request.get("case_type", "civil"),
        "our_role": request.get("our_role", "claimant"),
        "critical_date": request.get("critical_date"),
        "critical_note": request.get("critical_note"),
        "plan_admin": request.get("plan_admin"),
        "plan_admin_email": request.get("plan_admin_email"),
        "plan_admin_address": request.get("plan_admin_address"),
        "fiduciary": request.get("fiduciary"),
        "opposing_counsel": request.get("opposing_counsel"),
        "our_claim_basis": request.get("our_claim_basis"),
        "petition_date": request.get("petition_date"),
        "notes": request.get("notes"),
    })
    result = cur.fetchone()
    conn.commit()
    cur.close()
    _put_conn(conn)

    log.info(f"New case created: {result['case_slug']} (id={result['id']})")
    return {"created": True, "case_id": result["id"], "case_slug": result["case_slug"],
            "nas_path": str(case_dir)}


# ═══════════════════════════════════════════════════════════════════════════════
# API: CASE ACTIONS (Timeline)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/cases/{case_slug}/actions")
async def add_action(case_slug: str, request: dict):
    """Add an action to a case timeline."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM legal.cases WHERE case_slug = %s", (case_slug,))
    case = cur.fetchone()
    if not case:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "Case not found"}, status_code=404)

    cur.execute("""
        INSERT INTO legal.case_actions (case_id, action_type, description, status, tracking_number, notes)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
    """, (case["id"], request.get("action_type", "note"), request["description"],
          request.get("status", "pending"), request.get("tracking_number"),
          request.get("notes")))
    action_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    _put_conn(conn)
    return {"created": True, "action_id": action_id}


@app.put("/api/cases/{case_slug}/actions/{action_id}")
async def update_action(case_slug: str, action_id: int, request: dict):
    """Update an action status (e.g., mark as completed)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE legal.case_actions SET status = %s, notes = COALESCE(%s, notes),
        tracking_number = COALESCE(%s, tracking_number)
        WHERE id = %s
    """, (request.get("status", "completed"), request.get("notes"),
          request.get("tracking_number"), action_id))
    conn.commit()
    cur.close()
    _put_conn(conn)
    return {"updated": True, "action_id": action_id}


# ═══════════════════════════════════════════════════════════════════════════════
# API: WATCHDOG (Add/Remove search terms per case)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/cases/{case_slug}/watchdog")
async def add_watchdog_term(case_slug: str, request: dict):
    """Add a watchdog search term to a case."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM legal.cases WHERE case_slug = %s", (case_slug,))
    case = cur.fetchone()
    if not case:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "Case not found"}, status_code=404)

    cur.execute("""
        INSERT INTO legal.case_watchdog (case_id, search_type, search_term, priority)
        VALUES (%s, %s, %s, %s) RETURNING id
    """, (case["id"], request.get("search_type", "sender"), request["search_term"],
          request.get("priority", "P2")))
    wid = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    _put_conn(conn)
    return {"created": True, "watchdog_id": wid}


@app.get("/api/watchdog/scan-all")
async def scan_all_cases():
    """Scan email archive against ALL active case watchdog terms."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT w.*, c.case_slug, c.case_number, c.case_name
        FROM legal.case_watchdog w
        JOIN legal.cases c ON c.id = w.case_id
        WHERE w.is_active = true AND c.status = 'active'
        ORDER BY w.priority, c.case_slug
    """)
    terms = [dict(r) for r in cur.fetchall()]

    alerts = []
    for t in terms:
        if t["search_type"] == "sender":
            cur.execute("""
                SELECT id, sender, subject, sent_at::text FROM email_archive
                WHERE sender ILIKE %s ORDER BY sent_at DESC LIMIT 3
            """, (f"%{t['search_term']}%",))
        elif t["search_type"] == "subject":
            cur.execute("""
                SELECT id, sender, subject, sent_at::text FROM email_archive
                WHERE subject ILIKE %s ORDER BY sent_at DESC LIMIT 3
            """, (f"%{t['search_term']}%",))
        elif t["search_type"] == "body":
            cur.execute("""
                SELECT id, sender, subject, sent_at::text FROM email_archive
                WHERE content ILIKE %s AND sent_at > NOW() - INTERVAL '30 days'
                ORDER BY sent_at DESC LIMIT 3
            """, (f"%{t['search_term']}%",))
        else:
            continue

        for row in cur.fetchall():
            alerts.append({
                "case_slug": t["case_slug"],
                "case_number": t["case_number"],
                "priority": t["priority"],
                "search_type": t["search_type"],
                "search_term": t["search_term"],
                **dict(row),
            })

    cur.close()
    _put_conn(conn)

    # Deduplicate by email ID per case
    seen = set()
    unique = []
    for a in alerts:
        key = (a["case_slug"], a["id"])
        if key not in seen:
            seen.add(key)
            unique.append(a)

    return {
        "alerts": unique,
        "total_alerts": len(unique),
        "cases_scanned": len(set(t["case_slug"] for t in terms)),
        "terms_checked": len(terms),
        "scan_time": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# API: EVIDENCE (Add/List evidence per case)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/cases/{case_slug}/evidence")
async def add_evidence(case_slug: str, request: dict):
    """Add evidence to a case."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM legal.cases WHERE case_slug = %s", (case_slug,))
    case = cur.fetchone()
    if not case:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "Case not found"}, status_code=404)

    cur.execute("""
        INSERT INTO legal.case_evidence (case_id, evidence_type, email_id, file_path, description, relevance, is_critical)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
    """, (case["id"], request.get("evidence_type", "document"), request.get("email_id"),
          request.get("file_path"), request["description"], request.get("relevance"),
          request.get("is_critical", False)))
    eid = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    _put_conn(conn)
    return {"created": True, "evidence_id": eid}


# ═══════════════════════════════════════════════════════════════════════════════
# API: FORENSIC SCAN (Reusable for any case)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/cases/{case_slug}/forensic-scan")
async def forensic_scan(case_slug: str):
    """Run a forensic scan of email archive for a specific case using its watchdog terms."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT * FROM legal.cases WHERE case_slug = %s", (case_slug,))
    case = cur.fetchone()
    if not case:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "Case not found"}, status_code=404)

    # Get watchdog terms for this case
    cur.execute("""
        SELECT * FROM legal.case_watchdog WHERE case_id = %s AND is_active = true
    """, (case["id"],))
    terms = [dict(r) for r in cur.fetchall()]

    # Archive stats
    cur.execute("SELECT COUNT(*) as total FROM email_archive")
    total = cur.fetchone()["total"]
    cur.execute("SELECT MIN(sent_at)::text as earliest, MAX(sent_at)::text as latest FROM email_archive")
    date_range = cur.fetchone()

    # Search each term
    results = []
    for t in terms:
        if t["search_type"] == "sender":
            cur.execute("SELECT COUNT(*) as cnt FROM email_archive WHERE sender ILIKE %s",
                       (f"%{t['search_term']}%",))
        elif t["search_type"] == "subject":
            cur.execute("SELECT COUNT(*) as cnt FROM email_archive WHERE subject ILIKE %s",
                       (f"%{t['search_term']}%",))
        elif t["search_type"] == "body":
            cur.execute("SELECT COUNT(*) as cnt FROM email_archive WHERE content ILIKE %s",
                       (f"%{t['search_term']}%",))
        else:
            continue
        results.append({
            "search_type": t["search_type"],
            "search_term": t["search_term"],
            "priority": t["priority"],
            "matches": cur.fetchone()["cnt"],
        })

    # Compute hash
    report_hash = hashlib.sha256(
        json.dumps({"case": case_slug, "total": total, "results": results}, sort_keys=True).encode()
    ).hexdigest()

    cur.close()
    _put_conn(conn)

    return {
        "case_slug": case_slug,
        "case_number": str(case["case_number"]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "integrity_hash": report_hash,
        "archive_scope": {
            "total_emails": total,
            "date_range_start": date_range["earliest"],
            "date_range_end": date_range["latest"],
        },
        "search_results": results,
        "total_matches": sum(r["matches"] for r in results),
        "zero_match_terms": [r for r in results if r["matches"] == 0],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# API: DASHBOARD OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/dashboard")
async def dashboard_data():
    """Aggregate dashboard data across all active cases."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT COUNT(*) as cnt FROM legal.cases WHERE status = 'active'")
    active = cur.fetchone()["cnt"]

    cur.execute("""
        SELECT c.case_slug, c.case_number, c.case_name, c.status, c.critical_date::text,
               c.our_role, c.case_type,
               (SELECT COUNT(*) FROM legal.case_actions a WHERE a.case_id = c.id AND a.status = 'pending') as pending
        FROM legal.cases c WHERE c.status = 'active'
        ORDER BY c.critical_date ASC NULLS LAST
    """)
    cases = []
    for r in cur.fetchall():
        c = dict(r)
        c["days_remaining"] = days_until(c.get("critical_date"))
        cases.append(c)

    cur.execute("""
        SELECT COUNT(*) as cnt FROM legal.case_actions WHERE status = 'pending'
    """)
    pending_total = cur.fetchone()["cnt"]

    cur.close()
    _put_conn(conn)

    return {
        "active_cases": active,
        "pending_actions": pending_total,
        "cases": cases,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# API: CORRESPONDENCE (CRM Communication Tracking)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/cases/{case_slug}/correspondence")
async def list_correspondence(case_slug: str):
    """List all correspondence for a case, newest first."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM legal.cases WHERE case_slug = %s", (case_slug,))
    case = cur.fetchone()
    if not case:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "Case not found"}, status_code=404)

    cur.execute("""
        SELECT * FROM legal.correspondence
        WHERE case_id = %s
        ORDER BY created_at DESC
    """, (case["id"],))
    items = []
    for r in cur.fetchall():
        row = dict(r)
        for k in ("approved_at", "sent_at", "created_at"):
            if row.get(k):
                row[k] = str(row[k])
        items.append(row)
    cur.close()
    _put_conn(conn)
    return {"correspondence": items, "total": len(items)}


@app.post("/api/cases/{case_slug}/correspondence")
async def create_correspondence(case_slug: str, request: dict):
    """Create a new correspondence record (starts as draft)."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM legal.cases WHERE case_slug = %s", (case_slug,))
    case = cur.fetchone()
    if not case:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "Case not found"}, status_code=404)

    if "subject" not in request:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "subject is required"}, status_code=400)

    cur.execute("""
        INSERT INTO legal.correspondence (
            case_id, direction, comm_type, recipient, recipient_email,
            subject, body, status, file_path
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        case["id"],
        request.get("direction", "outbound"),
        request.get("comm_type", "email"),
        request.get("recipient"),
        request.get("recipient_email"),
        request["subject"],
        request.get("body"),
        request.get("status", "draft"),
        request.get("file_path"),
    ))
    cid = cur.fetchone()["id"]
    conn.commit()

    # Log action
    cur.execute("""
        INSERT INTO legal.case_actions (case_id, action_type, description, status)
        VALUES (%s, 'correspondence', %s, 'completed')
    """, (case["id"], f"Created {request.get('comm_type', 'email')} draft: {request['subject']}"))
    conn.commit()
    cur.close()
    _put_conn(conn)

    log.info(f"Correspondence created: #{cid} for {case_slug}")
    return {"created": True, "correspondence_id": cid}


@app.put("/api/correspondence/{corr_id}/approve")
async def approve_correspondence(corr_id: int, request: dict = None):
    """Approve a correspondence draft for sending."""
    if request is None:
        request = {}
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE legal.correspondence
        SET status = 'approved',
            approved_by = %s,
            approved_at = NOW()
        WHERE id = %s AND status = 'draft'
        RETURNING id
    """, (request.get("approved_by", "admin"), corr_id))
    result = cur.fetchone()
    conn.commit()
    cur.close()
    _put_conn(conn)
    if not result:
        return JSONResponse({"error": "Correspondence not found or not in draft status"}, status_code=404)
    log.info(f"Correspondence #{corr_id} approved")
    return {"approved": True, "correspondence_id": corr_id}


@app.put("/api/correspondence/{corr_id}/mark-sent")
async def mark_sent(corr_id: int, request: dict = None):
    """Mark correspondence as sent (after human sends the Gmail draft or mails it)."""
    if request is None:
        request = {}
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE legal.correspondence
        SET status = 'sent',
            sent_at = NOW(),
            tracking_number = COALESCE(%s, tracking_number)
        WHERE id = %s
        RETURNING id
    """, (request.get("tracking_number"), corr_id))
    result = cur.fetchone()
    conn.commit()
    cur.close()
    _put_conn(conn)
    if not result:
        return JSONResponse({"error": "Correspondence not found"}, status_code=404)
    return {"marked_sent": True, "correspondence_id": corr_id}


@app.post("/api/correspondence/{corr_id}/create-gmail-draft")
async def create_gmail_draft(corr_id: int):
    """Push approved correspondence to Gmail as a draft. Human reviews and clicks Send."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT c.*, cs.case_slug, cs.case_number
        FROM legal.correspondence c
        JOIN legal.cases cs ON cs.id = c.case_id
        WHERE c.id = %s
    """, (corr_id,))
    corr = cur.fetchone()
    cur.close()
    _put_conn(conn)

    if not corr:
        return JSONResponse({"error": "Correspondence not found"}, status_code=404)
    if corr["status"] not in ("approved", "draft"):
        return JSONResponse({"error": f"Cannot create draft from status '{corr['status']}'"}, status_code=400)
    if not corr.get("recipient_email"):
        return JSONResponse({"error": "No recipient_email set"}, status_code=400)

    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from gmail_auth import get_gmail_service
        from email.mime.text import MIMEText
        import base64

        service = get_gmail_service()

        message = MIMEText(corr["body"] or "")
        message["to"] = corr["recipient_email"]
        message["subject"] = corr["subject"]

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft = service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}}
        ).execute()

        draft_id = draft.get("id", "")

        # Update record with draft ID
        conn2 = get_conn()
        cur2 = conn2.cursor()
        cur2.execute("""
            UPDATE legal.correspondence
            SET gmail_draft_id = %s, status = 'approved'
            WHERE id = %s
        """, (draft_id, corr_id))
        conn2.commit()
        cur2.close()
        conn2.close()

        log.info(f"Gmail draft created for correspondence #{corr_id}: draft_id={draft_id}")
        return {
            "gmail_draft_created": True,
            "draft_id": draft_id,
            "correspondence_id": corr_id,
            "recipient": corr["recipient_email"],
            "subject": corr["subject"],
        }

    except FileNotFoundError:
        return JSONResponse(
            {"error": "Gmail credentials not configured. Run: python -m src.gmail_auth"},
            status_code=503
        )
    except Exception as e:
        log.error(f"Gmail draft creation failed: {e}")
        return JSONResponse({"error": f"Gmail API error: {str(e)}"}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════════════
# API: DEADLINES (Countdown & Escalation)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/cases/{case_slug}/deadlines")
async def list_deadlines(case_slug: str):
    """List all deadlines for a case with countdown."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM legal.cases WHERE case_slug = %s", (case_slug,))
    case = cur.fetchone()
    if not case:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "Case not found"}, status_code=404)

    cur.execute("""
        SELECT * FROM legal.deadlines
        WHERE case_id = %s
        ORDER BY due_date ASC
    """, (case["id"],))
    items = []
    for r in cur.fetchall():
        row = dict(r)
        effective_date = row.get("extended_to") or row.get("due_date")
        row["days_remaining"] = days_until(effective_date)
        row["effective_date"] = str(effective_date) if effective_date else None
        for k in ("due_date", "extended_to", "created_at"):
            if row.get(k):
                row[k] = str(row[k])
        # Color coding
        dr = row["days_remaining"]
        if dr is not None:
            if dr < 0:
                row["urgency"] = "overdue"
            elif dr <= 3:
                row["urgency"] = "critical"
            elif dr <= 7:
                row["urgency"] = "urgent"
            elif dr <= 14:
                row["urgency"] = "warning"
            else:
                row["urgency"] = "normal"
        items.append(row)
    cur.close()
    _put_conn(conn)
    return {"deadlines": items, "total": len(items)}


@app.post("/api/cases/{case_slug}/deadlines")
async def add_deadline(case_slug: str, request: dict):
    """Add a deadline to a case."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM legal.cases WHERE case_slug = %s", (case_slug,))
    case = cur.fetchone()
    if not case:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "Case not found"}, status_code=404)

    for field in ("deadline_type", "description", "due_date"):
        if field not in request:
            cur.close(); _put_conn(conn)
            return JSONResponse({"error": f"Missing required field: {field}"}, status_code=400)

    cur.execute("""
        INSERT INTO legal.deadlines (
            case_id, deadline_type, description, due_date,
            alert_days_before, status, extended_to, extension_reason
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        case["id"],
        request["deadline_type"],
        request["description"],
        request["due_date"],
        request.get("alert_days_before", 7),
        request.get("status", "pending"),
        request.get("extended_to"),
        request.get("extension_reason"),
    ))
    did = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    _put_conn(conn)
    log.info(f"Deadline created: #{did} for {case_slug}")
    return {"created": True, "deadline_id": did}


@app.put("/api/deadlines/{deadline_id}")
async def update_deadline(deadline_id: int, request: dict):
    """Update a deadline (extend, complete, etc.)."""
    conn = get_conn()
    cur = conn.cursor()
    sets = []
    vals = []
    for field in ("status", "extended_to", "extension_reason", "description"):
        if field in request:
            sets.append(f"{field} = %s")
            vals.append(request[field])
    if not sets:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "No fields to update"}, status_code=400)
    vals.append(deadline_id)
    cur.execute(f"UPDATE legal.deadlines SET {', '.join(sets)} WHERE id = %s", vals)
    conn.commit()
    cur.close()
    _put_conn(conn)
    return {"updated": True, "deadline_id": deadline_id}


@app.get("/api/deadlines/all")
async def all_deadlines():
    """Get all upcoming deadlines across all active cases, sorted by urgency."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT d.*, c.case_slug, c.case_number, c.case_name
        FROM legal.deadlines d
        JOIN legal.cases c ON c.id = d.case_id
        WHERE c.status = 'active' AND d.status IN ('pending', 'extended')
        ORDER BY COALESCE(d.extended_to, d.due_date) ASC
    """)
    items = []
    for r in cur.fetchall():
        row = dict(r)
        effective_date = row.get("extended_to") or row.get("due_date")
        row["days_remaining"] = days_until(effective_date)
        row["effective_date"] = str(effective_date) if effective_date else None
        for k in ("due_date", "extended_to", "created_at"):
            if row.get(k):
                row[k] = str(row[k])
        dr = row["days_remaining"]
        if dr is not None:
            if dr < 0:
                row["urgency"] = "overdue"
            elif dr <= 3:
                row["urgency"] = "critical"
            elif dr <= 7:
                row["urgency"] = "urgent"
            elif dr <= 14:
                row["urgency"] = "warning"
            else:
                row["urgency"] = "normal"
        items.append(row)
    cur.close()
    _put_conn(conn)
    return {"deadlines": items, "total": len(items)}


# ═══════════════════════════════════════════════════════════════════════════════
# API: DOCUMENT GENERATION (Template Engine)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/templates")
async def list_available_templates():
    """List all available document templates."""
    from legal_templates import list_templates
    return {"templates": list_templates()}


@app.get("/api/cases/{case_slug}/documents")
async def list_documents(case_slug: str):
    """List all documents on NAS for a case, with text content for .txt/.md files."""
    case_dir = NAS_LEGAL / case_slug
    if not case_dir.exists():
        return {"documents": [], "total": 0, "nas_path": str(case_dir)}

    docs = []
    for root_path in case_dir.rglob("*"):
        if root_path.is_file():
            rel = root_path.relative_to(case_dir)
            entry = {
                "filename": root_path.name,
                "file_path": str(root_path),
                "path": str(rel),
                "size_bytes": root_path.stat().st_size,
                "modified": datetime.fromtimestamp(
                    root_path.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
                "category": str(rel).split("/")[0] if "/" in str(rel) else "root",
                "generated": "outgoing" in str(rel),
            }
            # Include content for text files (legal docs)
            if root_path.suffix in (".txt", ".md") and root_path.stat().st_size < 500_000:
                try:
                    entry["content"] = root_path.read_text(encoding="utf-8")
                except Exception:
                    entry["content"] = None
            docs.append(entry)
    docs.sort(key=lambda d: d["modified"], reverse=True)
    return {"documents": docs, "total": len(docs), "nas_path": str(case_dir)}


@app.post("/api/cases/{case_slug}/generate/{template_name}")
async def generate_document(case_slug: str, template_name: str, request: dict = None):
    """Generate a document from a template and save to NAS."""
    import re as _re
    if request is None:
        request = {}

    from legal_templates import render_template, hash_document, TEMPLATES
    if template_name not in TEMPLATES:
        return JSONResponse(
            {"error": f"Unknown template: {template_name}. Available: {list(TEMPLATES.keys())}"},
            status_code=400
        )

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM legal.cases WHERE case_slug = %s", (case_slug,))
    case_row = cur.fetchone()
    if not case_row:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "Case not found"}, status_code=404)

    case_data = dict(case_row)
    for k in ("created_at", "updated_at", "critical_date", "petition_date"):
        if case_data.get(k):
            case_data[k] = str(case_data[k])

    # Get counts for briefing
    cur.execute("SELECT COUNT(*) as cnt FROM legal.case_evidence WHERE case_id = %s", (case_row["id"],))
    case_data["evidence_count"] = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) as cnt FROM legal.case_actions WHERE case_id = %s AND status = 'pending'", (case_row["id"],))
    case_data["pending_actions"] = cur.fetchone()["cnt"]

    # -------------------------------------------------------------------
    # AUTO-ENRICH: Pull deadline data so templates get service_date,
    # original_deadline, proposed_deadline automatically
    # -------------------------------------------------------------------
    cur.execute(
        "SELECT * FROM legal.deadlines WHERE case_id = %s ORDER BY due_date",
        (case_row["id"],)
    )
    deadlines = [dict(r) for r in cur.fetchall()]

    answer_dl = None
    for dl in deadlines:
        if dl["deadline_type"] == "answer_due":
            answer_dl = dl
            break

    if answer_dl:
        orig_due = answer_dl["due_date"]
        if hasattr(orig_due, "strftime"):
            case_data.setdefault("original_deadline", orig_due.strftime("%B %d, %Y"))
        else:
            case_data.setdefault("original_deadline", str(orig_due))

        ext_to = answer_dl.get("extended_to")
        if ext_to:
            if hasattr(ext_to, "strftime"):
                case_data.setdefault("proposed_deadline", ext_to.strftime("%B %d, %Y"))
            else:
                case_data.setdefault("proposed_deadline", str(ext_to))

    # Parse service date from notes (e.g. "Served PERSONALLY on Gary M. Knight on Jan 14, 2026")
    notes = case_data.get("notes", "") or ""
    svc_match = _re.search(
        r'[Ss]erved\s+(?:PERSONALLY|personally)\s+on\s+\w[\w\s]*on\s+'
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2},?\s+\d{4})',
        notes
    )
    if svc_match:
        case_data.setdefault("service_date", svc_match.group(1))

    # Parse service method
    if "PERSONALLY" in notes or "personally" in notes:
        case_data.setdefault("service_method", "personal service by Deputy Sheriff")

    cur.close()
    _put_conn(conn)

    # Merge overrides (user-provided values win)
    case_data.update(request)

    doc_text = render_template(template_name, case_data, overrides=request)
    doc_hash = hash_document(doc_text)
    doc_text = doc_text.replace("{hash}", doc_hash)

    # Save to NAS
    outgoing_dir = NAS_LEGAL / case_slug / "filings" / "outgoing"
    outgoing_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{template_name}_{timestamp}.txt"
    file_path = outgoing_dir / filename
    file_path.write_text(doc_text)

    log.info(f"Document generated: {file_path} (hash: {doc_hash[:16]}...)")
    return {
        "generated": True,
        "template": template_name,
        "file_path": str(file_path),
        "filename": filename,
        "hash_sha256": doc_hash,
        "size_bytes": len(doc_text.encode()),
        "document": doc_text,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# API: PDF RENDERING & EMAIL DELIVERY
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/pdf/render")
async def render_pdf(request: dict):
    """
    Convert document text to a camera-ready legal PDF.

    Accepts:
        text (str): The plain-text legal document
        title (str): Document title (for filename & metadata)
        case_number (str): Case number (for filename)
    Returns:
        PDF file download (application/pdf)
    """
    text = (request or {}).get("text", "")
    title = (request or {}).get("title", "Legal_Document")
    case_number = (request or {}).get("case_number", "")
    if not text:
        return JSONResponse({"error": "No document text provided"}, status_code=400)

    try:
        pdf_bytes = _generate_legal_pdf(text, case_number=case_number, title=title)
    except Exception as e:
        log.error(f"PDF generation failed: {e}")
        return JSONResponse({"error": f"PDF generation failed: {str(e)}"}, status_code=500)

    safe_title = title.replace(" ", "_").replace("/", "-")
    filename = f"{safe_title}_{case_number}.pdf" if case_number else f"{safe_title}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/pdf/email")
async def email_pdf(request: dict):
    """
    Generate a legal PDF and email it as an attachment.

    Accepts:
        text (str): The plain-text legal document
        title (str): Document title
        case_number (str): Case number
        case_name (str): Full case name
        to (str): Recipient email (defaults to LEGAL_DEFAULT_EMAIL)
    Returns:
        JSON with {sent: true, to, filename} or {error: ...}
    """
    req = request or {}
    text = req.get("text", "")
    title = req.get("title", "Legal_Document")
    case_number = req.get("case_number", "")
    case_name = req.get("case_name", "")
    to_email = req.get("to", LEGAL_DEFAULT_EMAIL)

    if not text:
        return JSONResponse({"error": "No document text provided"}, status_code=400)

    try:
        pdf_bytes = _generate_legal_pdf(text, case_number=case_number, title=title)
    except Exception as e:
        log.error(f"PDF generation for email failed: {e}")
        return JSONResponse({"error": f"PDF generation failed: {str(e)}"}, status_code=500)

    safe_title = title.replace(" ", "_").replace("/", "-")
    filename = f"{safe_title}_{case_number}.pdf" if case_number else f"{safe_title}.pdf"

    # Also save PDF to NAS for audit trail
    try:
        pdf_dir = NAS_LEGAL / "pdf_archive"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (pdf_dir / f"{safe_title}_{case_number}_{ts}.pdf").write_bytes(pdf_bytes)
    except Exception as e:
        log.warning(f"Could not archive PDF to NAS: {e}")

    result = _send_legal_email(pdf_bytes, filename, to_email, case_name, case_number)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# API: COURT FILINGS (Filing Status Tracking)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/cases/{case_slug}/filings")
async def list_filings(case_slug: str):
    """List all court filings for a case with status and service info."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM legal.cases WHERE case_slug = %s", (case_slug,))
    case_row = cur.fetchone()
    if not case_row:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "Case not found"}, status_code=404)

    cur.execute("""
        SELECT f.*,
            (SELECT COUNT(*) FROM legal.uploads u WHERE u.filing_id = f.id) as upload_count
        FROM legal.filings f
        WHERE f.case_id = %s
        ORDER BY f.filed_date DESC NULLS LAST, f.created_at DESC
    """, (case_row["id"],))
    filings = [dict(r) for r in cur.fetchall()]
    for f in filings:
        for k in ("filed_date", "served_date", "created_at", "updated_at"):
            if f.get(k):
                f[k] = str(f[k])
    cur.close(); _put_conn(conn)
    return filings


@app.post("/api/cases/{case_slug}/filings")
async def create_filing(case_slug: str, request: dict):
    """Create a new filing record for a case."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM legal.cases WHERE case_slug = %s", (case_slug,))
    case_row = cur.fetchone()
    if not case_row:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "Case not found"}, status_code=404)

    cur.execute("""
        INSERT INTO legal.filings (case_id, filing_type, title, filed_date, filed_by,
            filed_with, filing_location, status, served_on, served_date, served_method,
            original_path, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
    """, (
        case_row["id"],
        request.get("filing_type", "general"),
        request.get("title", "Untitled Filing"),
        request.get("filed_date"),
        request.get("filed_by"),
        request.get("filed_with"),
        request.get("filing_location"),
        request.get("status", "filed"),
        request.get("served_on"),
        request.get("served_date"),
        request.get("served_method"),
        request.get("original_path"),
        request.get("notes"),
    ))
    filing = dict(cur.fetchone())
    conn.commit()
    cur.close(); _put_conn(conn)
    for k in ("filed_date", "served_date", "created_at", "updated_at"):
        if filing.get(k):
            filing[k] = str(filing[k])
    return filing


# ═══════════════════════════════════════════════════════════════════════════════
# API: DOCUMENT UPLOADS (Stamped copies, scanned docs, receipts)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/cases/{case_slug}/uploads")
async def list_uploads(case_slug: str):
    """List all uploaded documents for a case."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM legal.cases WHERE case_slug = %s", (case_slug,))
    case_row = cur.fetchone()
    if not case_row:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "Case not found"}, status_code=404)

    cur.execute("""
        SELECT u.*, f.title as filing_title
        FROM legal.uploads u
        LEFT JOIN legal.filings f ON f.id = u.filing_id
        WHERE u.case_id = %s
        ORDER BY u.created_at DESC
    """, (case_row["id"],))
    uploads = [dict(r) for r in cur.fetchall()]
    for u in uploads:
        if u.get("created_at"):
            u["created_at"] = str(u["created_at"])
    cur.close(); _put_conn(conn)
    return uploads


@app.post("/api/cases/{case_slug}/upload")
async def upload_document(
    case_slug: str,
    file: UploadFile = File(...),
    upload_type: str = Form("general"),
    description: str = Form(""),
    filing_id: Optional[int] = Form(None),
):
    """
    Upload a document (PDF, image, etc.) to the case file on NAS.

    Upload types: stamped_copy, evidence, correspondence, receipt, general
    If filing_id is provided, links the upload to a specific filing record.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, case_slug FROM legal.cases WHERE case_slug = %s", (case_slug,))
    case_row = cur.fetchone()
    if not case_row:
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "Case not found"}, status_code=404)

    # Read file content
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:  # 50MB limit
        cur.close(); _put_conn(conn)
        return JSONResponse({"error": "File too large (max 50MB)"}, status_code=413)

    # Save to NAS under case directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = file.filename.replace(" ", "_").replace("/", "-") if file.filename else "upload"
    subdir = {
        "stamped_copy": "filings/stamped",
        "evidence": "evidence/uploaded",
        "correspondence": "correspondence",
        "receipt": "receipts",
    }.get(upload_type, "uploads")

    nas_dir = NAS_LEGAL / case_slug / subdir
    nas_dir.mkdir(parents=True, exist_ok=True)
    dest_filename = f"{ts}_{safe_name}"
    dest_path = nas_dir / dest_filename
    dest_path.write_bytes(content)

    # If this is a stamped copy linked to a filing, update the filing record
    if filing_id and upload_type == "stamped_copy":
        cur.execute(
            "UPDATE legal.filings SET stamped_path = %s, status = 'accepted', updated_at = NOW() WHERE id = %s",
            (str(dest_path), filing_id),
        )

    # Insert upload record
    cur.execute("""
        INSERT INTO legal.uploads (case_id, filename, original_name, content_type, file_size,
            nas_path, upload_type, description, filing_id, uploaded_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
    """, (
        case_row["id"],
        dest_filename,
        file.filename,
        file.content_type or "application/octet-stream",
        len(content),
        str(dest_path),
        upload_type,
        description or file.filename,
        filing_id,
        "admin",
    ))
    upload_rec = dict(cur.fetchone())
    conn.commit()
    cur.close(); _put_conn(conn)

    if upload_rec.get("created_at"):
        upload_rec["created_at"] = str(upload_rec["created_at"])

    log.info(f"Document uploaded: {dest_path} ({len(content)} bytes, type={upload_type})")
    return upload_rec


@app.get("/api/uploads/{upload_id}/download")
async def download_upload(upload_id: int):
    """Download a previously uploaded document."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM legal.uploads WHERE id = %s", (upload_id,))
    rec = cur.fetchone()
    cur.close(); _put_conn(conn)
    if not rec:
        return JSONResponse({"error": "Upload not found"}, status_code=404)

    file_path = Path(rec["nas_path"])
    if not file_path.exists():
        return JSONResponse({"error": "File not found on NAS"}, status_code=404)

    return Response(
        content=file_path.read_bytes(),
        media_type=rec["content_type"],
        headers={"Content-Disposition": f'attachment; filename="{rec["original_name"]}"'},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# API: UNIFIED ACTIVITY TIMELINE (The Case Narrative)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/cases/{case_slug}/timeline")
async def case_timeline(case_slug: str, limit: int = 50):
    """
    Unified chronological feed of ALL case events — filings, correspondence,
    actions, uploads, evidence additions. This is the single-pane case narrative.
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT id FROM legal.cases WHERE case_slug = %s", (case_slug,))
        case_row = cur.fetchone()
        if not case_row:
            return JSONResponse({"error": "Case not found"}, status_code=404)
        cid = case_row["id"]

        cur.execute("""
            (
              SELECT 'filing' as event_type,
                     f.title as summary,
                     COALESCE('Filed with ' || f.filed_with, '') as detail,
                     f.status,
                     f.created_at as event_time,
                     f.id as ref_id
              FROM legal.filings f WHERE f.case_id = %(cid)s
            )
            UNION ALL
            (
              SELECT 'correspondence' as event_type,
                     cr.subject as summary,
                     COALESCE(cr.direction || ' · ' || cr.comm_type || ' · ' || COALESCE(cr.recipient,''), '') as detail,
                     cr.status,
                     COALESCE(cr.sent_at, cr.created_at) as event_time,
                     cr.id as ref_id
              FROM legal.correspondence cr WHERE cr.case_id = %(cid)s
            )
            UNION ALL
            (
              SELECT CASE WHEN a.status='completed' THEN 'action_done' ELSE 'action' END as event_type,
                     a.description as summary,
                     COALESCE(a.action_type, '') as detail,
                     a.status,
                     a.action_date as event_time,
                     a.id as ref_id
              FROM legal.case_actions a WHERE a.case_id = %(cid)s
            )
            UNION ALL
            (
              SELECT 'upload' as event_type,
                     u.original_name as summary,
                     COALESCE(u.upload_type || ' · ' || u.description, '') as detail,
                     'completed' as status,
                     u.created_at as event_time,
                     u.id as ref_id
              FROM legal.uploads u WHERE u.case_id = %(cid)s
            )
            UNION ALL
            (
              SELECT 'evidence' as event_type,
                     COALESCE(e.description, e.evidence_type) as summary,
                     COALESCE(e.evidence_type || CASE WHEN e.relevance IS NOT NULL THEN ' · ' || e.relevance ELSE '' END, '') as detail,
                     'logged' as status,
                     e.discovered_at as event_time,
                     e.id as ref_id
              FROM legal.case_evidence e WHERE e.case_id = %(cid)s
            )
            ORDER BY event_time DESC NULLS LAST
            LIMIT %(lim)s
        """, {"cid": cid, "lim": limit})

        events = []
        for row in cur.fetchall():
            ev = dict(row)
            if ev.get("event_time"):
                ev["event_time"] = str(ev["event_time"])
            events.append(ev)
        return events
    finally:
        cur.close()
        _put_conn(conn)


# ═══════════════════════════════════════════════════════════════════════════════
# API: CASE SEARCH (Full-Text Across All Case Data)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/search")
async def search_case_data(q: str = "", case_slug: str = ""):
    """Search across all case data: actions, evidence, correspondence, filings, uploads."""
    if not q or len(q) < 2:
        return {"results": [], "query": q}

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        pattern = f"%{q}%"
        case_filter = ""
        params = {"q": pattern}
        if case_slug:
            cur.execute("SELECT id FROM legal.cases WHERE case_slug = %s", (case_slug,))
            row = cur.fetchone()
            if row:
                case_filter = "AND case_id = %(cid)s"
                params["cid"] = row["id"]

        cur.execute(f"""
            (SELECT 'action' as type, id, description as text, action_type as subtype, status, created_at
             FROM legal.case_actions WHERE (description ILIKE %(q)s OR notes ILIKE %(q)s) {case_filter})
            UNION ALL
            (SELECT 'evidence' as type, id, description as text, evidence_type as subtype, 'logged' as status, discovered_at as created_at
             FROM legal.case_evidence WHERE (description ILIKE %(q)s OR relevance ILIKE %(q)s) {case_filter})
            UNION ALL
            (SELECT 'correspondence' as type, id, subject as text, comm_type as subtype, status, created_at
             FROM legal.correspondence WHERE (subject ILIKE %(q)s OR body ILIKE %(q)s OR recipient ILIKE %(q)s) {case_filter})
            UNION ALL
            (SELECT 'filing' as type, id, title as text, filing_type as subtype, status, created_at
             FROM legal.filings WHERE (title ILIKE %(q)s OR notes ILIKE %(q)s OR filed_with ILIKE %(q)s) {case_filter})
            ORDER BY created_at DESC LIMIT 30
        """, params)

        results = []
        for row in cur.fetchall():
            r = dict(row)
            if r.get("created_at"):
                r["created_at"] = str(r["created_at"])
            results.append(r)
        return {"results": results, "query": q, "count": len(results)}
    finally:
        cur.close()
        _put_conn(conn)


# ═══════════════════════════════════════════════════════════════════════════════
# API: CRM DASHBOARD (Cross-Case Overview)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/crm/overview")
async def crm_overview():
    """Full CRM overview: cases, deadlines, pending correspondence, actions."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Active cases
    cur.execute("""
        SELECT c.*,
            (SELECT COUNT(*) FROM legal.case_actions a WHERE a.case_id = c.id AND a.status = 'pending') as pending_actions,
            (SELECT COUNT(*) FROM legal.case_evidence e WHERE e.case_id = c.id) as evidence_count,
            (SELECT COUNT(*) FROM legal.correspondence cr WHERE cr.case_id = c.id) as correspondence_count,
            (SELECT COUNT(*) FROM legal.correspondence cr WHERE cr.case_id = c.id AND cr.status = 'draft') as draft_count,
            (SELECT COUNT(*) FROM legal.deadlines d WHERE d.case_id = c.id AND d.status IN ('pending','extended')) as active_deadlines,
            (SELECT COUNT(*) FROM legal.filings f WHERE f.case_id = c.id) as filing_count,
            (SELECT COUNT(*) FROM legal.uploads u WHERE u.case_id = c.id) as upload_count
        FROM legal.cases c
        WHERE c.status = 'active'
        ORDER BY c.critical_date ASC NULLS LAST
    """)
    cases = []
    for r in cur.fetchall():
        row = dict(r)
        row["days_remaining"] = days_until(row.get("critical_date"))
        for k in ("created_at", "updated_at", "critical_date", "petition_date"):
            if row.get(k):
                row[k] = str(row[k])
        cases.append(row)

    # Upcoming deadlines across all cases
    cur.execute("""
        SELECT d.*, c.case_slug, c.case_number, c.case_name
        FROM legal.deadlines d
        JOIN legal.cases c ON c.id = d.case_id
        WHERE c.status = 'active' AND d.status IN ('pending', 'extended')
        ORDER BY COALESCE(d.extended_to, d.due_date) ASC
        LIMIT 10
    """)
    deadlines = []
    for r in cur.fetchall():
        row = dict(r)
        effective = row.get("extended_to") or row.get("due_date")
        row["days_remaining"] = days_until(effective)
        row["effective_date"] = str(effective) if effective else None
        for k in ("due_date", "extended_to", "created_at"):
            if row.get(k):
                row[k] = str(row[k])
        dr = row["days_remaining"]
        if dr is not None:
            if dr < 0: row["urgency"] = "overdue"
            elif dr <= 3: row["urgency"] = "critical"
            elif dr <= 7: row["urgency"] = "urgent"
            elif dr <= 14: row["urgency"] = "warning"
            else: row["urgency"] = "normal"
        deadlines.append(row)

    # Recent correspondence
    cur.execute("""
        SELECT cr.*, c.case_slug, c.case_number
        FROM legal.correspondence cr
        JOIN legal.cases c ON c.id = cr.case_id
        ORDER BY cr.created_at DESC
        LIMIT 15
    """)
    correspondence = []
    for r in cur.fetchall():
        row = dict(r)
        for k in ("approved_at", "sent_at", "created_at"):
            if row.get(k):
                row[k] = str(row[k])
        correspondence.append(row)

    # Pending actions
    cur.execute("""
        SELECT a.*, c.case_slug, c.case_number
        FROM legal.case_actions a
        JOIN legal.cases c ON c.id = a.case_id
        WHERE a.status IN ('pending', 'overdue')
        ORDER BY a.action_date DESC
        LIMIT 20
    """)
    actions = []
    for r in cur.fetchall():
        row = dict(r)
        for k in ("action_date", "created_at"):
            if row.get(k):
                row[k] = str(row[k])
        actions.append(row)

    cur.close()
    _put_conn(conn)

    return {
        "cases": cases,
        "deadlines": deadlines,
        "correspondence": correspondence,
        "pending_actions": actions,
        "total_cases": len(cases),
        "total_deadlines": len(deadlines),
        "total_drafts": sum(c.get("draft_count", 0) for c in cases),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/inbox")
async def email_inbox(case_slug: str = "", limit: int = 50, watchdog_only: bool = False):
    """Live email inbox — shows recent inbound emails, with watchdog alerts highlighted.

    Query params:
        case_slug: Filter to a specific case's watchdog matches
        limit: Max results (default 50)
        watchdog_only: If true, only show emails that matched watchdog terms
    """
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if watchdog_only or case_slug:
        # Show emails that have corresponding legal.correspondence entries (inbound)
        case_filter = ""
        params = [limit]
        if case_slug:
            case_filter = "AND c.case_slug = %s"
            params = [case_slug, limit]

        cur.execute(f"""
            SELECT cr.id as correspondence_id, cr.case_id,
                   c.case_slug, c.case_name, c.case_number,
                   cr.recipient as from_name, cr.recipient_email as from_email,
                   cr.subject, cr.body, cr.sent_at as received_at,
                   cr.direction, cr.status,
                   'watchdog_match' as tag,
                   COALESCE(
                       (SELECT e.is_critical FROM legal.case_evidence e
                        WHERE e.case_id = cr.case_id
                        AND e.description ILIKE '%%' || cr.subject || '%%'
                        LIMIT 1),
                       false
                   ) as is_critical
            FROM legal.correspondence cr
            JOIN legal.cases c ON c.id = cr.case_id
            WHERE cr.direction = 'inbound'
            {case_filter}
            ORDER BY cr.sent_at DESC NULLS LAST
            LIMIT %s
        """, params)
    else:
        # Show ALL recent emails from the bridge
        cur.execute("""
            SELECT ea.id as archive_id, ea.sender as from_email,
                   ea.subject, LEFT(ea.content, 500) as body,
                   ea.sent_at as received_at,
                   ea.division, ea.division_confidence,
                   ea.category as source_tag,
                   CASE WHEN ea.file_path LIKE 'imap://%%' THEN 'live' ELSE 'historical' END as feed,
                   EXISTS(
                       SELECT 1 FROM legal.correspondence cr
                       WHERE cr.recipient_email = ea.sender
                       AND cr.direction = 'inbound'
                       AND cr.subject = ea.subject
                   ) as has_watchdog_match
            FROM email_archive ea
            WHERE ea.file_path LIKE 'imap://%%'
            ORDER BY ea.sent_at DESC NULLS LAST
            LIMIT %s
        """, (limit,))

    rows = cur.fetchall()
    results = []
    for r in rows:
        row = dict(r)
        for k in ("received_at", "sent_at", "created_at"):
            if row.get(k):
                row[k] = str(row[k])
        results.append(row)

    cur.close()
    _put_conn(conn)

    return {"emails": results, "count": len(results)}


@app.get("/api/inbox/alerts")
async def inbox_alerts():
    """Active watchdog alerts — recent high-priority inbound communications."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT cr.id, cr.case_id, c.case_slug, c.case_name, c.case_number,
               cr.recipient as from_name, cr.recipient_email as from_email,
               cr.subject, LEFT(cr.body, 300) as body_preview,
               cr.sent_at as received_at, cr.created_at,
               e.is_critical, e.relevance as evidence_note
        FROM legal.correspondence cr
        JOIN legal.cases c ON c.id = cr.case_id
        LEFT JOIN legal.case_evidence e ON e.case_id = cr.case_id
            AND e.evidence_type = 'email'
            AND e.description ILIKE '%%' || LEFT(cr.subject, 30) || '%%'
        WHERE cr.direction = 'inbound'
        ORDER BY cr.sent_at DESC NULLS LAST
        LIMIT 20
    """)
    rows = cur.fetchall()
    alerts = []
    for r in rows:
        row = dict(r)
        for k in ("received_at", "created_at", "sent_at"):
            if row.get(k):
                row[k] = str(row[k])
        alerts.append(row)

    cur.close()
    _put_conn(conn)

    return {"alerts": alerts, "count": len(alerts)}


@app.get("/api/bridge/status")
async def bridge_status():
    """Email Bridge status — is it running and what's the latest ingestion?"""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE file_path LIKE 'imap://%%') as bridge_total,
            MAX(sent_at) FILTER (WHERE file_path LIKE 'imap://%%') as latest_email,
            COUNT(*) FILTER (WHERE file_path LIKE 'imap://%%' AND sent_at > NOW() - INTERVAL '1 hour') as last_hour,
            COUNT(*) FILTER (WHERE file_path LIKE 'imap://%%' AND sent_at > NOW() - INTERVAL '24 hours') as last_24h
        FROM email_archive
    """)
    row = dict(cur.fetchone())

    # Check if bridge process is running
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-f", "email_bridge.*--watch"],
            capture_output=True, text=True, timeout=5
        )
        row["bridge_running"] = result.returncode == 0
        row["bridge_pid"] = result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        row["bridge_running"] = False
        row["bridge_pid"] = None

    # Watchdog stats
    cur.execute("SELECT COUNT(*) as active_terms FROM legal.case_watchdog WHERE is_active = true")
    row["watchdog_terms"] = cur.fetchone()["active_terms"]

    for k in ("latest_email",):
        if row.get(k):
            row[k] = str(row[k])

    cur.close()
    _put_conn(conn)
    return row


@app.get("/", response_class=HTMLResponse)
async def root():
    """Fortress Legal CRM — standalone professional dashboard."""
    return CRM_HTML


# ═══════════════════════════════════════════════════════════════════════════════
# STANDALONE LEGAL CRM DASHBOARD HTML
# ═══════════════════════════════════════════════════════════════════════════════

CRM_HTML = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fortress Legal — Case Management</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,100..900;1,14..32,100..900&family=Crimson+Pro:ital,wght@0,400;0,500;0,600;0,700;0,800;0,900;1,400;1,500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --f:'Inter',system-ui,-apple-system,BlinkMacSystemFont,sans-serif;
  --serif:'Crimson Pro','Georgia','Times New Roman',serif;
  --mono:'SF Mono',ui-monospace,'Cascadia Code','Fira Code',Menlo,Consolas,monospace;
}
[data-theme="dark"]{
  --bg:#09090b;--surface:#111113;--surface2:#18181b;--surface3:#1f1f23;
  --tx:#fafafa;--tx2:#a1a1aa;--tx3:#6e6e77;
  --brd:rgba(255,255,255,.07);--brd2:rgba(255,255,255,.04);
  --accent:#3b82f6;--accent2:#60a5fa;--accent-bg:rgba(59,130,246,.1);--accent-brd:rgba(59,130,246,.25);
  --red:#ef4444;--red-bg:rgba(239,68,68,.1);--red-brd:rgba(239,68,68,.25);
  --amber:#f59e0b;--amber-bg:rgba(245,158,11,.1);--amber-brd:rgba(245,158,11,.25);
  --green:#22c55e;--green-bg:rgba(34,197,94,.1);--green-brd:rgba(34,197,94,.25);
  --blue:#3b82f6;--blue-bg:rgba(59,130,246,.1);--blue-brd:rgba(59,130,246,.25);
  --purple:#a855f7;--purple-bg:rgba(168,85,247,.1);--purple-brd:rgba(168,85,247,.25);
  --nav-bg:rgba(9,9,11,.85);
  --card-shadow:0 1px 3px rgba(0,0,0,.4);
  --card-hover:rgba(255,255,255,.04);
  --select-bg:#18181b;--select-tx:#fafafa;
  --toast-bg:#18181b;--toast-brd:rgba(255,255,255,.1);
}
[data-theme="light"]{
  --bg:#fafaf9;--surface:#fff;--surface2:#f4f4f5;--surface3:#e4e4e7;
  --tx:#18181b;--tx2:#52525b;--tx3:#a1a1aa;
  --brd:#e4e4e7;--brd2:#f4f4f5;
  --accent:#2563eb;--accent2:#3b82f6;--accent-bg:rgba(37,99,235,.06);--accent-brd:rgba(37,99,235,.2);
  --red:#dc2626;--red-bg:#fef2f2;--red-brd:#fecaca;
  --amber:#d97706;--amber-bg:#fffbeb;--amber-brd:#fde68a;
  --green:#16a34a;--green-bg:#f0fdf4;--green-brd:#bbf7d0;
  --blue:#2563eb;--blue-bg:#eff6ff;--blue-brd:#bfdbfe;
  --purple:#7c3aed;--purple-bg:#f5f3ff;--purple-brd:#ddd6fe;
  --nav-bg:rgba(250,250,249,.88);
  --card-shadow:0 1px 3px rgba(0,0,0,.06),0 0 0 1px rgba(0,0,0,.04);
  --card-hover:#f4f4f5;
  --select-bg:#fff;--select-tx:#18181b;
  --toast-bg:#fff;--toast-brd:#e4e4e7;
}
html{font-size:15px;background:var(--bg);-webkit-text-size-adjust:100%}
body{font-family:var(--f);color:var(--tx);line-height:1.55;
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;
  text-rendering:optimizeLegibility;font-kerning:normal;
  font-feature-settings:'kern' 1,'liga' 1,'calt' 1;
  min-height:100vh;transition:background .15s,color .15s}
::selection{background:rgba(59,130,246,.25)}
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(128,128,128,.2);border-radius:3px}
a{color:inherit;text-decoration:none}
button{font-family:var(--f)}

/* ── FORTRESS UNIFIED NAV ── */
.fn-bar{background:#0a0a0a;border-bottom:1px solid #1a1a1a;padding:0 16px;
  display:flex;align-items:center;height:36px;font-family:system-ui,-apple-system,sans-serif;
  position:sticky;top:0;z-index:9999;gap:0;flex-shrink:0;box-shadow:0 1px 3px rgba(0,0,0,.3)}
.fn-home{display:flex;align-items:center;gap:6px;color:#fff;text-decoration:none;
  font-weight:700;font-size:12px;letter-spacing:.03em;padding:6px 12px 6px 0;
  border-right:1px solid #222;margin-right:4px;white-space:nowrap;transition:color .15s}
.fn-home:hover{color:#4ade80}
.fn-home svg{opacity:.6}
.fn-links{display:flex;align-items:center;gap:0;overflow-x:auto;scrollbar-width:none;flex:1}
.fn-links::-webkit-scrollbar{display:none}
.fn-link{display:flex;align-items:center;gap:5px;padding:8px 12px;color:#888;
  text-decoration:none;font-size:11px;font-weight:500;white-space:nowrap;
  border-bottom:2px solid transparent;transition:all .15s}
.fn-link:hover{color:#fff;background:rgba(255,255,255,.04)}
.fn-link.fn-active{color:#fff;border-bottom-color:#4ade80}
.fn-link .fn-icon{font-size:13px;opacity:.5}
@media(max-width:768px){.fn-link span:not(.fn-icon){display:none}}

/* ── EMAIL INBOX ── */
.inbox-card{border:1px solid var(--border);border-radius:12px;background:var(--card);overflow:hidden}
.inbox-live-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-left:6px;vertical-align:middle}
.inbox-live-dot.live{background:var(--green);box-shadow:0 0 6px var(--green);animation:pulse-dot 2s infinite}
.inbox-live-dot.dead{background:var(--red);box-shadow:0 0 4px var(--red)}
@keyframes pulse-dot{0%,100%{opacity:1}50%{opacity:.4}}
.inbox-row{display:flex;align-items:flex-start;gap:10px;padding:10px 16px;border-bottom:1px solid var(--border);transition:background .15s}
.inbox-row:hover{background:var(--surface2)}
.inbox-row.alert{border-left:3px solid var(--red);background:color-mix(in srgb,var(--red) 5%,transparent)}
.inbox-row.alert:hover{background:color-mix(in srgb,var(--red) 10%,transparent)}
.inbox-icon{font-size:16px;flex-shrink:0;margin-top:2px}
.inbox-main{flex:1;min-width:0}
.inbox-from{font-weight:600;font-size:12px;color:var(--tx);margin-bottom:2px}
.inbox-subj{font-size:12px;color:var(--tx2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.inbox-preview{font-size:11px;color:var(--tx3);margin-top:2px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.inbox-meta{flex-shrink:0;text-align:right;font-size:10px;color:var(--tx3)}
.inbox-meta .case-tag{display:inline-block;padding:1px 6px;border-radius:4px;font-size:9px;font-weight:600;background:var(--red-bg);color:var(--red);margin-top:3px}
.inbox-empty{padding:24px;text-align:center;color:var(--tx3);font-size:13px}
.btn-xs{padding:3px 10px;border-radius:6px;font-size:11px;cursor:pointer;background:transparent;border:1px solid var(--border);color:var(--tx2);transition:all .15s}
.btn-xs:hover,.btn-xs.active{background:var(--surface2);color:var(--tx)}

/* ── TOAST NOTIFICATION SYSTEM ── */
.toast-container{position:fixed;top:56px;right:20px;z-index:999;display:flex;flex-direction:column;gap:8px;pointer-events:none}
.toast{pointer-events:auto;display:flex;align-items:center;gap:10px;padding:12px 18px;
  border-radius:10px;background:var(--toast-bg);border:1px solid var(--toast-brd);
  box-shadow:0 8px 30px rgba(0,0,0,.25);font-size:12px;font-weight:500;color:var(--tx);
  min-width:280px;max-width:420px;backdrop-filter:blur(12px);
  animation:toastIn .3s cubic-bezier(.16,1,.3,1)}
.toast.leaving{animation:toastOut .25s ease forwards}
.toast .t-icon{font-size:16px;flex-shrink:0}
.toast .t-msg{flex:1;line-height:1.4}
.toast .t-close{cursor:pointer;opacity:.5;font-size:14px;padding:2px 4px;flex-shrink:0}
.toast .t-close:hover{opacity:1}
.toast.t-success{border-color:var(--green-brd);background:var(--green-bg)}
.toast.t-success .t-icon{color:var(--green)}
.toast.t-error{border-color:var(--red-brd);background:var(--red-bg)}
.toast.t-error .t-icon{color:var(--red)}
.toast.t-info{border-color:var(--blue-brd);background:var(--blue-bg)}
.toast.t-info .t-icon{color:var(--blue)}
.toast.t-warning{border-color:var(--amber-brd);background:var(--amber-bg)}
.toast.t-warning .t-icon{color:var(--amber)}
@keyframes toastIn{from{opacity:0;transform:translateX(20px) scale(.96)}to{opacity:1;transform:none}}
@keyframes toastOut{to{opacity:0;transform:translateX(20px) scale(.96)}}

/* ── NAV ── */
.topbar{background:var(--nav-bg);backdrop-filter:saturate(180%) blur(20px);-webkit-backdrop-filter:saturate(180%) blur(20px);
  border-bottom:1px solid var(--brd);
  padding:0 24px;height:48px;display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:36px;z-index:100}
.topbar .brand-group{display:flex;align-items:center;gap:0}
.topbar .brand{font-weight:700;font-size:14px;letter-spacing:-.02em;display:flex;align-items:center;gap:8px;opacity:.9;transition:opacity .15s}
.topbar .brand:hover{opacity:1}
.topbar .brand svg{opacity:.7}
.topbar .nav-sep{opacity:.25;margin:0 10px;font-size:14px}
.topbar .nav-section{font-weight:600;font-size:13px;opacity:.65}
.topbar .right{display:flex;align-items:center;gap:10px;font-size:11px;color:var(--tx2)}
.topbar .status{display:flex;align-items:center;gap:5px}
.topbar .dot{width:6px;height:6px;border-radius:50%;background:var(--green);flex-shrink:0}
.topbar .dot.live{animation:pulse 2s ease infinite}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(34,197,94,.35)}50%{box-shadow:0 0 0 4px rgba(34,197,94,0)}}

/* ── Search bar ── */
.search-bar{position:relative;margin-left:12px}
.search-bar input{width:180px;padding:5px 10px 5px 28px;border-radius:7px;border:1px solid var(--brd);
  background:var(--surface);color:var(--tx);font-size:11px;font-family:var(--f);transition:all .15s;outline:none}
.search-bar input:focus{width:260px;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-bg)}
.search-bar input::placeholder{color:var(--tx3)}
.search-bar .s-icon{position:absolute;left:8px;top:50%;transform:translateY(-50%);font-size:12px;color:var(--tx3);pointer-events:none}
.search-bar .s-kbd{position:absolute;right:6px;top:50%;transform:translateY(-50%);font-size:9px;color:var(--tx3);
  border:1px solid var(--brd);border-radius:3px;padding:1px 4px;font-family:var(--mono);pointer-events:none}
.search-results{position:absolute;top:calc(100% + 6px);right:0;width:380px;max-height:360px;overflow-y:auto;
  background:var(--surface);border:1px solid var(--brd);border-radius:10px;
  box-shadow:0 12px 40px rgba(0,0,0,.3);display:none;z-index:300}
.search-results.open{display:block}
.sr-item{padding:10px 14px;border-bottom:1px solid var(--brd2);cursor:pointer;transition:background .1s}
.sr-item:hover{background:var(--card-hover)}
.sr-item:last-child{border-bottom:none}
.sr-type{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;padding:1px 6px;border-radius:4px;margin-right:6px}
.sr-text{font-size:12px;font-weight:500;color:var(--tx)}
.sr-meta{font-size:10px;color:var(--tx3);margin-top:2px}

.nav-btn{background:none;border:1px solid var(--brd);border-radius:6px;padding:4px 10px;
  cursor:pointer;font-size:11px;font-weight:500;color:var(--tx2);transition:all .15s}
.nav-btn:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-bg)}

/* ── LAYOUT ── */
.shell{max-width:1320px;margin:0 auto;padding:20px 24px 80px}

/* ── CASE HEADER ── */
.case-header{background:var(--surface);border:1px solid var(--brd);border-radius:12px;
  padding:22px 24px;margin-bottom:14px;box-shadow:var(--card-shadow)}
.case-header .case-title{font-family:var(--serif);font-size:21px;font-weight:700;
  color:var(--tx);letter-spacing:-.02em;margin-bottom:3px}
.case-header .case-number{font-size:11px;color:var(--tx2);font-weight:600;font-family:var(--mono);letter-spacing:.01em}
.case-header .case-meta{display:flex;gap:24px;margin-top:14px;flex-wrap:wrap}
.meta-item{font-size:11px}
.meta-item .label{color:var(--tx3);font-weight:700;text-transform:uppercase;letter-spacing:.07em;margin-bottom:2px;font-size:9.5px}
.meta-item .value{color:var(--tx);font-weight:600}

/* ── OPPOSING COUNSEL CARD ── */
.oc-card{background:var(--surface2);border:1px solid var(--brd);border-radius:8px;
  padding:10px 14px;margin-top:12px;display:flex;gap:20px;align-items:center;flex-wrap:wrap}
.oc-card .oc-label{font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--tx3)}
.oc-card .oc-value{font-size:11px;font-weight:600;color:var(--tx)}
.oc-card .oc-email{font-size:10px;color:var(--accent);font-family:var(--mono)}

/* ── CASE TABS ── */
.case-tabs{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap}
.case-tab{padding:7px 16px;border-radius:8px;border:1px solid var(--brd);
  background:var(--surface);font-size:11px;font-weight:600;cursor:pointer;
  transition:all .12s;color:var(--tx2);letter-spacing:.005em;box-shadow:var(--card-shadow)}
.case-tab:hover{border-color:var(--accent);color:var(--accent)}
.case-tab.active{background:var(--accent);color:#fff;border-color:var(--accent);box-shadow:0 2px 8px rgba(59,130,246,.3)}

/* ── ALERT ── */
.alert{border-radius:10px;padding:12px 16px;margin-bottom:14px;font-size:12px;
  display:flex;align-items:flex-start;gap:10px;line-height:1.5}
.alert.red{background:var(--red-bg);border:1px solid var(--red-brd);color:var(--red)}
.alert.amber{background:var(--amber-bg);border:1px solid var(--amber-brd);color:var(--amber)}
.alert.green{background:var(--green-bg);border:1px solid var(--green-brd);color:var(--green)}
.alert .icon{font-size:16px;flex-shrink:0;margin-top:1px}
.alert strong{font-weight:700}

/* ── GRID ── */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-bottom:14px}
@media(max-width:1000px){.grid3{grid-template-columns:1fr 1fr}}
@media(max-width:860px){.grid2,.grid3{grid-template-columns:1fr}}

/* ── CARD ── */
.card{background:var(--surface);border:1px solid var(--brd);border-radius:12px;
  overflow:hidden;box-shadow:var(--card-shadow);transition:background .15s}
.card-head{padding:12px 16px 10px;border-bottom:1px solid var(--brd2);
  display:flex;align-items:center;justify-content:space-between}
.card-head h3{font-size:10.5px;font-weight:800;color:var(--tx2);text-transform:uppercase;letter-spacing:.07em}
.card-head .badge{font-size:10px;font-weight:700;padding:2px 8px;border-radius:100px}
.badge-red{background:var(--red-bg);color:var(--red)}
.badge-amber{background:var(--amber-bg);color:var(--amber)}
.badge-green{background:var(--green-bg);color:var(--green)}
.badge-blue{background:var(--blue-bg);color:var(--blue)}
.badge-purple{background:var(--purple-bg);color:var(--purple)}
.card-body{padding:12px 16px}

/* ── SKELETON LOADING ── */
.skeleton{background:linear-gradient(90deg,var(--surface2) 25%,var(--surface3) 50%,var(--surface2) 75%);
  background-size:200% 100%;animation:shimmer 1.5s infinite;border-radius:6px}
@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}
.skel-line{height:12px;margin-bottom:8px;border-radius:4px}
.skel-line:last-child{width:60%}

/* ── DEADLINE ROW ── */
.dl-row{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--brd2)}
.dl-row:last-child{border-bottom:none}
.dl-desc{font-size:12px;font-weight:600;flex:1;color:var(--tx)}
.dl-date{font-size:10px;color:var(--tx2);font-weight:600;min-width:80px;text-align:right;font-family:var(--mono)}
.dl-badge{font-size:9px;font-weight:700;padding:2px 7px;border-radius:5px;margin-left:8px;white-space:nowrap;text-transform:uppercase;letter-spacing:.02em}

/* ── ACTION ROW ── */
.act-row{display:flex;align-items:flex-start;gap:10px;padding:7px 0;border-bottom:1px solid var(--brd2)}
.act-row:last-child{border-bottom:none}
.act-check{width:15px;height:15px;border-radius:4px;border:1.5px solid var(--tx3);flex-shrink:0;margin-top:2px;
  display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;font-weight:700}
.act-check.done{background:var(--green);border-color:var(--green)}
.act-check.overdue{background:var(--red);border-color:var(--red)}
.act-text{font-size:12px;line-height:1.45;color:var(--tx)}
.act-type{font-size:9px;color:var(--tx3);font-weight:700;text-transform:uppercase;letter-spacing:.05em}

/* ── CORRESPONDENCE / FILING ROW ── */
.corr-row{padding:9px 0;border-bottom:1px solid var(--brd2)}
.corr-row:last-child{border-bottom:none}
.corr-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:2px}
.corr-subject{font-size:12px;font-weight:600;color:var(--tx);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.corr-meta{font-size:10px;color:var(--tx3);line-height:1.5}
.corr-status{font-size:9px;font-weight:700;padding:2px 7px;border-radius:5px;text-transform:uppercase;flex-shrink:0;margin-left:8px}

/* ── DOCUMENTS ── */
.doc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(185px,1fr));gap:10px;padding:12px 16px}
.doc-card{border:1px solid var(--brd);border-radius:10px;padding:14px;cursor:pointer;
  transition:all .15s;background:var(--surface2)}
.doc-card:hover{border-color:var(--accent);transform:translateY(-1px);box-shadow:0 4px 12px rgba(59,130,246,.12)}
.doc-card .doc-icon{font-size:22px;margin-bottom:5px}
.doc-card .doc-name{font-size:11px;font-weight:600;color:var(--tx);margin-bottom:2px;line-height:1.35}
.doc-card .doc-detail{font-size:10px;color:var(--tx3)}

/* ── TIMELINE ── */
.tl-item{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--brd2);position:relative}
.tl-item:last-child{border-bottom:none}
.tl-icon{width:28px;height:28px;border-radius:7px;display:flex;align-items:center;justify-content:center;
  font-size:13px;flex-shrink:0}
.tl-icon.filing{background:var(--blue-bg);color:var(--blue)}
.tl-icon.correspondence{background:var(--green-bg);color:var(--green)}
.tl-icon.action{background:var(--amber-bg);color:var(--amber)}
.tl-icon.action_done{background:var(--green-bg);color:var(--green)}
.tl-icon.upload{background:var(--purple-bg);color:var(--purple)}
.tl-icon.evidence{background:var(--red-bg);color:var(--red)}
.tl-body{flex:1;min-width:0}
.tl-summary{font-size:12px;font-weight:600;color:var(--tx);line-height:1.35}
.tl-detail{font-size:10px;color:var(--tx3);margin-top:1px}
.tl-time{font-size:9.5px;color:var(--tx3);font-family:var(--mono);white-space:nowrap;flex-shrink:0}

/* ── DRAG & DROP UPLOAD ZONE ── */
.upload-zone{border:2px dashed var(--brd);border-radius:10px;padding:20px;text-align:center;
  transition:all .15s;cursor:pointer;margin:0 16px 12px}
.upload-zone.drag-over{border-color:var(--accent);background:var(--accent-bg)}
.upload-zone .uz-icon{font-size:28px;opacity:.4;margin-bottom:4px}
.upload-zone .uz-text{font-size:11px;color:var(--tx3);font-weight:500}
.upload-zone .uz-text strong{color:var(--accent);font-weight:700}
.upload-controls{padding:0 16px 12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.upload-controls select,.upload-controls input[type=text]{font-size:11px;padding:6px 10px;border-radius:7px;
  border:1px solid var(--brd);background:var(--surface);color:var(--tx);font-family:var(--f);outline:none;transition:border .15s}
.upload-controls select:focus,.upload-controls input:focus{border-color:var(--accent)}
.upload-controls input[type=text]{flex:1;min-width:100px}

/* ── DOCUMENT VIEWER (MODAL) ── */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.65);backdrop-filter:blur(4px);z-index:200;
  display:none;align-items:center;justify-content:center;padding:20px;animation:fadeIn .15s ease}
.modal-overlay.open{display:flex}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
.modal{background:#fff;border-radius:14px;max-width:850px;width:100%;
  max-height:92vh;display:flex;flex-direction:column;
  box-shadow:0 25px 60px rgba(0,0,0,.5);animation:modalIn .2s cubic-bezier(.16,1,.3,1)}
@keyframes modalIn{from{opacity:0;transform:scale(.97) translateY(8px)}to{opacity:1;transform:none}}
.modal-top{padding:14px 24px;border-bottom:1px solid #e5e5e5;
  display:flex;align-items:center;justify-content:space-between;flex-shrink:0;background:#fafafa;border-radius:14px 14px 0 0}
.modal-top h2{font-family:var(--serif);font-size:16px;font-weight:700;color:#000;letter-spacing:-.01em}
.modal-top .close-btn{width:28px;height:28px;border-radius:7px;border:1px solid #ddd;
  background:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;
  font-size:16px;color:#666;transition:.12s}
.modal-top .close-btn:hover{background:#f0f0f0;color:#333}
.modal-actions{display:flex;gap:8px;padding:10px 24px;border-bottom:1px solid #eee;background:#fafafa;flex-wrap:wrap}
.modal-actions button{padding:7px 16px;border-radius:7px;font-size:11px;font-weight:700;
  cursor:pointer;border:1px solid #ddd;background:#fff;color:#222;transition:.12s;font-family:var(--f);letter-spacing:.01em}
.modal-actions button:hover{background:#f0f0f0}
.modal-actions button.primary{background:#18181b;color:#fff;border-color:#18181b}
.modal-actions button.primary:hover{background:#333}
.modal-actions button.accent{background:#2563eb;color:#fff;border-color:#2563eb}
.modal-actions button.accent:hover{background:#3b82f6}
.modal-actions button.success{background:#16a34a;color:#fff;border-color:#16a34a}
.modal-actions button.success:hover{background:#22c55e}
.modal-actions .email-status{font-size:10px;color:#888;align-self:center;margin-left:auto}
.modal-content{flex:1;overflow-y:auto;padding:0;background:#fff}

/* ── COURT DOCUMENT RENDER (page simulation) ── */
.page-frame{max-width:680px;margin:40px auto;padding:60px 72px;
  background:#fff;color:#000;font-family:var(--serif);font-size:15px;line-height:1.8;
  min-height:800px;box-shadow:0 1px 6px rgba(0,0,0,.06);border:1px solid #e5e5e5;
  white-space:pre-wrap;word-wrap:break-word;
  text-rendering:optimizeLegibility;font-kerning:normal;
  -webkit-font-smoothing:auto;-moz-osx-font-smoothing:auto;
  font-feature-settings:'kern' 1,'liga' 1,'onum' 1}
.page-frame .court-header{text-align:center;font-size:14px;font-weight:700;
  letter-spacing:.03em;line-height:1.55;margin-bottom:24px;
  border-bottom:2.5px solid #000;padding-bottom:14px;text-transform:uppercase}
.page-frame .doc-heading{text-align:center;font-weight:800;font-size:16px;
  text-transform:uppercase;letter-spacing:.06em;margin:28px 0 20px;
  text-decoration:underline;text-underline-offset:5px;text-decoration-thickness:2px}
.page-frame .section-title{font-weight:800;font-size:14px;text-transform:uppercase;
  letter-spacing:.05em;margin:24px 0 8px;color:#000}
.page-frame .defense-title{font-weight:700;font-size:13.5px;margin:18px 0 6px;
  text-decoration:underline;text-underline-offset:3px;text-decoration-thickness:1.5px}
.page-frame .paragraph{text-indent:40px;margin:10px 0}
.page-frame .sig-line{border-bottom:1.5px solid #000;width:300px;margin:32px 0 4px}
.page-frame .sig-name{font-weight:700}
.page-frame .sig-detail{font-size:13.5px;color:#222;line-height:1.5}
.page-frame .service-block{margin-top:32px;padding-top:16px;border-top:1px solid #999;page-break-inside:avoid}
.page-frame .meta-footer{margin-top:36px;padding-top:12px;border-top:1px solid #ccc;
  font-family:var(--f);font-size:9px;color:#888;letter-spacing:.02em;font-weight:500}

/* ── GENERATE BAR ── */
.gen-bar{background:var(--surface);border:1px solid var(--brd);border-radius:10px;
  padding:14px 18px;margin-bottom:14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;box-shadow:var(--card-shadow)}
.gen-bar label{font-size:10.5px;font-weight:700;color:var(--tx2);text-transform:uppercase;letter-spacing:.05em}
.gen-bar select{padding:6px 12px;border-radius:7px;border:1px solid var(--brd);
  font-size:11px;font-weight:600;background:var(--select-bg);color:var(--select-tx);min-width:160px;font-family:var(--f);outline:none}
.gen-bar select:focus{border-color:var(--accent)}
.gen-bar button,.btn-accent,.btn-outline{padding:7px 16px;border-radius:7px;border:none;
  font-size:11px;font-weight:700;cursor:pointer;transition:all .12s;font-family:var(--f);letter-spacing:.01em}
.btn-accent{background:var(--accent);color:#fff;border:1px solid transparent}
.btn-accent:hover{filter:brightness(1.1)}
.btn-accent:disabled{opacity:.5;cursor:not-allowed}
.btn-outline{background:transparent;color:var(--tx2);border:1px solid var(--brd)}
.btn-outline:hover{background:var(--surface2);border-color:var(--tx3);color:var(--tx)}

/* ── PRINT ── */
@media print{
  .topbar,.case-tabs,.gen-bar,.modal-top,.modal-actions,.card,.alert,.shell,.toast-container{display:none!important}
  body{background:#fff!important;color:#000!important}
  .modal-overlay.open{position:static;background:none!important;padding:0;display:block!important}
  .modal{max-height:none!important;box-shadow:none!important;border-radius:0!important;border:none!important}
  .modal-content{padding:0!important;overflow:visible!important}
  .page-frame{box-shadow:none!important;border:none!important;margin:0!important;
    padding:0.75in 1in!important;max-width:100%!important;font-size:12pt!important;line-height:1.7!important}
  .page-frame .meta-footer{display:none!important}
}
@media(max-width:640px){
  .shell{padding:12px}
  .case-header{padding:16px}
  .page-frame{padding:24px;margin:12px}
  .topbar{padding:0 12px}
  .search-bar input{width:100px}
  .search-bar input:focus{width:160px}
}
@keyframes fadeUp{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.card,.case-header,.gen-bar{animation:fadeUp .3s ease both}
</style>
</head>
<body>

<!-- ─── FORTRESS UNIFIED NAV ─── -->
<div class="fn-bar">
  <a href="http://192.168.0.100:9800" class="fn-home">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
      <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>
    </svg>
    FORTRESS PRIME
  </a>
  <div class="fn-links">
    <a href="http://192.168.0.100:9800" class="fn-link"><span class="fn-icon">&#9733;</span><span>Command Center</span></a>
    <a href="http://192.168.0.100:9878" class="fn-link fn-active"><span class="fn-icon">&#9878;</span><span>Legal CRM</span></a>
    <a href="http://192.168.0.100:9876" class="fn-link"><span class="fn-icon">&#9881;</span><span>System Health</span></a>
    <a href="http://192.168.0.100:9877" class="fn-link"><span class="fn-icon">&#9783;</span><span>Classifier</span></a>
    <a href="http://192.168.0.100:3000" class="fn-link"><span class="fn-icon">&#9776;</span><span>Grafana</span></a>
    <a href="http://192.168.0.100:8888" class="fn-link"><span class="fn-icon">&#9638;</span><span>Portainer</span></a>
    <a href="http://192.168.0.100:8080" class="fn-link"><span class="fn-icon">&#9798;</span><span>Mission Control</span></a>
  </div>
</div>

<!-- ─── TOASTS ─── -->
<div class="toast-container" id="toastContainer"></div>

<!-- ─── TOP BAR ─── -->
<div class="topbar">
  <div class="brand-group">
    <a href="http://192.168.0.100:9800" class="brand">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
      Fortress Prime
    </a>
    <span class="nav-sep">/</span>
    <span class="nav-section">Legal CRM</span>
  </div>
  <div class="right">
    <div class="status"><span class="dot live" id="statusDot"></span><span id="statusText">Connecting...</span></div>
    <div class="search-bar">
      <span class="s-icon">&#128269;</span>
      <input type="text" id="searchInput" placeholder="Search case data..." autocomplete="off">
      <span class="s-kbd" id="searchKbd">/</span>
      <div class="search-results" id="searchResults"></div>
    </div>
    <span id="clock" style="font-family:var(--mono);font-size:10px;opacity:.5"></span>
    <button class="nav-btn" onclick="toggleTheme()" title="Toggle theme"><span id="themeIcon">&#9789;</span></button>
  </div>
</div>

<!-- ─── MAIN SHELL ─── -->
<div class="shell">

  <!-- CASE TABS -->
  <div class="case-tabs" id="caseTabs"></div>

  <!-- ALERT BANNER -->
  <div id="alertBanner"></div>

  <!-- EMAIL INBOX / BRIDGE STATUS -->
  <div class="card inbox-card" id="inboxCard" style="margin-bottom:14px">
    <div class="card-head">
      <h3>Email Inbox <span class="inbox-live-dot" id="bridgeDot" title="Bridge status"></span></h3>
      <div style="display:flex;gap:8px;align-items:center">
        <button class="btn-outline btn-xs" id="inboxFilterAll" onclick="loadInbox(false)" style="font-size:11px">All Emails</button>
        <button class="btn-outline btn-xs active" id="inboxFilterWatch" onclick="loadInbox(true)" style="font-size:11px;border-color:var(--red);color:var(--red)">Watchdog Alerts</button>
        <span class="badge badge-red" id="inboxAlertBadge" style="font-size:11px">0</span>
      </div>
    </div>
    <div class="card-body" id="inboxList" style="max-height:320px;overflow-y:auto">
      <div class="skeleton skel-line"></div><div class="skeleton skel-line"></div>
    </div>
    <div class="inbox-status" id="inboxStatus" style="padding:6px 16px;font-size:11px;color:var(--tx3);border-top:1px solid var(--border)">
      Bridge: checking...
    </div>
  </div>

  <!-- CASE HEADER -->
  <div class="case-header" id="caseHeader">
    <div class="case-title" id="caseTitle"><div class="skeleton skel-line" style="width:60%;height:22px"></div></div>
    <div class="case-number" id="caseNumber"><div class="skeleton skel-line" style="width:40%;height:11px;margin-top:6px"></div></div>
    <div class="case-meta" id="caseMeta">
      <div class="skeleton skel-line" style="width:100%;height:30px;margin-top:14px"></div>
    </div>
    <div id="ocCard"></div>
  </div>

  <!-- GENERATE BAR -->
  <div class="gen-bar">
    <label>Generate:</label>
    <select id="templateSelect"></select>
    <button class="btn-accent" onclick="generateDoc()">Generate &amp; Preview</button>
    <button class="btn-outline" onclick="generateDoc('answer_complaint')">Answer to Complaint</button>
    <button class="btn-outline" onclick="generateDoc('motion_extension')">Motion for Extension</button>
    <button class="btn-outline" onclick="generateDoc('attorney_briefing')">Attorney Briefing</button>
  </div>

  <!-- MAIN GRID: Deadlines + Actions | Documents + Correspondence -->
  <div class="grid2">
    <div>
      <div class="card" style="margin-bottom:14px">
        <div class="card-head"><h3>Court Deadlines</h3><span class="badge badge-red" id="dlBadge">0</span></div>
        <div class="card-body" id="deadlineList"><div class="skeleton skel-line"></div><div class="skeleton skel-line"></div><div class="skeleton skel-line"></div></div>
      </div>
      <div class="card">
        <div class="card-head"><h3>Action Checklist</h3><span class="badge badge-amber" id="actBadge">0</span></div>
        <div class="card-body" id="actionList"><div class="skeleton skel-line"></div><div class="skeleton skel-line"></div><div class="skeleton skel-line"></div></div>
      </div>
    </div>
    <div>
      <div class="card" style="margin-bottom:14px">
        <div class="card-head"><h3>Filed &amp; Draft Documents</h3><span class="badge badge-blue" id="docBadge">0</span></div>
        <div class="doc-grid" id="docGrid"><div class="skeleton skel-line" style="height:60px"></div></div>
      </div>
      <div class="card">
        <div class="card-head"><h3>Correspondence Log</h3><span class="badge badge-green" id="corrBadge">0</span></div>
        <div class="card-body" id="corrList"><div class="skeleton skel-line"></div><div class="skeleton skel-line"></div></div>
      </div>
    </div>
  </div>

  <!-- FILINGS + UPLOADS + TIMELINE -->
  <div class="grid3">
    <div class="card">
      <div class="card-head"><h3>Court Filings</h3><span class="badge badge-blue" id="filingBadge">0</span></div>
      <div class="card-body" id="filingList"><div class="skeleton skel-line"></div><div class="skeleton skel-line"></div></div>
    </div>
    <div class="card">
      <div class="card-head"><h3>Document Vault</h3><span class="badge badge-purple" id="uploadBadge">0</span></div>
      <div class="card-body" id="uploadList" style="padding-bottom:0"><div class="skeleton skel-line"></div></div>
      <div class="upload-zone" id="uploadZone">
        <div class="uz-icon">&#128194;</div>
        <div class="uz-text">Drop files here or <strong>click to browse</strong></div>
        <input type="file" id="uploadFile" accept=".pdf,.jpg,.jpeg,.png,.tiff,.doc,.docx" style="display:none" multiple>
      </div>
      <div class="upload-controls" id="uploadControls" style="display:none">
        <select id="uploadType" onchange="toggleFilingSelect()">
          <option value="stamped_copy">Stamped Court Copy</option>
          <option value="evidence">Evidence</option>
          <option value="correspondence">Correspondence</option>
          <option value="receipt">Receipt</option>
          <option value="general" selected>General</option>
        </select>
        <select id="filingSelect" style="display:none"><option value="">Link to filing...</option></select>
        <input type="text" id="uploadDesc" placeholder="Description (optional)">
        <button class="btn-accent" id="uploadBtn" onclick="submitUpload()">Upload</button>
      </div>
    </div>
    <div class="card">
      <div class="card-head"><h3>Activity Timeline</h3><span class="badge" style="background:var(--surface2);color:var(--tx2)" id="tlBadge">0</span></div>
      <div class="card-body" id="timelineList" style="max-height:500px;overflow-y:auto">
        <div class="skeleton skel-line"></div><div class="skeleton skel-line"></div><div class="skeleton skel-line"></div>
      </div>
    </div>
  </div>

</div>

<!-- ─── DOCUMENT VIEWER MODAL ─── -->
<div class="modal-overlay" id="docModal">
  <div class="modal">
    <div class="modal-top">
      <h2 id="modalTitle">Document Preview</h2>
      <button class="close-btn" onclick="closeDoc()" title="Close">&times;</button>
    </div>
    <div class="modal-actions">
      <button class="accent" onclick="downloadPdf(this)">&#128196; Download PDF</button>
      <button class="success" onclick="emailPdf(this)">&#9993; Email PDF</button>
      <button class="primary" onclick="printDoc()">&#9113; Print</button>
      <button onclick="copyDoc()">&#128203; Copy Text</button>
      <span class="email-status" id="emailStatus"></span>
    </div>
    <div class="modal-content">
      <div class="page-frame" id="docBody"></div>
    </div>
  </div>
</div>

<script>
/* ═══════════════════════════════════════════════════════════════════════
   FORTRESS LEGAL CRM v2.0 — Production Client Controller
   ═══════════════════════════════════════════════════════════════════════ */

const API = '';
let _cases = [];
let _activeSlug = '';
let _currentDoc = '';
let _filings = [];
let _refreshTimer = null;

// ── Helpers ──────────────────────────────────────────────────────────

function esc(s){const d=document.createElement('div');d.textContent=s||'';return d.innerHTML}
function fmtDate(d){if(!d)return'\u2014';const dt=new Date(d+'T00:00:00');return dt.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})}
function fmtTime(d){if(!d)return'';try{const dt=new Date(d);return dt.toLocaleDateString('en-US',{month:'short',day:'numeric'})+' '+dt.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'})}catch(e){return d}}
function urgColor(u){return{overdue:'var(--red)',critical:'var(--red)',urgent:'var(--amber)',warning:'var(--amber)',normal:'var(--green)'}[u]||'var(--tx3)'}
function urgBg(u){return{overdue:'var(--red-bg)',critical:'var(--red-bg)',urgent:'var(--amber-bg)',warning:'var(--amber-bg)',normal:'var(--green-bg)'}[u]||'var(--surface2)'}

// ── Toast Notification System ────────────────────────────────────────

function toast(msg, type='info', duration=4000){
  const icons = {success:'\u2713',error:'\u2717',warning:'\u26A0',info:'\u2139'};
  const container = document.getElementById('toastContainer');
  const el = document.createElement('div');
  el.className = `toast t-${type}`;
  el.innerHTML = `<span class="t-icon">${icons[type]||icons.info}</span><span class="t-msg">${esc(msg)}</span><span class="t-close" onclick="this.parentElement.classList.add('leaving');setTimeout(()=>this.parentElement.remove(),250)">\u2715</span>`;
  container.appendChild(el);
  if(duration > 0) setTimeout(()=>{if(el.parentElement){el.classList.add('leaving');setTimeout(()=>el.remove(),250)}},duration);
}

// ── Theme Toggle ────────────────────────────────────────────────────

function toggleTheme(){
  const html=document.documentElement;
  const next=html.getAttribute('data-theme')==='dark'?'light':'dark';
  html.setAttribute('data-theme',next);
  localStorage.setItem('fortress-theme',next);
  document.getElementById('themeIcon').innerHTML=next==='dark'?'&#9789;':'&#9788;';
}
(function(){const s=localStorage.getItem('fortress-theme');if(s){document.documentElement.setAttribute('data-theme',s);document.getElementById('themeIcon').innerHTML=s==='dark'?'&#9789;':'&#9788;'}})();

// ── Clock ────────────────────────────────────────────────────────────

setInterval(()=>{document.getElementById('clock').textContent=new Date().toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',second:'2-digit'})},1000);

// ── Search ───────────────────────────────────────────────────────────

let _searchTimeout = null;
const searchInput = document.getElementById('searchInput');
const searchResults = document.getElementById('searchResults');

searchInput.addEventListener('input', () => {
  clearTimeout(_searchTimeout);
  const q = searchInput.value.trim();
  if(q.length < 2){ searchResults.classList.remove('open'); return; }
  _searchTimeout = setTimeout(async () => {
    try {
      const r = await fetch(API + '/api/search?q=' + encodeURIComponent(q) + (_activeSlug ? '&case_slug=' + _activeSlug : ''));
      const d = await r.json();
      if(!d.results || !d.results.length){
        searchResults.innerHTML = '<div style="padding:14px;font-size:12px;color:var(--tx3)">No results found</div>';
      } else {
        const typeColors = {action:'var(--amber)',evidence:'var(--red)',correspondence:'var(--green)',filing:'var(--blue)'};
        searchResults.innerHTML = d.results.map(r =>
          `<div class="sr-item"><span class="sr-type" style="color:${typeColors[r.type]||'var(--tx3)'}">${r.type}</span><span class="sr-text">${esc((r.text||'').substring(0,60))}</span><div class="sr-meta">${r.subtype||''} \u00B7 ${r.status||''}</div></div>`
        ).join('');
      }
      searchResults.classList.add('open');
    } catch(e){ console.error(e) }
  }, 300);
});
searchInput.addEventListener('blur', () => setTimeout(()=>searchResults.classList.remove('open'), 200));

// ── Keyboard Shortcuts ───────────────────────────────────────────────

document.addEventListener('keydown', e => {
  if(e.key === 'Escape'){ closeDoc(); searchResults.classList.remove('open'); searchInput.blur(); }
  if(e.key === '/' && !e.ctrlKey && !e.metaKey && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA'){
    e.preventDefault(); searchInput.focus();
  }
});

// ── Load Overview ────────────────────────────────────────────────────

// ── Email Inbox ─────────────────────────────────────────────────────

let _inboxWatchdogOnly = true;

async function loadInbox(watchdogOnly) {
  if (watchdogOnly !== undefined) _inboxWatchdogOnly = watchdogOnly;
  const allBtn = document.getElementById('inboxFilterAll');
  const watchBtn = document.getElementById('inboxFilterWatch');
  if (_inboxWatchdogOnly) {
    watchBtn.classList.add('active'); allBtn.classList.remove('active');
  } else {
    allBtn.classList.add('active'); watchBtn.classList.remove('active');
  }

  const list = document.getElementById('inboxList');
  try {
    const url = _inboxWatchdogOnly
      ? `${API}/api/inbox?watchdog_only=true&limit=30`
      : `${API}/api/inbox?limit=30`;
    const r = await fetch(url);
    const data = await r.json();
    const emails = data.emails || [];

    document.getElementById('inboxAlertBadge').textContent = emails.filter(e => e.is_critical || e.has_watchdog_match || e.tag === 'watchdog_match').length;

    if (!emails.length) {
      list.innerHTML = '<div class="inbox-empty">No emails to display</div>';
      return;
    }

    list.innerHTML = emails.map(em => {
      const isAlert = em.is_critical || em.has_watchdog_match || em.tag === 'watchdog_match';
      const from = em.from_name || em.from_email || '';
      const subj = em.subject || '(no subject)';
      const body = em.body_preview || em.body || '';
      const time = fmtTime(em.received_at);
      const caseName = em.case_name ? `<div class="case-tag">${esc(em.case_name.split(',')[0])}</div>` : '';
      const icon = isAlert ? '&#9888;' : em.direction === 'inbound' ? '&#128229;' : '&#128232;';

      return `<div class="inbox-row ${isAlert ? 'alert' : ''}">
        <div class="inbox-icon">${icon}</div>
        <div class="inbox-main">
          <div class="inbox-from">${esc(from)}</div>
          <div class="inbox-subj">${esc(subj)}</div>
          ${body ? `<div class="inbox-preview">${esc(body.substring(0, 200))}</div>` : ''}
        </div>
        <div class="inbox-meta">${time}${caseName}</div>
      </div>`;
    }).join('');
  } catch(e) {
    list.innerHTML = '<div class="inbox-empty">Failed to load inbox</div>';
  }
}

async function loadBridgeStatus() {
  const dot = document.getElementById('bridgeDot');
  const status = document.getElementById('inboxStatus');
  try {
    const r = await fetch(API + '/api/bridge/status');
    const data = await r.json();
    dot.className = 'inbox-live-dot ' + (data.bridge_running ? 'live' : 'dead');
    const parts = [];
    if (data.bridge_running) parts.push('Bridge: ACTIVE (PID ' + data.bridge_pid + ')');
    else parts.push('Bridge: OFFLINE');
    parts.push(data.bridge_total + ' emails ingested');
    if (data.latest_email) parts.push('Latest: ' + fmtTime(data.latest_email));
    parts.push(data.last_24h + ' in 24h');
    parts.push(data.watchdog_terms + ' watchdog terms');
    status.textContent = parts.join(' | ');
  } catch(e) {
    dot.className = 'inbox-live-dot dead';
    status.textContent = 'Bridge: error checking status';
  }
}

async function loadOverview(silent){
  try {
    const r = await fetch(API + '/api/crm/overview');
    const data = await r.json();
    _cases = data.cases || [];
    document.getElementById('statusDot').className = 'dot live';
    document.getElementById('statusText').textContent = _cases.length + ' Active Case' + (_cases.length!==1?'s':'');

    const tabs = document.getElementById('caseTabs');
    tabs.innerHTML = '';
    _cases.forEach((c,i)=>{
      const tab = document.createElement('div');
      tab.className = 'case-tab' + (i===0&&!_activeSlug?' active':(c.case_slug===_activeSlug?' active':''));
      tab.textContent = c.case_number + ' \u2014 ' + c.case_name.substring(0,40) + (c.case_name.length>40?'\u2026':'');
      tab.onclick = () => selectCase(c.case_slug);
      tabs.appendChild(tab);
    });

    if(!_activeSlug && _cases.length) _activeSlug = _cases[0].case_slug;
    if(_activeSlug) loadCase(_activeSlug);
    if(!silent) toast('Dashboard loaded', 'success', 2000);
  } catch(e){
    document.getElementById('statusDot').className = 'dot';
    document.getElementById('statusDot').style.background = 'var(--red)';
    document.getElementById('statusText').textContent = 'API Unreachable';
    if(!silent) toast('Cannot reach Legal CRM API', 'error');
  }
}

function selectCase(slug){
  _activeSlug = slug;
  document.querySelectorAll('.case-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.case-tab').forEach(t => {
    if(t.textContent.includes(_cases.find(c => c.case_slug === slug)?.case_number || '')) t.classList.add('active');
  });
  loadCase(slug);
}

// ── Load Case Detail ─────────────────────────────────────────────────

async function loadCase(slug){
  const c = _cases.find(x => x.case_slug === slug);
  if(!c) return;

  document.getElementById('caseTitle').textContent = c.case_name;
  document.getElementById('caseNumber').textContent = 'Civil Action No. ' + c.case_number + '  \u2022  ' + (c.court || '');

  const meta = document.getElementById('caseMeta');
  const role = c.our_role === 'defendant' ? 'Defendant (Pro Se)' : 'Plaintiff / Creditor';
  const critDays = c.days_remaining;
  const critColor = critDays <= 0 ? 'var(--red)' : critDays <= 7 ? 'var(--amber)' : 'var(--green)';
  const daysLabel = critDays <= 0 ? 'OVERDUE' : critDays + ' day' + (critDays!==1?'s':'') + ' remaining';
  meta.innerHTML = `
    <div class="meta-item"><div class="label">Judge</div><div class="value">${esc(c.judge || 'Not assigned')}</div></div>
    <div class="meta-item"><div class="label">Our Role</div><div class="value">${esc(role)}</div></div>
    <div class="meta-item"><div class="label">Case Type</div><div class="value" style="text-transform:capitalize">${esc(c.case_type)}</div></div>
    <div class="meta-item"><div class="label">Critical Deadline</div><div class="value" style="color:${critColor}">${fmtDate(c.critical_date)} &mdash; ${daysLabel}</div></div>
    <div class="meta-item"><div class="label">Evidence</div><div class="value">${c.evidence_count}</div></div>
    <div class="meta-item"><div class="label">Filings</div><div class="value">${c.filing_count || 0}</div></div>
    <div class="meta-item"><div class="label">Uploads</div><div class="value">${c.upload_count || 0}</div></div>
  `;

  // Opposing counsel card
  const oc = document.getElementById('ocCard');
  if(c.opposing_counsel || c.plan_admin){
    const name = c.opposing_counsel || c.plan_admin || '';
    const email = c.plan_admin_email || '';
    oc.innerHTML = `<div class="oc-card">
      <div><div class="oc-label">Opposing Counsel</div><div class="oc-value">${esc(name)}</div></div>
      ${email ? `<div><div class="oc-label">Email</div><div class="oc-email">${esc(email)}</div></div>` : ''}
      ${c.plan_admin_address ? `<div><div class="oc-label">Address</div><div class="oc-value" style="font-size:10px">${esc(c.plan_admin_address)}</div></div>` : ''}
    </div>`;
  } else { oc.innerHTML = ''; }

  // Alert banner
  const banner = document.getElementById('alertBanner');
  if(critDays <= 0){
    banner.innerHTML = `<div class="alert red"><span class="icon">\u26A0</span><div><strong>DEADLINE PASSED</strong> \u2014 ${esc(c.critical_note||'Immediate court action required.')}</div></div>`;
  } else if(critDays <= 7){
    banner.innerHTML = `<div class="alert amber"><span class="icon">\u26A0</span><div><strong>${critDays} DAY${critDays!==1?'S':''} REMAINING</strong> \u2014 ${esc(c.critical_note||'File response before deadline.')}</div></div>`;
  } else {
    banner.innerHTML = c.critical_note ? `<div class="alert green"><span class="icon">\u2713</span><div>${esc(c.critical_note)}</div></div>` : '';
  }

  // Parallel data load (7 endpoints)
  const [dlRes,corrRes,docRes,caseRes,filingsRes,uploadsRes,tlRes] = await Promise.all([
    fetch(API+'/api/cases/'+slug+'/deadlines').then(r=>r.json()),
    fetch(API+'/api/cases/'+slug+'/correspondence').then(r=>r.json()),
    fetch(API+'/api/cases/'+slug+'/documents').then(r=>r.json()),
    fetch(API+'/api/cases/'+slug).then(r=>r.json()),
    fetch(API+'/api/cases/'+slug+'/filings').then(r=>r.json()).catch(()=>[]),
    fetch(API+'/api/cases/'+slug+'/uploads').then(r=>r.json()).catch(()=>[]),
    fetch(API+'/api/cases/'+slug+'/timeline?limit=30').then(r=>r.json()).catch(()=>[]),
  ]);

  renderDeadlines(dlRes.deadlines||dlRes||[]);
  renderCorrespondence(corrRes.correspondence||corrRes||[]);
  renderDocuments(docRes.documents||docRes||[]);
  renderActions(caseRes.actions||[]);
  renderFilings(filingsRes||[]);
  renderUploads(uploadsRes||[]);
  renderTimeline(tlRes||[]);
  loadTemplates();
}

// ── Render: Deadlines ────────────────────────────────────────────────

function renderDeadlines(dls){
  const el=document.getElementById('deadlineList');
  document.getElementById('dlBadge').textContent=dls.length;
  if(!dls.length){el.innerHTML='<p style="color:var(--green);font-size:12px;padding:4px 0">No pending deadlines \u2014 all clear.</p>';return}
  el.innerHTML=dls.map(d=>{
    const days=d.days_remaining;const urg=d.urgency||'normal';
    const daysText=days<0?Math.abs(days)+'d overdue':days===0?'TODAY':days+'d';
    const effDate=d.effective_date||d.due_date;
    const ext=d.status==='extended'?' <span style="font-size:9px;color:var(--amber);font-weight:700">(EXT)</span>':'';
    return `<div class="dl-row"><div class="dl-desc">${esc(d.description).substring(0,60)}${ext}</div><div class="dl-date">${fmtDate(effDate)}</div><span class="dl-badge" style="background:${urgBg(urg)};color:${urgColor(urg)}">${daysText}</span></div>`;
  }).join('');
}

// ── Render: Actions ──────────────────────────────────────────────────

function renderActions(acts){
  const pending=acts.filter(a=>a.status==='pending'||a.status==='overdue');
  const done=acts.filter(a=>a.status==='completed');
  document.getElementById('actBadge').textContent=pending.length+' pending';
  const el=document.getElementById('actionList');
  const renderOne=a=>{
    const isDone=a.status==='completed';const isOverdue=a.status==='overdue';
    const cls=isDone?'done':isOverdue?'overdue':'';
    const check=isDone?'\u2713':isOverdue?'!':'';
    return `<div class="act-row"><div class="act-check ${cls}">${check}</div><div><div class="act-type">${esc(a.action_type)}</div><div class="act-text">${esc(a.description)}</div></div></div>`;
  };
  el.innerHTML=pending.map(renderOne).join('')+
    (done.length?'<div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--brd2)"><div style="font-size:9px;font-weight:700;color:var(--tx3);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Completed</div>'+done.slice(0,8).map(renderOne).join('')+(done.length>8?`<div style="font-size:10px;color:var(--tx3);padding:4px 0">+ ${done.length-8} more completed</div>`:'')+' </div>':'');
}

// ── Render: Documents ────────────────────────────────────────────────

function renderDocuments(docs){
  const el=document.getElementById('docGrid');
  document.getElementById('docBadge').textContent=docs.length;
  if(!docs.length){el.innerHTML='<p style="color:var(--tx3);font-size:12px;padding:16px">No documents generated yet.</p>';return}
  el.innerHTML=docs.map(d=>{
    const icon=d.filename.includes('motion')?'\u2696':d.filename.includes('answer')?'\u270E':d.filename.includes('briefing')?'\uD83D\uDCCB':'\uD83D\uDCC4';
    const name=d.filename.replace(/_/g,' ').replace(/\.txt$/,'').replace(/\s*\d{8}\s*\d{6}\s*$/,'');
    const kb=d.size_bytes?Math.round(d.size_bytes/1024)+' KB':'';
    return `<div class="doc-card" onclick="viewDocument('${esc(d.file_path)}','${esc(d.filename)}')"><div class="doc-icon">${icon}</div><div class="doc-name">${esc(name)}</div><div class="doc-detail">${kb}</div></div>`;
  }).join('');
}

// ── Render: Correspondence ───────────────────────────────────────────

function renderCorrespondence(items){
  const el=document.getElementById('corrList');
  document.getElementById('corrBadge').textContent=items.length;
  if(!items.length){el.innerHTML='<p style="color:var(--tx3);font-size:12px;padding:4px 0">No correspondence on file.</p>';return}
  el.innerHTML=items.map(c=>{
    const statusColors={draft:'badge-amber',approved:'badge-blue',sent:'badge-green',filed:'badge-green'};
    const dir=c.direction==='inbound'?'\u2190 IN':'\u2192 OUT';
    return `<div class="corr-row"><div class="corr-top"><div class="corr-subject">${esc(c.subject)}</div><span class="corr-status ${statusColors[c.status]||'badge-amber'}">${c.status.toUpperCase()}</span></div><div class="corr-meta">${dir} \u00B7 ${esc(c.comm_type)} \u00B7 ${esc(c.recipient||'')} \u00B7 ${c.created_at?new Date(c.created_at).toLocaleDateString():''}</div></div>`;
  }).join('');
}

// ── Render: Filings ──────────────────────────────────────────────────

function renderFilings(filings){
  _filings=filings;
  const el=document.getElementById('filingList');
  document.getElementById('filingBadge').textContent=filings.length;
  if(!filings.length){el.innerHTML='<p style="color:var(--tx3);font-size:12px;padding:4px 0">No filings recorded yet.</p>';return}
  el.innerHTML=filings.map(f=>{
    const sc={filed:'badge-blue',accepted:'badge-green',served:'badge-green',draft:'badge-amber',rejected:'badge-red'};
    const stamp=f.stamped_path?'<span style="color:var(--green);margin-left:4px" title="Court-stamped copy on file">\u2705</span>':'';
    return `<div class="corr-row"><div class="corr-top"><div class="corr-subject">${esc(f.title)}${stamp}</div><span class="corr-status ${sc[f.status]||'badge-amber'}">${(f.status||'').toUpperCase()}</span></div><div class="corr-meta">${f.filed_date?'Filed: '+f.filed_date.substring(0,10):'Pending'}${f.filed_with?' \u00B7 '+esc(f.filed_with):''}${f.filing_location?' \u00B7 '+esc(f.filing_location):''}</div>${f.served_on?`<div class="corr-meta">Served: ${esc(f.served_on)} \u00B7 ${esc(f.served_method||'')} \u00B7 ${f.served_date?f.served_date.substring(0,10):''}</div>`:''}${f.upload_count>0?`<div class="corr-meta" style="color:var(--green)">\u{1F4CE} ${f.upload_count} attachment(s)</div>`:'<div class="corr-meta" style="color:var(--amber)">No stamped copy yet</div>'}</div>`;
  }).join('');
}

// ── Render: Uploads ──────────────────────────────────────────────────

function renderUploads(uploads){
  const el=document.getElementById('uploadList');
  document.getElementById('uploadBadge').textContent=uploads.length;
  if(!uploads.length){el.innerHTML='<p style="color:var(--tx3);font-size:12px;padding:4px 0">No documents uploaded yet.</p>';return}
  el.innerHTML=uploads.map(u=>{
    const tc={stamped_copy:'badge-green',evidence:'badge-blue',correspondence:'badge-amber',receipt:'badge-amber'};
    const kb=u.file_size?(u.file_size/1024).toFixed(0)+' KB':'';
    return `<div class="corr-row" style="cursor:pointer" onclick="window.open(API+'/api/uploads/${u.id}/download','_blank')"><div class="corr-top"><div class="corr-subject">\u{1F4CE} ${esc(u.original_name||u.filename)}</div><span class="corr-status ${tc[u.upload_type]||'badge-amber'}">${(u.upload_type||'').replace(/_/g,' ').toUpperCase()}</span></div><div class="corr-meta">${esc(u.description||'')} \u00B7 ${kb} \u00B7 ${u.created_at?new Date(u.created_at).toLocaleDateString():''}${u.filing_title?' \u00B7 Filing: '+esc(u.filing_title):''}</div></div>`;
  }).join('');
}

// ── Render: Activity Timeline ────────────────────────────────────────

function renderTimeline(events){
  const el=document.getElementById('timelineList');
  document.getElementById('tlBadge').textContent=events.length;
  if(!events.length){el.innerHTML='<p style="color:var(--tx3);font-size:12px;padding:4px 0">No activity recorded yet.</p>';return}
  const icons={filing:'\u2696',correspondence:'\u2709',action:'\u25CB',action_done:'\u2713',upload:'\u{1F4CE}',evidence:'\u{1F50D}'};
  el.innerHTML=events.map(ev=>{
    const icon=icons[ev.event_type]||'\u2022';
    return `<div class="tl-item"><div class="tl-icon ${ev.event_type}">${icon}</div><div class="tl-body"><div class="tl-summary">${esc((ev.summary||'').substring(0,70))}</div><div class="tl-detail">${esc(ev.detail||'')}</div></div><div class="tl-time">${fmtTime(ev.event_time)}</div></div>`;
  }).join('');
}

// ── Drag & Drop Upload Zone ──────────────────────────────────────────

const uploadZone = document.getElementById('uploadZone');
const uploadFile = document.getElementById('uploadFile');
const uploadControls = document.getElementById('uploadControls');

uploadZone.addEventListener('click', () => uploadFile.click());
uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('drag-over'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
uploadZone.addEventListener('drop', e => {
  e.preventDefault(); uploadZone.classList.remove('drag-over');
  if(e.dataTransfer.files.length){ uploadFile.files = e.dataTransfer.files; onFileSelected(); }
});
uploadFile.addEventListener('change', onFileSelected);

function onFileSelected(){
  if(!uploadFile.files.length) return;
  uploadControls.style.display = 'flex';
  uploadZone.querySelector('.uz-text').innerHTML = '<strong>' + esc(uploadFile.files[0].name) + '</strong> (' + (uploadFile.files[0].size/1024).toFixed(0) + ' KB)';
}

function toggleFilingSelect(){
  const sel=document.getElementById('filingSelect');
  const type=document.getElementById('uploadType').value;
  if(type==='stamped_copy'&&_filings.length>0){
    sel.style.display='';
    sel.innerHTML='<option value="">Link to filing\u2026</option>'+_filings.map(f=>`<option value="${f.id}">${esc(f.title).substring(0,35)} (${f.filed_date||'pending'})</option>`).join('');
  } else {sel.style.display='none'}
}

async function submitUpload(){
  if(!uploadFile.files.length){toast('Select a file first','warning');return}
  const btn=document.getElementById('uploadBtn');
  const orig=btn.textContent;
  btn.textContent='Uploading\u2026';btn.disabled=true;

  const fd=new FormData();
  fd.append('file',uploadFile.files[0]);
  fd.append('upload_type',document.getElementById('uploadType').value);
  fd.append('description',document.getElementById('uploadDesc').value||uploadFile.files[0].name);
  const fid=document.getElementById('filingSelect').value;
  if(fid)fd.append('filing_id',fid);

  try{
    const r=await fetch(API+'/api/cases/'+_activeSlug+'/upload',{method:'POST',body:fd});
    const d=await r.json();
    if(d.id){
      toast('Document uploaded successfully','success');
      uploadFile.value='';document.getElementById('uploadDesc').value='';
      uploadControls.style.display='none';
      uploadZone.querySelector('.uz-text').innerHTML='Drop files here or <strong>click to browse</strong>';
      const res=await fetch(API+'/api/cases/'+_activeSlug+'/uploads').then(r=>r.json()).catch(()=>[]);
      renderUploads(res||[]);
      const tl=await fetch(API+'/api/cases/'+_activeSlug+'/timeline?limit=30').then(r=>r.json()).catch(()=>[]);
      renderTimeline(tl||[]);
    } else {toast('Upload failed: '+(d.error||'Unknown error'),'error')}
  }catch(e){toast('Upload failed: '+e.message,'error')}
  finally{btn.textContent=orig;btn.disabled=false}
}

// ── Templates ────────────────────────────────────────────────────────

async function loadTemplates(){
  try{const r=await fetch(API+'/api/templates');const d=await r.json();const sel=document.getElementById('templateSelect');
  sel.innerHTML=(d.templates||[]).map(t=>`<option value="${t.name}">${t.name.replace(/_/g,' ')} \u2014 ${t.description.substring(0,50)}</option>`).join('')}catch(e){}
}

// ── Generate Document ────────────────────────────────────────────────

async function generateDoc(template){
  const tmpl=template||document.getElementById('templateSelect').value;
  if(!_activeSlug||!tmpl)return;
  const btn=event?.target;const origText=btn?btn.textContent:'';
  if(btn){btn.disabled=true;btn.textContent='Generating\u2026';btn.style.opacity='.6'}
  try{
    const r=await fetch(API+'/api/cases/'+_activeSlug+'/generate/'+tmpl,{method:'POST'});
    const d=await r.json();
    if(d.document){showDocument(tmpl.replace(/_/g,' ').toUpperCase(),d.document);toast('Document generated','success',2000)}
    loadCase(_activeSlug);
  }catch(e){toast('Generation failed: '+e.message,'error')}
  finally{if(btn){btn.disabled=false;btn.textContent=origText;btn.style.opacity=''}}
}

// ── View Existing Document ───────────────────────────────────────────

async function viewDocument(filePath,filename){
  try{
    const r=await fetch(API+'/api/cases/'+_activeSlug+'/documents');
    const data=await r.json();const docs=data.documents||data||[];
    const doc=docs.find(d=>d.file_path===filePath||d.filename===filename);
    if(doc&&doc.content){showDocument(filename.replace(/_/g,' '),doc.content)}
    else{const tmpl=filename.split('_202')[0]||filename;
    const genR=await fetch(API+'/api/cases/'+_activeSlug+'/generate/'+tmpl,{method:'POST'});
    const genD=await genR.json();
    if(genD.document)showDocument(filename.replace(/_/g,' '),genD.document);
    else toast('Could not load document','error')}
  }catch(e){console.error(e)}
}

// ── Show Document in Courthouse-Ready Modal ──────────────────────────

function showDocument(title, text){
  _currentDoc = text;
  document.getElementById('modalTitle').textContent = title;
  const body = document.getElementById('docBody');

  // Build structured court document from plain text
  const lines = text.split('\n');
  let html = '';
  let inCourtHeader = false;
  let courtHeaderLines = [];
  let foundBody = false;

  for(let i = 0; i < lines.length; i++){
    const line = lines[i];
    const trimmed = line.trim();

    // Detect court header block (IN THE SUPERIOR COURT ... through Defendant.)
    if(!foundBody && trimmed.startsWith('IN THE ')){
      inCourtHeader = true;
      courtHeaderLines = [];
    }

    if(inCourtHeader){
      courtHeaderLines.push(esc(trimmed));
      if(trimmed.endsWith('Defendant.') || trimmed.endsWith('Defendant')){
        html += '<div class="court-header">' + courtHeaderLines.join('<br>') + '</div>';
        inCourtHeader = false;
        foundBody = true;
        continue;
      }
      continue;
    }

    // Document title lines (all-caps, important headings)
    if(/^(DEFENDANT'S|MOTION FOR|ANSWER TO|ATTORNEY BRIEFING)/.test(trimmed)){
      html += '<div class="doc-heading">' + esc(trimmed) + '</div>';
      continue;
    }

    // Section headers (roman numerals, uppercase keywords)
    if(/^(I+V?I*\.\s+|JURISDICTIONAL|RESPONSE TO|AFFIRMATIVE DEFENSES|PRAYER FOR RELIEF|JURY TRIAL DEMAND|CERTIFICATE OF SERVICE|PROPOSED ORDER|ORDER$|CASE OVERVIEW|CLAIMS SUMMARY|OPPOSING COUNSEL|CASE NOTES|EVIDENCE INVENTORY|COMES NOW|WHEREFORE)/.test(trimmed)){
      html += '<div class="section-title">' + esc(trimmed) + '</div>';
      continue;
    }

    // Defense sub-headers
    if(/^(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH) DEFENSE/.test(trimmed)){
      html += '<div class="defense-title">' + esc(trimmed) + '</div>';
      continue;
    }

    // Signature lines
    if(/^_{4,}/.test(trimmed)){
      html += '<div class="sig-line"></div>';
      continue;
    }

    // Footer metadata line
    if(trimmed.startsWith('---') && i > lines.length - 5){
      html += '<div class="meta-footer">';
      for(let j = i; j < lines.length; j++){
        html += esc(lines[j].trim()) + '<br>';
      }
      html += '</div>';
      break;
    }

    // Blank lines = paragraph break
    if(!trimmed){
      html += '<div style="height:8px"></div>';
      continue;
    }

    // Regular paragraph
    html += '<div class="paragraph">' + esc(line) + '</div>';
  }

  body.innerHTML = html;
  document.getElementById('docModal').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeDoc(){
  document.getElementById('docModal').classList.remove('open');
  document.body.style.overflow='';
}

function printDoc(){ window.print() }

function copyDoc(){
  navigator.clipboard.writeText(_currentDoc).then(()=>{
    toast('Document copied to clipboard','success',2000);
    const btn=event.target;const orig=btn.innerHTML;
    btn.innerHTML='\u2713 Copied!';setTimeout(()=>btn.innerHTML=orig,1800);
  });
}

// ── PDF Download ─────────────────────────────────────────────────────

async function downloadPdf(btn){
  if(!_currentDoc)return;
  const orig=btn.innerHTML;btn.innerHTML='Generating\u2026';btn.disabled=true;
  document.getElementById('emailStatus').textContent='';
  try{
    const c=_cases.find(x=>x.case_slug===_activeSlug)||{};
    const title=document.getElementById('modalTitle').textContent;
    const r=await fetch(API+'/api/pdf/render',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:_currentDoc,title:title,case_number:c.case_number||''})});
    if(!r.ok){const err=await r.json().catch(()=>({}));throw new Error(err.error||'PDF generation failed')}
    const blob=await r.blob();const url=URL.createObjectURL(blob);
    const a=document.createElement('a');a.href=url;
    a.download=title.replace(/\s+/g,'_')+'_'+(c.case_number||'doc')+'.pdf';
    document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
    toast('PDF downloaded','success',2500);
    btn.innerHTML='\u2713 Downloaded!';setTimeout(()=>{btn.innerHTML=orig},2500);
  }catch(e){toast('PDF failed: '+e.message,'error');btn.innerHTML=orig}
  finally{btn.disabled=false}
}

// ── Email PDF ────────────────────────────────────────────────────────

async function emailPdf(btn){
  if(!_currentDoc)return;
  const orig=btn.innerHTML;btn.innerHTML='\u2709 Sending\u2026';btn.disabled=true;
  const status=document.getElementById('emailStatus');status.textContent='';
  try{
    const c=_cases.find(x=>x.case_slug===_activeSlug)||{};
    const title=document.getElementById('modalTitle').textContent;
    const r=await fetch(API+'/api/pdf/email',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:_currentDoc,title:title,case_number:c.case_number||'',case_name:c.case_name||''})});
    const d=await r.json();
    if(d.sent){
      toast('Email sent to '+d.to,'success');
      btn.innerHTML='\u2713 Sent!';status.textContent='Delivered to '+d.to;status.style.color='#22c55e';
      setTimeout(()=>{btn.innerHTML=orig;status.textContent='';status.style.color=''},4000);
    }else{toast('Email failed: '+(d.error||'Unknown error'),'error');btn.innerHTML=orig}
  }catch(e){toast('Email failed: '+e.message,'error');btn.innerHTML=orig}
  finally{btn.disabled=false}
}

// ── Auto-Refresh (every 60s) ─────────────────────────────────────────

_refreshTimer = setInterval(()=>{loadOverview(true);loadInbox();loadBridgeStatus()}, 60000);

// ── Init ─────────────────────────────────────────────────────────────
loadOverview();
loadInbox(true);
loadBridgeStatus();
</script>
</body>
</html>
"""


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("  FORTRESS PRIME — Legal Case Manager + CRM Engine")
    log.info(f"  http://192.168.0.100:{PORT}")
    log.info("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
