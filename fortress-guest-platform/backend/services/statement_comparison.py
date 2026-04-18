"""
Statement Comparison Service
==============================
Compares a Crog-VRS StatementResult against a Streamline StatementResult
and returns a ComparisonResult describing the outcome.

Streamline status:
  GetMonthEndStatement returns statement metadata only (no financial figures
  in JSON).  The financial data is in the PDF attachment.
  fetch_streamline_statement_normalized() currently returns None for all
  calls (comparison_status = 'streamline_unavailable') until the PDF
  extraction approach is confirmed by the product owner.

  See NOTES.md: "GetMonthEndStatement returns no financial data in JSON".

compare_statements() is fully implemented and testable using mocked
StatementResult objects — it does not depend on the Streamline client.

Winner policy:
  match              → winner = 'crog'        (we agree, trust our number)
  mismatch           → winner = 'streamline'  (tiebreaker until trust built)
  streamline_unavailable → winner = 'crog'    (no choice; flagged in audit row)

Match tolerance: diff <= $0.01 (one cent) counts as a match to protect
against Decimal/float rounding artifacts.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

import structlog
from pydantic import BaseModel

from backend.services.statement_computation import StatementResult

logger = structlog.get_logger(service="statement_comparison")

_MATCH_TOLERANCE_CENTS = 1  # diffs ≤ $0.01 count as a match


# ── Output model ──────────────────────────────────────────────────────────────

class ComparisonResult(BaseModel):
    """
    Result of compare_statements(crog, streamline).

    All cent values are integers (dollars × 100, rounded to nearest cent).
    diff_cents is the absolute difference in total_net_to_owner.
    """
    status: Literal["match", "mismatch", "streamline_unavailable"]
    winner: Literal["crog", "streamline"]
    diff_cents: int
    crog_total_cents: int
    streamline_total_cents: Optional[int] = None
    mismatched_fields: list[str]

    class Config:
        json_encoders = {Decimal: str}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_cents(amount: Decimal) -> int:
    """Convert a Decimal dollar amount to integer cents (half-up rounding)."""
    return int((amount * 100).to_integral_value())


def _fmt(amount: Decimal) -> str:
    return f"${amount:,.2f}"


# ── Main entry point ──────────────────────────────────────────────────────────

def compare_statements(
    crog: StatementResult,
    streamline: Optional[StatementResult],
) -> ComparisonResult:
    """
    Compare a Crog-VRS statement against a Streamline statement.

    If streamline is None (unavailable, API error, or PDF extraction pending),
    returns status='streamline_unavailable' with winner='crog'.

    All comparisons are on total_net_to_owner.  If the streamline result also
    has total_gross and total_commission populated, those are compared and any
    differences are reported in mismatched_fields.

    Match tolerance: diff <= $0.01 (one cent) is treated as a match.
    """
    crog_cents = _to_cents(crog.total_net_to_owner)

    if streamline is None:
        return ComparisonResult(
            status="streamline_unavailable",
            winner="crog",
            diff_cents=0,
            crog_total_cents=crog_cents,
            streamline_total_cents=None,
            mismatched_fields=[],
        )

    streamline_cents = _to_cents(streamline.total_net_to_owner)
    diff = abs(crog_cents - streamline_cents)
    mismatched: list[str] = []

    # Primary comparison: net_to_owner
    if diff > _MATCH_TOLERANCE_CENTS:
        crog_amt = crog.total_net_to_owner
        sl_amt = streamline.total_net_to_owner
        delta = crog_amt - sl_amt
        mismatched.append(
            f"net_to_owner: crog={_fmt(crog_amt)} "
            f"streamline={_fmt(sl_amt)} "
            f"diff={_fmt(abs(delta))} "
            f"({'crog higher' if delta > 0 else 'streamline higher'})"
        )

    # Secondary comparisons (only if streamline has non-zero gross to compare)
    if streamline.total_gross > Decimal("0"):
        gross_diff_cents = abs(_to_cents(crog.total_gross) - _to_cents(streamline.total_gross))
        if gross_diff_cents > _MATCH_TOLERANCE_CENTS:
            mismatched.append(
                f"gross: crog={_fmt(crog.total_gross)} "
                f"streamline={_fmt(streamline.total_gross)} "
                f"diff={_fmt(abs(crog.total_gross - streamline.total_gross))}"
            )

    if streamline.total_commission > Decimal("0"):
        comm_diff_cents = abs(
            _to_cents(crog.total_commission) - _to_cents(streamline.total_commission)
        )
        if comm_diff_cents > _MATCH_TOLERANCE_CENTS:
            mismatched.append(
                f"commission: crog={_fmt(crog.total_commission)} "
                f"streamline={_fmt(streamline.total_commission)} "
                f"diff={_fmt(abs(crog.total_commission - streamline.total_commission))}"
            )

    if diff <= _MATCH_TOLERANCE_CENTS:
        status: Literal["match", "mismatch"] = "match"
        winner: Literal["crog", "streamline"] = "crog"
    else:
        status = "mismatch"
        winner = "streamline"

    return ComparisonResult(
        status=status,
        winner=winner,
        diff_cents=diff,
        crog_total_cents=crog_cents,
        streamline_total_cents=streamline_cents,
        mismatched_fields=mismatched,
    )


# ── Streamline normalization (PENDING PRODUCT OWNER DECISION) ─────────────────

async def fetch_streamline_statement_normalized(
    streamline_owner_id: int,
    period_start: date,
    period_end: date,
    streamline_property_id: Optional[str] = None,
) -> Optional[StatementResult]:
    """
    Call Streamline's GetMonthEndStatement and normalize the response into
    a StatementResult with source='streamline'.

    CURRENT STATUS: Returns None for all calls.

    REASON: GetMonthEndStatement's JSON response contains no financial data.
    The response structure is:
        {
            "statements": {
                "statement": {
                    "id": <int>,
                    "location_name": <str>,
                    "name": <str>,
                    "start_date": <str MM/DD/YY>,
                    "end_date": <str MM/DD/YY>,
                    "total_number": <int>  ← count of statements, NOT dollars
                }
            }
        }

    Financial figures (gross revenue, owner net payout, management fee) are
    in the PDF attachment only.  The product owner must decide how to proceed:

        Option A — Parse the PDF (complex, brittle)
        Option B — Use GetReservations data as a proxy
        Option C — Accept 'streamline_unavailable' for all runs (current)

    See NOTES.md: "GetMonthEndStatement returns no financial data in JSON"
    and the Phase 3 report for the full analysis.

    When this is implemented, it must:
      - Use the existing StreamlineVRS.fetch_owner_statement() — do NOT write
        a new client.
      - Log the raw Streamline response at DEBUG level (financial data).
      - Return None on any failure, never raise.
      - Set source='streamline' on the returned StatementResult.
    """
    logger.info(
        "streamline_statement_normalized_stub",
        streamline_owner_id=streamline_owner_id,
        period_start=str(period_start),
        period_end=str(period_end),
        note="returning None — financial data not available in Streamline JSON API",
    )
    return None
