"""
Module CF-02: QuantRevenue — Enterprise Pricing API
=====================================================
Cabin Rentals of Georgia | Crog-Fortress-AI
Data Sovereignty: All computation local on DGX cluster. No cloud APIs.

Headless, API-First microservice wrapping the QuantRevenue pricing engine.
Provides strict contract validation via Pydantic, async concurrency for
multi-cabin pricing, and automatic audit persistence to the revenue_ledger
table in PostgreSQL.

Endpoints:
    POST /v1/quote              Single cabin-night price quote
    POST /v1/quote/batch        Multi-date range pricing
    POST /v1/sentiment          Sentiment analysis only (no pricing)
    GET  /v1/ledger/recent      Last N pricing decisions from the audit trail
    GET  /health                Cluster + service health check

Run:
    uvicorn Modules.CF-02_QuantRevenue.api:app --host 0.0.0.0 --port 8000 --reload

    # Or from project root with module-safe path:
    cd /home/admin/Fortress-Prime
    python3 -m uvicorn Modules.CF-02_QuantRevenue.api:app --host 0.0.0.0 --port 8000

Swagger UI:
    http://192.168.0.100:8000/docs
    https://api.crog-ai.com/docs  (via Cloudflare Tunnel)

Author: Fortress Prime Architect
Version: 1.0.0
"""

import os
import sys
import json
import asyncio
import importlib.util
from datetime import datetime, date
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
from functools import partial

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, APIRouter, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
import requests

# ---------------------------------------------------------------------------
# Engine Import  (directory has a hyphen — use importlib)
# ---------------------------------------------------------------------------
_engine_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pricing_engine.py")
_spec = importlib.util.spec_from_file_location("pricing_engine", _engine_path)
_engine_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_engine_mod)
QuantRevenueEngine = _engine_mod.QuantRevenueEngine

# ---------------------------------------------------------------------------
# Project config (DB credentials, cluster topology)
# ---------------------------------------------------------------------------
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _project_root)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_project_root, ".env"))
except ImportError:
    pass

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "5432"))
DB_NAME     = os.getenv("DB_NAME", "fortress_db")
DB_USER     = os.getenv("DB_USER", "miner_bot")
DB_PASSWORD = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", ""))

from config import SPARK_02_IP
CAPTAIN_URL = os.getenv("CAPTAIN_URL", "http://localhost:11434")
MUSCLE_URL  = os.getenv("MUSCLE_URL", f"http://{SPARK_02_IP}:11434")

# ---------------------------------------------------------------------------
# Database Connection Pool
# ---------------------------------------------------------------------------

_db_pool: Optional[Any] = None


def get_db_connection():
    """Get a PostgreSQL connection. Reuses a module-level connection pool."""
    global _db_pool
    try:
        if _db_pool is None or _db_pool.closed:
            _db_pool = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
            )
            _db_pool.autocommit = False
        # Test if connection is alive
        _db_pool.cursor().execute("SELECT 1")
        return _db_pool
    except Exception:
        # Reconnect on failure
        try:
            _db_pool = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
            )
            _db_pool.autocommit = False
            return _db_pool
        except Exception:
            return None


