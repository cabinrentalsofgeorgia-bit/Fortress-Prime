"""
Legal Email Intake — Autonomous MailPlus Ingestion Pipeline
============================================================
Polls a dedicated MailPlus inbox for incoming legal correspondence,
triages each email through the local LLM, links to active cases,
creates correspondence + timeline records, and auto-ingests attachments
into the E-Discovery vault.

Pipeline per email:
  1. IMAP UNSEEN fetch
  2. LLM triage → {is_legal, category, case_slug_guess, case_number_extracted, …}
  3. Case match: (a) regex case# from subject → legal.cases, (b) slug fuzzy-match
  4. Insert into legal.email_intake_queue (dedup by message_uid SHA-256)
  5. If linked: legal.correspondence row + legal.timeline_events row
  6. Attachments → process_vault_upload() (privilege-shielded, vectorized)
  7. Training capture → llm_training_captures flywheel

DB: fortress_db via LegacySession (same as all other legal API services)
Schema bootstrap: CREATE TABLE IF NOT EXISTS on first patrol cycle — no Alembic needed.

Run standalone:
  cd ~/Fortress-Prime/fortress-guest-platform
  .uv-venv/bin/python -m backend.services.legal_email_intake
"""
from __future__ import annotations

import asyncio
import email as email_lib
import hashlib
import json
import re
from datetime import datetime, timezone
from email.header import decode_header
from pathlib import Path
from typing import Optional

import httpx
import structlog

from backend.core.config import settings
from backend.services.the_captain import (
    _decode_header_value,
    _extract_plain_body,
    _extract_sender_email,
    _fetch_unseen_from_inbox,
    _parse_triage_json,
)
from backend.services.ediscovery_agent import LegacySession
from backend.services.swarm_service import submit_chat_completion

logger = structlog.get_logger(service="legal_email_intake")

# ──────────────────────────────────────────────────────────────────────────────
# LLM triage prompt
# ──────────────────────────────────────────────────────────────────────────────

LEGAL_TRIAGE_SYSTEM_PROMPT = """You are the Legal Intake Officer for Fortress Prime, an AI legal operations platform for Cabin Rentals of Georgia.

Read the email and determine:
1. Is this email legal in nature (court filing, opposing counsel correspondence, expert witness communication, discovery material, insurance claim, settlement negotiation, contract, subpoena, or any formal legal matter)?
2. What category best describes it?
3. Can you extract a case number from the subject or body?
4. What is the case slug guess (lowercase-hyphenated name of the case if mentioned)?
5. What type of document or communication is this?

Respond ONLY with valid JSON — no markdown, no explanation:
{
  "is_legal": true/false,
  "category": "court_filing|opposing_counsel|client_correspondence|expert_witness|discovery_material|insurance|settlement|contract|subpoena|unknown",
  "case_number_extracted": "the case number if found, e.g. 2024-CV-001234, otherwise empty string",
  "case_slug_guess": "kebab-case guess at the case name, e.g. 'johnson-v-cabin-rentals', otherwise empty string",
  "document_type": "brief|motion|demand_letter|deposition_notice|interrogatory|subpoena|correspondence|contract|invoice|other",
  "summary": "1-2 sentence description of the email content",
  "urgency": "low|medium|high|critical"
}

Examples of LEGAL: court notices, demand letters, subpoenas, correspondence from attorneys, discovery requests, settlement offers, contracts for legal services, insurance claims.
Examples of NOT LEGAL: booking inquiries, guest reviews, marketing emails, maintenance reports, general business correspondence."""


# ──────────────────────────────────────────────────────────────────────────────
# Schema bootstrap (fortress_db / LegacySession)
# ──────────────────────────────────────────────────────────────────────────────

_BOOTSTRAP_DDLS = [
    """
    CREATE TABLE IF NOT EXISTS legal.email_intake_queue (
        id               SERIAL PRIMARY KEY,
        message_uid      TEXT UNIQUE NOT NULL,
        sender_email     TEXT NOT NULL,
        sender_name      TEXT,
        subject          TEXT,
        body_text        TEXT,
        case_slug        TEXT,
        triage_result    JSONB,
        intake_status    TEXT NOT NULL DEFAULT 'pending',
        attachment_count INT  DEFAULT 0,
        correspondence_id INT,
        received_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        processed_at     TIMESTAMPTZ,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_legal_email_intake_status
        ON legal.email_intake_queue (intake_status)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_legal_email_intake_case
        ON legal.email_intake_queue (case_slug)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_legal_email_intake_rcvd
        ON legal.email_intake_queue (received_at DESC)
    """,
]

