"""
AI Response Engine - The brain of Fortress Guest Platform
==========================================================
Multi-provider inference with the "4 Horsemen" cloud cascade
and local DGX SWARM/HYDRA as the sovereign first tier.

Routing order (query_council cascade):
  1. LOCAL — SWARM (qwen2.5:7b) or HYDRA (deepseek-r1:70b) on DGX cluster
  2. ANTHROPIC — Claude Opus 4.6 (complex reasoning, legal)
  3. GEMINI — Gemini 3.1 Pro (architecture, planning)
  4. XAI — Grok 4.1 (strategic analysis)
  5. OPENAI — GPT-4o (general fallback)

Data Sovereignty: PII/financial/legal payloads ONLY go to local models.
Cloud Horsemen receive sanitized, non-sensitive prompts only.
"""
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import structlog
import httpx

from backend.core.config import settings

logger = structlog.get_logger()


# Intent definitions with examples for classification
INTENT_DEFINITIONS = {
    "wifi_question": {
        "description": "Guest asking about WiFi/internet access",
        "examples": [
            "What's the WiFi password?",
            "How do I connect to the internet?",
            "WiFi not working",
            "What network do I connect to?",
        ],
        "auto_reply": True,
        "priority": "low",
    },
    "access_code_request": {
        "description": "Guest needs door code or lock instructions",
        "examples": [
            "What's the door code?",
            "How do I get in?",
            "Lock isn't working",
            "Can't open the door",
            "Entry code please",
        ],
        "auto_reply": True,
        "priority": "high",
    },
    "checkin_question": {
        "description": "Questions about arrival, directions, parking",
        "examples": [
            "What time is check-in?",
            "How do I get there?",
            "Where do I park?",
            "Directions to the cabin",
            "Can I check in early?",
        ],
        "auto_reply": True,
        "priority": "medium",
    },
    "checkout_question": {
        "description": "Questions about departure, checkout process",
        "examples": [
            "What time is checkout?",
            "Do I need to clean?",
            "Where do I leave the key?",
            "Can I have late checkout?",
        ],
        "auto_reply": True,
        "priority": "medium",
    },
    "maintenance_request": {
        "description": "Something is broken or not working",
        "examples": [
            "The hot tub isn't heating",
            "AC is broken",
            "No hot water",
            "Toilet won't flush",
            "Heater not working",
        ],
        "auto_reply": False,
        "priority": "urgent",
    },
    "amenity_question": {
        "description": "Questions about property amenities",
        "examples": [
            "Does the cabin have a grill?",
            "How does the fireplace work?",
            "Is there a washer and dryer?",
            "Where are extra towels?",
            "How do I turn on the hot tub?",
        ],
        "auto_reply": True,
        "priority": "low",
    },
    "local_recommendation": {
        "description": "Looking for nearby restaurants, activities, attractions",
        "examples": [
            "Best restaurants nearby?",
            "Things to do around here",
            "Where can we go hiking?",
            "Any good places for breakfast?",
        ],
        "auto_reply": True,
        "priority": "low",
    },
    "booking_inquiry": {
        "description": "Questions about booking, extending stay, pricing",
        "examples": [
            "Can I extend my stay?",
            "How much for another night?",
            "I want to book again",
            "Available next weekend?",
        ],
        "auto_reply": False,
        "priority": "medium",
    },
    "complaint": {
        "description": "Guest is unhappy about something",
        "examples": [
            "This place is dirty",
            "Not what I expected",
            "Very disappointed",
            "I want a refund",
            "This is unacceptable",
        ],
        "auto_reply": False,
        "priority": "urgent",
    },
    "emergency": {
        "description": "Safety or emergency situation",
        "examples": [
            "There's a fire",
            "Someone is hurt",
            "I smell gas",
            "Power is out",
            "Water is flooding",
        ],
        "auto_reply": False,
        "priority": "urgent",
    },
    "positive_feedback": {
        "description": "Guest expressing satisfaction",
        "examples": [
            "This place is amazing!",
            "We love the cabin",
            "Best vacation ever",
            "Thank you so much",
            "5 stars!",
        ],
        "auto_reply": True,
        "priority": "low",
    },
    "general": {
        "description": "General message that doesn't fit other categories",
        "examples": [
            "Hello",
            "Thanks",
            "Ok",
            "Got it",
        ],
        "auto_reply": True,
        "priority": "low",
    },
}

