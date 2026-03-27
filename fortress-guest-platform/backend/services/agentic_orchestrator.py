"""
Agentic Orchestrator - The Autonomous AI Brain of Fortress Guest Platform
BETTER THAN: RueBaRue + Breezeway + Hospitable + Aeve AI --- COMBINED

This is the central nervous system that:
1. Receives every inbound guest message and autonomously decides what to do
2. Classifies intent with hybrid keyword + AI scoring
3. Analyzes sentiment and urgency in real-time
4. Routes to the correct handler (auto-answer, work order, escalation, etc.)
5. Generates contextual, Southern-hospitality-tone responses
6. Evaluates confidence before auto-sending anything
7. Runs daily automation (pre-arrival, mid-stay, checkout, reviews)
8. Escalates to staff with full context when the AI shouldn't handle it
9. Tracks every decision for continuous improvement

Architecture:
    Inbound Message
         |
    [Intent Classification] -> MessageIntent enum
         |
    [Sentiment Analysis] -> SentimentScore dataclass
         |
    [Route Decision] -> AgentDecision dataclass
         |
    +---------+---------+---------+---------+
    | auto    | work    | access  | escalate| booking | thank  |
    | answer  | order   | info    | staff   | flow    | & log  |
    +---------+---------+---------+---------+

Company: Cabin Rentals of Georgia (Blue Ridge, GA)
Tone:    Warm Southern hospitality — friendly, professional, concise
"""
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass, field
from uuid import UUID, uuid4
import re

import httpx
import structlog
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import (
    Message,
    Guest,
    Reservation,
    Property,
    WorkOrder,
    StaffUser,
)
from backend.core.config import settings
from backend.integrations.twilio_client import TwilioClient
from backend.services.knowledge_retriever import semantic_search, format_context
from backend.services.dgx_tools import (
    get_openai_tools,
    execute_tool_call,
)

logger = structlog.get_logger()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Data Classes & Enums
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class MessageIntent(str, Enum):
    """Every intent the orchestrator can classify."""
    QUESTION = "question"
    COMPLAINT = "complaint"
    REQUEST = "request"
    EMERGENCY = "emergency"
    REVIEW = "review"
    BOOKING_INQUIRY = "booking_inquiry"
    GREETING = "greeting"
    WIFI_QUESTION = "wifi_question"
    ACCESS_CODE = "access_code"
    CHECKIN_QUESTION = "checkin_question"
    CHECKOUT_QUESTION = "checkout_question"
    MAINTENANCE = "maintenance"
    DAMAGE_REPORT = "damage_report"
    AMENITY_QUESTION = "amenity_question"
    LOCAL_RECOMMENDATION = "local_recommendation"
    POSITIVE_FEEDBACK = "positive_feedback"
    OTHER = "other"


@dataclass
class SentimentScore:
    """Structured sentiment analysis result."""
    score: float          # -1.0 (very negative) to 1.0 (very positive)
    label: str            # positive, neutral, negative, urgent
    urgency_level: int    # 0 = none, 1 = low, 2 = medium, 3 = high, 4 = critical


