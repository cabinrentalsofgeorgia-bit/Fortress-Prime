"""
Live Email Ingestion & Triage Pipeline
========================================
Polls the company Gmail INBOX for unread messages, triages each through
a lightweight local LLM, and automatically fires the Damage Command Center
workflow when property damage is detected.

Pipeline:
  1. IMAP poll → UNSEEN emails
  2. Extract subject, sender, body
  3. Triage via local Ollama (qwen2.5:7b) — fast, sovereign
  4. If damage detected → process_damage_claim()
  5. Mark SEEN so it's not re-processed

Run standalone:
  cd ~/Fortress-Prime/fortress-guest-platform
  ./venv/bin/python -m backend.services.email_ingest

Or import run_email_ingestion_loop() into the lifespan handler.
"""

import asyncio
import email
import imaplib
import json
import re
from email.header import decode_header
from typing import Optional
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.reservation import Reservation
from backend.models.property import Property

logger = structlog.get_logger()

TRIAGE_SYSTEM_PROMPT = """You are a triage routing agent for Cabin Rentals of Georgia, a property management company in Blue Ridge, Georgia.

Read the email and determine if it is reporting property damage, broken items, missing inventory, guest misconduct, or anything requiring a damage claim.

Respond ONLY with a valid JSON object — no markdown, no explanation:
{"is_damage": true/false, "summary": "brief description of the damage if any", "property_guess": "property name if mentioned, otherwise empty string", "urgency": "low|medium|high|critical"}"""


def _decode_header_value(raw) -> str:
    """Decode an email header that may be encoded."""
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded = []
    for content, charset in parts:
        if isinstance(content, bytes):
            decoded.append(content.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(content))
    return " ".join(decoded)


def _extract_plain_body(msg: email.message.Message) -> str:
    """Extract plain text body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


async def _triage_email(subject: str, sender: str, body: str) -> Optional[dict]:
    """Send email content to local LLM for damage triage classification."""
    prompt = f"""EMAIL:
From: {sender}
Subject: {subject}

Body:
{body[:3000]}

