"""
LEGAL HOLD API — Forensic Evidence & Litigation Support Endpoints
================================================================

Replaces the legal-hold endpoints previously in tools/batch_classifier.py.
Provides forensic report generation, email evidence scanning, draft letter
generation, and evidence export for active litigation cases.

Endpoints:
    GET  /legal-hold                     — Litigation overview (cases, deadlines, evidence counts)
    GET  /legal-hold/scan                — Keyword scan of email archive
    GET  /legal-hold/emails/{case_id}    — Email evidence drilldown for a case
    GET  /legal-hold/forensic-report     — SHA-256 hashed forensic evidence report
    GET  /legal-hold/export/{case_slug}  — CSV export of case email evidence
    GET  /legal-hold/watchdog-status     — KYC watchdog scan status
    GET  /legal-hold/draft-letter/{slug} — Pre-drafted correspondence for a case

Database: fortress_db (via shared async engine)
"""

import csv
import hashlib
import io
import os
import structlog
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from backend.services.ediscovery_agent import LegacySession

logger = structlog.get_logger()
router = APIRouter()

NAS_LEGAL = "/mnt/fortress_nas/sectors/legal"

WATCHDOG_TERMS = {
    "prime-trust-23-11161": {
        "senders": [
            "primetrustwinddown", "stretto-services", "cases-cr.stretto",
            "terraforminfo", "ra.kroll", "detweiler", "wbd-us.com",
            "plan.administrator", "province", "womble",
        ],
        "subjects": [
            "Estate Property Determination", "KYC verification",
            "claim distribution", "unique code", "claimant ID", "Bar Date",
        ],
    },
    "fish-trap-suv2026000013": {
        "senders": [
            "stuartattorneys", "generaliglobalassistance", "rtsfg",
            "jdavidstuart",
        ],
        "subjects": [
            "SUV2026000013", "Generali", "travel insurance commission",
        ],
    },
}


def _row_dict(row) -> dict:
    d = dict(row._mapping)
    for k, v in d.items():
        if isinstance(v, (date, datetime)):
            d[k] = v.isoformat()
    return d


@router.get("/legal-hold", summary="Litigation overview dashboard")
async def legal_hold_overview():
    async with LegacySession() as session:
        cases_r = await session.execute(text(
            "SELECT id, case_slug, case_number, case_name, court, our_role, "
            "critical_date, status FROM legal.cases WHERE status = 'active' "
            "ORDER BY critical_date"
        ))
        cases = [_row_dict(r) for r in cases_r.fetchall()]

        for c in cases:
            cd = c.get("critical_date")
            if cd:
                try:
                    d = date.fromisoformat(cd) if isinstance(cd, str) else cd
                    c["days_remaining"] = (d - date.today()).days
                except (ValueError, TypeError):
                    c["days_remaining"] = None

            ev_r = await session.execute(text(
                "SELECT COUNT(*) as cnt FROM legal.case_evidence WHERE case_id = :cid"
            ), {"cid": c["id"]})
            c["evidence_count"] = ev_r.scalar() or 0

            dl_r = await session.execute(text(
                "SELECT COUNT(*) as cnt FROM legal.deadlines "
                "WHERE case_id = :cid AND status IN ('pending', 'extended')"
            ), {"cid": c["id"]})
            c["active_deadlines"] = dl_r.scalar() or 0

            corr_r = await session.execute(text(
                "SELECT COUNT(*) as cnt FROM legal.correspondence WHERE case_id = :cid"
            ), {"cid": c["id"]})
            c["correspondence_count"] = corr_r.scalar() or 0

    return {
        "cases": cases,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/legal-hold/scan", summary="Keyword scan of email archive")
async def legal_hold_scan(
    keyword: str = Query(..., min_length=2, description="Search term"),
    limit: int = Query(50, ge=1, le=500),
):
    async with LegacySession() as session:
        result = await session.execute(text("""
            SELECT id, sender, subject, LEFT(content, 500) as excerpt, sent_at
            FROM public.email_archive
            WHERE content ILIKE :kw OR subject ILIKE :kw OR sender ILIKE :kw
            ORDER BY sent_at DESC
            LIMIT :lim
        """), {"kw": f"%{keyword}%", "lim": limit})
        rows = [_row_dict(r) for r in result.fetchall()]

        count_r = await session.execute(text("""
            SELECT COUNT(*) FROM public.email_archive
            WHERE content ILIKE :kw OR subject ILIKE :kw OR sender ILIKE :kw
        """), {"kw": f"%{keyword}%"})
        total = count_r.scalar() or 0

    return {
        "keyword": keyword,
        "total_matches": total,
        "results": rows,
        "showing": len(rows),
    }


@router.get("/legal-hold/emails/{case_slug}", summary="Email evidence for a case")
async def legal_hold_emails(case_slug: str, limit: int = Query(100, ge=1, le=1000)):
    terms = WATCHDOG_TERMS.get(case_slug)
    if not terms:
        raise HTTPException(404, f"No watchdog terms configured for case '{case_slug}'")

    sender_clauses = " OR ".join(
        f"sender ILIKE '%{s}%'" for s in terms["senders"]
    )
    subject_clauses = " OR ".join(
        f"subject ILIKE '%{s}%'" for s in terms["subjects"]
    )

    query = f"""
        SELECT id, sender, subject, LEFT(content, 500) as excerpt, sent_at
        FROM public.email_archive
        WHERE ({sender_clauses}) OR ({subject_clauses})
        ORDER BY sent_at DESC
        LIMIT :lim
    """

    async with LegacySession() as session:
        result = await session.execute(text(query), {"lim": limit})
        rows = [_row_dict(r) for r in result.fetchall()]

        count_q = f"""
            SELECT COUNT(*) FROM public.email_archive
            WHERE ({sender_clauses}) OR ({subject_clauses})
        """
        count_r = await session.execute(text(count_q))
        total = count_r.scalar() or 0

    return {
        "case_slug": case_slug,
        "total_matches": total,
        "results": rows,
        "showing": len(rows),
        "search_terms": terms,
    }


@router.get("/legal-hold/forensic-report", summary="SHA-256 forensic evidence report")
async def forensic_report(case_slug: str = Query("prime-trust-23-11161")):
    terms = WATCHDOG_TERMS.get(case_slug)
    if not terms:
        raise HTTPException(404, f"No watchdog terms for '{case_slug}'")

    async with LegacySession() as session:
        total_r = await session.execute(text(
            "SELECT COUNT(*) FROM public.email_archive"
        ))
        archive_size = total_r.scalar() or 0

        date_r = await session.execute(text(
            "SELECT MIN(sent_at), MAX(sent_at) FROM public.email_archive"
        ))
        date_row = date_r.fetchone()
        min_date = date_row[0].isoformat() if date_row and date_row[0] else "unknown"
        max_date = date_row[1].isoformat() if date_row and date_row[1] else "unknown"

        sender_results = {}
        for term in terms["senders"]:
            r = await session.execute(text(
                "SELECT COUNT(*) FROM public.email_archive WHERE sender ILIKE :t"
            ), {"t": f"%{term}%"})
            sender_results[term] = r.scalar() or 0

        subject_results = {}
        for term in terms["subjects"]:
            r = await session.execute(text(
                "SELECT COUNT(*) FROM public.email_archive WHERE subject ILIKE :t"
            ), {"t": f"%{term}%"})
            subject_results[term] = r.scalar() or 0

    report_data = {
        "case_slug": case_slug,
        "archive_size": archive_size,
        "date_range": {"min": min_date, "max": max_date},
        "sender_scan": sender_results,
        "subject_scan": subject_results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    report_str = str(report_data)
    report_data["integrity_hash_sha256"] = hashlib.sha256(
        report_str.encode()
    ).hexdigest()

    return report_data


@router.get("/legal-hold/export/{case_slug}", summary="CSV export of case emails")
async def export_case_emails(case_slug: str):
    terms = WATCHDOG_TERMS.get(case_slug)
    if not terms:
        raise HTTPException(404, f"No watchdog terms for '{case_slug}'")

    sender_clauses = " OR ".join(
        f"sender ILIKE '%{s}%'" for s in terms["senders"]
    )
    subject_clauses = " OR ".join(
        f"subject ILIKE '%{s}%'" for s in terms["subjects"]
    )

    query = f"""
        SELECT id, sent_at, sender, subject, LEFT(content, 1000) as content_excerpt
        FROM public.email_archive
        WHERE ({sender_clauses}) OR ({subject_clauses})
        ORDER BY sent_at DESC
    """

    async with LegacySession() as session:
        result = await session.execute(text(query))
        rows = result.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "sent_at", "sender", "subject", "content_excerpt"])
    for row in rows:
        d = _row_dict(row)
        writer.writerow([
            d.get("id"), d.get("sent_at"), d.get("sender"),
            d.get("subject"), d.get("content_excerpt", "")[:500],
        ])

    output.seek(0)
    filename = f"legal_hold_{case_slug}_{date.today().isoformat()}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/legal-hold/watchdog-status", summary="KYC watchdog scan status")
