"""Database connection helpers for the CROG-AI backend."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def normalize_psycopg_url(url: str) -> str:
    """Convert SQLAlchemy psycopg URLs into psycopg-native URLs."""
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url.removeprefix("postgresql+psycopg://")
    if url.startswith("postgresql+psycopg:"):
        return "postgresql:" + url.removeprefix("postgresql+psycopg:")
    return url


def database_url() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        raise RuntimeError("DATABASE_URL is required")
    return normalize_psycopg_url(raw)


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url())
