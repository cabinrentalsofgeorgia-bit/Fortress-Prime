"""
Relativity-Style Email Threading & Deduplication Engine.

Before a document is vectorized, this engine:
  1. MD5 exact-duplicate drop (instant)
  2. Subject-line normalization for thread reconstruction
  3. Thread grouping in legal.email_threads
  4. Terminal email detection (longest/latest in chain)
  5. Only the terminal email gets vectorized; rest flagged duplicate_ignored

Works with CSV email archives (email_id, sender, subject, sent_at, content)
and raw .eml files.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import structlog
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

RE_PREFIX = re.compile(r"^(re|fwd|fw|fwd?)\s*:\s*", re.IGNORECASE)

_DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%m/%d/%Y %H:%M:%S",
]


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _normalize_subject(subject: str) -> str:
    """Strip Re:/Fwd: prefixes and normalize whitespace."""
    s = (subject or "").strip()
    while RE_PREFIX.match(s):
        s = RE_PREFIX.sub("", s).strip()
    return re.sub(r"\s+", " ", s).strip().lower()


def _md5(text_content: str) -> str:
    return hashlib.md5(text_content.encode("utf-8", errors="ignore")).hexdigest()


def parse_email_csv(raw_text: str) -> list[dict]:
    """Parse a CSV email archive into structured records."""
    reader = csv.DictReader(io.StringIO(raw_text))
    emails: list[dict] = []
    for row in reader:
        content = row.get("full_content") or row.get("content_preview") or ""
        emails.append({
            "email_id": row.get("email_id", ""),
            "sender": row.get("sender", ""),
            "subject": row.get("subject", ""),
            "sent_at": row.get("sent_at", ""),
            "content": content,
            "content_hash": _md5(content),
            "content_length": len(content),
        })
    return emails


async def dedupe_and_thread(
    db: AsyncSession,
    case_slug: str,
    emails: list[dict],
) -> dict:
    """Thread emails by normalized subject, detect terminals,
    return which email_ids should be vectorized vs skipped.

    Returns:
        {
            "threads_created": int,
            "total_emails": int,
            "exact_dupes_dropped": int,
            "terminal_ids": set[str],
            "duplicate_ids": set[str],
        }
    """
    seen_hashes: dict[str, str] = {}
    exact_dupes = 0
    unique_emails: list[dict] = []

    for em in emails:
        h = em["content_hash"]
        if h in seen_hashes:
            exact_dupes += 1
            continue
        seen_hashes[h] = em["email_id"]
        unique_emails.append(em)

    threads: dict[str, list[dict]] = {}
    for em in unique_emails:
        norm = _normalize_subject(em["subject"])
        if not norm:
            norm = f"_no_subject_{em['email_id']}"
        threads.setdefault(norm, []).append(em)

    terminal_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    threads_created = 0

    for norm_subject, members in threads.items():
        members.sort(key=lambda e: (e["content_length"], e.get("sent_at", "")), reverse=True)
        terminal = members[0]
        terminal_ids.add(terminal["email_id"])

        thread_id = str(uuid4())
        try:
            await db.execute(
                text("""
                    INSERT INTO legal.email_threads
                        (id, case_slug, normalized_subject, thread_size, terminal_email_id)
                    VALUES (:tid, :slug, :subj, :size, :term_id)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "tid": thread_id,
                    "slug": case_slug,
                    "subj": norm_subject[:1000],
                    "size": len(members),
                    "term_id": terminal["email_id"],
                },
            )

            for em in members:
                is_term = em["email_id"] == terminal["email_id"]
                if not is_term:
                    duplicate_ids.add(em["email_id"])
                sent_dt = _parse_date(em.get("sent_at"))
                await db.execute(
                    text("""
                        INSERT INTO legal.email_thread_members
                            (thread_id, email_id, sender, subject, sent_at,
                             content_hash, content_length, is_terminal, is_duplicate, status)
                        VALUES (:tid, :eid, :sender, :subj, :sent,
                                :hash, :clen, :is_term, :is_dup, :status)
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "tid": thread_id,
                        "eid": em["email_id"],
                        "sender": (em.get("sender") or "")[:500],
                        "subj": (em.get("subject") or "")[:1000],
                        "sent": sent_dt,
                        "hash": em["content_hash"],
                        "clen": em["content_length"],
                        "is_term": is_term,
                        "is_dup": not is_term,
                        "status": "terminal" if is_term else "duplicate_ignored",
                    },
                )

            threads_created += 1
        except Exception as exc:
            logger.warning("thread_insert_failed", subject=norm_subject[:80], error=str(exc)[:200])

    await db.commit()

    logger.info(
        "email_threading_complete",
        case_slug=case_slug,
        total=len(emails),
        unique=len(unique_emails),
        exact_dupes=exact_dupes,
        threads=threads_created,
        terminals=len(terminal_ids),
        duplicates=len(duplicate_ids),
    )

    return {
        "threads_created": threads_created,
        "total_emails": len(emails),
        "unique_after_md5": len(unique_emails),
        "exact_dupes_dropped": exact_dupes,
        "terminal_ids": terminal_ids,
        "duplicate_ids": duplicate_ids,
    }


async def should_vectorize_email(
    db: AsyncSession,
    case_slug: str,
    email_id: str,
    content_hash: str,
) -> bool:
    """Quick check: is this email a terminal in its thread?
    If no thread info exists yet, default to True (vectorize)."""
    r = await db.execute(
        text("""
            SELECT is_terminal FROM legal.email_thread_members
            WHERE email_id = :eid AND content_hash = :hash
            LIMIT 1
        """),
        {"eid": email_id, "hash": content_hash},
    )
    row = r.fetchone()
    if row is None:
        return True
    return bool(row[0])


def filter_terminal_emails(
    emails: list[dict],
    terminal_ids: set[str],
) -> list[dict]:
    """Return only the terminal emails from a parsed list."""
    return [e for e in emails if e["email_id"] in terminal_ids]
