#!/usr/bin/env python3
"""
Fortress Prime — Guest Conversation Training Data Builder
===========================================================
Extracts guest communications from email_archive, links them to
Streamline VRS properties/reservations, and populates the SMS platform
tables (message_archive, conversation_threads, guest_profiles) for
AI agent training.

DATA FLOW:
    email_archive (57K+ emails)
        |
        ├── Filter: cabin-specific + booking platform + guest reply threads
        |
        ├── Match: email content → ops_properties (by cabin name)
        |
        ├── Match: sender/subject → guest_leads (by email/name)
        |
        └── Output:
            ├── message_archive (enriched messages with property + reservation context)
            ├── conversation_threads (grouped by sender + property + time window)
            └── guest_profiles (enriched guest records)

USAGE:
    python3 -m src.build_guest_training_data                    # Full build
    python3 -m src.build_guest_training_data --dry-run          # Preview only
    python3 -m src.build_guest_training_data --cabin skyfall    # Single cabin
    python3 -m src.build_guest_training_data --stats            # Show stats only
"""

import sys
import os
import re
import hashlib
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

import psycopg2
import psycopg2.extras

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fortress.training_builder")


# =============================================================================
# INTENT CLASSIFICATION (rule-based for initial labeling)
# =============================================================================

INTENT_PATTERNS = {
    "checkin": [
        r"check.?in", r"early\s+(?:check|arrival)", r"what\s+time.*arrive",
        r"arrival\s+time", r"check.?in\s+instruc", r"door\s+code",
        r"access\s+code", r"lock.?box", r"keypad", r"how\s+(?:do|to)\s+(?:i\s+)?get\s+in",
    ],
    "checkout": [
        r"check.?out", r"(?:late|early)\s+check.?out", r"departure",
        r"leave\s+(?:by|before)", r"what\s+time.*leave", r"checkout\s+instruc",
    ],
    "wifi": [
        r"wi.?fi", r"wifi", r"internet", r"password.*(?:net|wifi|internet)",
        r"(?:net|wifi|internet).*password", r"can.t\s+connect",
    ],
    "directions": [
        r"direction", r"(?:how\s+to|how\s+do\s+i)\s+get\s+(?:to|there)",
        r"address", r"(?:gps|google)\s+map", r"find\s+(?:the|your)\s+(?:cabin|place)",
        r"lost", r"where\s+(?:is|are)\s+(?:you|the)",
    ],
    "maintenance": [
        r"broken", r"not\s+working", r"leak", r"doesn.t\s+work",
        r"repair", r"maintenance", r"fix", r"issue\s+with",
        r"problem\s+with", r"hot\s+tub.*(?:not|issue|problem|broken)",
        r"ac\s+(?:not|isn)", r"heat(?:er|ing)\s+(?:not|isn)",
    ],
    "amenities": [
        r"hot\s+tub", r"fire\s*(?:place|pit)", r"grill", r"pool\s+table",
        r"game\s+room", r"(?:washer|dryer|laundry)", r"towel", r"linen",
        r"kitchen", r"(?:dish|dishes)", r"coffee",
    ],
    "local_info": [
        r"restaurant", r"(?:things?\s+to|what\s+to)\s+do", r"hik(?:e|ing)",
        r"fish(?:ing)?", r"tubing", r"kayak", r"waterfall",
        r"downtown", r"blue\s+ridge", r"(?:grocery|store|shop)",
    ],
    "booking": [
        r"reserv(?:ation|e)", r"book(?:ing)?", r"availab(?:le|ility)",
        r"cancel(?:lation)?", r"modify", r"change\s+(?:my|the)\s+(?:date|reservation)",
        r"extend\s+(?:my|our)\s+stay", r"extra\s+night",
    ],
    "payment": [
        r"pay(?:ment)?", r"invoice", r"receipt", r"charge", r"refund",
        r"deposit", r"(?:credit|debit)\s+card", r"price",
        r"(?:how|what)\s+much", r"total\s+(?:cost|amount|due)",
    ],
    "pets": [
        r"(?:dog|cat|pet)", r"pet\s+(?:fee|policy|friendly|allow)",
        r"bring\s+(?:my|our|a)\s+(?:dog|pet)",
    ],
    "emergency": [
        r"emergenc", r"fire\s+(?!place|pit)", r"flood", r"carbon\s+monoxide",
        r"gas\s+(?:leak|smell)", r"power\s+out", r"no\s+(?:water|electric|power)",
        r"snake", r"bear", r"urgent",
    ],
    "feedback": [
        r"(?:great|wonderful|amazing|fantastic|excellent)\s+(?:stay|time|cabin|experience)",
        r"loved?\s+(?:the|it|our|your)", r"thank(?:s|\s+you)",
        r"review", r"recommend", r"come\s+back", r"return",
    ],
    "complaint": [
        r"disappoint", r"not\s+(?:clean|happy|satisfied)", r"dirty",
        r"complain", r"unaccept", r"terrible", r"worst",
        r"(?:want|need)\s+(?:a\s+)?refund",
    ],
}


