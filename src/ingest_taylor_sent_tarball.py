#!/usr/bin/env python3
"""
ingest_taylor_sent_tarball.py — One-shot ingestion of Taylor's sent-mail corpus
into the fgp_sent_mail Qdrant collection.

Source: 605MB cPanel Maildir backup on NAS containing taylor.knight@ sent history.
Target: fgp_sent_mail on spark-2 Qdrant (127.0.0.1:6333), 768-dim Cosine.

Design:
  - Stream-reads the tarball via tarfile; never extracts 605MB to disk
  - Filters: 2022-01-01 cutoff, body >= 50 chars, external recipient, taylor@ only
  - Embeds bodies in batches of 50 via nomic-embed-text
  - Upserts with point id = deterministic UUID from message_id (idempotent)
  - Logs UIDs and counts only — no body text in logs

Usage:
  python3 -m src.ingest_taylor_sent_tarball
  python3 -m src.ingest_taylor_sent_tarball --dry-run
  python3 -m src.ingest_taylor_sent_tarball --tarball /path/to/other.tar.gz
  python3 -m src.ingest_taylor_sent_tarball --since 2023-01-01
"""
from __future__ import annotations

import argparse
import email
import email.policy
import hashlib
import json
import logging
import re
import sys
import tarfile
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Optional

import httpx

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"tarball_ingest"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("tarball_ingest")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TARBALL_DEFAULT = (
    "/mnt/fortress_nas/Communications/System_MailPlus_Server/"
    "ENTERPRISE_DATA_LAKE/01_LANDING_ZONE/RAW_EMAIL_DUMP/"
    "download_cabinre_1769945883_38809.tar.gz"
)
SENT_PREFIX = "backup/email/cabin-rentals-of-georgia.com/taylor.knight/.Sent/cur/"
INTERNAL_DOMAIN = "cabin-rentals-of-georgia.com"
KNOWN_SENDERS = ("taylor.knight@cabin-rentals-of-georgia.com",)
SINCE_DEFAULT = datetime(2022, 1, 1, tzinfo=timezone.utc)

QDRANT_URL = "http://127.0.0.1:6333"
COLLECTION = "fgp_sent_mail"
VECTOR_DIM = 768

EMBED_URL = "http://192.168.0.106:11434/api/embeddings"  # spark-4 (spark-2 GPU busy)
EMBED_MODEL = "nomic-embed-text"
EMBED_BATCH = 50
EMBED_TIMEOUT = 30

# ---------------------------------------------------------------------------
# Topic classification
# ---------------------------------------------------------------------------

_TOPIC_RULES = [
    ("availability",        r"\b(availab|open dates?|calendar|memorial day|labor day|thanksgiving|holiday|weekend|check.?in|check.?out|dates?)\b"),
    ("pricing",             r"\b(rate|price|cost|quote|discount|deal|fee|deposit|refund|how much)\b"),
    ("amenity_question",    r"\b(hot tub|pool|fireplace|grill|wifi|wi.fi|parking|pet|dog|tv|game room|kayak|boat|fire pit)\b"),
    ("group_booking",       r"\b(group|family|reunion|wedding|bachelorette|bachelor|birthday|corporate|retreat|team|party of)\b"),
    ("pet_inquiry",         r"\b(pet.?friendly|dog|cat|animal|bring.*dog|dog.*allowed)\b"),
    ("check_in_logistics",  r"\b(check.?in|arrival|directions?|access code|door code|key|gate)\b"),
    ("confirmation",        r"\b(confirm|reservation|booking|receipt|booked|paid|payment)\b"),
    ("complaint_response",  r"\b(complaint|issue|problem|sorry|apologize|refund|disappoint|concern)\b"),
    ("policy",              r"\b(policy|cancel|cancellation|rule|contract|agreement|minimum|nights?)\b"),
]

def _detect_topic(body: str) -> str:
    b = body.lower()
    for topic, pattern in _TOPIC_RULES:
        if re.search(pattern, b, re.I):
            return topic
    return "other"

# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _dh(v: object) -> str:
    if not v:
        return ""
    try:
        return str(make_header(decode_header(str(v))))
    except Exception:
        return str(v)


def _to_str(v: object) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    return str(v) if v else ""


