"""
THE CAPTAIN — Autonomous Email Ingestion & Triage Agent
=========================================================
Monitors the company inboxes (Gmail + Synology MailPlus), triages every
unread email through a local LLM, and fires the Damage Command Center
workflow when property damage is detected.

Dual-inbox support:
  - Gmail (imap.gmail.com) via GMAIL_APP_PASSWORD
  - Synology MailPlus (NAS IP:993) via MAILPLUS_IMAP_PASSWORD

The Captain never sleeps. He stands watch on a 60-second polling cycle,
reading every inbound email, classifying it in milliseconds, and
dispatching the appropriate response pipeline.

Run standalone:
  cd ~/Fortress-Prime/fortress-guest-platform
  ./venv/bin/python -m backend.services.the_captain

Or as a background task in the FastAPI lifespan:
  from backend.services.the_captain import run_captain_loop
  asyncio.create_task(run_captain_loop())
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

logger = structlog.get_logger(service="the_captain")

TRIAGE_SYSTEM_PROMPT = """You are "The Captain", the frontline triage agent for Cabin Rentals of Georgia, a luxury cabin rental company in Blue Ridge, Georgia.

Read the email. Determine:
1. Is it reporting property damage, broken items, missing inventory, excessive mess, or guest misconduct?
2. What property is it about (if mentioned)?
3. How urgent is it?

Respond ONLY with valid JSON — no markdown, no explanation:
{"is_damage": true/false, "summary": "brief description of the issue", "property_guess": "property name if mentioned, otherwise empty string", "urgency": "low|medium|high|critical"}

Examples of DAMAGE: broken bed, stained carpet, hot tub chemical damage, missing remote, scratched floor, burnt pan, shattered glass, hole in wall.
Examples of NOT DAMAGE: booking inquiry, check-in question, positive review, payment question, general hello."""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Email parsing helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _decode_header_value(raw) -> str:
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


def _extract_sender_email(from_header: str) -> str:
    """Pull the bare email address from a From header like 'Name <addr>'."""
    match = re.search(r"<([^>]+)>", from_header)
    return match.group(1) if match else from_header.strip()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  IMAP connection factory — supports Gmail + MailPlus
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _get_inbox_configs() -> list[dict]:
    """Build a list of IMAP inbox configs from settings.

    Returns up to 2 entries: Gmail and MailPlus (if configured).
    """
    inboxes = []

    email_user = settings.email_user or settings.imap_user or settings.smtp_user

    # Gmail
    gmail_pass = settings.gmail_app_password or settings.imap_app_password
    if email_user and gmail_pass:
        inboxes.append({
            "name": "Gmail",
            "host": "imap.gmail.com",
            "port": 993,
            "user": email_user,
            "password": gmail_pass,
        })

    # Synology MailPlus
    if email_user and settings.mailplus_imap_password:
        inboxes.append({
            "name": "MailPlus",
            "host": settings.mailplus_imap_host,
            "port": settings.mailplus_imap_port,
            "user": email_user,
            "password": settings.mailplus_imap_password,
        })

    return inboxes


def _fetch_unseen_from_inbox(inbox: dict, max_emails: int = 20) -> list[dict]:
    """Connect to a single IMAP inbox and fetch UNSEEN messages."""
    emails = []
    mail = None
    try:
        mail = imaplib.IMAP4_SSL(inbox["host"], inbox["port"])
        mail.login(inbox["user"], inbox["password"])
        mail.select("INBOX")

        _, msg_nums = mail.search(None, "UNSEEN")
        if not msg_nums or not msg_nums[0]:
            return []

        msg_ids = msg_nums[0].split()
        logger.info(
            "captain_unseen_found",
            inbox=inbox["name"],
            count=len(msg_ids),
        )

        for mid in msg_ids[:max_emails]:
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
                    "sender_email": _extract_sender_email(sender),
                    "body": body,
                    "inbox": inbox["name"],
                    "imap_id": mid,
                })

                mail.store(mid, "+FLAGS", "\\Seen")

            except Exception as e:
                logger.warning("captain_fetch_error", mid=str(mid), error=str(e)[:200])

    except imaplib.IMAP4.error as e:
        logger.error("captain_imap_auth_failed", inbox=inbox["name"], error=str(e)[:200])
    except Exception as e:
        logger.error("captain_imap_error", inbox=inbox["name"], error=str(e)[:200])
    finally:
        if mail:
            try:
                mail.close()
                mail.logout()
            except Exception:
                pass

    return emails


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Triage — local LLM classification
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _triage(subject: str, sender: str, body: str) -> Optional[dict]:
    """Send email to local LLM for damage triage. Falls back to OpenAI."""
    prompt = f"""EMAIL TO TRIAGE:
From: {sender}
Subject: {subject}

Body:
{body[:3000]}

