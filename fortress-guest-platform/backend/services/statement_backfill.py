"""
Phase E.5 — Streamline backfill service.

Two functions:
  backfill_property_groups_from_streamline(db) -> BackfillReport
  backfill_owner_addresses_from_streamline(db)  -> BackfillReport

Both are idempotent: rows that already have the target field set are skipped.
Both sleep 200 ms between API calls and retry once on transient failure.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.integrations.streamline_vrs import StreamlineVRS
from backend.models.owner_payout import OwnerPayoutAccount
from backend.models.property import Property

logger = structlog.get_logger(service="statement_backfill")

_CALL_SLEEP = 0.20   # 200 ms between Streamline API calls
_RETRY_SLEEP = 2.00  # 2-second backoff on first retry


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class BackfillOutcome:
    id: int
    name: str
    status: str           # 'updated' | 'skipped' | 'no_sl_id' | 'api_empty' | 'error'
    detail: str = ""      # resolved value or error message


@dataclass
class BackfillReport:
    target: str           # 'property_groups' or 'owner_addresses'
    total: int = 0
    updated: int = 0
    skipped: int = 0
    outcomes: list[BackfillOutcome] = field(default_factory=list)

    def add(self, outcome: BackfillOutcome) -> None:
        self.total += 1
        self.outcomes.append(outcome)
        if outcome.status == "updated":
            self.updated += 1
        else:
            self.skipped += 1

    def __str__(self) -> str:
        lines = [
            f"=== Backfill: {self.target} ===",
            f"Total: {self.total}  Updated: {self.updated}  Skipped/no-op: {self.skipped}",
            "",
        ]
        for o in self.outcomes:
            lines.append(f"  [{o.status:12s}] {o.name} (id={o.id}) — {o.detail}")
        return "\n".join(lines)


# ── Internal helper ───────────────────────────────────────────────────────────

async def _call_with_retry(fn, *args, **kwargs) -> Any:
    """Call fn(*args, **kwargs) once; retry once after _RETRY_SLEEP on exception."""
    try:
        return await fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("streamline_call_retry", error=str(exc)[:120])
        await asyncio.sleep(_RETRY_SLEEP)
        return await fn(*args, **kwargs)  # let this raise on second failure


# ── Property data backfill (group + city/state/postal) ───────────────────────

async def backfill_property_data_from_streamline(
    db: AsyncSession,
) -> BackfillReport:
    """
    For each active/pre_launch property, fetch Streamline's GetPropertyList and
    populate: property_group (location_area_name), city, state, postal_code.

    Runs for all active/pre_launch properties regardless of current column state,
    so it re-syncs if Streamline changes a property's location data.
    """
    report = BackfillReport(target="property_data")

    result = await db.execute(
        select(Property)
        .where(Property.renting_state.in_(["active", "pre_launch"]))
        .order_by(Property.name)
    )
    properties = result.scalars().all()

    if not properties:
        logger.info("property_data_backfill_nothing_to_do")
        return report

    # Fetch the full property list from Streamline once, match by unit ID
    client = StreamlineVRS()
    try:
        raw = await _call_with_retry(client._call, "GetPropertyList")
    except Exception as exc:
        logger.error("property_data_backfill_list_failed", error=str(exc)[:200])
        for prop in properties:
            report.add(BackfillOutcome(
                id=str(prop.id), name=prop.name,
                status="error", detail=f"GetPropertyList failed: {str(exc)[:100]}",
            ))
        await client.close()
        return report

    # Build lookup: streamline_property_id → {group, city, state, postal_code}
    raw_props = raw.get("property", []) if isinstance(raw, dict) else []
    if isinstance(raw_props, dict):
        raw_props = [raw_props]

    def _s(v) -> str:
        return str(v).strip() if v and not isinstance(v, dict) else ""

    data_by_sl_id: dict[str, dict] = {}
    for p in raw_props:
        sl_id = _s(p.get("id"))
        if sl_id:
            data_by_sl_id[sl_id] = {
                "group":       _s(p.get("location_area_name")),
                "city":        _s(p.get("city")),
                "state":       _s(p.get("state_name")),
                "postal_code": _s(p.get("zip")),
            }

    await client.close()

    for prop in properties:
        sl_id = str(prop.streamline_property_id or "").strip()
        if not sl_id:
            report.add(BackfillOutcome(
                id=str(prop.id), name=prop.name,
                status="no_sl_id", detail="streamline_property_id is NULL",
            ))
            continue

        pdata = data_by_sl_id.get(sl_id)
        if not pdata:
            report.add(BackfillOutcome(
                id=str(prop.id), name=prop.name,
                status="api_empty",
                detail=f"sl_id={sl_id} not found in GetPropertyList response",
            ))
            continue

        prop.property_group = pdata["group"] or prop.property_group
        prop.city = pdata["city"] or None
        prop.state = pdata["state"] or None
        prop.postal_code = pdata["postal_code"] or None
        await db.flush()

        detail = (
            f"group={pdata['group']!r}  "
            f"city={pdata['city']!r}  "
            f"state={pdata['state']!r}  "
            f"postal={pdata['postal_code']!r}"
        )
        report.add(BackfillOutcome(
            id=str(prop.id), name=prop.name,
            status="updated", detail=detail,
        ))
        await asyncio.sleep(_CALL_SLEEP)

    await db.commit()
    logger.info(
        "property_data_backfill_complete",
        updated=report.updated,
        skipped=report.skipped,
    )
    return report


# Keep the Phase E.5 name as an alias so existing callers don't break.
backfill_property_groups_from_streamline = backfill_property_data_from_streamline


# ── Owner address backfill ────────────────────────────────────────────────────

async def backfill_owner_addresses_from_streamline(
    db: AsyncSession,
) -> BackfillReport:
    """
    For each owner_payout_account where mailing_address_line1 IS NULL,
    call GetOwnerInfo(streamline_owner_id) and populate the six address fields.

    Rows with NULL streamline_owner_id are skipped with status='no_sl_id'.
    Idempotent: rows that already have line1 set are not touched.
    """
    report = BackfillReport(target="owner_addresses")

    result = await db.execute(
        select(OwnerPayoutAccount)
        .where(OwnerPayoutAccount.mailing_address_line1.is_(None))
        .order_by(OwnerPayoutAccount.id)
    )
    accounts = result.scalars().all()

    if not accounts:
        logger.info("owner_address_backfill_nothing_to_do")
        return report

    client = StreamlineVRS()

    for opa in accounts:
        if opa.streamline_owner_id is None:
            report.add(BackfillOutcome(
                id=opa.id, name=opa.owner_name,
                status="no_sl_id", detail="streamline_owner_id is NULL — skipped",
            ))
            continue

        try:
            info = await _call_with_retry(
                client.fetch_owner_info, int(opa.streamline_owner_id)
            )
        except Exception as exc:
            logger.error(
                "owner_address_backfill_api_error",
                opa_id=opa.id, error=str(exc)[:200],
            )
            report.add(BackfillOutcome(
                id=opa.id, name=opa.owner_name,
                status="error", detail=f"API error: {str(exc)[:100]}",
            ))
            await asyncio.sleep(_CALL_SLEEP)
            continue

        if not info or not info.get("address1"):
            report.add(BackfillOutcome(
                id=opa.id, name=opa.owner_name,
                status="api_empty",
                detail=f"GetOwnerInfo returned no address for sl_owner_id={opa.streamline_owner_id}",
            ))
            await asyncio.sleep(_CALL_SLEEP)
            continue

        # Update mailing address
        opa.mailing_address_line1 = info["address1"] or None
        opa.mailing_address_line2 = info["address2"] or None
        opa.mailing_address_city = info["city"] or None
        opa.mailing_address_state = info["state"] or None
        opa.mailing_address_postal_code = info["zip"] or None
        opa.mailing_address_country = info["country"] or "USA"

        # Also refresh owner_name in Streamline's last-middle-first format
        display_name = info.get("display_name", "")
        if display_name:
            opa.owner_name = display_name

        await db.flush()

        addr_summary = (
            f"{info['address1']}, {info['city']}, {info['state']} {info['zip']}"
            f"  name={display_name!r}"
        )
        report.add(BackfillOutcome(
            id=opa.id, name=opa.owner_name,
            status="updated", detail=addr_summary,
        ))
        await asyncio.sleep(_CALL_SLEEP)

    await db.commit()
    await client.close()
    logger.info(
        "owner_address_backfill_complete",
        updated=report.updated,
        skipped=report.skipped,
    )
    return report
