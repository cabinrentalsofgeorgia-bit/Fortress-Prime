"""
AI Superpowers API — Voice co-pilot, conversational analytics, 
listing optimizer, forecasting, upsells, translations.
"""

from fastapi import APIRouter, Depends
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from typing import Any, Optional

from backend.core.security import require_operator_manager_admin
from backend.services.ai_superpowers import (
    ConversationalAnalytics,
    ListingOptimizer,
    RevenueForecast,
    UpsellEngine,
    PredictiveMaintenance,
    MessageTranslator,
)

router = APIRouter(dependencies=[Depends(require_operator_manager_admin)])

analytics = ConversationalAnalytics()
optimizer = ListingOptimizer()
forecaster = RevenueForecast()
upsell = UpsellEngine()
maintenance = PredictiveMaintenance()
translator = MessageTranslator()


def _coerce_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return dict(result)
    return {"result": result}


def _with_aliases(result: Any, **aliases: Any) -> dict[str, Any]:
    payload = _coerce_payload(result)
    for key, value in aliases.items():
        payload.setdefault(key, value)
    return payload


# ── Conversational Analytics ──

class AnalyticsQuestion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str = Field(validation_alias=AliasChoices("question", "query"))
    context: Optional[dict[str, Any]] = None


@router.post("/ask")
async def ask_analytics(body: AnalyticsQuestion):
    """Ask your data a question in natural language."""
    result = await analytics.ask(body.question, body.context)
    payload = _coerce_payload(result)
    return _with_aliases(payload, response=payload.get("answer", ""))


# ── Listing Optimizer ──

class ListingRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    property_name: str
    bedrooms: int
    bathrooms: float
    max_guests: int
    amenities: list[str] = Field(default_factory=list)
    location: str = "Blue Ridge, GA"


@router.post("/optimize-listing")
async def optimize_listing(body: ListingRequest):
    """Generate an SEO-optimized listing description."""
    result = await optimizer.generate_description(
        body.property_name, body.bedrooms, body.bathrooms,
        body.max_guests, body.amenities, body.location,
    )
    payload = _coerce_payload(result)
    return _with_aliases(payload, suggestions=payload.get("generated_description", ""))


# ── Revenue Forecasting ──

class ForecastRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    historical_data: list[dict[str, Any]]
    forecast_months: int = 3


@router.post("/forecast")
async def revenue_forecast(body: ForecastRequest):
    """Generate revenue forecast from historical data."""
    result = await forecaster.forecast(body.historical_data, body.forecast_months)
    payload = _coerce_payload(result)
    return _with_aliases(payload, summary=payload.get("forecast", ""))


# ── Upsell Engine ──

class UpsellRequest(BaseModel):
    guest_profile: dict[str, Any]
    reservation: dict[str, Any]
    available_extras: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/upsell")
async def generate_upsells(body: UpsellRequest):
    """Generate personalized upsell recommendations."""
    result = await upsell.generate_offers(body.guest_profile, body.reservation, body.available_extras)
    payload = _coerce_payload(result)
    return _with_aliases(payload, recommendations=payload.get("offers", ""))


# ── Predictive Maintenance ──

class MaintenanceAnalysisRequest(BaseModel):
    work_orders: list[dict[str, Any]] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/predict-maintenance")
async def predict_maintenance(body: MaintenanceAnalysisRequest):
    """Analyze work order patterns and predict maintenance needs."""
    result = await maintenance.analyze_patterns(body.work_orders, body.messages)
    payload = _coerce_payload(result)
    analysis = payload.get("analysis", "")
    alerts = [analysis] if analysis else []
    return _with_aliases(payload, alerts=alerts)


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