async def watchdog_status():
    results = {}

    async with LegacySession() as session:
        for slug, terms in WATCHDOG_TERMS.items():
            sender_clauses = " OR ".join(
                f"sender ILIKE '%{s}%'" for s in terms["senders"]
            )
            r = await session.execute(text(
                f"SELECT COUNT(*) FROM public.email_archive WHERE {sender_clauses}"
            ))
            sender_hits = r.scalar() or 0

            latest_r = await session.execute(text(f"""
                SELECT id, sender, subject, sent_at
                FROM public.email_archive
                WHERE {sender_clauses}
                ORDER BY sent_at DESC LIMIT 1
            """))
            latest = latest_r.fetchone()

            results[slug] = {
                "monitored_senders": terms["senders"],
                "total_sender_hits": sender_hits,
                "latest_match": _row_dict(latest) if latest else None,
            }

    nas_alerts = {}
    for slug in WATCHDOG_TERMS:
        alert_dir = os.path.join(NAS_LEGAL, slug, "alerts")
        if os.path.isdir(alert_dir):
            alerts = sorted(os.listdir(alert_dir), reverse=True)
            nas_alerts[slug] = {
                "alert_count": len(alerts),
                "latest_alert": alerts[0] if alerts else None,
            }

    return {
        "watchdog_terms": results,
        "nas_alerts": nas_alerts,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/legal-hold/draft-letter/{case_slug}",
            summary="Pre-drafted correspondence for a case")
async def draft_letter(case_slug: str):
    async with LegacySession() as session:
        result = await session.execute(text("""
            SELECT c.id, c.subject, c.body, c.status, c.file_path, c.created_at
            FROM legal.correspondence c
            JOIN legal.cases cs ON c.case_id = cs.id
            WHERE cs.case_slug = :slug AND c.direction = 'outbound'
            ORDER BY c.created_at DESC
        """), {"slug": case_slug})
        rows = [_row_dict(r) for r in result.fetchall()]

    drafts = []
    for r in rows:
        fp = r.get("file_path")
        content = None
        if fp and os.path.isfile(fp):
            try:
                with open(fp, "r") as f:
                    content = f.read()
            except OSError:
                content = "[File read error]"
        drafts.append({**r, "file_content": content})

    return {
        "case_slug": case_slug,
        "drafts": drafts,
        "total": len(drafts),
    }
