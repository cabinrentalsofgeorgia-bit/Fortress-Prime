#!/usr/bin/env python3
"""
Fortress Prime — AI Guest Agent
=================================
The brain of the guest communication system. Processes incoming guest messages,
retrieves relevant knowledge, generates AI drafts, and queues them for review.

Pipeline:
    Message In -> Classify Intent -> Retrieve Knowledge -> Build Context
              -> Generate AI Draft -> Queue for Review -> (Taylor approves) -> Send

Architecture:
    - SWARM mode (qwen2.5:7b) for fast responses
    - HYDRA mode (deepseek-r1:70b) for complex/escalation cases
    - PostgreSQL knowledge retrieval (property config, KB, message history)
    - Review queue with web dashboard for Taylor

Usage:
    # Process a single message
    from src.guest_agent import GuestAgent
    agent = GuestAgent()
    result = agent.process_message("+17065551234", "What's the WiFi password?")

    # CLI test
    python src/guest_agent.py --phone "+17065551234" --message "What's the WiFi?"
    python src/guest_agent.py --demo
"""

import sys
import os
import json
import time
import re
import logging
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("guest_agent")

DB_URL = os.getenv("DATABASE_URL", "")
if not DB_URL:
    _db_host = os.getenv("DB_HOST", "localhost")
    _db_port = os.getenv("DB_PORT", "5432")
    _db_name = os.getenv("DB_NAME", "fortress_db")
    _db_user = os.getenv("DB_USER", "miner_bot")
    _db_pass = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", ""))
    if _db_pass:
        DB_URL = f"postgresql://{_db_user}:{_db_pass}@{_db_host}:{_db_port}/{_db_name}"
    else:
        DB_URL = f"postgresql://{_db_user}@{_db_host}:{_db_port}/{_db_name}"


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class IntentResult:
    primary: str = "GENERAL"
    confidence: float = 0.5
    secondary: List[str] = field(default_factory=list)
    sentiment: str = "neutral"
    urgency: int = 1
    escalation_required: bool = False
    escalation_reason: str = ""


@dataclass
class KnowledgeContext:
    property_info: str = ""
    knowledge_articles: List[Dict] = field(default_factory=list)
    templates: List[Dict] = field(default_factory=list)
    conversation_history: List[Dict] = field(default_factory=list)
    guest_profile: Dict = field(default_factory=dict)
    area_guide: List[Dict] = field(default_factory=list)
    taylor_voice: List[str] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)


@dataclass
class AgentResult:
    phone_number: str = ""
    guest_name: str = ""
    cabin_name: str = ""
    guest_message: str = ""
    intent: IntentResult = field(default_factory=IntentResult)
    knowledge: KnowledgeContext = field(default_factory=KnowledgeContext)
    ai_draft: str = ""
    ai_model: str = ""
    duration_ms: float = 0.0
    confidence_score: float = 0.0
    queue_id: Optional[int] = None
    success: bool = False
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════
# INTENT CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════

INTENT_RULES = {
    "CHECKIN": {
        "keywords": ["check in", "checkin", "check-in", "arrival", "door code",
                     "access code", "key", "lockbox", "what time", "early check"],
        "urgency": 3,
    },
    "CHECKOUT": {
        "keywords": ["check out", "checkout", "check-out", "departure", "leaving",
                     "late checkout", "late check-out"],
        "urgency": 2,
    },
    "WIFI": {
        "keywords": ["wifi", "wi-fi", "password", "internet", "network", "connect"],
        "urgency": 2,
    },
    "DIRECTIONS": {
        "keywords": ["directions", "how to get", "address", "location", "gps",
                     "lost", "find the cabin", "where is", "navigate"],
        "urgency": 2,
    },
    "MAINTENANCE": {
        "keywords": ["broken", "not working", "doesn't work", "doesnt work",
                     "problem", "issue", "heat", "ac", "air condition",
                     "hot water", "no water", "cold water", "leak", "leaking",
                     "pipe", "clogged", "toilet", "toliet", "toilette",
                     "plumbing", "drain", "faucet", "sink", "shower",
                     "power", "electricity", "lights", "light out",
                     "flush", "won't flush", "overflowing", "overflow",
                     "stove", "oven", "dishwasher", "disposal", "washer",
                     "dryer", "furnace", "thermostat", "smoke detector"],
        "urgency": 4,
    },
    "EMERGENCY": {
        "keywords": ["emergency", "911", "fire", "flood", "flooding",
                     "gas smell", "smell gas", "smell of gas", "gas leak",
                     "carbon monoxide", "co detector", "intruder",
                     "medical", "ambulance", "police", "someone broke in",
                     "break in", "tree fell", "tree on", "roof collapse",
                     "no heat freezing", "pipe burst", "burst pipe",
                     "electrical fire", "sparking", "smoke"],
        "urgency": 5,
    },
    "AMENITIES": {
        "keywords": ["hot tub", "pool", "grill", "bbq", "fireplace", "tv",
                     "remote", "towels", "linens", "dishes", "game room",
                     "ping pong", "board games", "dvd"],
        "urgency": 1,
    },
    "PETS": {
        "keywords": ["pet", "dog", "cat", "animal", "pet fee", "pet friendly",
                     "pet-friendly", "bring my dog"],
        "urgency": 1,
    },
    "LOCAL_TIPS": {
        "keywords": ["restaurant", "eat", "food", "grocery", "store", "hike",
                     "hiking", "waterfall", "things to do", "activities",
                     "fishing", "tubing", "rafting", "winery", "vineyard",
                     "downtown", "blue ridge"],
        "urgency": 1,
    },
    "BOOKING": {
        "keywords": ["book", "reserve", "reservation", "cancel", "modify",
                     "dates", "availability", "price", "rate", "cost",
                     "discount", "extend", "stay longer"],
        "urgency": 2,
    },
    "NOISE_COMPLAINT": {
        "keywords": ["noise", "loud", "quiet hours", "neighbors", "party"],
        "urgency": 3,
    },
    "COMPLIMENT": {
        "keywords": ["amazing", "wonderful", "beautiful", "love", "perfect",
                     "thank you so much", "incredible", "best cabin", "great time"],
        "urgency": 1,
    },
}

