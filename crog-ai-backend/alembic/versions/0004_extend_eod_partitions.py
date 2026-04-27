"""add backward partitions for hedge_fund.eod_bars (2023-09 → 2024-08)

Revision ID: 0004_extend_eod_partitions
Revises: 0003_rehash_xsource_dedup
Create Date: 2026-04-27

Context: migration 0002 created hedge_fund.eod_bars partitioned monthly
from 2024-09-01. The Dochia v1 calibration corpus has its earliest alert
on 2024-03-18 and requires 63 prior trading days of EOD history (longest
Donchian lookback). Without partitions covering 2023-09 → 2024-08, EOD
bars for that window have no destination partition and the backfill
script has to drop them client-side, in turn excluding ~8k observations
from the calibration corpus (every alert in the first ~9 months of the
corpus loses its prior-history requirement).

This migration adds 12 monthly partitions covering 2023-09-01 through
2024-08-31, eliminating the gap. After this runs, the same Polygon
backfill that was filtered down to 2024-09-01 can fetch from 2023-09-01
without integrity errors.

Pattern matches migration 0002: monthly RANGE partitions with explicit
[start, next_month_start) bounds. The shared parent index
ix_eod_bars_date_ticker is automatically applied to new partitions
(Postgres propagates partitioned-table indexes).

Idempotent: re-running fails on the second CREATE — alembic up/down
discipline is enforced by the version table, so this is fine.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic
revision: str = "0004_extend_eod_partitions"
down_revision: str | None = "0003_rehash_xsource_dedup"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# Monthly partitions to add: (year, month) for 2023-09 through 2024-08.
_BACKWARD_PARTITIONS: list[tuple[int, int]] = [
    (2023, 9),
    (2023, 10),
    (2023, 11),
    (2023, 12),
    (2024, 1),
    (2024, 2),
    (2024, 3),
    (2024, 4),
    (2024, 5),
    (2024, 6),
    (2024, 7),
    (2024, 8),
]


def _next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def upgrade() -> None:
    for year, month in _BACKWARD_PARTITIONS:
        next_year, next_month = _next_month(year, month)
        op.execute(
            f"""
            CREATE TABLE hedge_fund.eod_bars_{year}_{month:02d}
            PARTITION OF hedge_fund.eod_bars
            FOR VALUES FROM ('{year}-{month:02d}-01')
                       TO   ('{next_year}-{next_month:02d}-01')
            """
        )


def downgrade() -> None:
    # Drop in reverse order so the most recently created goes first.
    for year, month in reversed(_BACKWARD_PARTITIONS):
        op.execute(f"DROP TABLE IF EXISTS hedge_fund.eod_bars_{year}_{month:02d}")
