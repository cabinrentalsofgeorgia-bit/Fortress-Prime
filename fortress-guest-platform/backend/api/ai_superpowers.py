"""
AI Superpowers API — Voice co-pilot, conversational analytics, 
listing optimizer, forecasting, upsells, translations.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List

from backend.services.ai_superpowers import (
    ConversationalAnalytics,
    ListingOptimizer,
    RevenueForecast,
    UpsellEngine,
    PredictiveMaintenance,
    MessageTranslator,
)

router = APIRouter()

analytics = ConversationalAnalytics()
optimizer = ListingOptimizer()
forecaster = RevenueForecast()
upsell = UpsellEngine()
maintenance = PredictiveMaintenance()
translator = MessageTranslator()


# ── Conversational Analytics ──

class AnalyticsQuestion(BaseModel):
    question: str
    context: Optional[dict] = None


@router.post("/ask")
async def ask_analytics(body: AnalyticsQuestion):
    """Ask your data a question in natural language."""
    return await analytics.ask(body.question, body.context)


# ── Listing Optimizer ──

class ListingRequest(BaseModel):
    property_name: str
    bedrooms: int
    bathrooms: float
    max_guests: int
    amenities: list[str] = []
    location: str = "Blue Ridge, GA"


@router.post("/optimize-listing")
async def optimize_listing(body: ListingRequest):
    """Generate an SEO-optimized listing description."""
    return await optimizer.generate_description(
        body.property_name, body.bedrooms, body.bathrooms,
        body.max_guests, body.amenities, body.location,
    )


# ── Revenue Forecasting ──

class ForecastRequest(BaseModel):
    historical_data: list[dict]
    forecast_months: int = 3


@router.post("/forecast")
async def revenue_forecast(body: ForecastRequest):
    """Generate revenue forecast from historical data."""
    return await forecaster.forecast(body.historical_data, body.forecast_months)


# ── Upsell Engine ──

class UpsellRequest(BaseModel):
    guest_profile: dict
    reservation: dict
    available_extras: list[dict] = []


@router.post("/upsell")
async def generate_upsells(body: UpsellRequest):
    """Generate personalized upsell recommendations."""
    return await upsell.generate_offers(body.guest_profile, body.reservation, body.available_extras)


# ── Predictive Maintenance ──

class MaintenanceAnalysisRequest(BaseModel):
    work_orders: list[dict] = []
    messages: list[dict] = []


@router.post("/predict-maintenance")
async def predict_maintenance(body: MaintenanceAnalysisRequest):
    """Analyze work order patterns and predict maintenance needs."""
    return await maintenance.analyze_patterns(body.work_orders, body.messages)


# ── Translation ──

class TranslateRequest(BaseModel):
    text: str
    source_lang: str = "auto"
    target_lang: str = "en"


@router.post("/translate")
async def translate_message(body: TranslateRequest):
    """Translate text using local LLM."""
    return await translator.translate(body.text, body.source_lang, body.target_lang)


@router.post("/detect-language")
async def detect_language(body: TranslateRequest):
    """Detect the language of a text."""
    lang = await translator.detect_language(body.text)
    return {"text": body.text[:100], "detected_language": lang}