def persist_to_ledger(ledger_row: dict) -> bool:
    """
    INSERT a pricing run result into the revenue_ledger table.
    Every quote is audited — no exceptions.
    Returns True on success, False on failure (non-blocking).
    """
    conn = get_db_connection()
    if conn is None:
        return False

    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO revenue_ledger (
                run_id, cabin_name, target_date, target_dow,
                base_rate, seasonal_baseline, adjusted_rate, alpha,
                previous_rate, rate_change, rate_change_pct,
                sentiment_score, weather_factor, event_factor,
                competitor_factor, volatility_index,
                trading_signal, confidence,
                weather_condition, weather_temp_f, event_name, event_weight,
                competitor_direction, competitor_rate_change, days_until_checkin,
                engine_version, tier, generated_at
            ) VALUES (
                %(run_id)s, %(cabin_name)s, %(target_date)s, %(target_dow)s,
                %(base_rate)s, %(seasonal_baseline)s, %(adjusted_rate)s, %(alpha)s,
                %(previous_rate)s, %(rate_change)s, %(rate_change_pct)s,
                %(sentiment_score)s, %(weather_factor)s, %(event_factor)s,
                %(competitor_factor)s, %(volatility_index)s,
                %(trading_signal)s, %(confidence)s,
                %(weather_condition)s, %(weather_temp_f)s, %(event_name)s, %(event_weight)s,
                %(competitor_direction)s, %(competitor_rate_change)s, %(days_until_checkin)s,
                %(engine_version)s, %(tier)s, %(generated_at)s
            )
            ON CONFLICT (cabin_name, target_date, run_id) DO NOTHING
        """, ledger_row)
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"[CF-02 API] Ledger persist failed (non-blocking): {e}")
        return False


# =============================================================================
# PYDANTIC MODELS — The Contract
# =============================================================================

# --- Request Models ---

class WeatherInput(BaseModel):
    """Local weather conditions. Source: API, NWS, or local sensor."""
    condition: str = Field(
        ...,
        description="Weather condition keyword",
        examples=["sunny", "rain", "snow", "cloudy", "extreme_heat"],
    )
    temperature_f: float = Field(
        ..., ge=-20, le=130,
        description="Temperature in Fahrenheit",
    )
    wind_mph: float = Field(
        default=5.0, ge=0, le=200,
        description="Wind speed in MPH",
    )
    humidity_pct: Optional[float] = Field(
        default=None, ge=0, le=100,
        description="Humidity percentage",
    )
    forecast_3day: Optional[str] = Field(
        default=None,
        description="Short 3-day forecast narrative",
    )
    uv_index: Optional[float] = Field(
        default=None, ge=0, le=15,
        description="UV index (0-15)",
    )

    @field_validator("condition")
    @classmethod
    def normalize_condition(cls, v: str) -> str:
        return v.lower().strip().replace(" ", "_")


class EventInput(BaseModel):
    """Blue Ridge area event data."""
    event_name: str = Field(
        ...,
        description="Name of the event",
        examples=["Blue Ridge Blues Festival", "Christmas Week", "none"],
    )
    event_weight: int = Field(
        ..., ge=0, le=10,
        description="Demand impact: 0=none, 1-3=minor, 4-6=moderate, 7-9=significant, 10=peak",
    )
    distance_miles: float = Field(
        default=10.0, ge=0,
        description="Distance from cabin cluster in miles",
    )
    expected_attendance: int = Field(
        default=0, ge=0,
        description="Estimated event attendance",
    )
    event_date: Optional[str] = Field(
        default=None,
        description="ISO date of event (YYYY-MM-DD)",
    )
    recurring: bool = Field(
        default=False,
        description="Whether this is an annual recurring event",
    )


class CompetitorInput(BaseModel):
    """Competitor rate velocity intelligence."""
    rate_change_24h: float = Field(
        ...,
        description="Absolute $ change in competitor rates over last 24 hours",
    )
    direction: str = Field(
        ...,
        description="Rate movement direction",
        examples=["rising", "stable", "falling"],
    )
    avg_competitor_rate: Optional[float] = Field(
        default=None, ge=0,
        description="Current average competitor nightly rate ($)",
    )
    sample_size: int = Field(
        default=5, ge=1, le=100,
        description="Number of competitors sampled",
    )
    platform: Optional[str] = Field(
        default=None,
        description="Data source platform",
        examples=["vrbo", "airbnb", "direct", "mixed"],
    )
    rate_change_7d: Optional[float] = Field(
        default=None,
        description="7-day rate change ($) for trend confirmation",
    )

    @field_validator("direction")
    @classmethod
    def normalize_direction(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("rising", "stable", "falling"):
            raise ValueError("direction must be 'rising', 'stable', or 'falling'")
        return v


class CabinPosition(BaseModel):
    """Cabin configuration for a pricing position."""
    cabin_name: str = Field(
        ...,
        description="Cabin identifier (matches cabins/*.yaml)",
        examples=["rolling_river"],
    )
    base_rate: float = Field(
        ..., gt=0, le=5000,
        description="Baseline nightly rate ($) before adjustments",
    )
    bedrooms: int = Field(default=3, ge=1, le=20)
    max_guests: int = Field(default=8, ge=1, le=50)
    tier: str = Field(
        default="premium",
        description="Property tier: standard, premium, luxury",
    )
    previous_rate: Optional[float] = Field(
        default=None, ge=0,
        description="Last quoted rate ($) for change tracking",
    )

    @field_validator("tier")
    @classmethod
    def normalize_tier(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("standard", "premium", "luxury"):
            raise ValueError("tier must be 'standard', 'premium', or 'luxury'")
        return v


class QuoteRequest(BaseModel):
    """
    Full pricing quote request.
    Accepts all three market signal inputs plus cabin context.
    """
    cabin: CabinPosition
    target_date: str = Field(
        ...,
        description="The night to price (YYYY-MM-DD)",
        examples=["2026-06-20"],
    )
    weather: WeatherInput
    event: EventInput
    competitor: CompetitorInput
    days_until_checkin: int = Field(
        default=14, ge=0, le=365,
        description="Days until check-in (urgency factor)",
    )
    historical_occupancy: Optional[List[float]] = Field(
        default=None,
        description="Last 30 days occupancy rates (0.0-1.0) for volatility calc",
    )
    persist: bool = Field(
        default=True,
        description="Write result to revenue_ledger audit trail",
    )

    @field_validator("target_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("target_date must be YYYY-MM-DD format")
        return v


class BatchQuoteRequest(BaseModel):
    """Batch pricing for a date range. Prices every night in the range."""
    cabin: CabinPosition
    start_date: str = Field(..., description="Range start (YYYY-MM-DD)")
    end_date: str = Field(..., description="Range end (YYYY-MM-DD)")
    weather: WeatherInput
    event: EventInput
    competitor: CompetitorInput
    historical_occupancy: Optional[List[float]] = None
    persist: bool = Field(default=True, description="Write all results to audit trail")

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_dates(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Date must be YYYY-MM-DD format")
        return v


class SentimentRequest(BaseModel):
    """Sentiment-only analysis (no pricing, no cabin needed)."""
    weather: WeatherInput
    event: EventInput
    competitor: CompetitorInput


# --- Response Models ---

class PricingBreakdown(BaseModel):
    """Detailed rate calculation layers."""
    seasonality_mult: float
    dow_mult: float
    tier_mult: float
    sentiment_mult: float
    volatility_dampened_mult: float


class QuoteResponse(BaseModel):
    """Full pricing quote result — maps 1:1 to revenue_ledger row."""
    # Identifiers
    run_id: str
    cabin_name: str
    target_date: str
    target_dow: str

    # Pricing
    base_rate: float
    seasonal_baseline: float
    adjusted_rate: float = Field(..., description="THE final nightly rate ($)")
    alpha: float = Field(..., description="Excess return above seasonal baseline ($)")
    previous_rate: float
    rate_change: float
    rate_change_pct: float

    # Market Intelligence
    sentiment_score: float = Field(..., ge=-1.0, le=1.0)
    weather_factor: float
    event_factor: float
    competitor_factor: float
    volatility_index: float = Field(..., ge=0.0, le=1.0)

    # Trading Signal
    trading_signal: str = Field(
        ..., description="STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL",
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Decision confidence (0-1)")

    # Input Snapshot
    weather_condition: str
    weather_temp_f: float
    event_name: str
    event_weight: int
    competitor_direction: str
    competitor_rate_change: float
    days_until_checkin: int

    # Metadata
    engine_version: str
    tier: str
    generated_at: str
    persisted: bool = Field(
        default=False,
        description="Whether this quote was written to the revenue_ledger audit trail",
    )


class BatchQuoteResponse(BaseModel):
    """Batch pricing response with summary statistics."""
    quotes: List[QuoteResponse]
    summary: Dict[str, Any] = Field(
        ..., description="Aggregate stats: avg_rate, min_rate, max_rate, total_revenue",
    )
    cabin_name: str
    date_range: str
    quotes_generated: int
    quotes_persisted: int


class SentimentResponse(BaseModel):
    """Sentiment analysis result (no pricing)."""
    sentiment_score: float = Field(..., ge=-1.0, le=1.0)
    weather_factor: float
    event_factor: float
    competitor_factor: float
    signal: str
    components: Dict[str, Any]


class HealthResponse(BaseModel):
    """Service health check response."""
    status: str
    module: str
    engine_version: str
    cluster: Dict[str, str]
    database: str
    timestamp: str
    uptime_seconds: Optional[float] = None


class LedgerEntry(BaseModel):
    """A single revenue_ledger row from the audit trail."""
    id: int
    run_id: str
    cabin_name: str
    target_date: str
    adjusted_rate: float
    trading_signal: str
    confidence: float
    sentiment_score: float
    volatility_index: float
    generated_at: str


# =============================================================================
# APPLICATION LIFECYCLE
# =============================================================================

_startup_time: Optional[datetime] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup / shutdown lifecycle."""
    global _startup_time
    _startup_time = datetime.now()
    print("=" * 60)
    print("  CF-02 QuantRevenue API — ONLINE")
    print(f"  Startup: {_startup_time.isoformat()}")
    print(f"  Database: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"  Captain: {CAPTAIN_URL}")
    print(f"  Swagger: http://0.0.0.0:8000/docs")
    print("=" * 60)

    # Pre-warm DB connection
    conn = get_db_connection()
    if conn:
        print("  Database: CONNECTED")
    else:
        print("  Database: UNAVAILABLE (quotes will not persist)")

    yield

    # Shutdown
    global _db_pool
    if _db_pool and not _db_pool.closed:
        _db_pool.close()
    print("  CF-02 QuantRevenue API — OFFLINE")


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

app = FastAPI(
    title="Crog-Fortress QuantRevenue API",
    description=(
        "**Module CF-02** — Enterprise Dynamic Pricing Engine for "
        "Cabin Rentals of Georgia.\n\n"
        "Trading-desk style pricing that synthesizes weather, events, "
        "and competitor intelligence into optimal nightly cabin rates.\n\n"
        "- **Data Sovereignty**: All computation runs locally on the DGX cluster.\n"
        "- **Audit Trail**: Every quote is persisted to the `revenue_ledger` table.\n"
        "- **Signals**: STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL\n\n"
        "Part of the **Crog-Fortress-AI** proprietary PMS platform."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "Pricing", "description": "Core pricing engine endpoints"},
        {"name": "Intelligence", "description": "Market analysis without pricing"},
        {"name": "Audit", "description": "Revenue ledger audit trail"},
        {"name": "Operations", "description": "Health and diagnostics"},
    ],
    lifespan=lifespan,
)

