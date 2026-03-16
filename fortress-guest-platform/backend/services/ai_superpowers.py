"""
AI Superpowers — Advanced AI capabilities that no competitor has.
================================================================

Modules:
  1. Conversational Analytics: Ask your data questions in natural language
  2. AI Listing Optimizer: Auto-generate SEO descriptions, suggest improvements
  3. Revenue Forecasting: Time-series predictions from pricing data
  4. AI Upsell Engine: Personalized upsell offers based on guest profiles
  5. Predictive Maintenance: Pattern recognition from work orders
  6. Multi-language Translation: Auto-translate guest messages via local LLM

All inference runs on-prem via Ollama (data sovereignty).
"""

import json
import structlog
from typing import Optional, Dict, List, Any

from backend.core.config import settings

logger = structlog.get_logger()


async def _ask_llm(prompt: str, system: str = "", temperature: float = 0.7) -> str:
    """Send a prompt to the local LLM via Ollama."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model": settings.ollama_fast_model,
                    "prompt": prompt,
                    "system": system,
                    "stream": False,
                    "options": {"temperature": temperature},
                },
            )
            if resp.status_code == 200:
                return resp.json().get("response", "")
    except Exception as e:
        logger.warning("llm_call_failed", error=str(e))
    return ""


# ============================================================================
# 1. Conversational Analytics
# ============================================================================

class ConversationalAnalytics:
    """
    Ask your data questions in natural language.
    "Which property had the highest RevPAR last quarter?"
    "What's our occupancy trend for the last 6 months?"
    """

    SYSTEM_PROMPT = """You are a vacation rental analytics assistant for Cabin Rentals of Georgia.
You have access to reservation, property, and revenue data.
Answer questions concisely with specific numbers when available.
If you need to generate SQL, use PostgreSQL syntax against these tables:
- properties (id, name, bedrooms, max_guests, is_active)
- reservations (id, property_id, guest_id, check_in_date, check_out_date, total_amount, status)
- guests (id, first_name, last_name, total_stays)
- messages (id, guest_id, direction, body, intent, sentiment)
- work_orders (id, property_id, title, category, priority, status)
Always return both the answer and the SQL query you would use."""

    async def ask(self, question: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ctx = ""
        if context:
            ctx = f"\n\nCurrent context:\n{json.dumps(context, default=str)}\n"

        prompt = f"""Question: {question}{ctx}

Provide:
1. A direct answer based on the data patterns
2. The SQL query that would answer this question
3. Any caveats or assumptions"""

        response = await _ask_llm(prompt, self.SYSTEM_PROMPT, temperature=0.3)
        return {"question": question, "answer": response, "model": settings.ollama_fast_model}


# ============================================================================
# 2. AI Listing Optimizer
# ============================================================================

class ListingOptimizer:
    """
    Auto-generate SEO-optimized listing descriptions.
    Suggest photo improvements based on CF-01 vision analysis.
    """

    async def generate_description(
        self,
        property_name: str,
        bedrooms: int,
        bathrooms: float,
        max_guests: int,
        amenities: List[str],
        location: str = "Blue Ridge, GA",
    ) -> Dict[str, Any]:
        prompt = f"""Write an SEO-optimized vacation rental listing description for:

Property: {property_name}
Location: {location}
Bedrooms: {bedrooms}
Bathrooms: {bathrooms}
Sleeps: {max_guests}
Amenities: {', '.join(amenities)}

Requirements:
- Title (60 chars max)
- Short description (160 chars for meta)
- Full description (3-4 paragraphs)
- Include location keywords for SEO
- Highlight unique selling points
- Use emotional, aspirational language
- Include a call to action"""

        response = await _ask_llm(
            prompt,
            "You are a professional vacation rental copywriter specializing in mountain cabin listings.",
            temperature=0.8,
        )

        return {
            "property_name": property_name,
            "generated_description": response,
            "model": settings.ollama_fast_model,
        }

    async def suggest_improvements(self, listing_data: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"""Analyze this vacation rental listing and suggest improvements:

{json.dumps(listing_data, default=str)}

