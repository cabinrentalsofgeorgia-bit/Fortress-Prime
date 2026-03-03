#!/usr/bin/env python3
"""
FORTRESS PRIME — Covariance Engine (Quantitative Brain for The Jordi)
=====================================================================
Computes cross-asset correlation and covariance matrices from daily closing
prices and formats the output as LLM-readable Markdown for injection into
persona RAG context.

Usage:
    from src.covariance_engine import get_correlation_context

    context = get_correlation_context()
    # Returns a Markdown string ready for LLM system prompt injection

Caching:
    Results are cached in-memory with a configurable TTL (default 1 hour)
    to avoid redundant yfinance calls during a single Council voting session.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

logger = logging.getLogger("covariance_engine")

DEFAULT_TICKERS = ["SPY", "GLD", "TLT", "^VIX", "BTC-USD", "ETH-USD"]
DEFAULT_PERIOD_DAYS = 90
TRADING_DAYS_PER_YEAR = 252
CACHE_TTL_SECONDS = float(os.getenv("COVARIANCE_CACHE_TTL", "3600"))

_cache: dict[str, dict] = {}


def _cache_key(tickers: list[str], period_days: int) -> str:
    return f"{','.join(sorted(tickers))}:{period_days}"


def fetch_prices(
    tickers: list[str] | None = None,
    period_days: int = DEFAULT_PERIOD_DAYS,
) -> pd.DataFrame:
    """
    Fetch daily adjusted close prices from yfinance.

    Returns:
        DataFrame with tickers as columns and dates as index.
        Empty DataFrame on failure.
    """
    tickers = tickers or DEFAULT_TICKERS
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=period_days)

    try:
        data = yf.download(
            tickers,
            start=str(start_date),
            end=str(end_date),
            auto_adjust=True,
            progress=False,
            timeout=15,
        )
    except Exception as exc:
        logger.warning(f"yfinance download failed: {exc}")
        return pd.DataFrame()

    if data.empty:
        logger.warning("yfinance returned empty data")
        return pd.DataFrame()

    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"] if "Close" in data.columns.get_level_values(0) else data
    else:
        close = data

    close = close.dropna(how="all")
    if close.empty:
        logger.warning("No valid close prices after cleanup")
        return pd.DataFrame()

    friendly = {t: t.replace("-USD", "").replace("^", "") for t in tickers}
    close = close.rename(columns=friendly)
    return close


def compute_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily percentage returns."""
    return prices.pct_change().dropna()


def compute_covariance(returns: pd.DataFrame) -> pd.DataFrame:
    """Annualized covariance matrix (daily cov * 252)."""
    return returns.cov() * TRADING_DAYS_PER_YEAR


def compute_correlation(returns: pd.DataFrame) -> pd.DataFrame:
    """Correlation matrix (-1 to 1)."""
    return returns.corr()


def _top_pairs(corr: pd.DataFrame, n: int = 3) -> list[tuple[str, str, float]]:
    """Extract top-N strongest absolute correlations (excluding self-pairs)."""
    pairs = []
    cols = list(corr.columns)
    seen = set()
    for i, a in enumerate(cols):
        for j, b in enumerate(cols):
            if i >= j:
                continue
            key = (min(a, b), max(a, b))
            if key not in seen:
                seen.add(key)
                pairs.append((a, b, corr.iloc[i, j]))
    pairs.sort(key=lambda x: abs(x[2]), reverse=True)
    return pairs[:n]


def format_correlation_markdown(corr: pd.DataFrame) -> str:
    """
    Convert a correlation DataFrame into a Markdown table with interpretive summary.
    """
    cols = list(corr.columns)

    header = "| | " + " | ".join(cols) + " |"
    sep = "|---" + "|---" * len(cols) + "|"
    rows = []
    for row_label in cols:
        vals = " | ".join(f"{corr.loc[row_label, c]:.2f}" for c in cols)
        rows.append(f"| **{row_label}** | {vals} |")

    table = "\n".join([header, sep] + rows)

    top = _top_pairs(corr)
    summary_parts = []
    for a, b, val in top:
        strength = "strongly" if abs(val) > 0.7 else "moderately" if abs(val) > 0.4 else "weakly"
        direction = "positively" if val > 0 else "negatively"
        summary_parts.append(f"{a}/{b} are {strength} {direction} correlated ({val:.2f})")

    summary = "; ".join(summary_parts) + "." if summary_parts else ""

    return f"**90-Day Cross-Asset Correlation Matrix**\n\n{table}\n\n{summary}"


def get_correlation_context(
    tickers: list[str] | None = None,
    period_days: int = DEFAULT_PERIOD_DAYS,
) -> str:
    """
    Public API: returns a formatted Markdown string containing the correlation
    matrix table, key relationship summary, and data timestamp.

    Cached for CACHE_TTL_SECONDS (default 1 hour) to avoid redundant fetches.
    Returns empty string on any failure (graceful degradation).
    """
    tickers = tickers or DEFAULT_TICKERS
    key = _cache_key(tickers, period_days)

    cached = _cache.get(key)
    if cached and (time.time() - cached["ts"]) < CACHE_TTL_SECONDS:
        logger.debug("Returning cached correlation context")
        return cached["text"]

    try:
        prices = fetch_prices(tickers, period_days)
        if prices.empty:
            return ""

        returns = compute_returns(prices)
        if returns.empty or len(returns) < 10:
            return ""

        corr = compute_correlation(returns)
        md = format_correlation_markdown(corr)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        text = f"{md}\n\n_Data: {period_days}-day window ending {timestamp}_"

        _cache[key] = {"text": text, "ts": time.time()}
        logger.info(f"Correlation matrix computed: {len(returns)} trading days, {len(tickers)} assets")
        return text

    except Exception as exc:
        logger.warning(f"Correlation context generation failed: {exc}")
        return ""