@dataclass
class AgentDecision:
    """The orchestrator's autonomous decision on how to handle a message."""
    action: str                               # auto_reply, escalate, create_work_order, send_access_info, etc.
    response_text: Optional[str] = None       # Generated response (if applicable)
    confidence: float = 0.0                   # 0.0-1.0 how confident the agent is
    should_auto_send: bool = False            # True = send without human review
    escalation_reason: Optional[str] = None   # Why it was escalated (if applicable)
    intent: MessageIntent = MessageIntent.OTHER
    sentiment: Optional[SentimentScore] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def requires_human(self) -> bool:
        return not self.should_auto_send


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Intent classification keyword map
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_INTENT_KEYWORDS: Dict[MessageIntent, List[str]] = {
    MessageIntent.EMERGENCY: [
        "fire", "gas leak", "flood", "flooding", "smoke", "ambulance",
        "911", "police", "injured", "hurt", "dangerous", "carbon monoxide",
        "electrocuted", "medical", "chest pain", "can't breathe",
    ],
    MessageIntent.DAMAGE_REPORT: [
        "damage", "damaged", "broke", "stain", "stained", "scratched",
        "shattered", "cracked", "ripped", "torn", "burnt", "burned",
        "hole in wall", "ruined", "destroyed", "smashed", "chipped",
        "security deposit", "keeping deposit", "deduct", "charge guest",
        "guest caused", "guest broke", "guest damaged", "found damage",
        "post-checkout damage", "inspection damage", "damage report",
        "property damage", "broken mirror", "broken bed", "broken chair",
        "wine stain", "cigarette burn", "missing items", "stolen",
    ],
    MessageIntent.MAINTENANCE: [
        "not working", "repair", "fix", "leak", "clogged",
        "no hot water", "no water", "no power", "ac broken", "heater",
        "thermostat", "toilet", "fridge", "oven", "dishwasher",
    ],
    MessageIntent.COMPLAINT: [
        "dirty", "disgusting", "unacceptable", "refund", "disappointed",
        "horrible", "terrible", "worst", "misleading", "scam", "rip off",
        "not as described", "want my money back", "filing complaint",
    ],
    MessageIntent.WIFI_QUESTION: [
        "wifi", "wi-fi", "internet", "password", "network", "connect",
        "wifi password", "router", "ethernet",
    ],
    MessageIntent.ACCESS_CODE: [
        "door code", "lock code", "access code", "entry code", "key",
        "lockbox", "smart lock", "can't get in", "locked out",
        "how do i get in", "door won't open",
    ],
    MessageIntent.CHECKIN_QUESTION: [
        "check in", "checkin", "check-in", "arrival", "directions",
        "how to get there", "parking", "early check-in", "early arrival",
        "what time can i arrive", "where do i go",
    ],
    MessageIntent.CHECKOUT_QUESTION: [
        "check out", "checkout", "check-out", "departure", "leaving",
        "late checkout", "late check-out", "what time do i leave",
        "do i need to clean", "where do i leave the key",
    ],
    MessageIntent.AMENITY_QUESTION: [
        "hot tub", "jacuzzi", "fireplace", "grill", "pool table",
        "game room", "washer", "dryer", "towels", "linens",
        "how does the", "where are the",
    ],
    MessageIntent.LOCAL_RECOMMENDATION: [
        "restaurant", "things to do", "hiking", "waterfall", "winery",
        "brewery", "breakfast", "dinner", "attraction", "activity",
        "where should we eat", "recommend", "nearby",
    ],
    MessageIntent.BOOKING_INQUIRY: [
        "available", "book again", "extend", "extend my stay",
        "another night", "pricing", "rate", "cost", "how much",
        "next weekend", "reservation",
    ],
    MessageIntent.POSITIVE_FEEDBACK: [
        "amazing", "wonderful", "perfect", "love it", "best vacation",
        "5 stars", "beautiful", "fantastic", "awesome", "incredible",
        "blown away", "exceeded expectations",
    ],
    MessageIntent.REVIEW: [
        "review", "rating", "stars", "feedback", "rate my stay",
    ],
    MessageIntent.GREETING: [
        "hello", "hi", "hey", "good morning", "good afternoon",
        "good evening", "howdy",
    ],
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Response Templates — Southern Hospitality for Blue Ridge GA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RESPONSE_TEMPLATES: Dict[str, str] = {
    "wifi_answer": (
        "Hey {guest_name}! Here's the WiFi info for {property_name}:\n\n"
        "Network: {wifi_ssid}\n"
        "Password: {wifi_password}\n\n"
        "If the connection gives you any trouble, just holler and we'll "
        "get it sorted out. Enjoy your stay!"
    ),
    "access_info": (
        "Hey {guest_name}! Here's everything you need to get into "
        "{property_name}:\n\n"
        "Door Code: {access_code}\n"
        "The code is active starting at 4 PM on your check-in day.\n\n"
        "If you have any trouble at all, give us a ring at {support_phone} "
        "and we'll get you taken care of right away."
    ),
    "checkin_info": (
        "Hey {guest_name}! We're so excited to have you at "
        "{property_name}!\n\n"
        "Check-in: 4:00 PM on {check_in_date}\n"
        "Parking: {parking_instructions}\n\n"
        "Your door code and WiFi details will be sent the day before "
        "arrival. Safe travels up to the mountains!"
    ),
    "checkout_info": (
        "Hey {guest_name}! Here's your checkout info for "
        "{property_name}:\n\n"
        "Checkout: 11:00 AM\n"
        "- Lock all doors and windows\n"
        "- Turn off the fireplace\n"
        "- Start the dishwasher\n"
        "- Set the thermostat to 72\n"
        "- Take all your belongings\n\n"
        "Thank y'all for staying with us! We sure hope you had a "
        "wonderful time in Blue Ridge."
    ),
    "amenity_info": (
        "Hey {guest_name}! Great question about {property_name}.\n\n"
        "Every one of our cabins is different. Please check your "
        "digital guest guide for the complete amenity list and "
        "instructions specific to your cabin.\n\n"
        "If you can't find what you're looking for, just text us "
        "back and we'll get you the info right away!"
    ),
    "local_tips": (
        "Hey {guest_name}! Blue Ridge has so much to offer.\n\n"
        "Our favorites:\n"
        "- Blue Ridge Scenic Railway\n"
        "- Mercier Orchards (apple picking!)\n"
        "- Downtown Blue Ridge shops & galleries\n"
        "- Long Creek Falls trail\n"
        "- Lake Blue Ridge\n\n"
        "Your digital guest guide has our full list with directions "
        "and hours. Have a blast!"
    ),
    "maintenance_ack": (
        "Hey {guest_name}, thank you for letting us know about that. "
        "We take this seriously and want to make sure your stay is "
        "top-notch.\n\n"
        "We've created a service ticket (#{ticket_number}) and our "
        "team is on it. We'll keep you posted on the progress.\n\n"
        "If you need anything else in the meantime, just text us back."
    ),
    "damage_ack": (
        "Thank you for reporting this, {guest_name}. We take property "
        "condition very seriously.\n\n"
        "Our management team has been notified and a damage assessment "
        "(claim #{claim_number}) is being prepared. "
        "We'll review the details and follow up with you shortly.\n\n"
        "If you have any photos or additional details, please send "
        "them our way."
    ),
    "complaint_ack": (
        "Hey {guest_name}, we sincerely appreciate you bringing this "
        "to our attention. That is not the experience we want for our "
        "guests, and we are truly sorry.\n\n"
        "A member of our team will be reaching out to you shortly to "
        "make this right. Your satisfaction means the world to us."
    ),
    "emergency_ack": (
        "{guest_name}, we are taking this very seriously. Our team has "
        "been notified immediately.\n\n"
        "If this is a life-threatening emergency, please call 911 first.\n\n"
        "Our emergency contact: {support_phone}\n"
        "We are on our way to help."
    ),
    "positive_thank": (
        "Aw, {guest_name}, that just made our day! Thank you so much "
        "for the kind words about {property_name}.\n\n"
        "We'd love to have y'all back anytime. Use code RETURN15 for "
        "15% off your next mountain getaway!\n\n"
        "Safe travels home!"
    ),
    "booking_inquiry_ack": (
        "Hey {guest_name}! We'd love to have you back at "
        "{property_name} (or any of our beautiful cabins).\n\n"
        "Let us check availability for you. A member of our "
        "reservations team will follow up shortly with dates and rates.\n\n"
        "In the meantime, you can browse all our cabins at "
        "cabinrentalsofgeorgia.com"
    ),
    "greeting_reply": (
        "Hey {guest_name}! Welcome to Cabin Rentals of Georgia! "
        "How can we help you today?\n\n"
        "Whether you need WiFi info, local restaurant picks, or "
        "anything else — just let us know!"
    ),
    "generic_fallback": (
        "Hey {guest_name}! Thanks for reaching out to Cabin Rentals "
        "of Georgia.\n\n"
        "We got your message and our team will get back to you "
        "shortly. If this is urgent, call us at {support_phone}."
    ),
    # ── Daily Automation Templates ──
    "pre_arrival_24h": (
        "Hey {guest_name}! Tomorrow's the big day — {property_name} "
        "is all ready for y'all!\n\n"
        "Check-in: 4:00 PM\n"
        "Door Code: {access_code}\n"
        "WiFi: {wifi_ssid} / {wifi_password}\n\n"
        "Safe travels to the mountains! Text us if you need "
        "anything at all."
    ),
    "access_code_4h": (
        "Hey {guest_name}! Just a few hours until your mountain "
        "escape begins.\n\n"
        "Your door code for {property_name}: {access_code}\n\n"
        "The code activates at 4 PM. See you soon!"
    ),
    "mid_stay_checkin": (
        "Hey {guest_name}! Hope y'all are settling in nicely at "
        "{property_name}.\n\n"
        "Is everything working well? Need restaurant recommendations "
        "or anything at all? Just text us — we're here for you!"
    ),
    "checkout_reminder": (
        "Good morning, {guest_name}! Just a friendly reminder that "
        "checkout is at 11 AM tomorrow.\n\n"
        "We'll send the checkout checklist in the morning. "
        "Enjoy your last evening in the mountains!"
    ),
    "post_stay_review": (
        "Hey {guest_name}! We hope you had an amazing time at "
        "{property_name}!\n\n"
        "We'd love to hear how your stay was — a quick reply with "
        "a 1-5 star rating means the world to us.\n\n"
        "Planning another trip? Use code RETURN15 for 15% off! "
        "We'd love to host y'all again."
    ),
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Agentic Orchestrator — The AI Brain
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AgenticOrchestrator:
    """
    The autonomous AI brain of Fortress Guest Platform.

    Every inbound message flows through here.  The orchestrator classifies,
    analyzes, decides, and either auto-responds or escalates — all while
    logging every decision for continuous improvement.

    BETTER THAN every competitor because:
    - Fully autonomous decision loop (classify -> analyze -> decide -> act)
    - Hybrid keyword + AI classification with confidence scoring
    - Southern-hospitality tone baked into every template
    - Knowledge-base lookup for property-specific answers
    - Auto work-order creation with staff SMS escalation
    - Daily automation engine (pre-arrival through post-stay)
    - Transparent confidence gating — nothing auto-sends below threshold
    - Complete agent stats for operational dashboards
    """

    CONFIDENCE_THRESHOLD: float = 0.75  # Minimum confidence for auto-send

    def __init__(self):
        self.log = logger.bind(service="agentic_orchestrator")
        self.twilio = TwilioClient()

    # ──────────────────────────────────────────────────────────────────────
    #  1. process_incoming_message  — THE MAIN DECISION LOOP
    # ──────────────────────────────────────────────────────────────────────

    async def process_incoming_message(
        self,
        message: Message,
        guest: Guest,
        reservation: Optional[Reservation],
        db: AsyncSession,
    ) -> AgentDecision:
        """
        Master entry point.  Takes a raw inbound message, classifies it,
        analyzes sentiment, picks a handler, generates a response, evaluates
        confidence, and returns a fully-formed AgentDecision.
        """
        trace_id = uuid4()
        log = self.log.bind(
            trace_id=str(trace_id),
            guest_id=str(guest.id),
            message_id=str(message.id),
        )
        log.info("orchestrator_processing", body_preview=message.body[:80])

        body = message.body or ""

        # Step 1 — Classify intent
        intent = self._classify_intent(body)
        log.info("intent_classified", intent=intent.value)

        # Step 2 — Analyze sentiment
        sentiment = self._analyze_sentiment(body)
        log.info(
            "sentiment_analyzed",
            label=sentiment.label,
            score=sentiment.score,
            urgency=sentiment.urgency_level,
        )

        # Step 3 — Resolve property context
        prop: Optional[Property] = None
        if reservation:
            result = await db.execute(
                select(Property).where(Property.id == reservation.property_id)
            )
            prop = result.scalar_one_or_none()

        context = self._build_template_context(guest, reservation, prop)

        # Step 4 — Route to the correct handler
        decision: AgentDecision

        if intent == MessageIntent.EMERGENCY:
            decision = await self._handle_emergency(
                message, guest, reservation, prop, context, db
            )

        elif intent == MessageIntent.DAMAGE_REPORT:
            decision = await self._handle_damage_report(
                message, guest, reservation, prop, context, db
            )

        elif intent == MessageIntent.MAINTENANCE:
            decision = await self._handle_maintenance(
                message, guest, reservation, prop, context, db
            )

        elif intent == MessageIntent.COMPLAINT:
            decision = await self._handle_complaint(
                message, guest, context, db
            )

        elif intent in (
            MessageIntent.WIFI_QUESTION,
            MessageIntent.AMENITY_QUESTION,
            MessageIntent.LOCAL_RECOMMENDATION,
            MessageIntent.CHECKIN_QUESTION,
            MessageIntent.CHECKOUT_QUESTION,
            MessageIntent.QUESTION,
        ):
            decision = await self._handle_property_question(
                intent, message, guest, reservation, prop, context, db
            )

        elif intent == MessageIntent.ACCESS_CODE:
            decision = await self._handle_access_code(
                guest, reservation, prop, context, db
            )

        elif intent == MessageIntent.BOOKING_INQUIRY:
            decision = await self._handle_booking_inquiry(
                message, guest, context, db
            )

        elif intent == MessageIntent.POSITIVE_FEEDBACK:
            decision = self._handle_positive_feedback(guest, context)

        elif intent == MessageIntent.REVIEW:
            decision = self._handle_review(message, guest, reservation, context)

        elif intent == MessageIntent.GREETING:
            decision = self._handle_greeting(guest, context)

        else:
            decision = self._handle_generic(guest, context)

        # Attach classification metadata to decision
        decision.intent = intent
        decision.sentiment = sentiment
        decision.metadata["trace_id"] = str(trace_id)
        decision.metadata["guest_name"] = guest.full_name
        decision.metadata["property_name"] = prop.name if prop else None

        # Step 5 — Confidence gate
        if decision.response_text:
            eval_confidence = self.evaluate_auto_reply_confidence(
                message.body, decision.response_text
            )
            decision.confidence = max(decision.confidence, eval_confidence)

        auto_enabled = settings.enable_auto_replies and settings.enable_ai_responses
        if decision.confidence < self.CONFIDENCE_THRESHOLD or not auto_enabled:
            decision.should_auto_send = False

        log.info(
            "orchestrator_decision",
            action=decision.action,
            confidence=round(decision.confidence, 3),
            auto_send=decision.should_auto_send,
            escalation=decision.escalation_reason,
        )

        return decision

    # ──────────────────────────────────────────────────────────────────────
    #  2. auto_answer_from_knowledge_base
    # ──────────────────────────────────────────────────────────────────────

    STOP_WORDS = frozenset({
        "the", "and", "for", "are", "but", "not", "you", "all", "can",
        "her", "was", "one", "our", "out", "has", "have", "had", "its",
        "let", "say", "she", "too", "use", "way", "who", "how", "hey",
        "there", "their", "about", "would", "make", "like", "just",
        "over", "also", "back", "after", "with", "could", "them",
        "than", "been", "from", "that", "this", "what", "when", "where",
        "which", "some", "other", "into", "more", "does", "did", "get",
        "got", "any", "find", "here", "know", "take", "want", "come",
        "cabin", "cabins", "house", "place", "rental", "property",
    })

    def _extract_search_terms(self, text: str) -> tuple[list[str], list[str]]:
        """Extract meaningful keywords and bigrams from text, filtering stop words."""
        words = [w for w in re.split(r"\W+", text.lower()) if len(w) > 2]
        keywords = [w for w in words if w not in self.STOP_WORDS]
        bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]
        return keywords, bigrams

    async def auto_answer_from_knowledge_base(
        self,
        question: str,
        property_id: Optional[UUID],
        db: AsyncSession,
    ) -> Optional[str]:
        """
        Semantic vector search against fgp_knowledge (Qdrant) with
        automatic PostgreSQL keyword fallback.

        Returns the best matching answer text, or None if nothing
        relevant is found.
        """
        hits = await semantic_search(
            question=question,
            db=db,
            property_id=property_id,
            top_k=5,
        )

        if not hits:
            return None

        context = format_context(hits, max_chars=2000)
        if not context:
            return None

        self.log.info(
            "kb_semantic_match",
            top_score=hits[0].get("score", 0),
            results=len(hits),
            source=hits[0].get("source_table", ""),
        )
        return context

    # ──────────────────────────────────────────────────────────────────────
    #  2b. Board of Directors — Cloud-orchestrated tool delegation
    # ──────────────────────────────────────────────────────────────────────

    BOARD_CASCADE = ["anthropic", "gemini", "xai", "openai"]

    async def query_board_of_directors(
        self,
        user_message: str,
        system_context: str,
        db: AsyncSession,
        max_tool_rounds: int = 3,
    ) -> Optional[str]:
        """Delegate a complex query to the Board of Directors (cloud Horsemen).

        The primary orchestrator (Anthropic Opus 4.6) receives the user
        prompt along with DGX tool bindings.  It decides which local Spark
        nodes need to process data, executes tool calls, and synthesizes
        the final answer.  Falls back through Gemini -> xAI -> OpenAI
        if the primary is unavailable.

        Returns the final synthesized answer, or None if all providers fail.
        """
        system_msg = (
            "You are the Lead Orchestrator for Cabin Rentals of Georgia. "
            "You have access to local DGX GPU tools for vision analysis, "
            "deep document reasoning, and RAG knowledge retrieval. "
            "Use these tools when the guest's question requires property-specific "
            "knowledge, image analysis, or deep document analysis. "
            "Always provide warm, professional Southern hospitality in your answers.\n\n"
            f"{system_context}"
        )

        for provider_name in self.BOARD_CASCADE:
            try:
                result = await self._run_tool_loop(
                    provider_name, user_message, system_msg, db, max_tool_rounds,
                )
                if result:
                    self.log.info(
                        "board_orchestration_complete",
                        provider=provider_name,
                        answer_len=len(result),
                    )
                    return result
            except Exception as e:
                self.log.warning(
                    "board_provider_failed",
                    provider=provider_name,
                    error=str(e)[:200],
                )
                continue

        self.log.error("board_all_providers_failed")
        return None

    async def _run_tool_loop(
        self,
        provider_name: str,
        user_message: str,
        system_message: str,
        db: AsyncSession,
        max_rounds: int,
    ) -> Optional[str]:
        """Execute the tool-calling loop for a single provider."""
        api_key = str(settings.litellm_master_key or "").strip()
        if not api_key:
            return None

        model = getattr(settings, f"{provider_name}_model", "")

        if provider_name == "anthropic":
            return await self._anthropic_tool_loop(
                api_key, model, user_message, system_message, db, max_rounds,
            )
        else:
            return await self._openai_compat_tool_loop(
                provider_name, api_key, model, user_message, system_message, db, max_rounds,
            )

    async def _anthropic_tool_loop(
        self,
        api_key: str,
        model: str,
        user_message: str,
        system_message: str,
        db: AsyncSession,
        max_rounds: int,
    ) -> Optional[str]:
        """Anthropic aliases also route through the local LiteLLM tool lane."""
        return await self._openai_compat_tool_loop(
            "anthropic",
            api_key,
            model,
            user_message,
            system_message,
            db,
            max_rounds,
        )

    async def _openai_compat_tool_loop(
        self,
        provider_name: str,
        api_key: str,
        model: str,
        user_message: str,
        system_message: str,
        db: AsyncSession,
        max_rounds: int,
    ) -> Optional[str]:
        """OpenAI-compatible tool calling loop routed through LiteLLM."""
        import json as _json

        base_url = str(settings.litellm_base_url or "").strip().rstrip("/")
        if not base_url:
            return None
        url = f"{base_url.rstrip('/')}/chat/completions"
        tools = get_openai_tools()

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]

        async with httpx.AsyncClient(timeout=120) as client:
            for _round in range(max_rounds):
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "tools": tools,
                        "max_tokens": 2048,
                        "temperature": 0.4,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                choice = data["choices"][0]
                msg = choice["message"]
                finish = choice.get("finish_reason", "stop")

                if finish != "tool_calls" or "tool_calls" not in msg:
                    return (msg.get("content") or "").strip() or None

                messages.append(msg)

                for tc in msg["tool_calls"]:
                    fn_name = tc["function"]["name"]
                    fn_args = _json.loads(tc["function"]["arguments"])
                    self.log.info(
                        "board_tool_call",
                        provider=provider_name,
                        tool=fn_name,
                        round=_round + 1,
                    )
                    output = await execute_tool_call(fn_name, fn_args, db=db)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": output[:8000],
                    })

        return None

    # ──────────────────────────────────────────────────────────────────────
    #  3. run_daily_automation
    # ──────────────────────────────────────────────────────────────────────

    async def run_daily_automation(self, db: AsyncSession) -> Dict[str, Any]:
        """
        Daily autonomous operations:
        - Pre-arrival messages (24h before check-in)
        - Access codes (4h before check-in — scheduled)
        - Mid-stay check-in (day 2)
        - Checkout reminders (day before checkout)
        - Post-stay review requests (24h after checkout)
        - Auto-update reservation statuses
        - Schedule housekeeping for checkouts
        """
        self.log.info("daily_automation_starting")
        today = date.today()
        now = datetime.utcnow()
        results: Dict[str, Any] = {
            "pre_arrival_24h": 0,
            "access_code_scheduled": 0,
            "mid_stay_checkin": 0,
            "checkout_reminder": 0,
            "post_stay_review": 0,
            "status_updates": 0,
            "housekeeping_scheduled": 0,
            "errors": [],
        }

        # ── Pre-Arrival Messages (24h before check-in) ──
        tomorrow = today + timedelta(days=1)
        pre_arrival_res = await db.execute(
            select(Reservation)
            .options(selectinload(Reservation.guest), selectinload(Reservation.prop))
            .where(
                and_(
                    Reservation.check_in_date == tomorrow,
                    Reservation.status == "confirmed",
                    Reservation.pre_arrival_sent == False,  # noqa: E712
                )
            )
        )
        for res in pre_arrival_res.scalars().all():
            try:
                ctx = self._build_template_context(res.guest, res, res.prop)
                body = self.generate_response(ctx, "warm", "pre_arrival_24h")
                await self._send_automated_sms(
                    db, res.guest, res, body, "pre_arrival_24h"
                )
                res.pre_arrival_sent = True
                results["pre_arrival_24h"] += 1
            except Exception as exc:
                results["errors"].append(f"pre_arrival:{res.id}:{exc}")

        # ── Access Codes (schedule for 4h before check-in = noon) ──
        access_res = await db.execute(
            select(Reservation)
            .options(selectinload(Reservation.guest), selectinload(Reservation.prop))
            .where(
                and_(
                    Reservation.check_in_date == today,
                    Reservation.status == "confirmed",
                    Reservation.access_info_sent == False,  # noqa: E712
                )
            )
        )
        for res in access_res.scalars().all():
            try:
                ctx = self._build_template_context(res.guest, res, res.prop)
                body = self.generate_response(ctx, "warm", "access_code_4h")
                await self._send_automated_sms(
                    db, res.guest, res, body, "access_code_4h"
                )
                res.access_info_sent = True
                results["access_code_scheduled"] += 1
            except Exception as exc:
                results["errors"].append(f"access_code:{res.id}:{exc}")

        # ── Mid-Stay Check-in (day 2 of stay) ──
        day2_checkin = today - timedelta(days=2)
        mid_stay_res = await db.execute(
            select(Reservation)
            .options(selectinload(Reservation.guest), selectinload(Reservation.prop))
            .where(
                and_(
                    Reservation.check_in_date == day2_checkin,
                    Reservation.status == "checked_in",
                    Reservation.mid_stay_checkin_sent == False,  # noqa: E712
                    Reservation.check_out_date > today,
                )
            )
        )
        for res in mid_stay_res.scalars().all():
            try:
                ctx = self._build_template_context(res.guest, res, res.prop)
                body = self.generate_response(ctx, "warm", "mid_stay_checkin")
                await self._send_automated_sms(
                    db, res.guest, res, body, "mid_stay_checkin"
                )
                res.mid_stay_checkin_sent = True
                results["mid_stay_checkin"] += 1
            except Exception as exc:
                results["errors"].append(f"mid_stay:{res.id}:{exc}")

        # ── Checkout Reminders (day before checkout) ──
        checkout_tomorrow = today + timedelta(days=1)
        checkout_res = await db.execute(
            select(Reservation)
            .options(selectinload(Reservation.guest), selectinload(Reservation.prop))
            .where(
                and_(
                    Reservation.check_out_date == checkout_tomorrow,
                    Reservation.status.in_(["confirmed", "checked_in"]),
                    Reservation.checkout_reminder_sent == False,  # noqa: E712
                )
            )
        )
        for res in checkout_res.scalars().all():
            try:
                ctx = self._build_template_context(res.guest, res, res.prop)
                body = self.generate_response(ctx, "warm", "checkout_reminder")
                await self._send_automated_sms(
                    db, res.guest, res, body, "checkout_reminder"
                )
                res.checkout_reminder_sent = True
                results["checkout_reminder"] += 1
            except Exception as exc:
                results["errors"].append(f"checkout:{res.id}:{exc}")

        # ── Post-Stay Review Requests (24h after checkout) ──
        yesterday = today - timedelta(days=1)
        post_stay_res = await db.execute(
            select(Reservation)
            .options(selectinload(Reservation.guest), selectinload(Reservation.prop))
            .where(
                and_(
                    Reservation.check_out_date == yesterday,
                    Reservation.post_stay_followup_sent == False,  # noqa: E712
                )
            )
        )
        for res in post_stay_res.scalars().all():
            try:
                ctx = self._build_template_context(res.guest, res, res.prop)
                body = self.generate_response(ctx, "warm", "post_stay_review")
                await self._send_automated_sms(
                    db, res.guest, res, body, "post_stay_review"
                )
                res.post_stay_followup_sent = True
                # Update guest stats
                res.guest.total_stays = (res.guest.total_stays or 0) + 1
                res.guest.last_stay_date = res.check_out_date
                results["post_stay_review"] += 1
            except Exception as exc:
                results["errors"].append(f"post_stay:{res.id}:{exc}")

        # ── Auto-Update Reservation Statuses ──
        # Mark arrivals as checked_in, departures as checked_out
        arrivals = await db.execute(
            select(Reservation).where(
                and_(
                    Reservation.check_in_date <= today,
                    Reservation.check_out_date > today,
                    Reservation.status == "confirmed",
                )
            )
        )
        for res in arrivals.scalars().all():
            res.status = "checked_in"
            results["status_updates"] += 1

        departures = await db.execute(
            select(Reservation).where(
                and_(
                    Reservation.check_out_date <= today,
                    Reservation.status.in_(["confirmed", "checked_in"]),
                )
            )
        )
        for res in departures.scalars().all():
            res.status = "checked_out"
            results["status_updates"] += 1

        # ── Schedule Housekeeping for Checkouts ──
        checkout_today = await db.execute(
            select(Reservation)
            .options(selectinload(Reservation.prop))
            .where(
                and_(
                    Reservation.check_out_date == today,
                    Reservation.status.in_(["confirmed", "checked_in", "checked_out"]),
                )
            )
        )
        for res in checkout_today.scalars().all():
            existing_wo = await db.execute(
                select(WorkOrder).where(
                    and_(
                        WorkOrder.property_id == res.property_id,
                        WorkOrder.category == "housekeeping",
                        WorkOrder.created_at >= datetime.combine(today, datetime.min.time()),
                    )
                )
            )
            if existing_wo.scalar_one_or_none() is None:
                prop_name = res.prop.name if res.prop else "Unknown"
                wo = WorkOrder(
                    ticket_number=f"HK-{today.strftime('%Y%m%d')}-{str(uuid4())[:4].upper()}",
                    property_id=res.property_id,
                    reservation_id=res.id,
                    title=f"Checkout Turnover: {prop_name}",
                    description=(
                        f"Scheduled housekeeping turnover for {prop_name} "
                        f"following guest checkout on {today}."
                    ),
                    category="housekeeping",
                    priority="medium",
                    status="open",
                    created_by="ai_automated",
                )
                db.add(wo)
                results["housekeeping_scheduled"] += 1

        await db.commit()

        # ── AI Foreman: Morning Housekeeping Dispatch (6 AM ET window) ──
        import pytz
        et_now = datetime.now(pytz.timezone("America/New_York"))
        results["housekeeping_dispatched"] = 0

        if 5 <= et_now.hour <= 8:
            try:
                from backend.services.housekeeping_agent import dispatch_turnover
                from backend.services.housekeeping_service import HousekeepingTask

                checkout_res = await db.execute(
                    select(Reservation)
                    .where(
                        and_(
                            Reservation.check_out_date == today,
                            Reservation.status.in_(["confirmed", "checked_in", "checked_out"]),
                        )
                    )
                )
                checkout_reservations = checkout_res.scalars().all()

                for res in checkout_reservations:
                    existing_dispatch = await db.execute(
                        select(HousekeepingTask).where(
                            and_(
                                HousekeepingTask.property_id == res.property_id,
                                HousekeepingTask.scheduled_date == today,
                                HousekeepingTask.dispatched_by == "ai_agent",
                            )
                        ).limit(1)
                    )
                    if existing_dispatch.scalars().first():
                        continue

                    try:
                        result = await dispatch_turnover(res.id, res.property_id, db)
                        if not result.get("error"):
                            results["housekeeping_dispatched"] += 1
                    except Exception as e:
                        results["errors"].append(f"HK dispatch {res.confirmation_code}: {e}")

                if results["housekeeping_dispatched"]:
                    self.log.info(
                        "ai_foreman_morning_sweep",
                        dispatched=results["housekeeping_dispatched"],
                    )
            except Exception as e:
                results["errors"].append(f"AI Foreman sweep: {e}")

        self.log.info("daily_automation_complete", results=results)
        return results

    # ──────────────────────────────────────────────────────────────────────
    #  4. escalate_to_staff
    # ──────────────────────────────────────────────────────────────────────

    async def escalate_to_staff(
        self,
        message: Message,
        reason: str,
        priority: str,
        db: AsyncSession,
    ) -> None:
        """
        Send an SMS notification to on-duty staff and log the escalation.
        """
        log = self.log.bind(
            message_id=str(message.id),
            reason=reason,
            priority=priority,
        )

        # Find staff members who should be notified
        staff_result = await db.execute(
            select(StaffUser).where(
                and_(
                    StaffUser.is_active == True,  # noqa: E712
                    StaffUser.notify_urgent == True,  # noqa: E712
                    StaffUser.notification_phone.isnot(None),
                )
            )
        )
        staff_members = list(staff_result.scalars().all())

        # Build escalation SMS
        guest_info = ""
        if message.guest:
            guest_info = f"Guest: {message.guest.full_name} ({message.phone_from})\n"

        alert_body = (
            f"ALERT [{priority.upper()}] — Cabin Rentals of Georgia\n\n"
            f"{guest_info}"
            f"Reason: {reason}\n"
            f"Message: {message.body[:200]}\n\n"
            f"Reply CLAIM to take this on."
        )

        notified_count = 0

        # Notify all matching staff; fall back to global notification phone
        phones_to_notify: List[str] = []
        for staff in staff_members:
            if staff.notification_phone:
                phones_to_notify.append(staff.notification_phone)

        if not phones_to_notify and settings.staff_notification_phone:
            phones_to_notify.append(settings.staff_notification_phone)

        for phone in phones_to_notify:
            try:
                await self.twilio.send_sms(to=phone, body=alert_body)
                notified_count += 1
            except Exception as exc:
                log.error("staff_notification_failed", phone=phone, error=str(exc))

        # Mark message as requiring human review
        message.requires_human_review = True
        await db.commit()

        log.info("escalation_complete", notified_count=notified_count)

    # ──────────────────────────────────────────────────────────────────────
    #  5. generate_response
    # ──────────────────────────────────────────────────────────────────────

    def generate_response(
        self,
        context: Dict[str, str],
        tone: str = "warm",
        template_name: str = "generic_fallback",
    ) -> str:
        """
        Render a response from RESPONSE_TEMPLATES using the supplied
        context dict.  Gracefully falls back when template variables
        are missing.
        """
        template = RESPONSE_TEMPLATES.get(template_name)
        if not template:
            template = RESPONSE_TEMPLATES["generic_fallback"]

        try:
            return template.format_map(_SafeFormatDict(context))
        except Exception:
            return RESPONSE_TEMPLATES["generic_fallback"].format_map(
                _SafeFormatDict(context)
            )

    # ──────────────────────────────────────────────────────────────────────
    #  6. evaluate_auto_reply_confidence
    # ──────────────────────────────────────────────────────────────────────

    TOPIC_PHRASES = [
        "hot tub", "fire pit", "fireplace", "firewood", "fire wood",
        "washer", "dryer", "laundry", "pool", "grill", "bbq",
        "wifi", "wi-fi", "internet", "parking", "check in", "check out",
        "checkout", "checkin", "pet", "dog", "trash", "garbage",
        "thermostat", "heat", "ac", "air conditioning", "tv", "remote",
        "coffee", "kitchen", "oven", "dishwasher", "towel", "linen",
        "hot water", "shower", "bathtub", "deck", "porch", "grill",
        "propane", "gas", "fireplace", "smart lock", "door code",
        "key", "keypad", "lock box",
    ]

    def _extract_topics(self, text: str) -> set[str]:
        """Pull guest-relevant topic phrases from a message."""
        low = text.lower()
        found: set[str] = set()
        for phrase in self.TOPIC_PHRASES:
            if phrase in low:
                found.add(phrase)
        single_words = set(re.findall(r"[a-z]{3,}", low)) - self.STOP_WORDS
        found.update(single_words)
        return found

    def evaluate_auto_reply_confidence(
        self, original_message: str, proposed_response: str
    ) -> float:
        """
        Score 0.0-1.0 on whether the proposed auto-reply is safe to send.

        Factors:
        - Response is non-empty and reasonable length
        - No leftover template placeholders
        - No sensitive/dangerous content
        - Original message doesn't contain profanity or legal terms
        - **Semantic relevance** — the response must address the topics
          the guest actually asked about
        """
        if not proposed_response or not proposed_response.strip():
            return 0.0

        score = 0.5  # baseline

        # Length sanity — too short or too long is risky
        resp_len = len(proposed_response)
        if 20 <= resp_len <= 1200:
            score += 0.15
        elif resp_len > 1200:
            score -= 0.1

        # Leftover {placeholders} indicate a rendering failure
        if re.search(r"\{[a-z_]+\}", proposed_response):
            score -= 0.3

        # Contains actual property-specific info (not just filler)
        info_signals = ["code", "password", "network", "4 PM", "11 AM", "cabin"]
        if any(sig.lower() in proposed_response.lower() for sig in info_signals):
            score += 0.1

        # Dangerous content in the original message lowers confidence
        danger_words = [
            "lawyer", "attorney", "lawsuit", "sue", "legal action",
            "health department", "police report", "media",
        ]
        msg_lower = original_message.lower()
        if any(dw in msg_lower for dw in danger_words):
            score -= 0.4

        # Profanity detection (simple)
        profanity = ["fuck", "shit", "damn", "ass", "bitch", "hell"]
        if any(p in msg_lower for p in profanity):
            score -= 0.15

        # Semantic relevance — do the question topics appear in the answer?
        q_topics = self._extract_topics(original_message)
        a_topics = self._extract_topics(proposed_response)
        if q_topics:
            overlap = q_topics & a_topics
            if not overlap:
                score -= 0.3
            elif len(overlap) >= 2:
                score += 0.1

        return max(0.0, min(1.0, round(score, 3)))

    # ──────────────────────────────────────────────────────────────────────
    #  7. get_agent_stats
    # ──────────────────────────────────────────────────────────────────────

    async def get_agent_stats(
        self, db: AsyncSession, days: int = 30
    ) -> Dict[str, Any]:
        """
        Comprehensive stats on the orchestrator's autonomous performance.
        """
        since = datetime.utcnow() - timedelta(days=days)

        # Total messages
        total_q = await db.execute(
            select(func.count(Message.id)).where(Message.created_at >= since)
        )
        total_messages = total_q.scalar() or 0

        # Auto-answered
        auto_q = await db.execute(
            select(func.count(Message.id)).where(
                and_(
                    Message.created_at >= since,
                    Message.is_auto_response == True,  # noqa: E712
                )
            )
        )
        auto_answered = auto_q.scalar() or 0

        # Escalated (required human review)
        escalated_q = await db.execute(
            select(func.count(Message.id)).where(
                and_(
                    Message.created_at >= since,
                    Message.requires_human_review == True,  # noqa: E712
                    Message.direction == "inbound",
                )
            )
        )
        escalated = escalated_q.scalar() or 0

        # Average AI confidence
        confidence_q = await db.execute(
            select(func.avg(Message.ai_confidence)).where(
                and_(
                    Message.created_at >= since,
                    Message.ai_confidence.isnot(None),
                )
            )
        )
        avg_confidence = float(confidence_q.scalar() or 0)

        # Sentiment breakdown
        sentiment_q = await db.execute(
            select(Message.sentiment, func.count(Message.id))
            .where(
                and_(
                    Message.created_at >= since,
                    Message.direction == "inbound",
                    Message.sentiment.isnot(None),
                )
            )
            .group_by(Message.sentiment)
        )
        sentiment_dist = dict(sentiment_q.all())

        # Intent breakdown
        intent_q = await db.execute(
            select(Message.intent, func.count(Message.id))
            .where(
                and_(
                    Message.created_at >= since,
                    Message.direction == "inbound",
                    Message.intent.isnot(None),
                )
            )
            .group_by(Message.intent)
        )
        intent_dist = dict(intent_q.all())

        # Work orders auto-created
        wo_q = await db.execute(
            select(func.count(WorkOrder.id)).where(
                and_(
                    WorkOrder.created_at >= since,
                    WorkOrder.created_by.in_(["ai_detected", "ai_automated"]),
                )
            )
        )
        auto_work_orders = wo_q.scalar() or 0

        # Average response time (outbound sent_at - most recent inbound created_at)
        inbound_count = total_messages - auto_answered
        automation_rate = (
            (auto_answered / total_messages * 100) if total_messages > 0 else 0.0
        )

        return {
            "period_days": days,
            "total_messages": total_messages,
            "auto_answered": auto_answered,
            "escalated_to_human": escalated,
            "automation_rate_pct": round(automation_rate, 1),
            "avg_ai_confidence": round(avg_confidence, 3),
            "sentiment_distribution": sentiment_dist,
            "intent_distribution": intent_dist,
            "auto_work_orders_created": auto_work_orders,
            "generated_at": datetime.utcnow().isoformat(),
        }

    # ══════════════════════════════════════════════════════════════════════
    #  PRIVATE — Intent Classification
    # ══════════════════════════════════════════════════════════════════════

    def _classify_intent(self, body: str) -> MessageIntent:
        """Hybrid keyword classification with weighted scoring."""
        body_lower = body.lower().strip()
        if not body_lower:
            return MessageIntent.OTHER

        best_intent = MessageIntent.OTHER
        best_score = 0.0

        for intent, keywords in _INTENT_KEYWORDS.items():
            score = 0.0
            for kw in keywords:
                if kw in body_lower:
                    # Longer keyword phrases get higher weight
                    weight = 1.0 + (kw.count(" ") * 0.5)
                    score += weight

            if score > best_score:
                best_score = score
                best_intent = intent

        # If the message is very short and nothing matched well, check
        # for single-word greetings
        if best_score < 1.0 and len(body_lower.split()) <= 3:
            greets = {"hi", "hey", "hello", "howdy", "yo", "sup"}
            if body_lower.strip("!. ") in greets:
                return MessageIntent.GREETING

        return best_intent

    # ══════════════════════════════════════════════════════════════════════
    #  PRIVATE — Sentiment Analysis
    # ══════════════════════════════════════════════════════════════════════

    def _analyze_sentiment(self, body: str) -> SentimentScore:
        """Lexicon-based sentiment with urgency detection."""
        body_lower = body.lower()

        # Urgency keywords (highest priority)
        urgent_kw = [
            "emergency", "urgent", "help", "asap", "immediately",
            "dangerous", "fire", "flood", "gas leak", "911",
            "injured", "ambulance", "can't breathe",
        ]
        if any(kw in body_lower for kw in urgent_kw):
            return SentimentScore(score=-1.0, label="urgent", urgency_level=4)

        # Negative keywords
        negative_kw = [
            "terrible", "horrible", "disgusting", "disappointed",
            "angry", "upset", "unacceptable", "worst", "awful",
            "dirty", "broken", "refund", "complaint", "rude",
        ]
        neg_hits = sum(1 for kw in negative_kw if kw in body_lower)

        # Positive keywords
        positive_kw = [
            "amazing", "wonderful", "perfect", "love", "great",
            "excellent", "beautiful", "fantastic", "awesome",
            "thank", "appreciate", "best", "stunning", "cozy",
        ]
        pos_hits = sum(1 for kw in positive_kw if kw in body_lower)

        if neg_hits > pos_hits and neg_hits >= 1:
            urgency = 2 if neg_hits >= 3 else 1
            score = -0.3 - (min(neg_hits, 5) * 0.12)
            return SentimentScore(
                score=round(score, 2), label="negative", urgency_level=urgency
            )

        if pos_hits > neg_hits and pos_hits >= 1:
            score = 0.3 + (min(pos_hits, 5) * 0.12)
            return SentimentScore(
                score=round(score, 2), label="positive", urgency_level=0
            )

        return SentimentScore(score=0.0, label="neutral", urgency_level=0)

    # ══════════════════════════════════════════════════════════════════════
    #  PRIVATE — Handler Methods
    # ══════════════════════════════════════════════════════════════════════

    async def _handle_emergency(
        self,
        message: Message,
        guest: Guest,
        reservation: Optional[Reservation],
        prop: Optional[Property],
        context: Dict[str, str],
        db: AsyncSession,
    ) -> AgentDecision:
        """Immediately escalate — lives may be at stake."""
        response = self.generate_response(context, "urgent", "emergency_ack")

        await self.escalate_to_staff(
            message, reason="EMERGENCY detected in guest message", priority="urgent", db=db
        )

        return AgentDecision(
            action="escalate_emergency",
            response_text=response,
            confidence=0.95,
            should_auto_send=True,  # Always send the ack immediately
            escalation_reason="Emergency keywords detected — staff notified",
        )

    async def _handle_damage_report(
        self,
        message: Message,
        guest: Guest,
        reservation: Optional[Reservation],
        prop: Optional[Property],
        context: Dict[str, str],
        db: AsyncSession,
    ) -> AgentDecision:
        """Enterprise escalation: idempotent damage claim dispatch.

        1. Idempotency lock — check message isn't already processing
        2. Async dispatch — fire damage workflow in background task
        3. Dead letter — catch dispatch failures, mark for manual review
        """
        import asyncio

        log = self.log.bind(
            handler="damage_report",
            message_id=str(message.id),
            guest=guest.full_name if guest else "unknown",
        )

        # ── Idempotency Lock ──
        if hasattr(message, "processing_status") and message.processing_status not in (None, "PENDING"):
            log.info("damage_already_processing", status=message.processing_status)
            return AgentDecision(
                action="damage_already_processing",
                response_text=None,
                confidence=0.95,
                should_auto_send=False,
                metadata={"status": message.processing_status},
            )

        # Mark as processing to prevent duplicate dispatch
        if hasattr(message, "processing_status"):
            message.processing_status = "PROCESSING_DAMAGE"
        message.requires_human_review = True
        await db.commit()

        log.info("damage_report_escalating", body_preview=message.body[:80])

        # ── Audit Trail ──
        from backend.models.analytics import AnalyticsEvent
        audit = AnalyticsEvent(
            event_type="damage_escalation",
            guest_id=guest.id if guest else None,
            reservation_id=reservation.id if reservation else None,
            property_id=prop.id if prop else None,
            event_data={
                "source": "orchestrator_auto_escalation",
                "intent": "damage_report",
                "message_preview": message.body[:200],
                "confidence": 0.90,
                "note": "System automatically escalated high-confidence damage report to Council of Giants.",
            },
        )
        db.add(audit)
        await db.commit()

        reservation_id = reservation.id if reservation else None
        claim_number = None

        if reservation_id:
            # ── Async Dispatch with Dead Letter ──
            try:
                from backend.services.damage_workflow import process_damage_claim

                async def _bg_damage():
                    from backend.core.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as bg_db:
                        return await process_damage_claim(
                            reservation_id=reservation_id,
                            staff_notes=message.body,
                            db=bg_db,
                            reported_by=f"{guest.full_name} (auto-escalated)" if guest else "auto-escalated",
                        )

                task = asyncio.create_task(_bg_damage())
                task.add_done_callback(
                    lambda t: log.info(
                        "damage_bg_task_complete",
                        error=str(t.exception())[:200] if t.exception() else None,
                    )
                )

                ts = int(time.time())
                short = str(uuid4())[:6].upper()
                claim_number = f"DC-{ts}-{short}"
                context["claim_number"] = claim_number

                log.info("damage_workflow_dispatched", claim_number=claim_number)

            except Exception as e:
                # ── Dead Letter ──
                log.error("damage_dispatch_failed_dead_letter", error=str(e)[:200])
                if hasattr(message, "processing_status"):
                    message.processing_status = "DEAD_LETTER"
                await db.commit()

                return AgentDecision(
                    action="damage_dead_letter",
                    response_text=None,
                    confidence=0.0,
                    should_auto_send=False,
                    escalation_reason=f"Damage workflow dispatch failed: {str(e)[:100]}",
                    metadata={"dead_letter": True},
                )

        # Notify staff immediately regardless of workflow status
        await self.escalate_to_staff(
            message,
            reason=f"DAMAGE REPORT detected — Damage Command Center dispatched (claim {claim_number or 'pending'})",
            priority="high",
            db=db,
        )

        response = self.generate_response(context, "empathetic", "damage_ack")

        return AgentDecision(
            action="damage_report_escalated",
            response_text=response,
            confidence=0.90,
            should_auto_send=True,
            escalation_reason="Damage report — Council of Giants workflow dispatched",
            metadata={
                "claim_number": claim_number,
                "source": "damage_report_auto_escalation",
            },
        )

    async def _handle_maintenance(
        self,
        message: Message,
        guest: Guest,
        reservation: Optional[Reservation],
        prop: Optional[Property],
        context: Dict[str, str],
        db: AsyncSession,
    ) -> AgentDecision:
        """Create work order and acknowledge to guest."""
        property_id = reservation.property_id if reservation else (prop.id if prop else None)
        ticket_number = f"WO-{datetime.now().strftime('%Y%m%d%H%M')}-{str(uuid4())[:4].upper()}"

        if property_id:
            # Detect category from body
            body_lower = message.body.lower()
            category = "other"
            category_map = {
                "hvac": ["ac", "heat", "thermostat", "cold", "warm", "temperature"],
                "plumbing": ["water", "toilet", "shower", "drain", "leak", "faucet", "sink"],
                "electrical": ["light", "power", "outlet", "switch", "electric", "breaker"],
                "hot_tub": ["hot tub", "jacuzzi", "spa", "jets", "tub"],
                "appliance": ["fridge", "oven", "stove", "dishwasher", "washer", "dryer", "microwave"],
            }
            for cat, kws in category_map.items():
                if any(kw in body_lower for kw in kws):
                    category = cat
                    break

            priority = "high" if any(
                w in body_lower for w in ["not working", "broken", "emergency", "no water", "no power"]
            ) else "medium"

            wo = WorkOrder(
                ticket_number=ticket_number,
                property_id=property_id,
                guest_id=guest.id,
                reservation_id=reservation.id if reservation else None,
                reported_via_message_id=message.id,
                title=f"Guest Report: {message.body[:80]}",
                description=message.body,
                category=category,
                priority=priority,
                status="open",
                created_by="ai_detected",
            )
            db.add(wo)
            await db.commit()

            context["ticket_number"] = ticket_number
            self.log.info("auto_work_order_created", ticket=ticket_number, category=category)

        response = self.generate_response(context, "empathetic", "maintenance_ack")

        await self.escalate_to_staff(
            message, reason=f"Maintenance request — ticket {ticket_number}", priority="high", db=db
        )

        return AgentDecision(
            action="create_work_order",
            response_text=response,
            confidence=0.88,
            should_auto_send=True,
            escalation_reason="Maintenance issue — work order created and staff notified",
            metadata={"ticket_number": ticket_number},
        )

    async def _handle_complaint(
        self,
        message: Message,
        guest: Guest,
        context: Dict[str, str],
        db: AsyncSession,
    ) -> AgentDecision:
        """Acknowledge the complaint and escalate for human follow-up."""
        response = self.generate_response(context, "empathetic", "complaint_ack")

        await self.escalate_to_staff(
            message, reason="Guest complaint — requires human empathy", priority="high", db=db
        )

        return AgentDecision(
            action="acknowledge_and_escalate",
            response_text=response,
            confidence=0.80,
            should_auto_send=True,
            escalation_reason="Complaint — staff will follow up personally",
        )

    @staticmethod
    def _format_amenity_names(prop: Optional["Property"]) -> str:
        """Extract a concise, comma-separated amenity list from the cached JSONB."""
        if not prop or not prop.amenities:
            return ""
        seen: set[str] = set()
        names: list[str] = []
        for a in prop.amenities:
            name = (a.get("amenity_name") or a.get("name") or "").strip()
            low = name.lower()
            if not name or low in seen:
                continue
            seen.add(low)
            names.append(name)
        return ", ".join(names[:40])

    async def _handle_property_question(
        self,
        intent: MessageIntent,
        message: Message,
        guest: Guest,
        reservation: Optional[Reservation],
        prop: Optional[Property],
        context: Dict[str, str],
        db: AsyncSession,
    ) -> AgentDecision:
        """Answer property questions via 3-tier cascade:
        Tier 1: Local Qdrant RAG (instant, sovereign)
        Tier 2: Board of Directors cloud orchestration with DGX tool calls
        Tier 3: Dynamic template fallback (uses real property amenities)
        """
        greeting = f"Hey {context.get('guest_name', 'there')}! "
        property_id = reservation.property_id if reservation else None
        amenity_summary = self._format_amenity_names(prop)

        # Tier 1: Local RAG (fast, no cloud egress)
        kb_answer = await self.auto_answer_from_knowledge_base(
            message.body, property_id, db
        )

        if kb_answer:
            response = greeting + kb_answer
            return AgentDecision(
                action="auto_reply_from_kb",
                response_text=response,
                confidence=0.78,
                should_auto_send=True,
                metadata={"source": "knowledge_base"},
            )

        # Tier 2: Board of Directors — cloud Horsemen with DGX tool delegation
        board_context = (
            f"Guest: {context.get('guest_name', 'Unknown')}\n"
            f"Property: {context.get('property_name', 'Unknown')}\n"
            f"Property ID: {property_id or 'N/A'}\n"
            f"Check-in: {context.get('check_in', 'N/A')}\n"
            f"Check-out: {context.get('check_out', 'N/A')}\n"
        )
        if amenity_summary:
            board_context += f"Property Amenities: {amenity_summary}\n"

        try:
            board_answer = await self.query_board_of_directors(
                user_message=message.body,
                system_context=board_context,
                db=db,
            )
            if board_answer:
                response = greeting + board_answer
                return AgentDecision(
                    action="auto_reply_from_board",
                    response_text=response,
                    confidence=0.80,
                    should_auto_send=True,
                    metadata={"source": "board_of_directors"},
                )
        except Exception as e:
            self.log.warning("board_escalation_failed", error=str(e)[:200])

        # Tier 3: Dynamic template fallback (uses real amenity data)
        if intent == MessageIntent.AMENITY_QUESTION and amenity_summary:
            response = (
                f"{greeting}Great question about {context.get('property_name', 'your cabin')}!\n\n"
                f"This cabin's amenities include: {amenity_summary}.\n\n"
                "Check your digital guest guide for the full rundown. "
                "Enjoy every minute of it!"
            )
            return AgentDecision(
                action="auto_reply_dynamic_amenity",
                response_text=response,
                confidence=0.70,
                should_auto_send=False,
                metadata={"source": "dynamic_amenity_template"},
            )

        template_map = {
            MessageIntent.WIFI_QUESTION: "wifi_answer",
            MessageIntent.CHECKIN_QUESTION: "checkin_info",
            MessageIntent.CHECKOUT_QUESTION: "checkout_info",
            MessageIntent.AMENITY_QUESTION: "amenity_info",
            MessageIntent.LOCAL_RECOMMENDATION: "local_tips",
        }
        template_name = template_map.get(intent, "generic_fallback")
        response = self.generate_response(context, "warm", template_name)

        return AgentDecision(
            action="auto_reply_template",
            response_text=response,
            confidence=0.70,
            should_auto_send=False,
            metadata={"template": template_name},
        )

    async def _handle_access_code(
        self,
        guest: Guest,
        reservation: Optional[Reservation],
        prop: Optional[Property],
        context: Dict[str, str],
        db: AsyncSession,
    ) -> AgentDecision:
        """Send access info if we have it, otherwise escalate."""
        has_code = reservation and reservation.access_code
        if has_code:
            response = self.generate_response(context, "warm", "access_info")
            return AgentDecision(
                action="send_access_info",
                response_text=response,
                confidence=0.92,
                should_auto_send=True,
            )

        # We don't have the code on file — escalate
        response = (
            f"Hey {context.get('guest_name', 'there')}! Let me get that "
            f"access info for you right away. One of our team members "
            f"will text you back shortly with the code."
        )
        return AgentDecision(
            action="escalate_access_code",
            response_text=response,
            confidence=0.70,
            should_auto_send=True,
            escalation_reason="Access code not on file — staff needs to provide",
        )

    async def _handle_booking_inquiry(
        self,
        message: Message,
        guest: Guest,
        context: Dict[str, str],
        db: AsyncSession,
    ) -> AgentDecision:
        """Route booking inquiries to human — we don't auto-book."""
        response = self.generate_response(context, "warm", "booking_inquiry_ack")

        await self.escalate_to_staff(
            message, reason="Booking inquiry — guest wants to book or extend", priority="medium", db=db
        )

        return AgentDecision(
            action="route_to_booking_flow",
            response_text=response,
            confidence=0.80,
            should_auto_send=True,
            escalation_reason="Booking inquiry requires human decision",
        )

    def _handle_positive_feedback(
        self, guest: Guest, context: Dict[str, str]
    ) -> AgentDecision:
        """Thank the guest and offer a return discount."""
        response = self.generate_response(context, "warm", "positive_thank")
        return AgentDecision(
            action="log_and_thank",
            response_text=response,
            confidence=0.92,
            should_auto_send=True,
        )

    def _handle_review(
        self,
        message: Message,
        guest: Guest,
        reservation: Optional[Reservation],
        context: Dict[str, str],
    ) -> AgentDecision:
        """Parse star rating if present, thank the guest."""
        rating_match = re.search(r"\b([1-5])\s*(?:star|stars|/5)?\b", message.body)
        if rating_match and reservation:
            rating = int(rating_match.group(1))
            response = (
                f"Thank you so much, {context.get('guest_name', 'there')}! "
                f"We really appreciate your {rating}-star rating. "
            )
            if rating >= 4:
                response += "That means the world to us! We'd love to host y'all again."
            else:
                response += (
                    "We're sorry it wasn't 5 stars. We'd love to hear "
                    "what we can improve — feel free to share any details."
                )
            return AgentDecision(
                action="log_review",
                response_text=response,
                confidence=0.88,
                should_auto_send=True,
                metadata={"rating": rating},
            )

        response = self.generate_response(context, "warm", "positive_thank")
        return AgentDecision(
            action="log_and_thank",
            response_text=response,
            confidence=0.78,
            should_auto_send=True,
        )

    def _handle_greeting(
        self, guest: Guest, context: Dict[str, str]
    ) -> AgentDecision:
        """Reply to greetings warmly."""
        response = self.generate_response(context, "warm", "greeting_reply")
        return AgentDecision(
            action="auto_reply_greeting",
            response_text=response,
            confidence=0.90,
            should_auto_send=True,
        )

    def _handle_generic(
        self, guest: Guest, context: Dict[str, str]
    ) -> AgentDecision:
        """Fallback for anything the classifier couldn't categorize."""
        response = self.generate_response(context, "warm", "generic_fallback")
        return AgentDecision(
            action="auto_reply_generic",
            response_text=response,
            confidence=0.55,
            should_auto_send=False,  # Low confidence — queue for review
            escalation_reason="Intent unclear — queued for human review",
        )

    # ══════════════════════════════════════════════════════════════════════
    #  PRIVATE — Helpers
    # ══════════════════════════════════════════════════════════════════════

    def _build_template_context(
        self,
        guest: Optional[Guest],
        reservation: Optional[Reservation],
        prop: Optional[Property],
    ) -> Dict[str, str]:
        """Assemble the variable dict used by all response templates."""
        ctx: Dict[str, str] = {
            "guest_name": (guest.first_name or "there") if guest else "there",
            "guest_full_name": guest.full_name if guest else "Valued Guest",
            "property_name": prop.name if prop else "your cabin",
            "business_name": "Cabin Rentals of Georgia",
            "support_phone": settings.staff_notification_phone or "(706) 525-5482",
            "wifi_ssid": "",
            "wifi_password": "",
            "access_code": "",
            "check_in_date": "",
            "check_out_date": "",
            "parking_instructions": "Park in the designated driveway area",
            "ticket_number": "",
        }

        if prop:
            ctx["wifi_ssid"] = prop.wifi_ssid or "See info card in the cabin"
            ctx["wifi_password"] = prop.wifi_password or "On the info card"
            ctx["parking_instructions"] = (
                prop.parking_instructions or "Park in the designated driveway area"
            )

        if reservation:
            ctx["access_code"] = reservation.access_code or "Check your booking confirmation"
            ctx["check_in_date"] = (
                reservation.check_in_date.strftime("%A, %B %d")
                if reservation.check_in_date
                else ""
            )
            ctx["check_out_date"] = (
                reservation.check_out_date.strftime("%A, %B %d")
                if reservation.check_out_date
                else ""
            )

        return ctx

    async def _send_automated_sms(
        self,
        db: AsyncSession,
        guest: Guest,
        reservation: Reservation,
        body: str,
        automation_type: str,
    ) -> Message:
        """Send an automated SMS and persist the Message record."""
        trace_id = uuid4()

        try:
            result = await self.twilio.send_sms(
                to=guest.phone_number,
                body=body,
                status_callback=settings.twilio_status_callback_url or None,
            )
            status = "sent"
            external_id = result.get("sid")
            error_msg = None
        except Exception as exc:
            status = "failed"
            external_id = None
            error_msg = str(exc)
            self.log.error(
                "automated_sms_failed",
                automation=automation_type,
                guest_id=str(guest.id),
                error=str(exc),
            )

        msg = Message(
            external_id=external_id,
            direction="outbound",
            phone_from=settings.twilio_phone_number,
            phone_to=guest.phone_number,
            body=body,
            status=status,
            sent_at=datetime.utcnow() if status == "sent" else None,
            guest_id=guest.id,
            reservation_id=reservation.id,
            is_auto_response=True,
            ai_confidence=0.95,
            intent=automation_type,
            provider="twilio",
            trace_id=trace_id,
            error_message=error_msg,
        )
        db.add(msg)

        # Update guest message count
        guest.total_messages_sent = (guest.total_messages_sent or 0) + 1

        return msg


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Utility: safe format_map that returns placeholder name on missing keys
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class _SafeFormatDict(dict):
    """Dict subclass that returns '{key}' for missing keys instead of raising."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"