Provide specific, actionable suggestions for:
1. Title optimization
2. Description improvements
3. Photo recommendations
4. Amenity highlights
5. Pricing strategy"""

        response = await _ask_llm(
            prompt,
            "You are a vacation rental optimization expert.",
            temperature=0.5,
        )

        return {"suggestions": response}


# ============================================================================
# 3. Revenue Forecasting
# ============================================================================

class RevenueForecast:
    """
    Time-series revenue predictions using historical booking data.
    """

    async def forecast(
        self,
        historical_data: List[Dict[str, Any]],
        forecast_months: int = 3,
    ) -> Dict[str, Any]:
        """Generate revenue forecast from historical monthly data."""
        prompt = f"""Given this historical monthly revenue data for a vacation rental portfolio:

{json.dumps(historical_data, default=str)}

Predict revenue for the next {forecast_months} months.
Consider:
- Seasonal patterns (summer peak, winter holiday)
- Year-over-year growth trends
- Current booking pace

Return predictions as JSON array with keys: month, predicted_revenue, confidence, reasoning"""

        response = await _ask_llm(
            prompt,
            "You are a revenue management analyst for vacation rentals. Provide data-driven forecasts.",
            temperature=0.3,
        )

        return {
            "forecast_months": forecast_months,
            "historical_periods": len(historical_data),
            "forecast": response,
            "model": settings.ollama_fast_model,
        }


# ============================================================================
# 4. AI Upsell Engine
# ============================================================================

class UpsellEngine:
    """
    Personalized upsell offers based on guest profile, trip type, and timing.
    """

    async def generate_offers(
        self,
        guest_profile: Dict[str, Any],
        reservation: Dict[str, Any],
        available_extras: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        prompt = f"""Generate personalized upsell recommendations for this guest:

Guest Profile:
{json.dumps(guest_profile, default=str)}

Reservation:
{json.dumps(reservation, default=str)}

Available Extras:
{json.dumps(available_extras, default=str)}

Select the top 3 most relevant extras for this guest and write a personalized message for each.
Consider: guest history, party size, season, trip length, and past preferences."""

        response = await _ask_llm(
            prompt,
            "You are a hospitality upsell specialist. Create tasteful, personalized recommendations.",
            temperature=0.7,
        )

        return {"offers": response, "guest_id": guest_profile.get("id")}


# ============================================================================
# 5. Predictive Maintenance
# ============================================================================

class PredictiveMaintenance:
    """
    Pattern recognition from work orders and guest messages to predict failures.
    """

    async def analyze_patterns(
        self,
        work_orders: List[Dict[str, Any]],
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        prompt = f"""Analyze these work orders and guest messages to identify maintenance patterns:

Recent Work Orders:
{json.dumps(work_orders[:20], default=str)}

Recent Guest Messages (maintenance-related):
{json.dumps(messages[:20], default=str)}

Identify:
1. Recurring issues by property
2. Seasonal patterns
3. Predicted upcoming failures
4. Preventive maintenance recommendations
5. Priority ranking of issues"""

        response = await _ask_llm(
            prompt,
            "You are a property maintenance analyst specializing in vacation rental properties.",
            temperature=0.3,
        )

        return {"analysis": response, "work_orders_analyzed": len(work_orders)}


# ============================================================================
# 6. Multi-Language Translation
# ============================================================================

class MessageTranslator:
    """Auto-translate guest messages using local LLM."""

    async def translate(self, text: str, source_lang: str = "auto", target_lang: str = "en") -> Dict[str, Any]:
        if source_lang == target_lang:
            return {"original": text, "translated": text, "source_lang": source_lang, "target_lang": target_lang}

        prompt = f"""Translate the following text to {target_lang}. Return only the translation, no explanations.

Text: {text}"""

        response = await _ask_llm(prompt, "You are a professional translator.", temperature=0.1)
        return {"original": text, "translated": response, "source_lang": source_lang, "target_lang": target_lang}

    async def detect_language(self, text: str) -> str:
        prompt = f"""Detect the language of this text. Return only the ISO 639-1 code (e.g., "en", "es", "fr", "de").

Text: {text}"""

        response = await _ask_llm(prompt, temperature=0.1)
        return response.strip().lower()[:2]