ESCALATION_INTENTS = {"EMERGENCY", "NOISE_COMPLAINT"}
ESCALATION_KEYWORDS = ["refund", "lawyer", "legal", "complaint", "health department",
                       "better business", "sue", "compensation", "unacceptable"]


def classify_intent(message: str) -> IntentResult:
    """Rule-based intent classification with confidence scoring."""
    body = message.lower().strip()
    result = IntentResult()
    scores = {}

    for intent, rules in INTENT_RULES.items():
        hits = sum(1 for kw in rules["keywords"] if kw in body)
        if hits > 0:
            scores[intent] = hits

    if scores:
        sorted_intents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        result.primary = sorted_intents[0][0]
        total_hits = sum(scores.values())
        result.confidence = min(sorted_intents[0][1] / max(total_hits, 1), 0.99)
        if len(sorted_intents) > 1:
            result.secondary = [s[0] for s in sorted_intents[1:3]]

    result.urgency = INTENT_RULES.get(result.primary, {}).get("urgency", 1)

    # Sentiment detection
    negative = ["angry", "upset", "frustrated", "disappointed", "terrible",
                "awful", "horrible", "worst", "disgusted", "unacceptable"]
    positive = ["thank", "great", "amazing", "wonderful", "love", "perfect",
                "awesome", "excellent", "beautiful", "fantastic"]
    urgent = ["help", "emergency", "asap", "immediately", "urgent", "now"]

    neg_count = sum(1 for w in negative if w in body)
    pos_count = sum(1 for w in positive if w in body)
    urg_count = sum(1 for w in urgent if w in body)

    if urg_count >= 2 or result.primary == "EMERGENCY":
        result.sentiment = "urgent"
        result.urgency = max(result.urgency, 4)
    elif neg_count > pos_count:
        result.sentiment = "negative"
        result.urgency = max(result.urgency, 3)
    elif pos_count > neg_count:
        result.sentiment = "positive"
    else:
        result.sentiment = "neutral"

    # Escalation check
    if result.primary in ESCALATION_INTENTS:
        result.escalation_required = True
        result.escalation_reason = f"Auto-escalate: {result.primary} intent"
    if any(kw in body for kw in ESCALATION_KEYWORDS):
        result.escalation_required = True
        result.escalation_reason = "Escalation keyword detected"

    return result


# ═══════════════════════════════════════════════════════════════════════
# KNOWLEDGE RETRIEVER
# ═══════════════════════════════════════════════════════════════════════