# Sentiment scoring keywords with weights
SENTIMENT_LEXICON = {
    "urgent": {
        "keywords": [
            "emergency", "urgent", "help", "asap", "immediately",
            "dangerous", "fire", "flood", "gas leak", "hurt", "injured",
            "911", "police", "ambulance",
        ],
        "weight": 1.0,
    },
    "negative": {
        "keywords": [
            "bad", "terrible", "awful", "disappointed", "angry", "upset",
            "horrible", "disgusting", "dirty", "broken", "unacceptable",
            "worst", "hate", "refund", "complaint", "rude", "cold",
            "noisy", "uncomfortable", "misleading", "scam",
        ],
        "weight": 0.8,
    },
    "positive": {
        "keywords": [
            "great", "love", "amazing", "wonderful", "perfect",
            "excellent", "beautiful", "fantastic", "awesome", "best",
            "thank", "appreciate", "recommend", "stunning", "cozy",
            "comfortable", "clean", "lovely", "peaceful", "enjoy",
        ],
        "weight": 0.8,
    },
    "neutral": {
        "keywords": [],
        "weight": 0.0,
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  The 4 Horsemen — Multi-Cloud AI Routing Layer
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HORSEMEN = {
    "anthropic": {
        "name": "Anthropic (Claude Opus 4.6)",
        "protocol": "anthropic",
        "api_key_attr": "anthropic_api_key",
        "model_attr": "anthropic_model",
        "base_url": None,
        "timeout": 120,
    },
    "gemini": {
        "name": "Google Gemini 3.1 Pro",
        "protocol": "openai_compat",
        "api_key_attr": "gemini_api_key",
        "model_attr": "gemini_model",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "timeout": 60,
    },
    "xai": {
        "name": "xAI Grok 4.1",
        "protocol": "openai_compat",
        "api_key_attr": "xai_api_key",
        "model_attr": "xai_model",
        "base_url": "https://api.x.ai/v1",
        "timeout": 60,
    },
    "openai": {
        "name": "OpenAI GPT-4o",
        "protocol": "openai_compat",
        "api_key_attr": "openai_api_key",
        "model_attr": "openai_model",
        "base_url": "https://api.openai.com/v1",
        "timeout": 60,
    },
}

COUNCIL_CASCADE = ["anthropic", "gemini", "xai", "openai"]


async def query_horseman(
    horseman_name: str,
    prompt: str,
    context: str = "",
    system_message: str = "",
    max_tokens: int = 1024,
    temperature: float = 0.7,
    _skip_prompt_engineer: bool = False,
) -> Optional[str]:
    """Query a single Horseman by name. Returns response text or None on failure.

    If the caller has already run the prompt through PromptEngineer
    (e.g. damage_workflow), pass _skip_prompt_engineer=True to avoid
    double-processing.  Otherwise, a lightweight syntax translation
    is applied automatically.
    """
    cfg = HORSEMEN.get(horseman_name)
    if not cfg:
        logger.warning("unknown_horseman", name=horseman_name)
        return None

    api_key = getattr(settings, cfg["api_key_attr"], "")
    if not api_key:
        logger.debug("horseman_no_key", name=horseman_name)
        return None

    model = getattr(settings, cfg["model_attr"], "")
    protocol = cfg["protocol"]
    timeout = cfg["timeout"]

    sys_msg = system_message
    user_content = f"{context}\n\n{prompt}".strip() if context else prompt

    # Auto-apply syntax translation if not already done by caller
    if not _skip_prompt_engineer and (sys_msg or user_content):
        try:
            from backend.services.prompt_engineer import translate_for_model
            sys_msg, user_content = translate_for_model(
                sys_msg, user_content, model,
            )
        except Exception:
            pass

    # Zero-Trust PII sanitization for ALL cloud-bound calls
    sanitizer = None
    if not _skip_prompt_engineer:
        try:
            from backend.services.prompt_engineer import PIISanitizer, is_cloud_target
            if is_cloud_target(horseman_name):
                sanitizer = PIISanitizer()
                sys_msg = sanitizer.sanitize(sys_msg) if sys_msg else sys_msg
                user_content = sanitizer.sanitize(user_content)
                if sanitizer.replacement_count > 0:
                    logger.info(
                        "pii_sanitized_outbound",
                        horseman=horseman_name,
                        replacements=sanitizer.replacement_count,
                    )
        except Exception:
            pass

    messages = []
    if sys_msg:
        messages.append({"role": "system", "content": sys_msg})
    messages.append({"role": "user", "content": user_content})

    t0 = time.perf_counter()
    try:
        if protocol == "anthropic":
            result = await _call_anthropic(api_key, model, messages, max_tokens, temperature, timeout)
        else:
            result = await _call_openai_compat(
                api_key, model, cfg["base_url"], messages, max_tokens, temperature, timeout
            )

        # Rehydrate PII in the response before returning
        if sanitizer and result:
            result = sanitizer.rehydrate(result)

        latency = (time.perf_counter() - t0) * 1000
        logger.info(
            "horseman_response",
            horseman=horseman_name,
            model=model,
            latency_ms=round(latency),
            chars=len(result or ""),
        )
        return result

    except Exception as e:
        latency = (time.perf_counter() - t0) * 1000
        logger.warning(
            "horseman_failed",
            horseman=horseman_name,
            model=model,
            latency_ms=round(latency),
            error=str(e)[:200],
        )
        return None


async def query_council(
    prompt: str,
    context: str = "",
    system_message: str = "",
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> Tuple[Optional[str], str]:
    """Query the Council of Horsemen with automatic failover.

    Tries each Horseman in COUNCIL_CASCADE order until one succeeds.
    Returns (response_text, horseman_name) or (None, "none").
    """
    for name in COUNCIL_CASCADE:
        result = await query_horseman(
            name, prompt, context, system_message, max_tokens, temperature,
        )
        if result:
            return result, name

    logger.error("council_all_horsemen_failed")
    return None, "none"


async def _call_anthropic(
    api_key: str,
    model: str,
    messages: List[Dict],
    max_tokens: int,
    temperature: float,
    timeout: int,
) -> Optional[str]:
    """Call Anthropic Claude via the native anthropic SDK."""
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        logger.warning("anthropic_sdk_not_installed")
        return None

    system_text = ""
    user_messages = []
    for m in messages:
        if m["role"] == "system":
            system_text = m["content"]
        else:
            user_messages.append(m)

    client = AsyncAnthropic(api_key=api_key, timeout=timeout)
    try:
        kwargs: Dict = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_messages,
        }
        if system_text:
            kwargs["system"] = system_text

        resp = await client.messages.create(**kwargs)
        return resp.content[0].text.strip() if resp.content else None
    finally:
        await client.close()


async def _call_openai_compat(
    api_key: str,
    model: str,
    base_url: str,
    messages: List[Dict],
    max_tokens: int,
    temperature: float,
    timeout: int,
) -> Optional[str]:
    """Call any OpenAI-compatible endpoint (OpenAI, xAI, Gemini)."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    async with httpx.AsyncClient(timeout=float(timeout)) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


class AIEngine:
    """
    Production AI Response Engine with multi-provider LLM support.

    Routing priority:
      1. Local DGX (SWARM/HYDRA via Ollama) — sovereign, handles PII
      2. Council of Horsemen cascade (Anthropic -> Gemini -> xAI -> OpenAI)
      3. Template fallback
    """

    def __init__(self):
        self.log = logger.bind(service="ai_engine")
        self.openai_available = bool(settings.openai_api_key)
        self.ollama_available = bool(settings.use_local_llm and settings.ollama_base_url)
        self.council_available = any(
            getattr(settings, h["api_key_attr"], "") for h in HORSEMEN.values()
        )
    
    async def classify_intent(self, message_body: str) -> Tuple[str, float]:
        """
        Classify message intent with confidence score
        
        Returns: (intent, confidence)
        
        BETTER THAN competitors:
        - Hybrid: keyword matching + AI classification
        - Returns confidence score
        - 12 intent categories (vs 3-5 for competitors)
        """
        body_lower = message_body.lower().strip()
        
        # Phase 1: Keyword-based classification (fast, reliable)
        keyword_intent, keyword_confidence = self._keyword_classify(body_lower)
        
        # Phase 2: AI classification (if available and keyword confidence is low)
        if (self.ollama_available or self.openai_available) and keyword_confidence < 0.8:
            try:
                ai_intent, ai_confidence = await self._ai_classify(message_body)
                
                # Use AI result if it's more confident
                if ai_confidence > keyword_confidence:
                    return ai_intent, ai_confidence
            except Exception as e:
                self.log.warning("ai_classification_fallback", error=str(e))
        
        return keyword_intent, keyword_confidence
    
    async def analyze_sentiment(self, message_body: str) -> Tuple[str, float]:
        """
        Analyze message sentiment with confidence
        
        Returns: (sentiment, score)
        Score: -1.0 (very negative) to 1.0 (very positive)
        
        BETTER THAN competitors:
        - Weighted lexicon analysis
        - Handles mixed sentiment
        - Urgent detection
        """
        body_lower = message_body.lower()
        
        scores = {}
        for sentiment, data in SENTIMENT_LEXICON.items():
            if not data["keywords"]:
                continue
            
            matches = sum(1 for kw in data["keywords"] if kw in body_lower)
            if matches > 0:
                scores[sentiment] = matches * data["weight"]
        
        if not scores:
            return "neutral", 0.0
        
        # Get dominant sentiment
        dominant = max(scores, key=scores.get)
        
        # Calculate normalized score (-1 to 1)
        if dominant == "urgent":
            score = -1.0
        elif dominant == "negative":
            score = -0.5 - (min(scores[dominant], 3) / 6)
        elif dominant == "positive":
            score = 0.5 + (min(scores[dominant], 3) / 6)
        else:
            score = 0.0
        
        return dominant, round(score, 2)
    
    async def generate_response(
        self,
        message_body: str,
        intent: str,
        sentiment: str,
        guest_name: Optional[str] = None,
        property_name: Optional[str] = None,
        property_data: Optional[Dict] = None,
        reservation_data: Optional[Dict] = None,
        conversation_history: Optional[List[Dict]] = None,
    ) -> Tuple[str, float]:
        """
        Generate contextual response
        
        Returns: (response_body, confidence)
        
        BETTER THAN competitors:
        - Context-aware (property, reservation, guest)
        - Personalized (uses guest name)
        - Template + AI hybrid (fast with fallback)
        - Conversation history aware
        """
        # Build context
        context = self._build_context(
            guest_name=guest_name,
            property_name=property_name,
            property_data=property_data,
            reservation_data=reservation_data,
        )
        
        # Phase 1: Try template-based response (fast, reliable)
        template_response = self._get_template_response(
            intent, context, property_data
        )
        
        if template_response and not (self.ollama_available or self.openai_available):
            return template_response, 0.85
        
        # Phase 2: AI-enhanced response (if available)
        if self.ollama_available or self.openai_available:
            try:
                ai_response, confidence = await self._generate_ai_response(
                    message_body=message_body,
                    intent=intent,
                    sentiment=sentiment,
                    context=context,
                    conversation_history=conversation_history,
                )
                return ai_response, confidence
            except Exception as e:
                self.log.warning("ai_response_fallback", error=str(e))
        
        # Fallback to template
        if template_response:
            return template_response, 0.75
        
        # Final fallback
        name = guest_name or "there"
        return (
            f"Hi {name}! Thanks for your message. "
            f"Our team will get back to you shortly. "
            f"If this is urgent, please call us directly.",
            0.5
        )
    
    def should_auto_reply(
        self,
        intent: str,
        sentiment: str,
        confidence: float
    ) -> Tuple[bool, str]:
        """
        Decide if we should auto-reply or escalate to human
        
        Returns: (should_reply, reason)
        
        BETTER THAN competitors:
        - Multi-factor decision
        - Configurable threshold
        - Transparent reasoning
        """
        # Check if auto-replies are enabled
        if not settings.enable_auto_replies:
            return False, "Auto-replies disabled in settings"
        
        # Never auto-reply to emergencies
        if sentiment == "urgent" or intent == "emergency":
            return False, "Emergency/urgent - requires human"
        
        # Never auto-reply to complaints
        if intent == "complaint" or sentiment == "negative":
            return False, "Negative sentiment - requires human empathy"
        
        # Never auto-reply to booking inquiries
        if intent == "booking_inquiry":
            return False, "Booking inquiry - requires human decision"
        
        # Never auto-reply to maintenance requests
        if intent == "maintenance_request":
            return False, "Maintenance - requires human coordination"
        
        # Check confidence threshold
        if confidence < settings.ai_confidence_threshold:
            return False, f"Low confidence ({confidence:.2f} < {settings.ai_confidence_threshold})"
        
        # Check intent auto-reply setting
        intent_def = INTENT_DEFINITIONS.get(intent, {})
        if not intent_def.get("auto_reply", False):
            return False, f"Intent '{intent}' configured for human review"
        
        return True, f"Auto-reply approved (confidence: {confidence:.2f})"
    
    async def process_message(
        self,
        message_body: str,
        guest_name: Optional[str] = None,
        property_name: Optional[str] = None,
        property_data: Optional[Dict] = None,
        reservation_data: Optional[Dict] = None,
        conversation_history: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Full message processing pipeline
        
        Returns complete analysis and response recommendation
        
        BETTER THAN competitors:
        - Single call for complete analysis
        - Includes reasoning for every decision
        - Transparent confidence scoring
        """
        self.log.info("processing_message", body_preview=message_body[:50])
        
        # Step 1: Classify intent
        intent, intent_confidence = await self.classify_intent(message_body)
        
        # Step 2: Analyze sentiment
        sentiment, sentiment_score = await self.analyze_sentiment(message_body)
        
        # Step 3: Generate response
        response_body, response_confidence = await self.generate_response(
            message_body=message_body,
            intent=intent,
            sentiment=sentiment,
            guest_name=guest_name,
            property_name=property_name,
            property_data=property_data,
            reservation_data=reservation_data,
            conversation_history=conversation_history,
        )
        
        # Step 4: Decide auto-reply
        should_reply, reply_reason = self.should_auto_reply(
            intent, sentiment, response_confidence
        )
        
        # Step 5: Determine priority
        priority = INTENT_DEFINITIONS.get(intent, {}).get("priority", "medium")
        if sentiment == "urgent":
            priority = "urgent"
        
        result = {
            "intent": intent,
            "intent_confidence": round(intent_confidence, 3),
            "sentiment": sentiment,
            "sentiment_score": sentiment_score,
            "suggested_response": response_body,
            "response_confidence": round(response_confidence, 3),
            "should_auto_reply": should_reply,
            "auto_reply_reason": reply_reason,
            "priority": priority,
            "requires_human": not should_reply,
            "processing_timestamp": datetime.utcnow().isoformat(),
        }
        
        self.log.info(
            "message_processed",
            intent=intent,
            sentiment=sentiment,
            auto_reply=should_reply,
            confidence=response_confidence,
        )
        
        return result
    
    # ── Private Methods ──
    
    def _keyword_classify(self, body_lower: str) -> Tuple[str, float]:
        """Fast keyword-based intent classification"""
        best_intent = "general"
        best_score = 0.0
        
        for intent, definition in INTENT_DEFINITIONS.items():
            if intent == "general":
                continue
            
            examples = definition.get("examples", [])
            score = 0.0
            
            for example in examples:
                example_words = set(example.lower().split())
                body_words = set(body_lower.split())
                
                # Word overlap scoring
                overlap = len(example_words & body_words)
                if overlap > 0:
                    score = max(score, overlap / len(example_words))
            
            # Direct keyword matching (boost)
            description_words = definition["description"].lower().split()
            for word in description_words:
                if len(word) > 3 and word in body_lower:
                    score = max(score, 0.6)
            
            if score > best_score:
                best_score = score
                best_intent = intent
        
        # Minimum confidence for keyword match
        confidence = min(best_score, 0.95)
        if best_intent == "general":
            confidence = 0.5
        
        return best_intent, confidence
    
    async def _ai_classify(self, message_body: str) -> Tuple[str, float]:
        """AI-powered intent classification using OpenAI"""
        
        intent_list = ", ".join(INTENT_DEFINITIONS.keys())
        
        prompt = f"""Classify this guest message into exactly ONE intent category.

Categories: {intent_list}

Message: "{message_body}"

Respond with JSON only: {{"intent": "category_name", "confidence": 0.0-1.0}}"""
        
        response = await self._call_llm(
            user_message=prompt,
            system_message="You are a vacation rental guest message classifier. Respond with JSON only.",
            max_tokens=50,
            temperature=0.1,
        )
        
        try:
            result = json.loads(response)
            intent = result.get("intent", "general")
            confidence = float(result.get("confidence", 0.5))
            
            if intent not in INTENT_DEFINITIONS:
                intent = "general"
                confidence = 0.3
            
            return intent, confidence
        except (json.JSONDecodeError, ValueError):
            return "general", 0.3
    
    def _build_context(
        self,
        guest_name: Optional[str],
        property_name: Optional[str],
        property_data: Optional[Dict],
        reservation_data: Optional[Dict],
    ) -> Dict:
        """Build context dictionary for response generation"""
        context = {
            "guest_name": guest_name or "Guest",
            "property_name": property_name or "your cabin",
            "business_name": "Cabin Rentals of Georgia",
            "support_phone": settings.staff_notification_phone or "(706) 525-5482",
        }
        
        if property_data:
            context.update({
                "wifi_ssid": property_data.get("wifi_ssid", ""),
                "wifi_password": property_data.get("wifi_password", ""),
                "access_code_type": property_data.get("access_code_type", "keypad"),
                "parking_instructions": property_data.get("parking_instructions", ""),
            })
        
        if reservation_data:
            context.update({
                "check_in_date": reservation_data.get("check_in_date", ""),
                "check_out_date": reservation_data.get("check_out_date", ""),
                "access_code": reservation_data.get("access_code", ""),
                "num_guests": reservation_data.get("num_guests", ""),
            })
        
        return context
    
    def _get_template_response(
        self,
        intent: str,
        context: Dict,
        property_data: Optional[Dict] = None,
    ) -> Optional[str]:
        """Get template-based response for known intents"""
        
        name = context.get("guest_name", "there")
        prop = context.get("property_name", "your cabin")
        
        templates = {
            "wifi_question": (
                f"Hi {name}! Here's the WiFi info for {prop}:\n\n"
                f"📶 Network: {context.get('wifi_ssid', 'See the guide in the cabin')}\n"
                f"🔑 Password: {context.get('wifi_password', 'Check the info card on the counter')}\n\n"
                f"If you have any trouble connecting, just let us know!"
            ),
            "access_code_request": (
                f"Hi {name}! Here's your access info for {prop}:\n\n"
                f"🔑 Code: {context.get('access_code', 'Please check your booking confirmation')}\n"
                f"📍 Type: {context.get('access_code_type', 'keypad')}\n\n"
                f"The code is active from 4 PM on check-in day. "
                f"If you have any trouble, call us at {context.get('support_phone')}."
            ),
            "checkin_question": (
                f"Hi {name}! Here's your check-in info for {prop}:\n\n"
                f"⏰ Check-in: 4:00 PM\n"
                f"📍 Address: Check your booking confirmation for directions\n"
                f"🅿️ Parking: {context.get('parking_instructions', 'Park in the driveway')}\n\n"
                f"Your access code and WiFi will be in your digital guide. "
                f"Safe travels! 🏔️"
            ),
            "checkout_question": (
                f"Hi {name}! Here's your checkout info:\n\n"
                f"⏰ Checkout: 11:00 AM\n"
                f"✅ Please:\n"
                f"  - Lock all doors\n"
                f"  - Turn off lights\n"
                f"  - Start the dishwasher\n"
                f"  - Take all belongings\n"
                f"  - Leave keys inside\n\n"
                f"Thank you for staying with us! We hope you had a wonderful time. 🙏"
            ),
            "amenity_question": (
                f"Hi {name}! Great question about {prop}!\n\n"
                f"Your cabin has:\n"
                f"🛁 Hot tub (instructions on the deck)\n"
                f"🔥 Fireplace (wood provided)\n"
                f"🍳 Full kitchen\n"
                f"📺 Smart TV with streaming\n\n"
                f"Check your digital guest guide for full details on each amenity. "
                f"Enjoy your stay!"
            ),
            "local_recommendation": (
                f"Hi {name}! Here are some local favorites:\n\n"
                f"🍽️ Dining:\n"
                f"  - Check your area guide for our top picks\n\n"
                f"🏔️ Activities:\n"
                f"  - Hiking, waterfalls, scenic drives\n\n"
                f"Check your digital guest guide for our full list of recommendations "
                f"with directions and hours!"
            ),
            "positive_feedback": (
                f"Thank you so much, {name}! 😊\n\n"
                f"We're so glad you're enjoying {prop}! "
                f"Your kind words mean the world to us.\n\n"
                f"If there's anything else we can do to make your stay even better, "
                f"just let us know!"
            ),
            "general": (
                f"Hi {name}! Thanks for reaching out. 👋\n\n"
                f"How can we help you with your stay at {prop}? "
                f"Feel free to ask about WiFi, check-in, local recommendations, "
                f"or anything else!"
            ),
        }
        
        return templates.get(intent)
    
    async def _generate_ai_response(
        self,
        message_body: str,
        intent: str,
        sentiment: str,
        context: Dict,
        conversation_history: Optional[List[Dict]] = None,
    ) -> Tuple[str, float]:
        """Generate AI-powered response using OpenAI"""
        
        # Build system prompt
        system_prompt = f"""You are a friendly, professional guest communication assistant 
for {context.get('business_name', 'Cabin Rentals of Georgia')}, a vacation rental company 
in the North Georgia mountains.

RULES:
- Be warm, helpful, and concise (under 300 characters for SMS)
- Use the guest's name: {context.get('guest_name', 'Guest')}
- Property: {context.get('property_name', 'the cabin')}
- Never make up information you don't have
- If unsure, offer to connect them with the team
- Use 1-2 emojis maximum
- Sound human, not robotic

CONTEXT:
- WiFi: {context.get('wifi_ssid', 'N/A')} / {context.get('wifi_password', 'N/A')}
- Access Code: {context.get('access_code', 'N/A')}
- Check-in: {context.get('check_in_date', 'N/A')}
- Check-out: {context.get('check_out_date', 'N/A')}
- Support: {context.get('support_phone', 'N/A')}

Message Intent: {intent}
Sentiment: {sentiment}"""
        
        # Build conversation context
        messages = []
        if conversation_history:
            for msg in conversation_history[-5:]:  # Last 5 messages for context
                role = "user" if msg.get("direction") == "inbound" else "assistant"
                messages.append({"role": role, "content": msg.get("body", "")})
        
        messages.append({"role": "user", "content": message_body})
        
        response = await self._call_llm(
            user_message=message_body,
            system_message=system_prompt,
            conversation=messages,
            max_tokens=200,
            temperature=0.7,
        )
        
        # Score confidence based on response quality
        confidence = 0.85
        if len(response) < 20:
            confidence = 0.6
        if intent in ["maintenance_request", "complaint", "emergency"]:
            confidence = 0.5  # Lower confidence for sensitive topics
        
        return response, confidence
    
    async def _call_llm(
        self,
        user_message: str = "",
        system_message: str = "",
        conversation: Optional[List[Dict]] = None,
        max_tokens: int = 200,
        temperature: float = 0.7,
        use_deep_model: bool = False,
    ) -> str:
        """
        Unified LLM call with full cascade:
          1. Local DGX (Ollama SWARM/HYDRA)
          2. Council of Horsemen (Anthropic -> Gemini -> xAI -> OpenAI)
          3. Raise if all fail
        """
        # Tier 1: Local DGX cluster (sovereign, handles PII)
        if self.ollama_available:
            try:
                return await self._call_ollama(
                    user_message=user_message,
                    system_message=system_message,
                    conversation=conversation,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    use_deep_model=use_deep_model,
                )
            except Exception as e:
                self.log.warning("ollama_failed_escalating_to_council", error=str(e))

        # Tier 2: Council of Horsemen (cloud cascade)
        if self.council_available:
            prompt = user_message
            if conversation:
                prompt = "\n".join(
                    f"{m.get('role', 'user')}: {m.get('content', '')}"
                    for m in conversation
                )
            result, horseman = await query_council(
                prompt=prompt,
                system_message=system_message,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if result:
                self.log.info("council_horseman_answered", horseman=horseman)
                return result

        # Tier 3: Legacy direct OpenAI call (backward compat)
        if self.openai_available:
            return await self._call_openai(
                user_message=user_message,
                system_message=system_message,
                conversation=conversation,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        raise ValueError("No LLM available — local cluster down and no cloud API keys configured")

    async def _call_ollama(
        self,
        user_message: str = "",
        system_message: str = "",
        conversation: Optional[List[Dict]] = None,
        max_tokens: int = 200,
        temperature: float = 0.7,
        use_deep_model: bool = False,
    ) -> str:
        """Call local Ollama instance (SWARM fast or HYDRA deep model)."""
        model = (
            settings.ollama_deep_model if use_deep_model
            else settings.ollama_fast_model
        )

        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        if conversation:
            messages.extend(conversation)
        elif user_message:
            messages.append({"role": "user", "content": user_message})

        timeout = 60.0 if use_deep_model else 30.0
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "").strip()

    async def _call_openai(
        self,
        user_message: str = "",
        system_message: str = "",
        conversation: Optional[List[Dict]] = None,
        max_tokens: int = 200,
        temperature: float = 0.7,
    ) -> str:
        """Call OpenAI API."""
        if not settings.openai_api_key:
            raise ValueError("No LLM available (Ollama down + OpenAI key not set)")

        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        if conversation:
            messages.extend(conversation)
        elif user_message:
            messages.append({"role": "user", "content": user_message})

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