def classify_intent(text: str) -> Tuple[str, float]:
    """Classify message intent using pattern matching."""
    text_lower = text.lower()
    scores = {}
    for intent, patterns in INTENT_PATTERNS.items():
        matches = sum(1 for p in patterns if re.search(p, text_lower))
        if matches > 0:
            scores[intent] = matches

    if not scores:
        return "general", 0.1

    best = max(scores, key=scores.get)
    confidence = min(scores[best] / 3.0, 1.0)
    return best, round(confidence, 3)


def classify_sentiment(text: str) -> str:
    """Basic sentiment classification."""
    text_lower = text.lower()
    positive = ["thank", "great", "wonderful", "amazing", "love", "perfect",
                "excellent", "fantastic", "beautiful", "recommend", "enjoy"]
    negative = ["disappoint", "broken", "dirty", "terrible", "worst", "complaint",
                "refund", "unacceptable", "not clean", "not happy", "problem"]
    urgent = ["emergency", "urgent", "fire", "flood", "gas leak", "help",
              "asap", "immediately", "right now", "dangerous"]

    pos = sum(1 for w in positive if w in text_lower)
    neg = sum(1 for w in negative if w in text_lower)
    urg = sum(1 for w in urgent if w in text_lower)

    if urg > 0:
        return "urgent"
    if neg > pos:
        return "negative"
    if pos > neg:
        return "positive"
    return "neutral"


# =============================================================================
# DATABASE
# =============================================================================

def get_conn():
    db_pass = (os.getenv("LEGAL_DB_PASS") or os.getenv("DB_PASS")
               or os.getenv("DB_PASSWORD") or os.getenv("ADMIN_DB_PASS") or "")
    return psycopg2.connect(dbname="fortress_db", user="admin", password=db_pass)


def load_properties(conn) -> Dict[str, Dict]:
    """Load active properties with Streamline IDs.
    Returns {property_id: {name, streamline_id, ...}}
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT property_id, internal_name, name, streamline_id,
               address, city, bedrooms, bathrooms, max_occupants,
               access_code_wifi, access_code_door
        FROM ops_properties
        WHERE status_name = 'Active'
    """)
    props = {}
    for row in cur.fetchall():
        props[row["property_id"]] = dict(row)
    cur.close()
    return props


def build_cabin_patterns(properties: Dict[str, Dict]) -> List[Tuple[re.Pattern, str]]:
    """Build regex patterns for cabin name matching."""
    patterns = []
    for pid, p in properties.items():
        name = p["internal_name"]
        words = name.split()
        if len(words) >= 2:
            pattern = r"\b" + r"\s+".join(re.escape(w) for w in words) + r"\b"
            patterns.append((re.compile(pattern, re.IGNORECASE), pid))
        pattern_simple = re.compile(re.escape(name), re.IGNORECASE)
        patterns.append((pattern_simple, pid))
    return patterns


def match_property(text: str, patterns: List[Tuple[re.Pattern, str]]) -> Optional[str]:
    """Match text against cabin name patterns. Returns property_id or None."""
    for pat, pid in patterns:
        if pat.search(text):
            return pid
    return None


# =============================================================================
# EMAIL EXTRACTION
# =============================================================================