def _strip_quotes(body: str) -> str:
    result = []
    for line in body.splitlines():
        s = line.strip()
        if re.match(r"^On .{5,100}wrote:\s*$", s, re.I):
            break
        if not s.startswith(">"):
            result.append(line)
    return "\n".join(result).strip()


def _body_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                part.get("Content-Disposition", "")
            ):
                try:
                    return _to_str(part.get_payload(decode=True))
                except Exception:
                    return ""
    pl = msg.get_payload(decode=True)
    return _to_str(pl) if pl else ""


def _msg_id_to_uuid(message_id: str) -> str:
    h = hashlib.md5(message_id.encode("utf-8"), usedforsecurity=False).digest()
    return str(uuid.UUID(bytes=h))

# ---------------------------------------------------------------------------
# Qdrant helpers (synchronous — ingest script is not async)
# ---------------------------------------------------------------------------

def _qdrant_collection_exists(name: str) -> bool:
    try:
        r = httpx.get(f"{QDRANT_URL}/collections/{name}", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _create_collection(name: str) -> None:
    payload = {
        "vectors": {"size": VECTOR_DIM, "distance": "Cosine"},
        "on_disk_payload": True,
    }
    r = httpx.put(f"{QDRANT_URL}/collections/{name}", json=payload, timeout=10)
    r.raise_for_status()
    log.info("qdrant_collection_created name=%s", name)


def _upsert_batch(points: list[dict]) -> tuple[int, int]:
    """Upsert a batch of points. Returns (upserted, failed)."""
    payload = {"points": points}
    try:
        r = httpx.put(
            f"{QDRANT_URL}/collections/{COLLECTION}/points?wait=false",
            json=payload,
            timeout=30,
        )
        if r.status_code in (200, 201):
            return len(points), 0
        log.warning("qdrant_upsert_failed status=%d body=%s", r.status_code, r.text[:200])
        return 0, len(points)
    except Exception as exc:
        log.warning("qdrant_upsert_exception error=%s", str(exc)[:200])
        return 0, len(points)

# ---------------------------------------------------------------------------
# Embed helpers
# ---------------------------------------------------------------------------

def _embed_batch(texts: list[str]) -> list[Optional[list[float]]]:
    results: list[Optional[list[float]]] = []
    for text in texts:
        try:
            r = httpx.post(
                EMBED_URL,
                json={"model": EMBED_MODEL, "prompt": text[:8000]},
                timeout=EMBED_TIMEOUT,
            )
            r.raise_for_status()
            emb = r.json().get("embedding", [])
            results.append(emb if len(emb) == VECTOR_DIM else None)
        except Exception as exc:
            log.warning("embed_failed error=%s", str(exc)[:120])
            results.append(None)
    return results

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(tarball: str, since: datetime, dry_run: bool) -> None:
    t0 = time.perf_counter()
    log.info("starting tarball=%s since=%s dry_run=%s", tarball, since.date(), dry_run)

    # Ensure collection exists
    if not dry_run:
        if not _qdrant_collection_exists(COLLECTION):
            _create_collection(COLLECTION)
        else:
            log.info("collection_exists name=%s", COLLECTION)

    # --- Pass 1: collect qualifying emails ---
    records: list[dict] = []
    rej = Counter()

    with tarfile.open(tarball, "r:gz") as tf:
        for member in tf.getmembers():
            if not (member.name.startswith(SENT_PREFIX) and member.isfile()):
                continue
            f = tf.extractfile(member)
            if f is None:
                rej["unreadable"] += 1
                continue
            try:
                msg = email.message_from_bytes(f.read(), policy=email.policy.compat32)
            except Exception:
                rej["parse_error"] += 1
                continue

            # Sender filter
            _, sa = parseaddr(_dh(msg.get("From", "")))
            if not any(k in sa.lower() for k in KNOWN_SENDERS):
                rej["wrong_sender"] += 1
                continue

            # Auto-responder filter
            subj_low = _dh(msg.get("Subject", "")).lower()
            auto = str(msg.get("Auto-Submitted", "")).lower()
            if (auto and auto != "no") or any(
                p in subj_low for p in ("out of office", "auto-reply", "automatic reply")
            ):
                rej["auto_responder"] += 1
                continue

            # Date filter
            date_str = _dh(msg.get("Date", ""))
            sent_at: Optional[datetime] = None
            sent_at_epoch: int = 0
            if date_str:
                try:
                    sent_at = parsedate_to_datetime(date_str)
                    if sent_at.tzinfo is None:
                        sent_at = sent_at.replace(tzinfo=timezone.utc)
                    sent_at_epoch = int(sent_at.timestamp())
                except Exception:
                    pass
            if sent_at is None or sent_at < since:
                rej["before_cutoff"] += 1
                continue

            # External recipient filter
            recipients = _dh(msg.get("To", "")) + "," + _dh(msg.get("Cc", ""))
            extern = [
                parseaddr(a)[1].lower()
                for a in recipients.split(",")
                if "@" in a and INTERNAL_DOMAIN not in a.lower()
            ]
            if not extern:
                rej["all_internal"] += 1
                continue

            # Body filter
            body = _strip_quotes(_body_text(msg))
            if len(body) < 50:
                rej["body_short"] += 1
                continue

            message_id = (
                str(msg.get("Message-ID", "") or "").strip("<>").strip()
                or f"no-id-{member.name}"
            )
            in_reply_to = (
                str(msg.get("In-Reply-To", "") or "").strip("<>").strip() or None
            )
            subject = _dh(msg.get("Subject", ""))
            topic = _detect_topic(body)

            records.append(
                {
                    "point_id": _msg_id_to_uuid(message_id),
                    "message_id": message_id,
                    "subject": subject,
                    "body": body,
                    "body_length": len(body),
                    "sent_to": extern[0] if extern else "",
                    "sent_at": sent_at.isoformat(),
                    "sent_at_epoch": sent_at_epoch,
                    "detected_topic": topic,
                    "source": "taylor_sent_tarball_2022_2026",
                    "in_reply_to": in_reply_to,
                }
            )

    log.info(
        "preflight_complete total_qualifying=%d rejected=%s",
        len(records),
        dict(rej),
    )

    if dry_run:
        topic_dist = Counter(r["detected_topic"] for r in records)
        log.info("dry_run_topic_distribution %s", dict(topic_dist))
        log.info("dry_run complete — no writes performed")
        return

    # --- Pass 2: embed + upsert in batches ---
    total_upserted = 0
    total_embed_failed = 0
    total_qdrant_failed = 0
    topic_dist = Counter()

    for i in range(0, len(records), EMBED_BATCH):
        batch = records[i : i + EMBED_BATCH]
        texts = [r["body"] for r in batch]
        vectors = _embed_batch(texts)

        points = []
        for rec, vec in zip(batch, vectors):
            if vec is None:
                total_embed_failed += 1
                continue
            points.append(
                {
                    "id": rec["point_id"],
                    "vector": vec,
                    "payload": {
                        k: v
                        for k, v in rec.items()
                        if k not in ("point_id", "body")  # don't store full body in log; do store in Qdrant
                    } | {"body": rec["body"]},
                }
            )
            topic_dist[rec["detected_topic"]] += 1

        upserted, failed = _upsert_batch(points)
        total_upserted += upserted
        total_qdrant_failed += failed

        pct = min(100, int((i + len(batch)) / len(records) * 100))
        log.info("progress %d%% — batch %d/%d upserted=%d", pct, i // EMBED_BATCH + 1, (len(records) + EMBED_BATCH - 1) // EMBED_BATCH, total_upserted)

    elapsed = time.perf_counter() - t0
    log.info(
        "ingest_complete upserted=%d embed_failed=%d qdrant_failed=%d elapsed=%.1fs",
        total_upserted, total_embed_failed, total_qdrant_failed, elapsed,
    )
    log.info("topic_distribution %s", dict(topic_dist))
    log.info("rejection_summary %s", dict(rej))


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest Taylor sent-mail tarball into fgp_sent_mail")
    ap.add_argument("--tarball", default=TARBALL_DEFAULT)
    ap.add_argument("--since", default="2022-01-01", help="ISO date cutoff (inclusive)")
    ap.add_argument("--dry-run", action="store_true", help="Parse + filter only; no writes")
    args = ap.parse_args()

    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    try:
        run(tarball=args.tarball, since=since, dry_run=args.dry_run)
    except Exception as exc:
        log.error("ingest_failed error=%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