_schema_bootstrapped = False


async def _bootstrap_intake_schema() -> None:
    global _schema_bootstrapped
    if _schema_bootstrapped:
        return
    from sqlalchemy import text
    async with LegacySession() as session:
        for ddl in _BOOTSTRAP_DDLS:
            await session.execute(text(ddl))
        await session.commit()
    _schema_bootstrapped = True
    logger.info("legal_intake_schema_bootstrapped")


# ──────────────────────────────────────────────────────────────────────────────
# IMAP config
# ──────────────────────────────────────────────────────────────────────────────

def _get_legal_inbox_config() -> Optional[dict]:
    host = settings.legal_mailplus_host
    user = settings.legal_mailplus_user
    password = settings.legal_mailplus_password
    if not host or not user or not password:
        return None
    return {
        "name": "LegalMailPlus",
        "host": host,
        "port": settings.legal_mailplus_port,
        "user": user,
        "password": password,
        "folder": settings.legal_mailplus_folder,
    }


# ──────────────────────────────────────────────────────────────────────────────
# IMAP fetch — uses the_captain's _fetch_unseen_from_inbox with folder override
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_unseen_legal_emails(inbox: dict, max_emails: int = 30) -> list[dict]:
    """Fetch UNSEEN from MailPlus legal inbox; supports folder selection."""
    import imaplib

    emails = []
    mail = None
    folder = inbox.get("folder", "INBOX")
    try:
        mail = imaplib.IMAP4_SSL(inbox["host"], inbox["port"])
        mail.login(inbox["user"], inbox["password"])
        mail.select(folder)

        _, msg_nums = mail.search(None, "UNSEEN")
        if not msg_nums or not msg_nums[0]:
            return []

        msg_ids = msg_nums[0].split()
        logger.info("legal_intake_unseen_found", count=len(msg_ids), folder=folder)

        for mid in msg_ids[:max_emails]:
            try:
                _, data = mail.fetch(mid, "(RFC822)")
                raw_bytes = data[0][1]
                msg = email_lib.message_from_bytes(raw_bytes)

                subject = _decode_header_value(msg.get("Subject", ""))
                sender = _decode_header_value(msg.get("From", ""))
                body = _extract_plain_body(msg)

                # Count attachments
                attachment_count = 0
                attachment_data: list[dict] = []
                if msg.is_multipart():
                    for part in msg.walk():
                        disp = str(part.get("Content-Disposition", ""))
                        if "attachment" in disp:
                            fname = part.get_filename() or "attachment"
                            fname = _decode_header_value(fname)
                            content_bytes = part.get_payload(decode=True)
                            ctype = part.get_content_type() or "application/octet-stream"
                            if content_bytes:
                                attachment_count += 1
                                attachment_data.append({
                                    "file_name": fname,
                                    "mime_type": ctype,
                                    "file_bytes": content_bytes,
                                })

                emails.append({
                    "subject":          subject,
                    "sender":           sender,
                    "sender_email":     _extract_sender_email(sender),
                    "body":             body,
                    "inbox":            inbox["name"],
                    "imap_id":          mid,
                    "attachment_count": attachment_count,
                    "attachments":      attachment_data,
                    "raw_bytes":        raw_bytes,
                })

                mail.store(mid, "+FLAGS", "\\Seen")

            except Exception as exc:
                logger.warning("legal_intake_fetch_error", mid=str(mid), error=str(exc)[:200])

    except Exception as exc:
        logger.error("legal_intake_imap_error", inbox=inbox["name"], error=str(exc)[:200])
    finally:
        if mail:
            try:
                mail.close()
                mail.logout()
            except Exception:
                pass

    return emails


# ──────────────────────────────────────────────────────────────────────────────
# LLM triage
# ──────────────────────────────────────────────────────────────────────────────

