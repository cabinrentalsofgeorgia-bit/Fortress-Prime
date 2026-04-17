#!/usr/bin/env python3
"""
Grand Ingestion — Backfill legacy reservations with Universal Ledger line items.

Hydrates ``price_breakdown['line_items']`` and ``tax_breakdown`` from Streamline
``GetReservationPrice`` via :meth:`StreamlineClient.fetch_live_quote`, using the
same classification and tax resolver as storefront checkout.

Does **not** create trust ledger entries.

Default is dry-run (no DB commits). Pass ``--apply`` to persist.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from dotenv import load_dotenv

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.models.property import Property
    from backend.models.reservation import Reservation
    from backend.services.streamline_client import DisplayFee, LiveQuoteResult, StreamlineClient

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = SCRIPT_PATH.parents[2]

for candidate in (PROJECT_ROOT, REPO_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

for env_file in (REPO_ROOT / ".env", PROJECT_ROOT / ".env", REPO_ROOT / ".env.security"):
    if env_file.exists():
        load_dotenv(env_file, override=True)

import structlog
from sqlalchemy import and_, select, text
from sqlalchemy.orm import joinedload

logger = structlog.get_logger(service="grand_ingestion")

BATCH_SIZE = 50
INTER_CALL_DELAY = 1.0
BACKOFF_BASE = 5.0
BACKOFF_MAX = 60.0
ONE_HUNDRED = Decimal("100")

# Streamline GetReservationPrice only accepts legacy PMS confirmation IDs — not Sovereign-native codes.
SOVEREIGN_NATIVE_CONFIRMATION_PREFIXES: tuple[str, ...] = (
    "CRG-",
)


def _to_cents(value: Decimal) -> int:
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _slugify_id(s: str, max_len: int = 32) -> str:
    out = re.sub(r"[^a-z0-9_]+", "_", s.lower().strip())
    return out[:max_len] or "item"


def _fee_ledger_id(fee: Any) -> str:
    sid = (fee.streamline_id or "").strip()
    if sid:
        return f"{fee.fee_type}_{_slugify_id(sid, 40)}"
    return f"{fee.fee_type}_{_slugify_id(fee.name, 32)}"


def _build_hydrated_ledger(
    live: Any,
    county: str | None,
    nights: int,
) -> tuple[list[dict], dict, int, int]:
    """
    Build line_items dicts and tax_breakdown dict.

    Returns (line_items as list[dict], tax_breakdown dict, grand_total_cents, tax_total_cents).
    """
    from backend.api.storefront_checkout import LedgerLineItem
    from backend.services.ledger import BucketedItem, classify_item_full, resolve_taxes

    ledger_before_tax: list[LedgerLineItem] = []

    if live.streamline_rent and live.streamline_rent > Decimal("0"):
        cls = classify_item_full("rent", "Base Rent")
        ledger_before_tax.append(
            LedgerLineItem(
                id="base_rent_streamline",
                name=f"Base Rent ({nights} nights)",
                amount_cents=_to_cents(live.streamline_rent),
                is_taxable=True,
                is_refundable=cls.is_refundable,
                refund_policy=cls.refund_policy,
                type="rent",
                bucket=cls.bucket.value,
            )
        )

    for fee in live.fees:
        if fee.fee_type == "tax":
            continue
        cls = classify_item_full(fee.fee_type, fee.name)
        ledger_before_tax.append(
            LedgerLineItem(
                id=_fee_ledger_id(fee),
                name=fee.name,
                amount_cents=_to_cents(fee.amount),
                is_taxable=fee.is_taxable,
                is_refundable=cls.is_refundable,
                refund_policy=cls.refund_policy,
                type=fee.fee_type,
                bucket=cls.bucket.value,
            )
        )

    bucketed_items: list[BucketedItem] = []
    for li in ledger_before_tax:
        cls = classify_item_full(li.type, li.name)
        bucketed_items.append(
            BucketedItem(
                name=li.name,
                amount=Decimal(li.amount_cents) / ONE_HUNDRED,
                item_type=li.type,
                bucket=cls.bucket,
            )
        )

    tax_result = resolve_taxes(bucketed_items, county, nights)

    full_ledger: list[LedgerLineItem] = list(ledger_before_tax)
    for detail in tax_result.details:
        if detail.amount == Decimal("0.00"):
            continue
        full_ledger.append(
            LedgerLineItem(
                id=f"tax_{detail.tax_name[:30].replace(' ', '_').lower()}",
                name=detail.tax_name,
                amount_cents=_to_cents(detail.amount),
                is_taxable=False,
                is_refundable=False,
                refund_policy="follows_base",
                type="tax",
                bucket="tax",
            )
        )

    line_dicts = [li.model_dump() for li in full_ledger]
    tax_dict = tax_result.to_dict()
    tax_total_cents = _to_cents(tax_result.total_tax)
    grand_total_cents = sum(int(d.get("amount_cents") or 0) for d in line_dicts)

    return line_dicts, tax_dict, grand_total_cents, tax_total_cents


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hydrate legacy reservations with Streamline-derived ledger line items.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Reservations per DB fetch (default: {BATCH_SIZE}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max reservations to process (0 = no cap).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only; do not commit (default when --apply is not passed).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit changes to the database.",
    )
    args = parser.parse_args()
    if args.dry_run and args.apply:
        parser.error("Use only one of --dry-run or --apply")
    return args


async def _hydrate_one(
    db: "AsyncSession",
    reservation: "Reservation",
    prop: "Property | None",
    client: "StreamlineClient",
    apply: bool,
) -> dict[str, Any]:
    confirmation = (reservation.confirmation_code or "").strip()
    if not confirmation:
        return {"status": "skipped_no_confirmation", "reservation_id": str(reservation.id)}

    live = await client.fetch_live_quote(confirmation)
    if live is None:
        return {
            "status": "skipped_no_data",
            "confirmation_code": confirmation,
            "reservation_id": str(reservation.id),
        }

    county = getattr(prop, "county", None) if prop else None
    nights = max(0, (reservation.check_out_date - reservation.check_in_date).days)

    line_items, tax_breakdown, grand_total_cents, tax_total_cents = _build_hydrated_ledger(
        live, county, nights
    )

    if not line_items:
        return {
            "status": "skipped_empty_ledger",
            "confirmation_code": confirmation,
            "reservation_id": str(reservation.id),
        }

    existing_pb = reservation.price_breakdown if isinstance(reservation.price_breakdown, dict) else {}
    merged_pb = {**existing_pb, "line_items": line_items}
    merged_pb["grand_ingestion_source"] = "streamline_get_reservation_price"
    merged_pb["grand_ingestion_at"] = date.today().isoformat()

    if not apply:
        return {
            "status": "would_hydrate",
            "confirmation_code": confirmation,
            "reservation_id": str(reservation.id),
            "line_item_count": len(line_items),
            "grand_total_cents": grand_total_cents,
            "tax_total_cents": tax_total_cents,
        }

    reservation.price_breakdown = merged_pb
    reservation.tax_breakdown = tax_breakdown
    await db.commit()
    return {
        "status": "hydrated",
        "confirmation_code": confirmation,
        "reservation_id": str(reservation.id),
        "line_item_count": len(line_items),
        "grand_total_cents": grand_total_cents,
        "tax_total_cents": tax_total_cents,
    }


async def _run(args: argparse.Namespace) -> int:
    from backend.core.database import AsyncSessionLocal, close_db
    from backend.models.property import Property
    from backend.models.reservation import Reservation
    from backend.services.streamline_client import StreamlineClient

    apply = bool(args.apply)
    batch_size = max(1, int(args.batch_size))
    limit = int(args.limit) if args.limit and args.limit > 0 else None

    today = date.today()
    stats: dict[str, int] = {
        "total_rows_fetched": 0,
        "would_hydrate": 0,
        "hydrated": 0,
        "skipped_no_confirmation": 0,
        "skipped_no_data": 0,
        "skipped_empty_ledger": 0,
        "errors": 0,
        "excluded_from_retry": 0,
    }

    empty_line_items_clause = text(
        "(reservations.price_breakdown IS NULL "
        "OR NOT (reservations.price_breakdown ? 'line_items') "
        "OR jsonb_array_length("
        "COALESCE(reservations.price_breakdown->'line_items', '[]'::jsonb)"
        ") = 0)"
    )

    sovereign_prefix_clause = and_(
        *[
            ~Reservation.confirmation_code.startswith(prefix)
            for prefix in SOVEREIGN_NATIVE_CONFIRMATION_PREFIXES
        ]
    )

    client = StreamlineClient()
    try:
        processed = 0
        consecutive_failures = 0
        excluded_ids: set[UUID] = set()

        async with AsyncSessionLocal() as db:
            while True:
                base_conditions = [
                    Reservation.check_out_date >= today,
                    Reservation.status == "confirmed",
                    Reservation.confirmation_code.isnot(None),
                    empty_line_items_clause,
                    sovereign_prefix_clause,
                ]
                if excluded_ids:
                    base_conditions.append(Reservation.id.notin_(excluded_ids))

                stmt = (
                    select(Reservation)
                    .options(joinedload(Reservation.prop))
                    .where(and_(*base_conditions))
                    .order_by(Reservation.check_in_date.asc())
                    .limit(batch_size)
                )
                result = await db.execute(stmt)
                reservations = result.scalars().unique().all()
                if not reservations:
                    break

                stats["total_rows_fetched"] += len(reservations)

                for res in reservations:
                    if limit is not None and processed >= limit:
                        stats["excluded_from_retry"] = len(excluded_ids)
                        await _print_summary(stats, apply)
                        return 0

                    prop: Property | None = res.prop
                    try:
                        outcome = await _hydrate_one(db, res, prop, client, apply)
                        st = outcome.get("status", "")
                        if st == "would_hydrate":
                            stats["would_hydrate"] += 1
                        elif st == "hydrated":
                            stats["hydrated"] += 1
                        elif st == "skipped_no_confirmation":
                            stats["skipped_no_confirmation"] += 1
                        elif st == "skipped_no_data":
                            stats["skipped_no_data"] += 1
                        elif st == "skipped_empty_ledger":
                            stats["skipped_empty_ledger"] += 1
                        print(json.dumps(outcome))
                        consecutive_failures = 0
                        if st in (
                            "skipped_no_confirmation",
                            "skipped_no_data",
                            "skipped_empty_ledger",
                        ):
                            excluded_ids.add(res.id)
                    except Exception as exc:
                        stats["errors"] += 1
                        consecutive_failures += 1
                        excluded_ids.add(res.id)
                        logger.warning(
                            "grand_ingestion_row_error",
                            reservation_id=str(res.id),
                            error=str(exc)[:400],
                        )
                        print(
                            json.dumps(
                                {
                                    "status": "error",
                                    "reservation_id": str(res.id),
                                    "error": str(exc)[:500],
                                }
                            )
                        )
                        try:
                            await db.rollback()
                        except Exception:
                            pass
                        backoff = min(
                            BACKOFF_BASE * (2 ** (consecutive_failures - 1)),
                            BACKOFF_MAX,
                        )
                        await asyncio.sleep(backoff)
                        processed += 1
                        continue

                    processed += 1
                    if st != "skipped_no_confirmation":
                        await asyncio.sleep(INTER_CALL_DELAY)

        stats["excluded_from_retry"] = len(excluded_ids)
        await _print_summary(stats, apply)
        return 0
    finally:
        await client.close()
        await close_db()


async def _print_summary(stats: dict[str, int], apply: bool) -> None:
    summary = {
        "total_rows_fetched": stats.get("total_rows_fetched", 0),
        "would_hydrate": stats.get("would_hydrate", 0),
        "hydrated": stats.get("hydrated", 0),
        "skipped_no_confirmation": stats.get("skipped_no_confirmation", 0),
        "skipped_no_data": stats.get("skipped_no_data", 0),
        "skipped_empty_ledger": stats.get("skipped_empty_ledger", 0),
        "errors": stats.get("errors", 0),
        "excluded_from_retry": stats.get("excluded_from_retry", 0),
        "apply": apply,
    }
    print(json.dumps({"summary": summary}))


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