class KnowledgeRetriever:
    """Retrieves relevant context from the database for the AI agent."""

    def __init__(self, db_url: str = DB_URL):
        self.db_url = db_url

    def _conn(self):
        return psycopg2.connect(self.db_url, cursor_factory=RealDictCursor)

    def get_property_context(self, cabin_name: str) -> str:
        """Get full property details from property_sms_config + ops_properties."""
        if not cabin_name:
            return "(No property identified for this guest)"

        conn = self._conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT property_name, address, wifi_password, door_code,
                   checkin_instructions, house_rules, welcome_message_template,
                   checkout_reminder_template, wifi_info_template,
                   emergency_contact, escalation_phone
            FROM property_sms_config
            WHERE property_name = %s
        """, (cabin_name,))
        prop = cur.fetchone()

        if not prop:
            conn.close()
            return f"(No config found for property: {cabin_name})"

        # Get Streamline details
        cur.execute("""
            SELECT bedrooms, bathrooms, max_occupants, max_pets,
                   description_short, access_code_wifi, access_code_door,
                   latitude, longitude, location_area_name
            FROM ops_properties
            WHERE internal_name = %s AND status_name = 'Active'
        """, (cabin_name,))
        sl = cur.fetchone()
        conn.close()

        lines = [f"Property: {prop['property_name']}"]
        if prop.get("address") and prop["address"] != "Address":
            lines.append(f"Address: {prop['address']}")
        if prop.get("wifi_password"):
            lines.append(f"WiFi Password: {prop['wifi_password']}")
        if prop.get("door_code"):
            lines.append(f"Door Code: {prop['door_code']}")
        if prop.get("emergency_contact"):
            lines.append(f"Emergency Contact: {prop['emergency_contact']}")
        if prop.get("escalation_phone"):
            lines.append(f"Manager Phone: {prop['escalation_phone']}")

        if sl:
            if sl.get("bedrooms"):
                lines.append(f"Bedrooms: {int(sl['bedrooms'])}, Bathrooms: {sl['bathrooms']}")
            if sl.get("max_occupants"):
                lines.append(f"Max Guests: {int(sl['max_occupants'])}")
            if sl.get("max_pets"):
                lines.append(f"Max Pets: {int(sl['max_pets'])}")
            else:
                lines.append("Pets: Not allowed")
            if sl.get("description_short"):
                lines.append(f"Description: {sl['description_short'][:300]}")

        if prop.get("checkin_instructions"):
            lines.append(f"\nCheck-in Instructions:\n{prop['checkin_instructions'][:500]}")
        if prop.get("house_rules"):
            lines.append(f"\nHouse Rules:\n{prop['house_rules'][:500]}")

        return "\n".join(lines)

    def search_knowledge_base(self, query: str, cabin_name: str = None, limit: int = 5) -> List[Dict]:
        """Search the RueBaRue knowledge base for relevant articles."""
        conn = self._conn()
        cur = conn.cursor()

        words = [w for w in query.lower().split() if len(w) > 2]
        if not words:
            conn.close()
            return []

        like_clauses = " OR ".join(["content ILIKE %s" for _ in words])
        title_clauses = " OR ".join(["title ILIKE %s" for _ in words])
        params = [f"%{w}%" for w in words] * 2

        sql = f"""
            SELECT id, category, subcategory, title, content, source, property_name,
                (CASE WHEN ({title_clauses}) THEN 2 ELSE 0 END +
                 CASE WHEN ({like_clauses}) THEN 1 ELSE 0 END) as relevance
            FROM ruebarue_knowledge_base
            WHERE ({like_clauses}) OR ({title_clauses})
        """
        # Add all params (title_clauses params + like_clauses params + WHERE like + WHERE title)
        all_params = params + params

        if cabin_name:
            sql += " AND (property_name IS NULL OR property_name = %s)"
            all_params.append(cabin_name)

        sql += " ORDER BY relevance DESC LIMIT %s"
        all_params.append(limit)

        cur.execute(sql, all_params)
        results = [dict(r) for r in cur.fetchall()]
        conn.close()
        return results

    def get_matching_templates(self, intent: str, cabin_name: str = None) -> List[Dict]:
        """Get RueBaRue scheduler templates matching the intent and/or cabin."""
        conn = self._conn()
        cur = conn.cursor()

        intent_to_template = {
            "CHECKIN": ["check-in", "welcome", "door code", "wifi", "arrival"],
            "CHECKOUT": ["check-out", "checkout", "departure"],
            "WIFI": ["wifi", "door code", "password"],
            "DIRECTIONS": ["direction", "address"],
            "MAINTENANCE": ["maintenance", "issue"],
        }
        keywords = intent_to_template.get(intent, [intent.lower()])

        like_clauses = " OR ".join(["name ILIKE %s OR message_text ILIKE %s" for _ in keywords])
        params = []
        for k in keywords:
            params.extend([f"%{k}%", f"%{k}%"])

        sql = f"""
            SELECT name, type, message_text
            FROM ruebarue_message_templates
            WHERE ({like_clauses})
        """

        if cabin_name:
            sql += " OR name ILIKE %s OR message_text ILIKE %s"
            params.extend([f"%{cabin_name}%", f"%{cabin_name}%"])

        sql += " LIMIT 8"
        cur.execute(sql, params)
        results = [dict(r) for r in cur.fetchall()]
        conn.close()
        return results

    def get_cabin_wifi_doorcode(self, cabin_name: str) -> Dict:
        """Get the exact WiFi and door code from templates for a specific cabin."""
        if not cabin_name:
            return {}
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT name, message_text
            FROM ruebarue_message_templates
            WHERE (name ILIKE %s OR message_text ILIKE %s)
              AND (name ILIKE '%%wifi%%' OR name ILIKE '%%door%%')
        """, (f"%{cabin_name}%", f"%{cabin_name}%"))
        row = cur.fetchone()
        conn.close()
        if not row:
            return {}

        text = row["message_text"] or ""
        info = {"template_name": row["name"]}
        import re
        wifi_match = re.search(r'WiFi\s*Password:\s*(.+?)(?:\n|$)', text)
        door_match = re.search(r'Door\s*Code:\s*(.+?)(?:\n|$)', text)
        gate_match = re.search(r'Gate\s*Code:\s*(.+?)(?:\n|$)', text)
        if wifi_match:
            info["wifi_password"] = wifi_match.group(1).strip()
        if door_match:
            info["door_code"] = door_match.group(1).strip()
        if gate_match:
            info["gate_code"] = gate_match.group(1).strip()
        return info

    def get_taylor_voice_exemplars(self, intent: str, cabin_name: str = None, limit: int = 3) -> List[str]:
        """Get examples of real CROG outbound responses for tone matching.
        
        Priority: outbound SMS (same medium) > CROG staff emails (info@, Taylor, team)
        Filters out marketing blasts, automated notifications, and spam.
        """
        conn = self._conn()
        cur = conn.cursor()
        results = []

        intent_to_keywords = {
            "CHECKIN": ["check-in", "welcome", "arrival", "door code", "looking forward"],
            "CHECKOUT": ["check-out", "checkout", "departure", "thank you for staying"],
            "WIFI": ["wifi", "password", "internet", "code"],
            "BOOKING": ["reservation", "booking", "rental agreement", "deposit"],
            "COMPLIMENT": ["thank you", "glad", "wonderful", "great time"],
            "MAINTENANCE": ["maintenance", "repair", "issue", "sorry", "plumb", "toilet", "fix"],
            "EMERGENCY": ["emergency", "urgent", "gas", "leak", "fire"],
            "LOCAL_TIPS": ["restaurant", "activity", "recommend", "downtown"],
            "AMENITIES": ["hot tub", "fireplace", "grill", "pool table"],
            "DAMAGE": ["damage", "repair", "charge", "security deposit"],
            "REFUND": ["refund", "cancel", "credit", "reimburse"],
        }
        keywords = intent_to_keywords.get(intent, ["guest", "cabin"])

        # 1. Outbound SMS — same medium, highest relevance
        like_clauses = " OR ".join(["message_body ILIKE %s" for _ in keywords])
        params = [f"%{k}%" for k in keywords]

        sql = f"""
            SELECT message_body as excerpt
            FROM message_archive
            WHERE direction = 'outbound'
              AND message_body IS NOT NULL
              AND LENGTH(message_body) > 20
              AND message_body NOT LIKE 'http%%'
              AND ({like_clauses})
        """
        if cabin_name:
            sql += " AND cabin_name = %s"
            params.append(cabin_name)

        sql += " ORDER BY sent_at DESC NULLS LAST LIMIT %s"
        params.append(limit)

        cur.execute(sql, params)
        results = [r["excerpt"] for r in cur.fetchall()]

        # 2. If we don't have enough SMS, supplement with ALL CROG staff emails
        #    (info@, taylor, cynthia, brian, lissa, etc.) — filtered for guest comms
        if len(results) < limit:
            remaining = limit - len(results)
            email_clauses = " OR ".join(["content ILIKE %s" for _ in keywords])
            email_params = [f"%{k}%" for k in keywords]

            cur.execute(f"""
                SELECT LEFT(content, 400) as excerpt
                FROM email_archive
                WHERE sender ILIKE '%%@cabin-rentals-of-georgia.com%%'
                  AND ({email_clauses})
                  AND content NOT ILIKE '%%utm_source%%'
                  AND content NOT ILIKE '%%utm_campaign%%'
                  AND content NOT ILIKE '%%unsubscribe%%'
                  AND content NOT ILIKE '%%click below to sign%%'
                  AND content NOT ILIKE '%%new sign-in%%'
                  AND content NOT ILIKE '%%cpanel%%'
                  AND LENGTH(content) > 50
                  AND LENGTH(content) < 5000
                ORDER BY sent_at DESC NULLS LAST
                LIMIT %s
            """, email_params + [remaining])
            results.extend([r["excerpt"] for r in cur.fetchall()])

        conn.close()
        return results

    def get_conversation_history(self, phone_number: str, limit: int = 10) -> List[Dict]:
        """Get recent message history for this guest."""
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT direction, message_body, cabin_name, sent_at, intent
            FROM message_archive
            WHERE phone_number = %s
            ORDER BY COALESCE(sent_at, created_at) DESC
            LIMIT %s
        """, (phone_number, limit))
        results = [dict(r) for r in cur.fetchall()]
        conn.close()
        return list(reversed(results))

    def get_guest_profile(self, phone_number: str) -> Dict:
        """Get guest profile with preferences and history."""
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT name, email, total_messages, total_stays,
                   favorite_cabins, overall_sentiment, communication_style,
                   vip_guest, requires_human_touch, special_requests,
                   last_stay_date, next_booking_date
            FROM guest_profiles
            WHERE phone_number = %s
        """, (phone_number,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else {}

    def get_area_guide(self, query: str, limit: int = 3) -> List[Dict]:
        """Search the area guide for local recommendations."""
        conn = self._conn()
        cur = conn.cursor()
        words = [w for w in query.lower().split() if len(w) > 2]
        if not words:
            conn.close()
            return []

        like_clauses = " OR ".join(
            ["place_name ILIKE %s OR raw_text ILIKE %s" for _ in words]
        )
        params = []
        for w in words:
            params.extend([f"%{w}%", f"%{w}%"])

        cur.execute(f"""
            SELECT section, place_name, address, phone, rating, tip
            FROM ruebarue_area_guide
            WHERE {like_clauses}
            LIMIT %s
        """, params + [limit])
        results = [dict(r) for r in cur.fetchall()]
        conn.close()
        return results

    def identify_guest(self, phone_number: str) -> Tuple[str, str]:
        """Identify guest name and cabin from phone number."""
        conn = self._conn()
        cur = conn.cursor()

        # Check guest_profiles first
        cur.execute("SELECT name FROM guest_profiles WHERE phone_number = %s", (phone_number,))
        row = cur.fetchone()
        guest_name = row["name"] if row else ""

        # Get most recent cabin from message history
        cur.execute("""
            SELECT cabin_name FROM message_archive
            WHERE phone_number = %s AND cabin_name IS NOT NULL AND cabin_name != ''
            ORDER BY COALESCE(sent_at, created_at) DESC
            LIMIT 1
        """, (phone_number,))
        row = cur.fetchone()
        cabin_name = row["cabin_name"] if row else ""

        # Also check guest name from messages if not in profile
        if not guest_name:
            cur.execute("""
                SELECT guest_name FROM message_archive
                WHERE phone_number = %s AND guest_name IS NOT NULL AND guest_name != ''
                ORDER BY COALESCE(sent_at, created_at) DESC LIMIT 1
            """, (phone_number,))
            row = cur.fetchone()
            guest_name = row["guest_name"] if row else "Guest"

        conn.close()
        return guest_name, cabin_name

    def retrieve_all(self, phone_number: str, message: str, intent: IntentResult) -> KnowledgeContext:
        """Master retrieval: gather all relevant context for the agent."""
        ctx = KnowledgeContext()

        guest_name, cabin_name = self.identify_guest(phone_number)

        # Property context
        ctx.property_info = self.get_property_context(cabin_name)
        ctx.sources_used.append("property_sms_config")

        # Get exact WiFi/door code from RueBaRue templates for this cabin
        cabin_access = self.get_cabin_wifi_doorcode(cabin_name)
        if cabin_access:
            access_lines = []
            if cabin_access.get("wifi_password"):
                access_lines.append(f"VERIFIED WiFi Password: {cabin_access['wifi_password']}")
            if cabin_access.get("door_code"):
                access_lines.append(f"VERIFIED Door Code: {cabin_access['door_code']}")
            if cabin_access.get("gate_code"):
                access_lines.append(f"VERIFIED Gate Code: {cabin_access['gate_code']}")
            if access_lines:
                ctx.property_info += "\n\n" + "\n".join(access_lines)
                ctx.sources_used.append("ruebarue_templates (verified access codes)")

        # Knowledge base search
        ctx.knowledge_articles = self.search_knowledge_base(message, cabin_name)
        if ctx.knowledge_articles:
            ctx.sources_used.append(f"knowledge_base ({len(ctx.knowledge_articles)} articles)")

        # Templates for this intent (includes inactive templates too)
        ctx.templates = self.get_matching_templates(intent.primary, cabin_name)
        if ctx.templates:
            ctx.sources_used.append(f"templates ({len(ctx.templates)} matched)")

        # Conversation history
        ctx.conversation_history = self.get_conversation_history(phone_number)
        if ctx.conversation_history:
            ctx.sources_used.append(f"history ({len(ctx.conversation_history)} messages)")

        # Guest profile
        ctx.guest_profile = self.get_guest_profile(phone_number)
        if ctx.guest_profile:
            ctx.sources_used.append("guest_profile")

        # Taylor/CROG voice exemplars — real SMS + emails as tone reference
        taylor_examples = self.get_taylor_voice_exemplars(intent.primary, cabin_name)
        if taylor_examples:
            ctx.taylor_voice = taylor_examples
            ctx.sources_used.append(f"crog_voice ({len(taylor_examples)} real responses)")

        # Area guide for local tips
        if intent.primary == "LOCAL_TIPS" or any(i == "LOCAL_TIPS" for i in intent.secondary):
            ctx.area_guide = self.get_area_guide(message)
            if ctx.area_guide:
                ctx.sources_used.append(f"area_guide ({len(ctx.area_guide)} places)")

        return ctx, guest_name, cabin_name


# ═══════════════════════════════════════════════════════════════════════
# AI GUEST AGENT
# ═══════════════════════════════════════════════════════════════════════

class GuestAgent:
    """The AI guest communication agent."""

    def __init__(self, db_url: str = DB_URL, mode: str = "SWARM"):
        self.db_url = db_url
        self.mode = mode
        self.retriever = KnowledgeRetriever(db_url)
        logger.info(f"GuestAgent initialized in {mode} mode")

    def _build_prompt(self, guest_name: str, guest_message: str,
                      cabin_name: str, knowledge: KnowledgeContext) -> str:
        """Assemble the full prompt from the template and retrieved context."""
        from prompts.loader import load_prompt

        tmpl = load_prompt("guest_sms_agent")

        # Format property context
        property_context = knowledge.property_info

        # Format knowledge articles
        kb_lines = []
        for art in knowledge.knowledge_articles[:5]:
            kb_lines.append(f"[{art.get('category', '')}] {art.get('title', '')}")
            content = art.get('content', '')[:300]
            kb_lines.append(f"  {content}")
        for tmpl_match in knowledge.templates[:3]:
            kb_lines.append(f"[Template: {tmpl_match.get('name', '')}]")
            text = tmpl_match.get('message_text') or tmpl_match.get('full_modal_text', '')
            kb_lines.append(f"  {text[:300]}")
        for place in knowledge.area_guide[:3]:
            kb_lines.append(f"[Area Guide: {place.get('section', '')}] {place.get('place_name', '')}")
            if place.get("tip"):
                kb_lines.append(f"  Tip: {place['tip']}")
            if place.get("address"):
                kb_lines.append(f"  Address: {place['address']}")

        # Taylor's voice exemplars — real email excerpts to teach tone
        if knowledge.taylor_voice:
            kb_lines.append("\n[TAYLOR'S REAL COMMUNICATION STYLE — match this tone and voice]")
            for i, excerpt in enumerate(knowledge.taylor_voice[:3], 1):
                clean = excerpt.strip().replace("\r\n", " ").replace("\n", " ")[:250]
                kb_lines.append(f"  Example {i}: \"{clean}\"")

        knowledge_context = "\n".join(kb_lines) if kb_lines else "(No specific knowledge articles found)"

        # Format conversation history
        history_lines = []
        for msg in knowledge.conversation_history[-6:]:
            direction = "Guest" if msg.get("direction") == "inbound" else "CROG"
            body = (msg.get("message_body") or "")[:200]
            history_lines.append(f"  {direction}: {body}")
        conversation_history = "\n".join(history_lines) if history_lines else "(New conversation)"

        # Format guest profile
        profile = knowledge.guest_profile
        if profile:
            profile_lines = []
            if profile.get("name"):
                profile_lines.append(f"Name: {profile['name']}")
            if profile.get("total_stays"):
                profile_lines.append(f"Total stays: {profile['total_stays']}")
            if profile.get("vip_guest"):
                profile_lines.append("VIP Guest: Yes")
            if profile.get("communication_style"):
                profile_lines.append(f"Style: {profile['communication_style']}")
            if profile.get("special_requests"):
                profile_lines.append(f"Special requests: {', '.join(profile['special_requests'])}")
            guest_profile = "\n".join(profile_lines)
        else:
            guest_profile = "(First-time or unrecognized guest)"

        rendered = tmpl.render(
            guest_name=guest_name or "Guest",
            guest_message=guest_message,
            cabin_name=cabin_name or "Unknown Property",
            property_context=property_context,
            knowledge_context=knowledge_context,
            conversation_history=conversation_history,
            guest_profile=guest_profile,
            current_datetime=datetime.now().strftime("%A, %B %d, %Y at %I:%M %p ET"),
        )

        return rendered

    def _generate_draft(self, prompt: str, intent: IntentResult) -> Tuple[str, str, float]:
        """Call the LLM to generate a response draft."""
        from config import get_inference_client

        # Use HYDRA for escalations only, SWARM for everything else (including urgent)
        # HYDRA is 70B and takes 60-120s; SWARM (7B) responds in 2-6s
        if intent.escalation_required:
            mode = "HYDRA"
        else:
            mode = self.mode

        client, model = get_inference_client(mode)

        system_msg = (
            "You are a guest communication assistant for Cabin Rentals of Georgia. "
            "Draft a warm, accurate SMS text response. Keep it concise and friendly. "
            "Only use information from the provided context. Never fabricate details."
        )

        start = time.time()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
                max_tokens=512,
            )
            draft = response.choices[0].message.content or ""
            duration = (time.time() - start) * 1000

            # Clean up the draft
            draft = draft.strip()
            if draft.startswith("RESPONSE:"):
                draft = draft[9:].strip()
            if draft.startswith('"') and draft.endswith('"'):
                draft = draft[1:-1]

            return draft, model, duration

        except Exception as e:
            duration = (time.time() - start) * 1000
            logger.error(f"LLM call failed: {e}")
            return f"[LLM ERROR: {e}]", model, duration

    def _queue_for_review(self, result: AgentResult) -> int:
        """Insert the draft into the review queue."""
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO agent_response_queue (
                phone_number, guest_name, cabin_name,
                guest_message, intent, intent_confidence,
                sentiment, urgency_level, escalation_required, escalation_reason,
                ai_draft, ai_model, ai_duration_ms,
                knowledge_sources, confidence_score,
                status, expires_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            ) RETURNING id
        """, (
            result.phone_number,
            result.guest_name,
            result.cabin_name,
            result.guest_message,
            result.intent.primary,
            result.intent.confidence,
            result.intent.sentiment,
            result.intent.urgency,
            result.intent.escalation_required,
            result.intent.escalation_reason or None,
            result.ai_draft,
            result.ai_model,
            int(result.duration_ms),
            json.dumps(result.knowledge.sources_used),
            result.confidence_score,
            "pending_review",
            datetime.now() + timedelta(hours=24),
        ))

        queue_id = cur.fetchone()[0]
        conn.commit()
        conn.close()
        return queue_id

    def process_message(self, phone_number: str, message: str,
                        cabin_name_override: str = None) -> AgentResult:
        """
        Full pipeline: classify -> retrieve -> generate -> queue.

        Args:
            phone_number: Guest's phone number
            message: The guest's message text
            cabin_name_override: Force a specific cabin (for testing)

        Returns:
            AgentResult with the AI draft and queue status.
        """
        result = AgentResult(phone_number=phone_number, guest_message=message)
        pipeline_start = time.time()

        # Step 1: Classify intent
        logger.info(f"[1/5] Classifying intent for: {message[:60]}...")
        result.intent = classify_intent(message)
        logger.info(f"  Intent: {result.intent.primary} (conf: {result.intent.confidence:.2f})"
                     f" sentiment={result.intent.sentiment} urgency={result.intent.urgency}")

        # Step 2: Retrieve knowledge
        logger.info("[2/5] Retrieving knowledge context...")
        knowledge, guest_name, cabin_name = self.retriever.retrieve_all(
            phone_number, message, result.intent
        )
        result.knowledge = knowledge
        result.guest_name = guest_name
        result.cabin_name = cabin_name_override or cabin_name
        logger.info(f"  Guest: {result.guest_name}, Cabin: {result.cabin_name}")
        logger.info(f"  Sources: {', '.join(knowledge.sources_used)}")

        # Step 3: Build prompt
        logger.info("[3/5] Building prompt...")
        prompt = self._build_prompt(
            result.guest_name, message, result.cabin_name, knowledge
        )

        # Step 4: Generate draft
        logger.info("[4/5] Generating AI draft...")
        draft, model, duration = self._generate_draft(prompt, result.intent)
        result.ai_draft = draft
        result.ai_model = model
        result.duration_ms = duration
        result.success = not draft.startswith("[LLM ERROR")

        # Confidence score based on knowledge availability
        conf = 0.5
        if knowledge.property_info and "No config" not in knowledge.property_info:
            conf += 0.15
        if knowledge.knowledge_articles:
            conf += 0.1
        if knowledge.templates:
            conf += 0.1
        if knowledge.conversation_history:
            conf += 0.05
        if knowledge.guest_profile:
            conf += 0.05
        if result.intent.confidence > 0.7:
            conf += 0.05
        result.confidence_score = min(conf, 0.99)

        logger.info(f"  Model: {model}, Duration: {duration:.0f}ms")
        logger.info(f"  Confidence: {result.confidence_score:.2f}")
        logger.info(f"  Draft preview: {draft[:100]}...")

        # Step 5: Queue for review
        logger.info("[5/5] Queuing for review...")
        try:
            result.queue_id = self._queue_for_review(result)
            logger.info(f"  Queued as #{result.queue_id}")
        except Exception as e:
            logger.error(f"  Queue failed: {e}")
            result.error = str(e)

        total_time = (time.time() - pipeline_start) * 1000
        logger.info(f"Pipeline complete in {total_time:.0f}ms")

        return result


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def run_demo():
    """Run a demo with realistic guest messages."""
    agent = GuestAgent()

    demo_messages = [
        {
            "phone": "+17065551001",
            "cabin": "Cohutta Sunset",
            "message": "Hey! What's the WiFi password? We just got here and can't find it posted anywhere.",
        },
        {
            "phone": "+17065551002",
            "cabin": "Skyfall",
            "message": "What time is check-in? We're driving from Atlanta and should arrive around 3pm. Is early check-in possible?",
        },
        {
            "phone": "+17065551003",
            "cabin": "Fallen Timber Lodge",
            "message": "Can you recommend any good restaurants nearby? We're looking for something family-friendly.",
        },
        {
            "phone": "+17065551004",
            "cabin": "Above the Timberline",
            "message": "The hot water isn't working in the master bathroom. We've tried both handles and it's only cold water coming out.",
        },
        {
            "phone": "+17065551005",
            "cabin": "Aska Escape Lodge",
            "message": "We had the most AMAZING weekend! The cabin was absolutely perfect. Thank you so much for everything!",
        },
        {
            "phone": "+17065551006",
            "cabin": "High Hopes",
            "message": "We smell gas near the fireplace. What should we do??",
        },
    ]

    print("=" * 70)
    print("  FORTRESS PRIME — AI GUEST AGENT DEMO")
    print("=" * 70)

    for i, msg in enumerate(demo_messages, 1):
        print(f"\n{'━' * 70}")
        print(f"  TEST {i}/{len(demo_messages)}")
        print(f"  Phone:   {msg['phone']}")
        print(f"  Cabin:   {msg['cabin']}")
        print(f"  Message: {msg['message']}")
        print(f"{'━' * 70}")

        result = agent.process_message(
            msg["phone"], msg["message"],
            cabin_name_override=msg["cabin"]
        )

        print(f"\n  Intent:     {result.intent.primary} ({result.intent.sentiment})")
        print(f"  Urgency:    {'🔴' * result.intent.urgency}{'⚪' * (5 - result.intent.urgency)}")
        print(f"  Escalation: {'YES' if result.intent.escalation_required else 'No'}")
        print(f"  Model:      {result.ai_model}")
        print(f"  Duration:   {result.duration_ms:.0f}ms")
        print(f"  Confidence: {result.confidence_score:.2f}")
        print(f"  Queue ID:   #{result.queue_id}")
        print(f"\n  AI DRAFT:")
        print(f"  {'─' * 60}")
        for line in result.ai_draft.split("\n"):
            print(f"  {line}")
        print(f"  {'─' * 60}")

    print(f"\n{'=' * 70}")
    print(f"  DEMO COMPLETE — {len(demo_messages)} messages processed")
    print(f"{'=' * 70}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fortress Prime — AI Guest Agent")
    parser.add_argument("--phone", type=str, help="Guest phone number")
    parser.add_argument("--message", "-m", type=str, help="Guest message")
    parser.add_argument("--cabin", "-c", type=str, help="Cabin name override")
    parser.add_argument("--demo", action="store_true", help="Run demo suite")
    parser.add_argument("--mode", type=str, default="SWARM", help="SWARM or HYDRA")
    args = parser.parse_args()

    if args.demo:
        run_demo()
        return

    if not args.phone or not args.message:
        parser.print_help()
        return

    agent = GuestAgent(mode=args.mode)
    result = agent.process_message(args.phone, args.message, args.cabin)

    print(f"\nIntent: {result.intent.primary} ({result.intent.sentiment})")
    print(f"Cabin:  {result.cabin_name}")
    print(f"Model:  {result.ai_model}")
    print(f"Queue:  #{result.queue_id}")
    print(f"\nAI Draft:\n{result.ai_draft}")


if __name__ == "__main__":
    main()
