"""
Deep Sync Calendars — full historical + 2-year future blocked-days pull.

Bypasses the incremental sync window and forces a complete refresh of every
blocked date from Streamline for all active properties. Stale blocks that no
longer exist upstream are purged using a timestamp watermark.

Usage:
    .uv-venv/bin/python -m backend.scripts.deep_sync_calendars
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta

import structlog

logger = structlog.get_logger(service="deep_sync")

LOOKBACK_DAYS = 90
LOOKAHEAD_DAYS = 730


async def deep_sync() -> None:
    from sqlalchemy import select, text as sa_text
    from backend.core.database import AsyncSessionLocal
    from backend.integrations.streamline_vrs import StreamlineVRS
    from backend.models.property import Property

    vrs = StreamlineVRS()
    if not vrs.is_configured:
        print("[ERROR] Streamline VRS is not configured. Check .env for API keys.")
        sys.exit(1)

    start = date.today() - timedelta(days=LOOKBACK_DAYS)
    end = date.today() + timedelta(days=LOOKAHEAD_DAYS)

    print(f"[DEEP SYNC] Window: {start} → {end} ({(end - start).days} days)\n")

    async with AsyncSessionLocal() as db:
        props = (await db.execute(
            select(Property)
            .where(Property.is_active.is_(True))
            .where(Property.streamline_property_id.isnot(None))
            .order_by(Property.name)
        )).scalars().all()
        print(f"[DEEP SYNC] Found {len(props)} active properties with Streamline IDs\n")

    total_upserted = 0
    total_purged = 0
    errors: list[str] = []

    for prop in props:
        unit_id = int(prop.streamline_property_id)
        print(f"  {prop.name} (unit {unit_id}) ... ", end="", flush=True)

        try:
            blocks = await vrs.fetch_blocked_days(unit_id, start, end)
        except Exception as exc:
            msg = f"{prop.name}: fetch failed — {exc}"
            errors.append(msg)
            print(f"FETCH ERROR: {exc}")
            continue

        upserted = 0
        async with AsyncSessionLocal() as db:
            for b in blocks:
                sd = b.get("start_date")
                ed = b.get("end_date")
                if not sd or not ed:
                    continue
                block_type = (b.get("type_name") or "reservation").lower().replace(" ", "_")[:50]
                cc = str(b.get("confirmation_id") or "")[:50] or None

                await db.execute(
                    sa_text("""
                        INSERT INTO blocked_days
                            (id, property_id, start_date, end_date, block_type,
                             confirmation_code, source, created_at, updated_at)
                        VALUES
                            (gen_random_uuid(), :pid, :sd, :ed, :bt, :cc,
                             'streamline', NOW(), NOW())
                        ON CONFLICT (property_id, start_date, end_date, block_type)
                        DO UPDATE SET
                            confirmation_code = EXCLUDED.confirmation_code,
                            updated_at = NOW()
                    """),
                    {"pid": str(prop.id), "sd": sd, "ed": ed, "bt": block_type, "cc": cc},
                )
                upserted += 1
            await db.commit()

            purge_result = await db.execute(
                sa_text("""
                    DELETE FROM blocked_days
                    WHERE property_id = :pid
                      AND source = 'streamline'
                      AND updated_at < NOW() - INTERVAL '30 seconds'
                """),
                {"pid": str(prop.id)},
            )
            purged = purge_result.rowcount
            await db.commit()

        total_upserted += upserted
        total_purged += purged
        status = f"{upserted} blocks"
        if purged:
            status += f", {purged} stale purged"
        print(status)

    print(f"\n{'='*50}")
    print(f"[DEEP SYNC COMPLETE]")
    print(f"  Properties synced: {len(props) - len(errors)}")
    print(f"  Blocks upserted:   {total_upserted}")
    print(f"  Stale purged:      {total_purged}")
    if errors:
        print(f"  Errors ({len(errors)}):")
        for e in errors:
            print(f"    - {e}")
    print()

    await vrs.close()


def main() -> None:
    asyncio.run(deep_sync())


if __name__ == "__main__":
    main()
