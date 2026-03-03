"""
CROG Gateway - FastAPI Application Entry Point

Strangler Fig Pattern Microservice for migrating guest communication
from legacy systems (RueBaRue SMS, Streamline VRS) to CROG AI.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.core.config import settings
from app.core.logging import setup_logging
from app.services.router import TrafficRouter
from app.adapters.legacy.ruebarue import RueBaRueAdapter
from app.adapters.legacy.streamline import StreamlineVRSAdapter
from app.adapters.ai.crog import CrogAIAdapter
from app.api.routes import router

# Initialize structured logging
setup_logging()
logger = structlog.get_logger()

# Global TrafficRouter instance (initialized at startup)
traffic_router: TrafficRouter = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifecycle manager.
    
    Handles startup and shutdown logic for adapters and connections.
    """
    global traffic_router

    log = logger.bind(event="startup")
    log.info(
        "starting_crog_gateway",
        version=settings.app_version,
        environment=settings.environment,
    )

    # Initialize adapters
    legacy_sms = RueBaRueAdapter()
    legacy_pms = StreamlineVRSAdapter()
    ai_service = CrogAIAdapter()

    # Initialize Traffic Router
    traffic_router = TrafficRouter(
        legacy_sms=legacy_sms,
        legacy_pms=legacy_pms,
        ai_service=ai_service,
    )

    log.info(
        "traffic_router_initialized",
        feature_flags={
            "enable_ai_replies": settings.enable_ai_replies,
            "shadow_mode": settings.shadow_mode,
            "ai_intent_filter": settings.ai_intent_filter,
        },
    )

    yield  # Application runs here

    # Shutdown: Cleanup resources
    log.info("shutting_down_crog_gateway")
    await legacy_sms.close()
    await legacy_pms.close()
    await ai_service.close()
    log.info("shutdown_complete")


# Initialize FastAPI application
app = FastAPI(
    title="CROG Gateway",
    description="Strangler Fig Pattern Microservice for Guest Communication",
    version=settings.app_version,
    lifespan=lifespan,
)

# CORS Middleware (adjust for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.environment == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(router, prefix="")


@app.get("/")
async def root():
    """
    Root endpoint - API documentation pointer.
    """
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "docs": "/docs",
        "health": "/health",
        "strangler_pattern": {
            "enabled": True,
            "shadow_mode": settings.shadow_mode,
            "ai_enabled": settings.enable_ai_replies,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower(),
    )