Classify this email now."""

    raw = None

    # Tier 1: Local Ollama (fast, sovereign)
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
            if resp.status_code == 200:
                raw = resp.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.debug("captain_triage_local_failed", error=str(e)[:100])

    # Tier 2: OpenAI fallback
    if not raw and settings.openai_api_key:
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
        except Exception as e:
            logger.debug("captain_triage_openai_failed", error=str(e)[:100])

    if not raw:
        return None

    return _parse_triage_json(raw)


def _parse_triage_json(raw: str) -> Optional[dict]:
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Damage workflow trigger
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _find_reservation(
    property_guess: str, db: AsyncSession,
) -> Optional[UUID]:
    """Match a property name guess to the most recent reservation."""
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


async def _handle_damage_email(
    em: dict, triage: dict, db: AsyncSession,
) -> dict:
    """Fire the Damage Command Center for a triaged damage email."""
    property_guess = triage.get("property_guess", "")
    reservation_id = await _find_reservation(property_guess, db)

    if not reservation_id:
        logger.warning(
            "captain_damage_no_reservation",
            property_guess=property_guess,
            subject=em["subject"][:60],
        )
        return {
            "action": "damage_detected_no_reservation",
            "subject": em["subject"][:60],
            "summary": triage.get("summary", ""),
            "property_guess": property_guess,
        }

    from backend.services.damage_workflow import process_damage_claim

    staff_notes = (
        f"[Email from {em['sender_email']}] "
        f"Subject: {em['subject']}\n\n"
        f"{em['body'][:4000]}"
    )

    result = await process_damage_claim(
        reservation_id=reservation_id,
        staff_notes=staff_notes,
        db=db,
        reported_by=em["sender_email"],
    )

    logger.info(
        "captain_damage_workflow_fired",
        claim_number=result.get("claim_number"),
        inbox=em.get("inbox"),
        subject=em["subject"][:60],
    )

    return {
        "action": "damage_claim_created",
        "subject": em["subject"][:60],
        "claim_number": result.get("claim_number"),
        "claim_id": result.get("claim_id"),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Main polling loop
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def run_single_patrol() -> dict:
    """Run one patrol cycle across all configured inboxes."""
    inboxes = _get_inbox_configs()
    if not inboxes:
        return {"status": "no_credentials", "inboxes": 0}

    all_emails = []
    for inbox in inboxes:
        fetched = await asyncio.to_thread(_fetch_unseen_from_inbox, inbox)
        all_emails.extend(fetched)

    if not all_emails:
        return {"status": "clear", "inboxes": len(inboxes), "emails": 0}

    stats = {"processed": 0, "damage": 0, "clean": 0, "triage_failed": 0}

    async with AsyncSessionLocal() as db:
        for em in all_emails:
            stats["processed"] += 1

            triage = await _triage(em["subject"], em["sender"], em["body"])

            if not triage:
                stats["triage_failed"] += 1
                logger.warning("captain_triage_failed", subject=em["subject"][:60])
                continue

            is_damage = triage.get("is_damage", False)

            logger.info(
                "captain_triaged",
                inbox=em.get("inbox"),
                subject=em["subject"][:60],
                is_damage=is_damage,
                summary=triage.get("summary", "")[:80],
                urgency=triage.get("urgency", "low"),
            )

            if is_damage:
                await _handle_damage_email(em, triage, db)
                stats["damage"] += 1
            else:
                stats["clean"] += 1

    return {
        "status": "patrol_complete",
        "inboxes": len(inboxes),
        **stats,
    }


async def run_captain_loop():
    """The Captain's eternal watch. Polls every EMAIL_POLL_INTERVAL seconds."""
    interval = settings.email_poll_interval

    logger.info(
        "the_captain_reporting_for_duty",
        poll_interval=interval,
        inboxes=len(_get_inbox_configs()),
    )

    await asyncio.sleep(30)

    while True:
        try:
            result = await run_single_patrol()
            if result.get("emails", result.get("processed", 0)) > 0:
                logger.info("captain_patrol_report", **result)
        except Exception as e:
            logger.error("captain_patrol_error", error=str(e)[:200])

        await asyncio.sleep(interval)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Standalone entry point
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    RESET = "\033[0m"

    print(f"""
{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════════╗
║           THE CAPTAIN — Email Triage & Damage Dispatch           ║
║           Monitoring company inboxes for damage reports           ║
╚══════════════════════════════════════════════════════════════════╝{RESET}
""")

    inboxes = _get_inbox_configs()
    if not inboxes:
        print("  No inbox credentials configured. Set EMAIL_USER + GMAIL_APP_PASSWORD or MAILPLUS_IMAP_PASSWORD in .env")
    else:
        for ib in inboxes:
            print(f"  Inbox: {ib['name']} ({ib['user']}@{ib['host']}:{ib['port']})")

    async def _run():
        print("\n  Running single patrol...\n")
        result = await run_single_patrol()
        print(f"  Result: {json.dumps(result, indent=2, default=str)}")

    asyncio.run(_run())