# CORS — centralized origins from config.py (Cloudflare tunnel hostnames + LAN)
try:
    from config import CORS_ORIGINS as _cors_origins
except ImportError:
    _cors_origins = [
        "https://fortress.crog-ai.com",
        "https://api.crog-ai.com",
        "http://localhost:8501",
        "http://localhost:3000",
        "http://192.168.0.100:8501",
        "http://192.168.0.100:3000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# ROUTER (exported for gateway mounting)
# =============================================================================

router = APIRouter()

# =============================================================================
# HELPER: Run CPU-bound engine in executor (true async)
# =============================================================================

async def run_engine_async(func, *args, **kwargs):
    """
    Offload CPU-bound pricing calculations to a thread pool executor.
    Prevents blocking the event loop when pricing 50 cabins concurrently.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, **kwargs) if kwargs else func)


def _build_engine(cabin: CabinPosition) -> QuantRevenueEngine:
    """Construct a QuantRevenueEngine from a Pydantic CabinPosition."""
    return QuantRevenueEngine(
        cabin_name=cabin.cabin_name,
        base_rate=cabin.base_rate,
        bedrooms=cabin.bedrooms,
        max_guests=cabin.max_guests,
        tier=cabin.tier,
        previous_rate=cabin.previous_rate,
    )


def _execute_single_quote(
    cabin: CabinPosition,
    target_date_str: str,
    weather: WeatherInput,
    event: EventInput,
    competitor: CompetitorInput,
    days_until_checkin: int,
    historical_occupancy: Optional[List[float]],
) -> dict:
    """Synchronous single-quote execution (runs in thread pool)."""
    engine = _build_engine(cabin)
    target_dt = datetime.strptime(target_date_str, "%Y-%m-%d")

    result = engine.execute_pricing_run(
        target_date=target_dt,
        weather_data=weather.model_dump(exclude_none=True),
        event_schedule=event.model_dump(exclude_none=True),
        competitor_velocity=competitor.model_dump(exclude_none=True),
        historical_occupancy=historical_occupancy,
        days_until_checkin=days_until_checkin,
    )
    return result


# =============================================================================
# ENDPOINTS
# =============================================================================

# ---- PRICING ----

@router.post(
    "/quote",
    response_model=QuoteResponse,
    tags=["Pricing"],
    summary="Generate a single-night price quote",
    description=(
        "Accepts weather, event, and competitor market signals for a specific "
        "cabin-night. Returns the optimal nightly rate with full trading analysis. "
        "Result is automatically persisted to the revenue_ledger audit trail."
    ),
)
async def generate_quote(req: QuoteRequest):
    """
    POST /v1/quote — The core pricing endpoint.

    Runs the full 7-layer pricing pipeline:
    Base Rate -> Seasonality -> Day-of-Week -> Tier -> Sentiment -> Volatility -> Caps
    """
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            _execute_single_quote,
            req.cabin,
            req.target_date,
            req.weather,
            req.event,
            req.competitor,
            req.days_until_checkin,
            req.historical_occupancy,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pricing engine error: {str(e)}")

    # Persist to audit trail
    persisted = False
    if req.persist:
        persisted = persist_to_ledger(result)

    result["persisted"] = persisted
    return result


@router.post(
    "/quote/batch",
    response_model=BatchQuoteResponse,
    tags=["Pricing"],
    summary="Generate pricing for a date range",
    description=(
        "Prices every night in the given date range for a single cabin. "
        "Returns individual quotes plus aggregate summary statistics. "
        "Ideal for setting weekly/monthly rate calendars."
    ),
)
async def generate_batch_quote(req: BatchQuoteRequest):
    """
    POST /v1/quote/batch — Batch date-range pricing.

    Chains rate updates across consecutive nights (previous_rate flows forward).
    """
    start = datetime.strptime(req.start_date, "%Y-%m-%d")
    end = datetime.strptime(req.end_date, "%Y-%m-%d")

    if end < start:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")
    if (end - start).days > 90:
        raise HTTPException(status_code=400, detail="Maximum batch range is 90 days")

    def _run_batch():
        engine = _build_engine(req.cabin)
        return engine.price_date_range(
            start_date=start,
            end_date=end,
            weather_data=req.weather.model_dump(exclude_none=True),
            event_schedule=req.event.model_dump(exclude_none=True),
            competitor_velocity=req.competitor.model_dump(exclude_none=True),
            historical_occupancy=req.historical_occupancy,
        )

    try:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, _run_batch)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch pricing error: {str(e)}")

    # Persist all to audit trail
    persisted_count = 0
    for row in results:
        row["persisted"] = False
        if req.persist:
            if persist_to_ledger(row):
                row["persisted"] = True
                persisted_count += 1

    # Build summary
    rates = [r["adjusted_rate"] for r in results]
    summary = {
        "avg_rate": round(sum(rates) / len(rates), 2),
        "min_rate": min(rates),
        "max_rate": max(rates),
        "total_revenue_if_booked": round(sum(rates), 2),
        "signals": {},
    }
    for r in results:
        sig = r["trading_signal"]
        summary["signals"][sig] = summary["signals"].get(sig, 0) + 1

    return BatchQuoteResponse(
        quotes=results,
        summary=summary,
        cabin_name=req.cabin.cabin_name,
        date_range=f"{req.start_date} to {req.end_date}",
        quotes_generated=len(results),
        quotes_persisted=persisted_count,
    )


# ---- INTELLIGENCE ----

@router.post(
    "/sentiment",
    response_model=SentimentResponse,
    tags=["Intelligence"],
    summary="Analyze market sentiment (no pricing)",
    description=(
        "Runs only the sentiment analysis pipeline. Useful for dashboards "
        "or when you need the signal without generating a rate."
    ),
)
async def analyze_sentiment(req: SentimentRequest):
    """
    POST /v1/sentiment — Sentiment analysis only.

    Returns the composite sentiment score and trading signal
    without running the full pricing pipeline.
    """
    def _run_sentiment():
        # Use a throwaway engine just for the scoring methods
        engine = QuantRevenueEngine(
            cabin_name="_sentiment_probe",
            base_rate=250.0,
        )
        return engine.calculate_market_sentiment(
            weather_data=req.weather.model_dump(exclude_none=True),
            event_schedule=req.event.model_dump(exclude_none=True),
            competitor_velocity=req.competitor.model_dump(exclude_none=True),
        )

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _run_sentiment)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sentiment analysis error: {str(e)}")

    return result


# ---- AUDIT TRAIL ----

@router.get(
    "/ledger/recent",
    response_model=List[LedgerEntry],
    tags=["Audit"],
    summary="Retrieve recent pricing decisions",
    description="Query the revenue_ledger audit trail. Returns the most recent N entries.",
)
async def get_recent_ledger(
    limit: int = Query(default=25, ge=1, le=500, description="Number of entries"),
    cabin: Optional[str] = Query(default=None, description="Filter by cabin name"),
    signal: Optional[str] = Query(default=None, description="Filter by trading signal"),
):
    """GET /v1/ledger/recent — Audit trail query."""
    conn = get_db_connection()
    if conn is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        where_clauses = []
        params = []

        if cabin:
            where_clauses.append("cabin_name = %s")
            params.append(cabin)
        if signal:
            where_clauses.append("trading_signal = %s")
            params.append(signal.upper())

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        cur.execute(
            f"""
            SELECT id, run_id, cabin_name, target_date::text, adjusted_rate,
                   trading_signal, confidence, sentiment_score, volatility_index,
                   generated_at::text
            FROM revenue_ledger
            {where_sql}
            ORDER BY generated_at DESC
            LIMIT %s
            """,
            params + [limit],
        )

        rows = cur.fetchall()
        return [dict(r) for r in rows]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ledger query failed: {str(e)}")


# ---- OPERATIONS ----

@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["Operations"],
    summary="Service health check",
    description=(
        "Returns the status of the QuantRevenue service, database connectivity, "
        "and cluster node reachability."
    ),
)
async def health_check():
    """
    GET /health — Standard health endpoint.

    Checks:
    - Service: always online if responding
    - Database: PostgreSQL connectivity
    - Captain Node: Ollama API reachability
    - Muscle Node: Ollama API reachability
    """
    now = datetime.now()

    # DB check
    db_status = "connected"
    conn = get_db_connection()
    if conn is None:
        db_status = "unavailable"

    # Cluster node checks (non-blocking, short timeout)
    async def check_node(url: str) -> str:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None, lambda: requests.get(f"{url}/api/tags", timeout=3)
            )
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                return f"online ({len(models)} models)"
            return f"degraded (HTTP {resp.status_code})"
        except Exception:
            return "offline"

    captain_status, muscle_status = await asyncio.gather(
        check_node(CAPTAIN_URL),
        check_node(MUSCLE_URL),
    )

    uptime = (now - _startup_time).total_seconds() if _startup_time else None

    return HealthResponse(
        status="online",
        module="CF-02 QuantRevenue",
        engine_version="1.0.0",
        cluster={
            "captain": captain_status,
            "muscle": muscle_status,
        },
        database=db_status,
        timestamp=now.isoformat(),
        uptime_seconds=round(uptime, 1) if uptime else None,
    )


@router.get(
    "/",
    tags=["Operations"],
    summary="Service root",
    include_in_schema=False,
)
async def root():
    """Redirect to docs for convenience."""
    return {
        "service": "CF-02 QuantRevenue API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "description": "Cabin Rentals of Georgia — Enterprise Dynamic Pricing Engine",
    }


# =============================================================================
# STANDALONE MODE: include router on the local app
# =============================================================================

app.include_router(router, prefix="/v1")

# =============================================================================
# STANDALONE RUNNER
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
