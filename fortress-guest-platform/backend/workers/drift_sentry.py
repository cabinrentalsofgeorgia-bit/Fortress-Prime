"""
Drift Sentry — Autonomous rate/tax coefficient verification worker.

Runs every 5 minutes, picks 3 random active cabins, fetches live
Streamline rate cards, and compares nightly rates + fee structures
against the locally cached rate_card in the properties table.
Discrepancies are auto-healed and logged to the drift_audit log.
"""

from __future__ import annotations

import asyncio
import os
import random
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.integrations.streamline_vrs import StreamlineVRS
from backend.models.property import Property
from backend.services.ledger import COUNTY_RATES, get_county_rates

logger = structlog.get_logger(service="drift_sentry")

SAMPLE_SIZE = 3
INTERVAL_SECONDS = 300  # 5 minutes


def _deprioritize() -> None:
    """Lower CPU priority so this worker never contends with request handlers."""
    try:
        os.nice(10)
    except (OSError, AttributeError):
        pass


async def _pick_random_cabins(db: AsyncSession, n: int) -> list[Any]:
    result = await db.execute(
        select(Property.id, Property.name, Property.slug, Property.streamline_property_id,
               Property.rate_card, Property.county)
        .where(Property.is_active.is_(True))
        .where(Property.streamline_property_id.isnot(None))
        .order_by(func.random())
        .limit(n)
    )
    return result.all()


def _extract_nightly_rates(rate_card: dict | None) -> dict[str, float]:
    """Build date→rate map from a local rate_card JSONB blob."""
    if not rate_card:
        return {}
    rates_list = rate_card.get("rates") or []
    out: dict[str, float] = {}
    for entry in rates_list:
        if not isinstance(entry, dict):
            continue
        d = entry.get("start_date") or entry.get("date")
        r = entry.get("nightly") or entry.get("nightly_rate") or entry.get("rate")
        if d and r:
            try:
                out[str(d)] = float(r)
            except (ValueError, TypeError):
                pass
    return out


def _compare_rates(
    local: dict[str, float], live: dict[str, float]
) -> list[dict[str, Any]]:
    """Return list of drift entries where local != live."""
    drifts = []
    for date_key, live_rate in live.items():
        local_rate = local.get(date_key)
        if local_rate is None:
            drifts.append({"date": date_key, "local": None, "live": live_rate, "type": "missing_local"})
        elif abs(local_rate - live_rate) > 0.01:
            drifts.append({"date": date_key, "local": local_rate, "live": live_rate, "type": "rate_mismatch"})
    return drifts


def _verify_tax_coefficients(county: str | None) -> list[dict[str, Any]]:
    """Verify that we have tax rates for this county."""
    issues = []
    key = (county or "").strip().lower()
    if not key:
        issues.append({"field": "county", "issue": "missing", "detail": "Property has no county assigned"})
    elif key not in COUNTY_RATES:
        issues.append({
            "field": "county", "issue": "unknown_jurisdiction",
            "detail": f"County '{county}' not in COUNTY_RATES — falling back to Fannin defaults",
        })
    return issues


async def _audit_cabin(
    vrs: StreamlineVRS, db: AsyncSession,
    prop_id: Any, prop_name: str, prop_slug: str,
    streamline_id: str, local_rate_card: dict | None, county: str | None,
) -> dict[str, Any]:
    """Audit a single cabin against Streamline live data."""
    report: dict[str, Any] = {
        "property": prop_name,
        "slug": prop_slug,
        "streamline_id": streamline_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rate_drifts": [],
        "tax_issues": [],
        "healed": False,
    }

    try:
        unit_id = int(streamline_id)
        live_data = await vrs.fetch_property_rates(unit_id)

        live_rates_raw = live_data.get("rates") or []
        live_rate_map: dict[str, float] = {}
        for entry in live_rates_raw:
            if isinstance(entry, dict):
                d = entry.get("start_date") or entry.get("date")
                r = entry.get("nightly") or entry.get("nightly_rate") or entry.get("rate")
                if d and r:
                    try:
                        live_rate_map[str(d)] = float(r)
                    except (ValueError, TypeError):
                        pass

        local_rate_map = _extract_nightly_rates(local_rate_card)
        report["rate_drifts"] = _compare_rates(local_rate_map, live_rate_map)

        if report["rate_drifts"]:
            await db.execute(
                update(Property)
                .where(Property.id == prop_id)
                .values(rate_card=live_data, updated_at=datetime.now(timezone.utc).replace(tzinfo=None))
            )
            await db.commit()
            report["healed"] = True
            logger.warning(
                "drift_sentry_rate_healed",
                property=prop_name,
                drift_count=len(report["rate_drifts"]),
            )

    except Exception as exc:
        report["rate_drifts"] = [{"error": str(exc)[:300]}]
        logger.error("drift_sentry_streamline_error", property=prop_name, error=str(exc)[:300])

    report["tax_issues"] = _verify_tax_coefficients(county)
    if report["tax_issues"]:
        logger.warning("drift_sentry_tax_issue", property=prop_name, issues=report["tax_issues"])

    return report


async def run_drift_sentry_cycle() -> list[dict[str, Any]]:
    """Execute one full drift sentry cycle. Returns audit reports."""
    if not settings.streamline_api_key or not settings.streamline_api_secret:
        logger.info("drift_sentry_skipped", reason="streamline_not_configured")
        return []

    vrs = StreamlineVRS()
    reports = []

    async with AsyncSessionLocal() as db:
        cabins = await _pick_random_cabins(db, SAMPLE_SIZE)
        if not cabins:
            logger.info("drift_sentry_no_cabins")
            return []

        logger.info("drift_sentry_cycle_start", cabin_count=len(cabins))

        for prop_id, prop_name, prop_slug, streamline_id, rate_card, county in cabins:
            report = await _audit_cabin(
                vrs, db, prop_id, prop_name, prop_slug,
                str(streamline_id), rate_card, county,
            )
            reports.append(report)
            await asyncio.sleep(1)

    total_drifts = sum(len(r["rate_drifts"]) for r in reports)
    total_healed = sum(1 for r in reports if r["healed"])
    total_tax_issues = sum(len(r["tax_issues"]) for r in reports)

    logger.info(
        "drift_sentry_cycle_complete",
        cabins_audited=len(reports),
        rate_drifts=total_drifts,
        auto_healed=total_healed,
        tax_issues=total_tax_issues,
    )
    return reports


async def drift_sentry_loop() -> None:
    """Infinite loop — call from ARQ startup or standalone process."""
    _deprioritize()
    logger.info("drift_sentry_started", interval=INTERVAL_SECONDS, sample_size=SAMPLE_SIZE)

    while True:
        try:
            await run_drift_sentry_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("drift_sentry_loop_error", error=str(exc)[:400])
        await asyncio.sleep(INTERVAL_SECONDS)