Classify this email now."""

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": settings.ollama_fast_model,
                    "messages": [
                        {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 256},
                },
            )
            if resp.status_code != 200:
                logger.warning("triage_llm_http_error", status=resp.status_code)
                return None

            raw = resp.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        # Fallback to OpenAI if local is down
        if settings.openai_api_key:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                        json={
                            "model": settings.openai_model,
                            "messages": [
                                {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
                                {"role": "user", "content": prompt},
                            ],
                            "temperature": 0.1,
                            "max_tokens": 256,
                        },
                    )
                    if resp.status_code == 200:
                        raw = resp.json()["choices"][0]["message"]["content"].strip()
                    else:
                        return None
            except Exception:
                return None
        else:
            logger.warning("triage_all_llm_failed", error=str(e)[:200])
            return None

    return _parse_triage(raw)


def _parse_triage(raw: str) -> Optional[dict]:
    """Parse the triage LLM JSON response."""
    if not raw:
        return None

    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start == -1 or brace_end == -1:
        return None

    try:
        return json.loads(text[brace_start:brace_end + 1])
    except json.JSONDecodeError:
        return None


async def _find_reservation_by_property_guess(
    property_guess: str, db: AsyncSession,
) -> Optional[UUID]:
    """Try to match a property name guess to the most recent reservation."""
    if not property_guess:
        return None

    slug = re.sub(r"[^a-z0-9]+", "%", property_guess.lower().strip())

    result = await db.execute(
        select(Property).where(Property.name.ilike(f"%{slug}%")).limit(1)
    )
    prop = result.scalar_one_or_none()
    if not prop:
        return None

    res_result = await db.execute(
        select(Reservation)
        .where(Reservation.property_id == prop.id)
        .order_by(desc(Reservation.check_out_date))
        .limit(1)
    )
    res = res_result.scalar_one_or_none()
    return res.id if res else None


async def process_single_email(
    subject: str,
    sender: str,
    body: str,
    db: AsyncSession,
) -> dict:
    """Process a single email through the triage pipeline.

    Returns a status dict describing what happened.
    """
    triage = await _triage_email(subject, sender, body)

    if not triage:
        return {"action": "triage_failed", "subject": subject[:60]}

    is_damage = triage.get("is_damage", False)
    summary = triage.get("summary", "")
    property_guess = triage.get("property_guess", "")
    urgency = triage.get("urgency", "low")

    logger.info(
        "email_triaged",
        subject=subject[:60],
        sender=sender,
        is_damage=is_damage,
        summary=summary[:80],
        urgency=urgency,
    )

    if not is_damage:
        return {
            "action": "no_damage",
            "subject": subject[:60],
            "summary": summary,
        }

    # Damage detected — find the reservation and trigger the workflow
    reservation_id = await _find_reservation_by_property_guess(property_guess, db)

    if not reservation_id:
        logger.warning(
            "damage_email_no_reservation_match",
            property_guess=property_guess,
            subject=subject[:60],
        )
        return {
            "action": "damage_detected_no_reservation",
            "subject": subject[:60],
            "summary": summary,
            "property_guess": property_guess,
        }

    from backend.services.damage_workflow import process_damage_claim

    staff_notes = f"[Email from {sender}] Subject: {subject}\n\n{body[:4000]}"
    workflow_result = await process_damage_claim(
        reservation_id=reservation_id,
        staff_notes=staff_notes,
        db=db,
        reported_by=sender,
    )

    logger.info(
        "damage_workflow_triggered_from_email",
        claim_number=workflow_result.get("claim_number"),
        subject=subject[:60],
    )

    return {
        "action": "damage_claim_created",
        "subject": subject[:60],
        "claim_number": workflow_result.get("claim_number"),
        "claim_id": workflow_result.get("claim_id"),
        "workflow_status": workflow_result.get("status"),
    }


def _fetch_unseen_emails() -> list[dict]:
    """Connect to IMAP, fetch UNSEEN messages, return as dicts.

    Marks each fetched message as SEEN after reading.
    Runs synchronously (imaplib is blocking).
    """
    imap_user = settings.imap_user or settings.smtp_user
    imap_pass = settings.imap_app_password or settings.smtp_password
    if not imap_user or not imap_pass:
        return []

    emails = []
    mail = None
    try:
        mail = imaplib.IMAP4_SSL(settings.imap_host)
        mail.login(imap_user, imap_pass)
        mail.select("INBOX")

        _, msg_nums = mail.search(None, "UNSEEN")
        if not msg_nums or not msg_nums[0]:
            return []

        msg_ids = msg_nums[0].split()

        for mid in msg_ids[:20]:
            try:
                _, data = mail.fetch(mid, "(RFC822)")
                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = _decode_header_value(msg.get("Subject", ""))
                sender = _decode_header_value(msg.get("From", ""))
                body = _extract_plain_body(msg)

                emails.append({
                    "subject": subject,
                    "sender": sender,
                    "body": body,
                    "imap_id": mid,
                })

                mail.store(mid, "+FLAGS", "\\Seen")

            except Exception as e:
                logger.warning("email_fetch_single_error", mid=str(mid), error=str(e)[:200])

    except imaplib.IMAP4.error as e:
        logger.error("imap_login_failed", error=str(e)[:200])
    except Exception as e:
        logger.error("imap_connection_error", error=str(e)[:200])
    finally:
        if mail:
            try:
                mail.close()
                mail.logout()
            except Exception:
                pass

    return emails


async def run_single_poll():
    """Run one poll cycle: fetch unseen emails, triage, and process."""
    emails = await asyncio.to_thread(_fetch_unseen_emails)

    if not emails:
        return {"polled": 0, "damage_found": 0}

    results = []
    async with AsyncSessionLocal() as db:
        for em in emails:
            result = await process_single_email(
                subject=em["subject"],
                sender=em["sender"],
                body=em["body"],
                db=db,
            )
            results.append(result)

    damage_count = sum(1 for r in results if r.get("action", "").startswith("damage"))
    logger.info(
        "email_poll_complete",
        emails_fetched=len(emails),
        damage_detected=damage_count,
    )

    return {
        "polled": len(emails),
        "damage_found": damage_count,
        "results": results,
    }


async def run_email_ingestion_loop():
    """Continuous polling loop. Runs forever as a background task."""
    interval = settings.email_poll_interval

    logger.info("email_ingestion_loop_starting", interval_seconds=interval)

    await asyncio.sleep(30)

    while True:
        try:
            imap_user = settings.imap_user or settings.smtp_user
            imap_pass = settings.imap_app_password or settings.smtp_password
            if not imap_user or not imap_pass:
                logger.debug("email_ingestion_skipped_no_credentials")
                await asyncio.sleep(interval)
                continue

            await run_single_poll()

        except Exception as e:
            logger.error("email_ingestion_error", error=str(e)[:200])

        await asyncio.sleep(interval)


if __name__ == "__main__":
    async def _main():
        print("Running single email poll...")
        result = await run_single_poll()
        print(f"Result: {json.dumps(result, indent=2, default=str)}")

    asyncio.run(_main())