async def _triage_legal_email(subject: str, sender: str, body: str) -> Optional[dict]:
    prompt = f"""EMAIL TO CLASSIFY:
From: {sender}
Subject: {subject}

Body:
{body[:3000]}

Classify this email now."""

    raw: Optional[str] = None

    # Tier 1: local Ollama (sovereign, fast)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/chat",
                json={
                    "model": settings.ollama_fast_model,
                    "messages": [
                        {"role": "system", "content": LEGAL_TRIAGE_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.05, "num_predict": 384},
                },
            )
            if resp.status_code == 200:
                raw = resp.json().get("message", {}).get("content", "").strip()
    except Exception as exc:
        logger.debug("legal_triage_ollama_failed", error=str(exc)[:100])

    # Tier 2: LiteLLM gateway
    if not raw:
        try:
            response = await submit_chat_completion(
                prompt=prompt,
                model=settings.openai_model,
                system_message=LEGAL_TRIAGE_SYSTEM_PROMPT,
                timeout_s=30.0,
                extra_payload={"temperature": 0.05, "max_tokens": 384},
            )
            choices = response.get("choices") or []
            if choices:
                raw = (((choices[0] or {}).get("message") or {}).get("content") or "").strip()
        except Exception as exc:
            logger.debug("legal_triage_gateway_failed", error=str(exc)[:100])

    if not raw:
        return None
    return _parse_triage_json(raw)


# ──────────────────────────────────────────────────────────────────────────────
# Case linking
# ──────────────────────────────────────────────────────────────────────────────

_CASE_NUMBER_RE = re.compile(r"\b(\d{2,4}-[A-Z]{2,4}-\d{3,8})\b")


async def _find_matching_case(triage: dict, subject: str) -> Optional[str]:
    """Try to link an email to an active case slug in fortress_db."""
    from sqlalchemy import text as sqltext

    # 1) Explicit case number extracted by LLM
    cn_from_triage = (triage.get("case_number_extracted") or "").strip()
    # 2) Regex extraction from subject as backup
    m = _CASE_NUMBER_RE.search(subject)
    cn_from_subject = m.group(1) if m else ""

    async with LegacySession() as session:
        # Try by case_number (exact, then ILIKE)
        for cn in filter(None, [cn_from_triage, cn_from_subject]):
            row = await session.execute(
                sqltext("SELECT case_slug FROM legal.cases WHERE case_number ILIKE :cn LIMIT 1"),
                {"cn": f"%{cn}%"},
            )
            hit = row.fetchone()
            if hit:
                return hit[0]

        # Fuzzy slug guess from LLM
        slug_guess = (triage.get("case_slug_guess") or "").strip().lower()
        if slug_guess:
            row = await session.execute(
                sqltext("SELECT case_slug FROM legal.cases WHERE case_slug ILIKE :sg LIMIT 1"),
                {"sg": f"%{slug_guess}%"},
            )
            hit = row.fetchone()
            if hit:
                return hit[0]

    return None


# ──────────────────────────────────────────────────────────────────────────────
# legal.correspondence + legal.timeline_events inserts
# ──────────────────────────────────────────────────────────────────────────────

async def _record_correspondence(
    case_slug: str,
    subject: str,
    body: str,
    sender_email: str,
    sender_name: str,
    category: str,
    session,
) -> Optional[int]:
    from sqlalchemy import text as sqltext
    try:
        row = await session.execute(
            sqltext("SELECT id FROM legal.cases WHERE case_slug = :slug LIMIT 1"),
            {"slug": case_slug},
        )
        case_row = row.fetchone()
        if not case_row:
            return None

        result = await session.execute(
            sqltext("""
                INSERT INTO legal.correspondence
                    (case_id, subject, body, direction, comm_type,
                     recipient, recipient_email, status)
                VALUES (:cid, :subject, :body, 'inbound', 'email',
                        :sender, :email, 'received')
                RETURNING id
            """),
            {
                "cid":     case_row[0],
                "subject": (subject or "")[:500],
                "body":    (body or "")[:32000],
                "sender":  (sender_name or sender_email)[:200],
                "email":   sender_email[:200],
            },
        )
        row2 = result.fetchone()
        await session.commit()
        return row2[0] if row2 else None
    except Exception as exc:
        logger.warning("record_correspondence_error", error=str(exc)[:200])
        return None


