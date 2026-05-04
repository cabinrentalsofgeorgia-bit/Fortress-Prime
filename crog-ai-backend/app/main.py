"""FastAPI application for CROG-AI."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.meta import router as meta_router
from app.api.signals import router as signals_router
from app.database import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")


def _cors_origins() -> list[str]:
    raw = os.environ.get(
        "CROG_AI_CORS_ORIGINS",
        "https://crog-ai.com,http://localhost:3000,http://localhost:5173",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    app = FastAPI(
        title="CROG-AI Backend",
        version="0.1.0",
        description="MarketClub / Dochia Financial Division signal API.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(meta_router)
    app.include_router(signals_router)

    return app


app = create_app()