def extract_guest_emails(conn, properties: Dict, cabin_patterns, cabin_filter: Optional[str] = None) -> List[Dict]:
    """Extract guest-relevant emails from email_archive."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cabin_names = [p["internal_name"] for p in properties.values()]
    cabin_like_clauses = " OR ".join([
        f"subject ILIKE '%{n}%' OR content ILIKE '%{n}%'"
        for n in cabin_names
    ])

    query = f"""
        SELECT id, sender, subject, content, sent_at, division, category, file_path
        FROM email_archive
        WHERE (
            ({cabin_like_clauses})
            OR sender ILIKE '%%airbnb%%'
            OR sender ILIKE '%%vrbo%%'
            OR sender ILIKE '%%homeaway%%'
            OR sender ILIKE '%%streamlinevrs%%'
            OR (
                subject ILIKE '%%Re:%%'
                AND (
                    subject ILIKE '%%check%%in%%'
                    OR subject ILIKE '%%reservation%%'
                    OR subject ILIKE '%%booking%%'
                    OR subject ILIKE '%%cabin%%'
                    OR subject ILIKE '%%stay%%'
                    OR subject ILIKE '%%guest%%'
                    OR subject ILIKE '%%rental%%agreement%%'
                )
            )
        )
        AND content IS NOT NULL
        AND LENGTH(content) > 20
        ORDER BY sent_at ASC
    """

    logger.info("Querying email_archive for guest conversations...")
    cur.execute(query)
    rows = cur.fetchall()
    cur.close()
    logger.info(f"Found {len(rows)} candidate emails")

    results = []
    for row in rows:
        text = f"{row['subject'] or ''} {(row['content'] or '')[:3000]}"

        property_id = match_property(text, cabin_patterns)
        if cabin_filter and property_id != cabin_filter:
            continue

        sender = row["sender"] or ""
        sender_email = sender
        sender_name = sender
        email_match = re.search(r"<([^>]+)>", sender)
        if email_match:
            sender_email = email_match.group(1).lower()
            sender_name = sender.split("<")[0].strip().strip('"').strip("'")
        elif "@" in sender:
            sender_email = sender.strip().lower()

        # Determine direction
        our_domains = [
            "cabin-rentals-of-georgia.com",
            "garyknight.com",
            "bookcrgluxury.com",
        ]
        direction = "inbound"
        for domain in our_domains:
            if domain in sender_email:
                direction = "outbound"
                break

        # Skip marketing / system emails
        skip_senders = [
            "noreply@", "no-reply@", "mailer-daemon",
            "marketing@", "newsletter@", "promotions@",
            "donotreply@", "notifications@",
        ]
        if any(s in sender_email.lower() for s in skip_senders):
            # But keep booking platform notifications
            if not any(p in sender_email for p in ["airbnb", "vrbo", "homeaway", "streamline"]):
                continue

        content = (row["content"] or "")[:5000]
        intent, confidence = classify_intent(f"{row['subject'] or ''} {content}")
        sentiment = classify_sentiment(f"{row['subject'] or ''} {content}")

        results.append({
            "email_id": row["id"],
            "sender_email": sender_email,
            "sender_name": sender_name,
            "subject": row["subject"] or "",
            "content": content,
            "sent_at": row["sent_at"],
            "direction": direction,
            "property_id": property_id,
            "cabin_name": properties[property_id]["internal_name"] if property_id else None,
            "streamline_id": properties[property_id]["streamline_id"] if property_id else None,
            "intent": intent,
            "intent_confidence": confidence,
            "sentiment": sentiment,
            "source": "email_archive",
        })

    logger.info(f"Extracted {len(results)} guest-relevant messages")
    return results


# =============================================================================
# GUEST PROFILE BUILDER
# =============================================================================

def build_guest_profiles(messages: List[Dict], conn) -> Dict[str, Dict]:
    """Build guest profiles from extracted messages."""
    profiles = defaultdict(lambda: {
        "name": None,
        "email": None,
        "total_messages": 0,
        "inbound": 0,
        "outbound": 0,
        "cabins": set(),
        "intents": defaultdict(int),
        "sentiments": defaultdict(int),
        "first_contact": None,
        "last_contact": None,
    })

    for msg in messages:
        email = msg["sender_email"]
        if not email or "@" not in email:
            continue

        p = profiles[email]
        p["email"] = email
        if msg["sender_name"] and msg["sender_name"] != email:
            p["name"] = msg["sender_name"]
        p["total_messages"] += 1
        if msg["direction"] == "inbound":
            p["inbound"] += 1
        else:
            p["outbound"] += 1
        if msg["cabin_name"]:
            p["cabins"].add(msg["cabin_name"])
        p["intents"][msg["intent"]] += 1
        p["sentiments"][msg["sentiment"]] += 1

        ts = msg["sent_at"]
        if ts:
            if p["first_contact"] is None or ts < p["first_contact"]:
                p["first_contact"] = ts
            if p["last_contact"] is None or ts > p["last_contact"]:
                p["last_contact"] = ts

    # Cross-reference with guest_leads
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT guest_name, guest_email, guest_phone FROM guest_leads WHERE guest_email IS NOT NULL AND guest_email != ''")
    leads = cur.fetchall()
    cur.close()

    lead_map = {}
    for lead in leads:
        if lead["guest_email"]:
            lead_map[lead["guest_email"].lower()] = lead

    for email, p in profiles.items():
        if email in lead_map:
            lead = lead_map[email]
            if lead.get("guest_name") and not p["name"]:
                p["name"] = lead["guest_name"]

    logger.info(f"Built {len(profiles)} guest profiles")
    return dict(profiles)


# =============================================================================
# CONVERSATION THREADING
# =============================================================================

def build_threads(messages: List[Dict]) -> List[Dict]:
    """Group messages into conversation threads by sender + property + time window."""
    threads = []
    thread_map = {}

    for msg in sorted(messages, key=lambda m: m["sent_at"] or datetime.min):
        key_parts = [
            msg["sender_email"] or "unknown",
            msg["property_id"] or "unknown",
        ]
        base_key = "|".join(key_parts)

        found_thread = None
        for tk, thread in thread_map.items():
            if tk.startswith(base_key):
                last_msg = thread["last_message_at"]
                if msg["sent_at"] and last_msg:
                    gap = abs((msg["sent_at"] - last_msg).total_seconds())
                    if gap < 7 * 86400:  # 7-day window
                        found_thread = thread
                        break

        if found_thread:
            found_thread["messages"].append(msg)
            found_thread["message_count"] += 1
            if msg["direction"] == "inbound":
                found_thread["inbound_count"] += 1
            else:
                found_thread["outbound_count"] += 1
            found_thread["last_message_at"] = msg["sent_at"]
        else:
            thread_key = f"{base_key}|{msg['sent_at'] or 'unknown'}"
            thread_hash = hashlib.md5(thread_key.encode()).hexdigest()
            new_thread = {
                "thread_hash": thread_hash,
                "phone_number": "",
                "property_id": msg["property_id"],
                "cabin_name": msg["cabin_name"],
                "sender_email": msg["sender_email"],
                "started_at": msg["sent_at"],
                "last_message_at": msg["sent_at"],
                "message_count": 1,
                "inbound_count": 1 if msg["direction"] == "inbound" else 0,
                "outbound_count": 1 if msg["direction"] == "outbound" else 0,
                "primary_intent": msg["intent"],
                "messages": [msg],
            }
            thread_map[thread_key] = new_thread
            threads.append(new_thread)

    logger.info(f"Built {len(threads)} conversation threads")
    return threads


# =============================================================================
# DATABASE POPULATION
# =============================================================================

def populate_message_archive(conn, messages: List[Dict], dry_run: bool = False) -> int:
    """Insert messages into message_archive."""
    if dry_run:
        logger.info(f"[DRY RUN] Would insert {len(messages)} messages into message_archive")
        return 0

    cur = conn.cursor()
    inserted = 0

    for msg in messages:
        try:
            cur.execute("""
                INSERT INTO message_archive (
                    source, external_id, phone_number, guest_name,
                    message_body, direction, sent_at,
                    property_id, cabin_name, reservation_id,
                    intent, intent_confidence, sentiment,
                    contains_question, extraction_method, extracted_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                )
                ON CONFLICT DO NOTHING
            """, (
                msg["source"],
                f"email_{msg['email_id']}",
                msg["sender_email"][:20] if msg["sender_email"] else "unknown",
                msg["sender_name"][:255] if msg["sender_name"] else None,
                msg["content"][:50000],
                msg["direction"],
                msg["sent_at"],
                None,  # integer property_id - will update with streamline mapping
                msg["cabin_name"],
                msg.get("streamline_id"),
                msg["intent"],
                msg["intent_confidence"],
                msg["sentiment"],
                "?" in (msg["subject"] or "") or "?" in (msg["content"] or "")[:500],
                "email_archive_extraction",
            ))
            inserted += 1
        except Exception as e:
            logger.warning(f"Insert error for email {msg['email_id']}: {e}")
            conn.rollback()
            continue

    conn.commit()
    cur.close()
    logger.info(f"Inserted {inserted} messages into message_archive")
    return inserted


def populate_guest_profiles(conn, profiles: Dict[str, Dict], dry_run: bool = False) -> int:
    """Insert/update guest profiles."""
    if dry_run:
        logger.info(f"[DRY RUN] Would upsert {len(profiles)} guest profiles")
        return 0

    cur = conn.cursor()
    upserted = 0

    for email, p in profiles.items():
        if not email or "@" not in email:
            continue

        overall_sentiment = max(p["sentiments"], key=p["sentiments"].get) if p["sentiments"] else "neutral"
        common_intents = sorted(p["intents"].keys(), key=lambda k: p["intents"][k], reverse=True)[:5]
        cabins = list(p["cabins"])[:10]

        try:
            cur.execute("""
                INSERT INTO guest_profiles (
                    phone_number, name, email,
                    total_messages, total_conversations,
                    common_intents, overall_sentiment,
                    total_stays, favorite_cabins,
                    first_contact, last_contact
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (phone_number) DO UPDATE SET
                    name = COALESCE(EXCLUDED.name, guest_profiles.name),
                    email = COALESCE(EXCLUDED.email, guest_profiles.email),
                    total_messages = EXCLUDED.total_messages,
                    common_intents = EXCLUDED.common_intents,
                    overall_sentiment = EXCLUDED.overall_sentiment,
                    favorite_cabins = EXCLUDED.favorite_cabins,
                    first_contact = LEAST(EXCLUDED.first_contact, guest_profiles.first_contact),
                    last_contact = GREATEST(EXCLUDED.last_contact, guest_profiles.last_contact),
                    updated_at = NOW()
            """, (
                email[:20],
                p["name"][:255] if p["name"] else None,
                email[:255],
                p["total_messages"],
                0,
                common_intents,
                overall_sentiment,
                len(cabins),
                cabins,
                p["first_contact"],
                p["last_contact"],
            ))
            upserted += 1
        except Exception as e:
            logger.warning(f"Guest profile error for {email}: {e}")
            conn.rollback()
            continue

    conn.commit()
    cur.close()
    logger.info(f"Upserted {upserted} guest profiles")
    return upserted


def populate_threads(conn, threads: List[Dict], dry_run: bool = False) -> int:
    """Insert conversation threads."""
    if dry_run:
        logger.info(f"[DRY RUN] Would insert {len(threads)} conversation threads")
        return 0

    cur = conn.cursor()
    inserted = 0

    for thread in threads:
        try:
            cur.execute("""
                INSERT INTO conversation_threads (
                    phone_number, property_id, thread_hash,
                    started_at, last_message_at,
                    message_count, inbound_count, outbound_count,
                    primary_intent, status, cabin_name
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (thread_hash) DO NOTHING
            """, (
                (thread["sender_email"] or "unknown")[:20],
                None,
                thread["thread_hash"],
                thread["started_at"],
                thread["last_message_at"],
                thread["message_count"],
                thread["inbound_count"],
                thread["outbound_count"],
                thread["primary_intent"],
                "resolved",
                thread["cabin_name"],
            ))
            inserted += 1
        except Exception as e:
            logger.warning(f"Thread insert error: {e}")
            conn.rollback()
            continue

    conn.commit()
    cur.close()
    logger.info(f"Inserted {inserted} conversation threads")
    return inserted


# =============================================================================
# PROPERTY SMS CONFIG SEEDING
# =============================================================================

def tag_role_model_responses(conn) -> Tuple[int, int]:
    """Tag only Taylor and Lissa outbound messages as approved training examples.
    All other outbound senders (Barbara, Gary, Brian, etc.) are excluded.
    """
    cur = conn.cursor()

    # Reset all training flags
    cur.execute("""
        UPDATE message_archive
        SET approved_for_fine_tuning = FALSE, used_for_training = FALSE, training_label = NULL
    """)

    # Tag Taylor responses
    cur.execute("""
        UPDATE message_archive
        SET approved_for_fine_tuning = TRUE, used_for_training = TRUE,
            training_label = 'taylor_response', human_reviewed = TRUE,
            human_reviewer = 'system_auto', response_generated_by = 'human'
        WHERE direction = 'outbound'
          AND (guest_name ILIKE '%%Taylor Knight%%' OR guest_name ILIKE '%%taylor.knight%%')
    """)
    taylor = cur.rowcount

    # Tag Lissa responses
    cur.execute("""
        UPDATE message_archive
        SET approved_for_fine_tuning = TRUE, used_for_training = TRUE,
            training_label = 'lissa_response', human_reviewed = TRUE,
            human_reviewer = 'system_auto', response_generated_by = 'human'
        WHERE direction = 'outbound'
          AND (guest_name ILIKE '%%Lissa Knight%%' OR guest_name ILIKE '%%Lissa CROG%%'
               OR guest_name ILIKE '%%lissa%%cabin-rentals%%')
    """)
    lissa = cur.rowcount

    # Tag inbound as training context
    cur.execute("""
        UPDATE message_archive
        SET used_for_training = TRUE, training_label = 'guest_input'
        WHERE direction = 'inbound'
    """)

    # Label other outbound as email-only staff (no RueBaRue access)
    # Barbara, Gary, Brian, Cynthia, Tara, etc. are email-only — they don't
    # handle guest SMS. Only Taylor and Lissa use RueBaRue for guest comms.
    cur.execute("""
        UPDATE message_archive
        SET training_label = 'email_only_not_sms', approved_for_fine_tuning = FALSE
        WHERE direction = 'outbound' AND approved_for_fine_tuning = FALSE
    """)

    conn.commit()
    cur.close()
    return taylor, lissa


def seed_property_config(conn, properties: Dict[str, Dict], dry_run: bool = False) -> int:
    """Seed property_sms_config from ops_properties."""
    if dry_run:
        logger.info(f"[DRY RUN] Would seed {len(properties)} property configs")
        return 0

    cur = conn.cursor()
    seeded = 0
    twilio_phone = os.getenv("TWILIO_PHONE_NUMBER", "+17064711479")

    for pid, p in properties.items():
        try:
            sid = int(p["streamline_id"]) if p.get("streamline_id") else None
            cur.execute("""
                INSERT INTO property_sms_config (
                    property_id, property_name, cabin_name,
                    assigned_phone_number, ai_enabled,
                    wifi_ssid, wifi_password, door_code, address,
                    timezone
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (property_id) DO UPDATE SET
                    property_name = EXCLUDED.property_name,
                    wifi_ssid = EXCLUDED.wifi_ssid,
                    wifi_password = EXCLUDED.wifi_password,
                    door_code = EXCLUDED.door_code,
                    updated_at = NOW()
            """, (
                sid or hash(pid) % 999999,
                p["internal_name"],
                p["internal_name"],
                twilio_phone,
                True,
                p.get("access_code_wifi"),
                p.get("access_code_wifi"),
                p.get("access_code_door"),
                p.get("address"),
                "America/New_York",
            ))
            seeded += 1
        except Exception as e:
            logger.warning(f"Config seed error for {pid}: {e}")
            conn.rollback()
            continue

    conn.commit()
    cur.close()
    logger.info(f"Seeded {seeded} property SMS configs")
    return seeded


# =============================================================================
# STATS
# =============================================================================

def print_stats(conn):
    """Print current database stats."""
    cur = conn.cursor()

    print("\n" + "=" * 65)
    print("  FORTRESS PRIME — GUEST TRAINING DATA STATUS")
    print("=" * 65)

    tables = [
        ("message_archive", "Messages"),
        ("conversation_threads", "Threads"),
        ("guest_profiles", "Guest Profiles"),
        ("property_sms_config", "Property Configs"),
        ("sms_providers", "SMS Providers"),
        ("ai_training_labels", "Training Labels"),
    ]
    for table, label in tables:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  {label:<25} {cur.fetchone()[0]:>8,}")

    # Intent distribution
    cur.execute("""
        SELECT intent, COUNT(*) FROM message_archive
        GROUP BY intent ORDER BY COUNT(*) DESC LIMIT 15
    """)
    rows = cur.fetchall()
    if rows:
        print(f"\n  Intent Distribution:")
        for intent, cnt in rows:
            bar = "█" * min(int(cnt / 50), 40)
            print(f"    {intent or 'unknown':<20} {cnt:>6,}  {bar}")

    # Sentiment distribution
    cur.execute("""
        SELECT sentiment, COUNT(*) FROM message_archive
        GROUP BY sentiment ORDER BY COUNT(*) DESC
    """)
    rows = cur.fetchall()
    if rows:
        print(f"\n  Sentiment Distribution:")
        for sent, cnt in rows:
            print(f"    {sent or 'unknown':<20} {cnt:>6,}")

    # Cabin distribution
    cur.execute("""
        SELECT cabin_name, COUNT(*) FROM message_archive
        WHERE cabin_name IS NOT NULL
        GROUP BY cabin_name ORDER BY COUNT(*) DESC
    """)
    rows = cur.fetchall()
    if rows:
        print(f"\n  Messages Per Cabin:")
        for cabin, cnt in rows:
            bar = "█" * min(int(cnt / 20), 40)
            print(f"    {cabin or 'unknown':<35} {cnt:>5,}  {bar}")

    # Direction
    cur.execute("""
        SELECT direction, COUNT(*) FROM message_archive
        GROUP BY direction
    """)
    rows = cur.fetchall()
    if rows:
        print(f"\n  Direction:")
        for d, cnt in rows:
            print(f"    {d:<20} {cnt:>6,}")

    print(f"\n{'=' * 65}\n")
    cur.close()


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Fortress Prime — Guest Training Data Builder")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no DB writes")
    parser.add_argument("--cabin", type=str, help="Filter to specific cabin (property_id)")
    parser.add_argument("--stats", action="store_true", help="Show current stats and exit")
    parser.add_argument("--reset", action="store_true", help="Clear all training data before rebuild")
    args = parser.parse_args()

    conn = get_conn()

    if args.stats:
        print_stats(conn)
        conn.close()
        return

    if args.reset and not args.dry_run:
        logger.info("Resetting training data tables...")
        cur = conn.cursor()
        cur.execute("TRUNCATE message_archive, conversation_threads, guest_profiles CASCADE")
        conn.commit()
        cur.close()
        logger.info("Tables cleared")

    banner = f"""
    ╔═══════════════════════════════════════════════════════════╗
    ║  FORTRESS PRIME — GUEST TRAINING DATA BUILDER             ║
    ║  Source: email_archive (57K+ emails)                      ║
    ║  Target: message_archive + guest_profiles + threads       ║
    ║  Mode: {'DRY RUN' if args.dry_run else 'LIVE BUILD':<12}                                   ║
    ║  Filter: {args.cabin or 'all cabins':<20}                         ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    logger.info(banner)

    # Load properties
    properties = load_properties(conn)
    logger.info(f"Loaded {len(properties)} active properties")
    cabin_patterns = build_cabin_patterns(properties)

    # Seed property SMS configs
    seed_property_config(conn, properties, dry_run=args.dry_run)

    # Extract guest emails
    messages = extract_guest_emails(conn, properties, cabin_patterns, cabin_filter=args.cabin)

    if not messages:
        logger.warning("No guest messages found. Check email_archive.")
        conn.close()
        return

    # Build profiles
    profiles = build_guest_profiles(messages, conn)

    # Build conversation threads
    threads = build_threads(messages)

    # Populate database
    msg_count = populate_message_archive(conn, messages, dry_run=args.dry_run)
    profile_count = populate_guest_profiles(conn, profiles, dry_run=args.dry_run)
    thread_count = populate_threads(conn, threads, dry_run=args.dry_run)

    # Tag role model responses (Taylor + Lissa only)
    if not args.dry_run:
        logger.info("Applying role model filter (Taylor + Lissa only)...")
        taylor, lissa = tag_role_model_responses(conn)
        logger.info(f"Tagged {taylor} Taylor + {lissa} Lissa responses as approved")

    # Print summary
    print("\n" + "=" * 65)
    print("  BUILD COMPLETE")
    print("=" * 65)
    print(f"  Emails scanned:      {len(messages):>8,}")
    print(f"  Messages archived:   {msg_count:>8,}")
    print(f"  Guest profiles:      {profile_count:>8,}")
    print(f"  Conv. threads:       {thread_count:>8,}")
    print(f"  Properties seeded:   {len(properties):>8}")
    print("=" * 65)

    if not args.dry_run:
        print_stats(conn)

    conn.close()


if __name__ == "__main__":
    main()