async def _record_timeline_event(
    case_slug: str,
    subject: str,
    sender_email: str,
    session,
) -> None:
    from sqlalchemy import text as sqltext
    try:
        await session.execute(
            sqltext("""
                INSERT INTO legal.timeline_events
                    (case_slug, event_date, description, source_evidence_id)
                VALUES (:slug, CURRENT_DATE, :desc, NULL)
            """),
            {
                "slug": case_slug,
                "desc": f"[Email Intake] {subject or 'No subject'} — from {sender_email}",
            },
        )
        await session.commit()
    except Exception as exc:
        logger.warning("record_timeline_error", error=str(exc)[:200])


# ──────────────────────────────────────────────────────────────────────────────
# Attachment ingestion into E-Discovery vault
# ──────────────────────────────────────────────────────────────────────────────

async def _ingest_attachments(attachments: list[dict], case_slug: str) -> int:
    """Push each attachment through the privilege-shielded vault pipeline."""
    from backend.services.legal_ediscovery import process_vault_upload
    ingested = 0
    async with LegacySession() as session:
        for att in attachments:
            try:
                result = await process_vault_upload(
                    db=session,
                    case_slug=case_slug,
                    file_bytes=att["file_bytes"],
                    file_name=att["file_name"],
                    mime_type=att["mime_type"],
                )
                if result.get("status") != "duplicate":
                    ingested += 1
                logger.info(
                    "legal_intake_attachment_ingested",
                    case_slug=case_slug,
                    file_name=att["file_name"],
                    status=result.get("status"),
                )
            except Exception as exc:
                logger.warning(
                    "legal_intake_attachment_error",
                    file_name=att.get("file_name"),
                    error=str(exc)[:200],
                )
    return ingested


# ──────────────────────────────────────────────────────────────────────────────
# Training flywheel capture
# ──────────────────────────────────────────────────────────────────────────────

async def _capture_to_flywheel(
    subject: str,
    triage: dict,
    case_slug: Optional[str],
) -> None:
    try:
        from backend.services.ai_router import _capture_interaction
        prompt = f"Legal email intake: subject='{subject}', triage={json.dumps(triage)}"
        response = (
            f"Classified as {triage.get('category', 'unknown')} legal correspondence. "
            f"Case link: {case_slug or 'unlinked'}. "
            f"Document type: {triage.get('document_type', 'unknown')}. "
            f"Summary: {triage.get('summary', '')}."
        )
        await _capture_interaction(
            source_module="legal_email_intake",
            prompt=prompt,
            response=response,
            model_label=f"triage/{settings.ollama_fast_model}",
        )
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Per-email processing
# ──────────────────────────────────────────────────────────────────────────────

