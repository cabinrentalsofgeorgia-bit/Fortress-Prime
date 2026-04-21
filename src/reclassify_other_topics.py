#!/usr/bin/env python3
"""
reclassify_other_topics.py — LLM-based reclassification of fgp_sent_mail
points whose detected_topic is 'other'.

Uses qwen2.5:7b on spark-4 (confirmed working) to classify each email's
subject + first 300 chars of body into a richer topic taxonomy.  Updates
Qdrant payloads in place.

Extended taxonomy (adds to existing guest-facing topics):
  Guest-facing (original):
    availability, pricing, amenity_question, group_booking, pet_inquiry,
    check_in_logistics, confirmation, complaint_response, policy

  Added (covers the 'other' bucket patterns):
    proactive_followup  — outbound follow-up to a guest lead
    firewood_add_on     — firewood / amenity add-on upsell
    owner_comms         — owner portal, charges, statements
    ops_support         — PMS tickets, Airbnb/VRBO issues, IT support
    vendor_comms        — marketing vendors, web dev, contractors
    internal            — internal team coordination, hiring
    corporate_inquiry   — corporate retreat, team offsite inquiries
    other               — genuinely unclassifiable

Usage:
  python3 -m src.reclassify_other_topics --dry-run
  python3 -m src.reclassify_other_topics
  python3 -m src.reclassify_other_topics --limit 50
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "fortress-guest-platform" / ".env", override=False)
load_dotenv(Path(__file__).parent.parent / ".env", override=False)

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"reclassify"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("reclassify")

QDRANT_URL = "http://127.0.0.1:6333"
COLLECTION = "fgp_sent_mail"

EMBED_URL = "http://192.168.0.106:11434"  # spark-4 Ollama base
MODEL = "qwen2.5:7b"

VALID_TOPICS = {
    "availability", "pricing", "amenity_question", "group_booking",
    "pet_inquiry", "check_in_logistics", "confirmation", "complaint_response",
    "policy", "proactive_followup", "firewood_add_on", "owner_comms",
    "ops_support", "vendor_comms", "internal", "corporate_inquiry", "other",
}

_CLASSIFY_SYSTEM = (
    "You classify emails sent by a vacation rental company. "
    "Output ONLY one topic label from this exact list:\n"
    "availability, pricing, amenity_question, group_booking, pet_inquiry, "
    "check_in_logistics, confirmation, complaint_response, policy, "
    "proactive_followup, firewood_add_on, owner_comms, ops_support, "
    "vendor_comms, internal, corporate_inquiry, other\n\n"
    "Definitions (brief):\n"
    "  availability — guest asking about open dates or calendar\n"
    "  pricing — rates, quotes, fees, discounts\n"
    "  amenity_question — hot tub, grill, wifi, fireplace, etc.\n"
    "  group_booking — family reunions, large groups, weddings\n"
    "  pet_inquiry — dog/cat/animal questions\n"
    "  check_in_logistics — arrival, door codes, directions\n"
    "  confirmation — booking confirmed, receipt, payment received\n"
    "  complaint_response — apology, issue resolution, refund\n"
    "  policy — cancellation, rules, contract, minimum nights\n"
    "  proactive_followup — outbound follow-up to a guest lead\n"
    "  firewood_add_on — firewood delivery or other amenity add-on upsell\n"
    "  owner_comms — owner portal, owner charges, owner statements\n"
    "  ops_support — PMS tickets, OTA platform issues, IT support\n"
    "  vendor_comms — marketing, web dev, contractors, vendors\n"
    "  internal — team coordination, hiring, internal ops\n"
    "  corporate_inquiry — corporate retreat, team offsite\n"
    "  other — genuinely unclassifiable\n\n"
    "Output exactly one label, nothing else."
)


async def _classify(subject: str, body: str) -> str:
    import httpx
    user = f"Subject: {subject[:100]}\nBody: {body[:300]}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{EMBED_URL}/api/chat",
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": _CLASSIFY_SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 10},
                },
            )
            resp.raise_for_status()
            raw = (resp.json().get("message", {}).get("content") or "").strip().lower()
            # Extract first word in case model adds punctuation
            label = raw.split()[0].rstrip(".,;") if raw else "other"
            return label if label in VALID_TOPICS else "other"
    except Exception as exc:
        log.warning("classify_failed subj=%s err=%s", subject[:40], str(exc)[:80])
        return "other"


async def _scroll_other_points(limit: Optional[int]) -> list[dict]:
    import httpx
    points = []
    offset = None
    while True:
        body: dict = {
            "filter": {"must": [{"key": "detected_topic", "match": {"value": "other"}}]},
            "limit": 100,
            "with_payload": True,
            "with_vector": False,
        }
        if offset:
            body["offset"] = offset
        resp = httpx.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
            json=body, timeout=10,
        )
        result = resp.json().get("result", {})
        batch = result.get("points", [])
        points.extend(batch)
        offset = result.get("next_page_offset")
        if not offset or (limit and len(points) >= limit):
            break
    if limit:
        points = points[:limit]
    return points


def _update_payload(point_id: str, new_topic: str) -> bool:
    import httpx
    try:
        resp = httpx.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/payload",
            json={"payload": {"detected_topic": new_topic}, "points": [point_id]},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


async def run(dry_run: bool, limit: Optional[int]) -> None:
    log.info("fetching other-topic points dry_run=%s limit=%s", dry_run, limit)
    points = await _scroll_other_points(limit)
    log.info("found_other count=%d", len(points))

    if not points:
        log.info("nothing_to_reclassify")
        return

    changed = Counter()
    unchanged = 0
    failed = 0
    t0 = time.perf_counter()

    for pt in points:
        pid = pt["id"]
        pay = pt.get("payload", {})
        subject = pay.get("subject", "")
        body = pay.get("body", "")

        new_topic = await _classify(subject, body)
        changed[new_topic] += 1

        if new_topic == "other":
            unchanged += 1
            continue

        if dry_run:
            log.info("dry_run id=%s subject=%s → %s", str(pid)[:8], subject[:50], new_topic)
        else:
            ok = _update_payload(str(pid), new_topic)
            if not ok:
                log.warning("update_failed id=%s", str(pid)[:8])
                failed += 1

    elapsed = time.perf_counter() - t0
    log.info(
        "complete total=%d unchanged=%d failed=%d elapsed=%.1fs",
        len(points), unchanged, failed, elapsed,
    )
    log.info("new_topic_distribution %s", dict(sorted(changed.items(), key=lambda x: -x[1])))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    try:
        asyncio.run(run(dry_run=args.dry_run, limit=args.limit))
    except Exception as exc:
        log.error("fatal error=%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