async def process_legal_email(em: dict) -> dict:
    """Full pipeline for one email dict from the IMAP fetch."""
    from sqlalchemy import text as sqltext

    subject       = em.get("subject", "")
    sender        = em.get("sender", "")
    sender_email  = em.get("sender_email", sender)
    body          = em.get("body", "")
    attachments   = em.get("attachments", [])
    att_count     = em.get("attachment_count", 0)

    # Stable dedup key
    uid_source = f"{sender_email}|{subject}|{body[:200]}"
    message_uid = hashlib.sha256(uid_source.encode()).hexdigest()

    # Triage
    triage = await _triage_legal_email(subject, sender, body)
    if not triage:
        logger.warning("legal_triage_failed", subject=subject[:60])
        # Still queue the email for manual review — don't discard on LLM failure
        triage = {"is_legal": True, "category": "triage_failed", "urgency": "normal"}

    is_legal = triage.get("is_legal", False)
    category = triage.get("category", "unknown")

    logger.info(
        "legal_email_triaged",
        subject=subject[:60],
        is_legal=is_legal,
        category=category,
        urgency=triage.get("urgency"),
    )

    if not is_legal:
        return {"action": "not_legal", "subject": subject[:60], "category": category}

    # Case matching
    case_slug = await _find_matching_case(triage, subject)
    intake_status = "linked" if case_slug else "unlinked"

    async with LegacySession() as session:
        # Dedup insert
        try:
            await session.execute(
                sqltext("""
                    INSERT INTO legal.email_intake_queue
                        (message_uid, sender_email, sender_name, subject, body_text,
                         case_slug, triage_result, intake_status, attachment_count,
                         processed_at)
                    VALUES (:uid, :email, :name, :subject, :body,
                            :slug, CAST(:triage AS JSONB), :status, :att_count, now())
                    ON CONFLICT (message_uid) DO NOTHING
                """),
                {
                    "uid":       message_uid,
                    "email":     sender_email[:200],
                    "name":      (sender or "")[:200],
                    "subject":   (subject or "")[:500],
                    "body":      (body or "")[:32000],
                    "slug":      case_slug,
                    "triage":    json.dumps(triage),
                    "status":    intake_status,
                    "att_count": att_count,
                },
            )
            await session.commit()
        except Exception as exc:
            logger.warning("legal_intake_queue_insert_error", error=str(exc)[:200])
            return {"action": "db_error", "subject": subject[:60]}

        correspondence_id: Optional[int] = None
        if case_slug:
            correspondence_id = await _record_correspondence(
                case_slug=case_slug,
                subject=subject,
                body=body,
                sender_email=sender_email,
                sender_name=sender,
                category=category,
                session=session,
            )
            await _record_timeline_event(case_slug, subject, sender_email, session)

            if correspondence_id:
                await session.execute(
                    sqltext("""
                        UPDATE legal.email_intake_queue
                        SET correspondence_id = :cid
                        WHERE message_uid = :uid
                    """),
                    {"cid": correspondence_id, "uid": message_uid},
                )
                await session.commit()

    # Attachment E-Discovery ingestion
    att_ingested = 0
    if attachments and case_slug:
        att_ingested = await _ingest_attachments(attachments, case_slug)

    # Training flywheel
    await _capture_to_flywheel(subject, triage, case_slug)

    logger.info(
        "legal_email_processed",
        subject=subject[:60],
        case_slug=case_slug,
        status=intake_status,
        attachments_ingested=att_ingested,
    )

    return {
        "action":           "legal_email_ingested",
        "subject":          subject[:60],
        "case_slug":        case_slug,
        "intake_status":    intake_status,
        "correspondence_id": correspondence_id,
        "attachments_ingested": att_ingested,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Patrol cycle + infinite loop
# ──────────────────────────────────────────────────────────────────────────────

async def run_legal_intake_patrol() -> dict:
    """Run one full patrol cycle. Safe to call on demand."""
    await _bootstrap_intake_schema()

    inbox = _get_legal_inbox_config()
    if not inbox:
        logger.info("legal_intake_no_credentials")
        return {"status": "no_credentials", "processed": 0}

    emails = await asyncio.to_thread(_fetch_unseen_legal_emails, inbox)

    if not emails:
        return {"status": "clear", "processed": 0}

    stats = {"processed": 0, "linked": 0, "unlinked": 0, "not_legal": 0, "errors": 0}

    for em in emails:
        try:
            result = await process_legal_email(em)
            stats["processed"] += 1
            action = result.get("action", "")
            if action == "legal_email_ingested":
                if result.get("intake_status") == "linked":
                    stats["linked"] += 1
                else:
                    stats["unlinked"] += 1
            elif action == "not_legal":
                stats["not_legal"] += 1
            else:
                stats["errors"] += 1
        except Exception as exc:
            stats["errors"] += 1
            logger.error("legal_intake_patrol_email_error", error=str(exc)[:200])

    logger.info("legal_intake_patrol_complete", **stats)
    return {"status": "patrol_complete", **stats}


async def run_legal_intake_loop() -> None:
    """Infinite polling loop — started by ARQ worker startup."""
    interval = settings.legal_email_poll_interval
    logger.info(
        "legal_intake_loop_started",
        poll_interval=interval,
        inbox_configured=bool(settings.legal_mailplus_host),
    )

    await asyncio.sleep(15)  # brief startup delay

    while True:
        try:
            result = await run_legal_intake_patrol()
            if result.get("processed", 0) > 0:
                logger.info("legal_intake_patrol_report", **result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("legal_intake_loop_error", error=str(exc)[:200])

        await asyncio.sleep(interval)


# ──────────────────────────────────────────────────────────────────────────────
# Standalone entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    async def _main() -> None:
        inbox = _get_legal_inbox_config()
        if not inbox:
            print("No legal MailPlus credentials configured.")
            print("Set LEGAL_MAILPLUS_HOST, LEGAL_MAILPLUS_USER, LEGAL_MAILPLUS_PASSWORD in .env")
            return
        print(f"Legal inbox: {inbox['user']}@{inbox['host']}:{inbox['port']} [{inbox['folder']}]")
        print("Running single patrol...\n")
        result = await run_legal_intake_patrol()
        print(json.dumps(result, indent=2, default=str))

    asyncio.run(_main())
