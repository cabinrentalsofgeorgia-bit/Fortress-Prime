"""
Revenue Realizer — Converting Ghost Revenue to Cash
=======================================================
The "Cash Wire" that connects Plaid deposits to the double-entry ledger.

Problem:
    Plaid gives us: "Stripe Transfer - $2,450.00" (dumb signal)
    We need:        cabin, checkin, checkout, reservation_id (smart context)

Solution (3-tier confidence):
    1. HIGH — Exact match to a single fin_reservations row → auto-confirm
    2. LOW  — Multiple candidates or fuzzy match → flag for Sovereign review
    3. ZERO — No match at all → "Unforecasted Windfall" → flag for review

Accounting Entry (4-line compound JE):
    Dr  1000  Bank:Operating                  (net deposit)
    Dr  6020  COGS:Merchant Processing Fees   (Stripe fee)
    Cr  4050  Rental Income:Forecast           (reverse forecast)
    Cr  4000  Rental Income:Management Fees    (realize actual)

    If no forecast existed (unforecasted), the entry is 3 lines:
    Dr  1000  Bank:Operating                  (net deposit)
    Dr  6020  COGS:Merchant Processing Fees   (Stripe fee)
    Cr  4000  Rental Income:Management Fees    (actual revenue)

Integration:
    Called from PropertyAgent._orient() when a Stripe deposit is detected.
    Feeds into accounting.revenue_bridge for forecast reversal.

Module: CF-02 QuantRevenue / Operation Strangler Fig
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("division_b.revenue_realizer")

# Stripe fee structure (as of 2025): 2.9% + $0.30 per transaction
STRIPE_PCT = Decimal("0.029")
STRIPE_FIXED = Decimal("0.30")

# Account codes
BANK_OPERATING = "1000"
MERCHANT_FEES = "6020"
FORECAST_AR = "1150"
FORECAST_REV = "4050"
ACTUAL_REV = "4000"

# Matching tolerance: ±2% to account for Stripe fee estimation variance
MATCH_TOLERANCE_PCT = Decimal("0.02")

# Minimum deposit amount to trigger revenue matching (filter noise)
MIN_DEPOSIT_THRESHOLD = Decimal("50.00")

SCHEMA = "division_b"


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class MatchResult:
    """Result of attempting to match a Stripe deposit to a reservation."""
    confidence: str  # "HIGH", "LOW", "ZERO"
    matches: List[Dict[str, Any]] = field(default_factory=list)
    deposit_net: Decimal = Decimal("0.00")
    estimated_gross: Decimal = Decimal("0.00")
    estimated_fees: Decimal = Decimal("0.00")
    message: str = ""
    auto_confirmed: bool = False
    journal_entry_id: Optional[str] = None


@dataclass
class ClarificationRequest:
    """When the agent can't auto-match, it asks the Sovereign."""
    request_id: str
    deposit_amount: Decimal
    estimated_gross: Decimal
    deposit_date: str
    vendor: str
    candidates: List[Dict[str, Any]]
    status: str = "pending"  # pending, resolved, expired
    resolved_reservation_id: Optional[str] = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


# =============================================================================
# 1. STRIPE FEE CALCULATOR
# =============================================================================

def estimate_stripe_fees(net_deposit: Decimal) -> Tuple[Decimal, Decimal]:
    """
    Reverse-engineer the gross revenue from a net Stripe deposit.

    Stripe takes: fee = gross * 2.9% + $0.30
    Net = gross - fee = gross * (1 - 0.029) - 0.30
    Therefore: gross = (net + 0.30) / (1 - 0.029)

    Returns: (estimated_gross, estimated_fees)
    """
    net = Decimal(str(net_deposit)).quantize(Decimal("0.01"))
    gross = ((net + STRIPE_FIXED) / (1 - STRIPE_PCT)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )
    fees = (gross - net).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return gross, fees


# =============================================================================
# 2. RESERVATION MATCHER — The Detective
# =============================================================================

def find_reservation_matches(
    net_deposit: Decimal,
    deposit_date: Optional[date] = None,
) -> MatchResult:
    """
    Search fin_reservations for bookings whose total_revenue matches
    the estimated gross of the Stripe deposit.

    Matching strategy:
        1. Estimate gross from net deposit (accounting for Stripe fees)
        2. Search fin_reservations WHERE total_revenue BETWEEN gross ± tolerance
        3. Prefer reservations with check_in near the deposit date
        4. Return confidence level based on match count

    Args:
        net_deposit: The amount Plaid reports (net of Stripe fees)
        deposit_date: When the deposit hit the bank (for proximity scoring)

    Returns:
        MatchResult with confidence and candidate reservations
    """
    gross, fees = estimate_stripe_fees(net_deposit)
    tolerance = gross * MATCH_TOLERANCE_PCT
    lower = gross - tolerance
    upper = gross + tolerance

    result = MatchResult(
        confidence="ZERO",
        deposit_net=net_deposit,
        estimated_gross=gross,
        estimated_fees=fees,
    )

    try:
        conn = _connect()
        cur = conn.cursor()

        # Search fin_reservations for total_revenue in range
        # Prefer recent / upcoming reservations, exclude already-realized ones
        cur.execute("""
            SELECT
                res_id, property_id, property_name,
                guest_name, check_in, check_out, nights,
                nightly_rate, total_revenue, status, source,
                ABS(total_revenue - %s) as delta
            FROM fin_reservations
            WHERE total_revenue BETWEEN %s AND %s
              AND status NOT IN ('Realized', 'Cancelled')
            ORDER BY
                delta ASC,
                ABS(check_in - %s) ASC
            LIMIT 10
        """, (float(gross), float(lower), float(upper),
              deposit_date or date.today()))
        rows = cur.fetchall()
        conn.close()

        candidates = [dict(r) for r in rows]

        if len(candidates) == 0:
            result.confidence = "ZERO"
            result.message = (
                f"No reservation found matching ${gross:,.2f} "
                f"(±{MATCH_TOLERANCE_PCT * 100:.0f}%). "
                f"Unforecasted deposit — flag for review."
            )

        elif len(candidates) == 1:
            match = candidates[0]
            result.confidence = "HIGH"
            result.matches = candidates
            result.message = (
                f"Confident match: {match['property_name']} "
                f"({match['check_in']} to {match['check_out']}), "
                f"res #{match['res_id']}, "
                f"total ${float(match['total_revenue']):,.2f} "
                f"(delta: ${float(match['delta']):,.2f})"
            )

        else:
            result.confidence = "LOW"
            result.matches = candidates
            names = [c["property_name"] for c in candidates[:3]]
            result.message = (
                f"Ambiguous: {len(candidates)} reservations match "
                f"${gross:,.2f} — candidates: {', '.join(names)}. "
                f"Sovereign review required."
            )

        logger.info(
            f"[REALIZER] Deposit ${net_deposit:,.2f} → "
            f"gross ${gross:,.2f} (fees ${fees:,.2f}) → "
            f"{result.confidence} confidence, {len(candidates)} matches"
        )

    except Exception as e:
        logger.error(f"[REALIZER] Match query failed: {e}")
        result.message = f"Database error: {e}"

    return result


# =============================================================================
# 3. REVENUE REALIZATION — The Compound Journal Entry
# =============================================================================

def realize_revenue(
    net_deposit: Decimal,
    reservation_id: str,
    plaid_txn_id: str = "",
    deposit_date: Optional[date] = None,
    schema: str = SCHEMA,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Execute the full revenue realization workflow:

        1. Look up the reservation in fin_reservations
        2. Calculate Stripe fees
        3. Reverse forecast accruals via revenue_bridge
        4. Post the compound 4-line journal entry:
               Dr 1000  Bank:Operating              (net)
               Dr 6020  COGS:Merchant Fees           (fee)
               Cr 4050  Rental Income:Forecast        (reverse ghost — if forecast existed)
               Cr 4000  Rental Income:Management Fees (actual revenue)
        5. Update fin_reservations status to 'Realized'

    If no forecast existed (unforecasted deposit), the entry is 3 lines
    (no Cr 4050 line, just Cr 4000).

    Args:
        net_deposit: Net amount received from Stripe
        reservation_id: The res_id from fin_reservations
        plaid_txn_id: Plaid transaction ID for audit trail
        deposit_date: Date the deposit hit the bank
        schema: Target division schema

    Returns:
        {"success": bool, "journal_entry_id": str, ...}
    """
    import sys
    proj_root = str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent)
    if proj_root not in sys.path:
        sys.path.insert(0, proj_root)

    from accounting.models import JournalEntry, LedgerLine, AccountingError
    from accounting.engine import post_journal_entry

    result = {
        "success": False,
        "journal_entry_id": None,
        "reservation_id": reservation_id,
        "net_deposit": float(net_deposit),
        "gross_revenue": 0.0,
        "stripe_fees": 0.0,
        "forecasts_reversed": 0,
    }

    conn = _connect()
    try:
        cur = conn.cursor()

        # 1. Look up reservation
        cur.execute("""
            SELECT res_id, property_id, property_name,
                   check_in, check_out, nights,
                   total_revenue, status
            FROM fin_reservations
            WHERE res_id = %s
        """, (reservation_id,))
        res = cur.fetchone()

        if not res:
            result["error"] = f"Reservation {reservation_id} not found"
            logger.error(f"[REALIZER] {result['error']}")
            conn.close()
            return result

        if res["status"] == "Realized":
            result["error"] = f"Reservation {reservation_id} already realized"
            logger.warning(f"[REALIZER] {result['error']}")
            conn.close()
            return result

        # 2. Calculate fees
        gross = Decimal(str(res["total_revenue"])).quantize(Decimal("0.01"))
        # Use actual gross from reservation (more accurate than estimating from net)
        fees = (gross * STRIPE_PCT + STRIPE_FIXED).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        net = (gross - fees).quantize(Decimal("0.01"))

        result["gross_revenue"] = float(gross)
        result["stripe_fees"] = float(fees)

        cabin = res["property_name"]
        checkin = res["check_in"]
        checkout = res["check_out"]
        nights = res["nights"] or (checkout - checkin).days

        logger.info(
            f"[REALIZER] Realizing: {cabin} | "
            f"${gross:,.2f} gross - ${fees:,.2f} fees = ${net:,.2f} net | "
            f"{checkin} to {checkout} ({nights} nights)"
        )

        if dry_run:
            result["success"] = True
            result["dry_run"] = True
            conn.close()
            return result

        # 3. Reverse forecast accruals (if they exist)
        forecasts_reversed = 0
        try:
            from accounting.revenue_bridge import confirm_booking_revenue
            # This reverses forecasts AND posts a simple actual entry.
            # But we want to handle the actual entry ourselves (with fees),
            # so we'll only use it for the reversal part.
            # Actually, let's do the reversal manually to keep the compound JE clean.
            forecasts_reversed = _reverse_forecasts_for_reservation(
                conn, res["property_id"] or cabin,
                checkin, checkout, schema,
            )
            result["forecasts_reversed"] = forecasts_reversed
        except Exception as e:
            logger.warning(f"[REALIZER] Forecast reversal skipped: {e}")

        # 4. Post compound journal entry
        display = cabin.replace("_", " ").title() if cabin else "Unknown Property"
        je_id = f"REAL-{reservation_id}"

        lines = [
            # Dr: Cash received (net of fees)
            LedgerLine(
                account_code=BANK_OPERATING,
                account_name="Bank:Operating",
                debit=net,
                credit=Decimal("0.00"),
                memo=f"Stripe deposit, plaid:{plaid_txn_id}",
            ),
            # Dr: Merchant processing fees
            LedgerLine(
                account_code=MERCHANT_FEES,
                account_name="COGS:Merchant Processing Fees",
                debit=fees,
                credit=Decimal("0.00"),
                memo=f"Stripe fee {STRIPE_PCT * 100}% + ${STRIPE_FIXED}",
            ),
            # Cr: Actual revenue (full gross)
            LedgerLine(
                account_code=ACTUAL_REV,
                account_name="Rental Income:Management Fees",
                debit=Decimal("0.00"),
                credit=gross,
                memo=f"res:{reservation_id} {display} {checkin}-{checkout}",
            ),
        ]

        entry = JournalEntry(
            entry_id=je_id,
            date=deposit_date or date.today(),
            description=(
                f"Revenue realized: {display}, "
                f"{nights} nights, ${gross:,.2f} gross "
                f"(${fees:,.2f} Stripe fees)"
            ),
            lines=lines,
            source_type="revenue_realization",
            source_ref=reservation_id,
            division=schema,
            created_by="revenue_realizer",
            memo=(
                f"plaid_txn:{plaid_txn_id} | "
                f"net:{net} fees:{fees} gross:{gross} | "
                f"forecasts_reversed:{forecasts_reversed}"
            ),
        )

        entry.validate()
        post_journal_entry(entry, schema)

        result["success"] = True
        result["journal_entry_id"] = je_id

        # 5. Update reservation status
        cur.execute("""
            UPDATE fin_reservations
            SET status = 'Realized',
                updated_at = NOW(),
                notes = COALESCE(notes, '') || %s
            WHERE res_id = %s
        """, (
            f"\n[{datetime.now().isoformat()}] Revenue realized: "
            f"JE {je_id}, net ${net}, fees ${fees}, "
            f"forecasts reversed: {forecasts_reversed}",
            reservation_id,
        ))
        conn.commit()

        logger.info(
            f"[REALIZER] SUCCESS: {je_id} | {display} | "
            f"${gross:,.2f} gross → Dr 1000 ${net} + Dr 6020 ${fees} / "
            f"Cr 4000 ${gross} | {forecasts_reversed} forecasts reversed"
        )

    except AccountingError as e:
        logger.error(f"[REALIZER] ACCOUNTING ERROR: {e}")
        result["error"] = str(e)
    except Exception as e:
        logger.error(f"[REALIZER] Failed: {e}")
        result["error"] = str(e)
    finally:
        conn.close()

    return result


# =============================================================================
# 4. FORECAST REVERSAL (per-reservation)
# =============================================================================

def _reverse_forecasts_for_reservation(
    conn, property_identifier: str,
    checkin: date, checkout: date,
    schema: str = SCHEMA,
) -> int:
    """
    Reverse forecast accrual entries for a specific property + date range.
    Called before posting the actual revenue to prevent double-counting.

    Returns the number of forecast entries reversed.
    """
    import sys
    proj_root = str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent)
    if proj_root not in sys.path:
        sys.path.insert(0, proj_root)

    from accounting.models import JournalEntry, LedgerLine
    from accounting.engine import post_journal_entry

    cur = conn.cursor()

    # Normalize property name for matching against source_ref
    normalized = property_identifier.lower().replace(" ", "_").replace("'", "")
    # Use a short prefix for LIKE matching (handles name truncation in entry IDs)
    prefix = normalized[:15]

    cur.execute(f"""
        SELECT DISTINCT je.entry_id, je.entry_date, je.description
        FROM {schema}.journal_entries je
        WHERE je.source_type = 'quantrevenue_forecast'
          AND je.entry_date BETWEEN %s AND %s
          AND je.source_ref LIKE %s
          AND je.is_posted = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM {schema}.journal_entries rev
              WHERE rev.source_ref = 'REVERSAL:' || je.entry_id
          )
    """, (checkin, checkout, f"%{prefix}%"))
    forecasts = cur.fetchall()

    if not forecasts:
        return 0

    reversed_count = 0
    for je in forecasts:
        original_id = je["entry_id"]
        cur.execute(f"""
            SELECT account_code, account_name, debit, credit
            FROM {schema}.general_ledger
            WHERE journal_entry_id = %s
        """, (original_id,))
        lines = cur.fetchall()
        if not lines:
            continue

        reversal_lines = [
            LedgerLine(
                account_code=l["account_code"],
                account_name=l["account_name"],
                debit=Decimal(str(l["credit"])),
                credit=Decimal(str(l["debit"])),
                memo=f"Revenue realized: reversal of {original_id}",
            ) for l in lines
        ]

        reversal = JournalEntry(
            entry_id=f"RREV-{original_id}",
            date=je["entry_date"],
            description=f"Realization reversal: {je['description']}",
            lines=reversal_lines,
            source_type="quantrevenue_reversal",
            source_ref=f"REVERSAL:{original_id}",
            division=schema,
            created_by="revenue_realizer",
            memo="Reversed upon booking confirmation",
        )

        try:
            reversal.validate()
            post_journal_entry(reversal, schema)
            reversed_count += 1
        except Exception as e:
            if "duplicate" not in str(e).lower():
                logger.warning(f"[REALIZER] Reversal failed for {original_id}: {e}")

    return reversed_count


# =============================================================================
# 5. CLARIFICATION REQUEST MANAGEMENT
# =============================================================================

def create_clarification_request(
    match_result: MatchResult,
    deposit_date: str = "",
    vendor: str = "Stripe",
    plaid_txn_id: str = "",
) -> ClarificationRequest:
    """
    Create a clarification request when the agent can't auto-match.
    This gets surfaced in the dashboard for the Sovereign to resolve.
    """
    request = ClarificationRequest(
        request_id=f"CLAR-{uuid.uuid4().hex[:12]}",
        deposit_amount=match_result.deposit_net,
        estimated_gross=match_result.estimated_gross,
        deposit_date=deposit_date,
        vendor=vendor,
        candidates=[
            {
                "res_id": c["res_id"],
                "property_name": c["property_name"],
                "check_in": str(c["check_in"]),
                "check_out": str(c["check_out"]),
                "total_revenue": float(c["total_revenue"]),
                "delta": float(c.get("delta", 0)),
            }
            for c in match_result.matches
        ],
    )

    # Persist to DB
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ops_overrides
                (entity_id, override_type, reason, active, effective_until)
            VALUES (%s, 'clarification_request', %s, TRUE, %s)
            ON CONFLICT DO NOTHING
        """, (
            request.request_id,
            (
                f"Revenue match needed: ${float(request.deposit_amount):,.2f} "
                f"from {vendor} on {deposit_date}. "
                f"Candidates: {len(request.candidates)}. "
                f"plaid_txn:{plaid_txn_id}"
            ),
            (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        ))
        conn.commit()
        conn.close()
        logger.info(
            f"[REALIZER] Clarification request created: {request.request_id} "
            f"(${float(request.deposit_amount):,.2f}, "
            f"{len(request.candidates)} candidates)"
        )
    except Exception as e:
        logger.error(f"[REALIZER] Failed to persist clarification request: {e}")

    return request


# =============================================================================
# 6. THE MAIN PIPELINE — Called from PropertyAgent
# =============================================================================

def process_stripe_deposit(
    plaid_txn: Dict[str, Any],
    schema: str = SCHEMA,
    auto_confirm_threshold: str = "HIGH",
) -> Dict[str, Any]:
    """
    The main entry point. Called by the PropertyAgent when it detects
    a Stripe deposit via Plaid.

    Pipeline:
        1. Extract deposit amount
        2. Run the detective (find_reservation_matches)
        3. HIGH confidence → auto-realize
        4. LOW confidence → create clarification request
        5. ZERO confidence → flag as unforecasted

    Args:
        plaid_txn: Raw Plaid transaction dict
        schema: Target division schema
        auto_confirm_threshold: "HIGH" (auto-confirm only exact matches)
                                or "LOW" (auto-confirm best candidate)

    Returns:
        {"action": "auto_confirmed"|"clarification_requested"|"flagged",
         "match_result": {...}, ...}
    """
    vendor = plaid_txn.get("merchant_name") or plaid_txn.get("name", "Stripe")
    raw_amount = plaid_txn.get("amount", 0)
    # Plaid convention: negative amount = money in (deposit)
    net_deposit = Decimal(str(abs(raw_amount))).quantize(Decimal("0.01"))
    txn_date = plaid_txn.get("date", date.today().isoformat())
    plaid_txn_id = plaid_txn.get("transaction_id", "")

    if isinstance(txn_date, str):
        try:
            dep_date = date.fromisoformat(txn_date)
        except ValueError:
            dep_date = date.today()
    else:
        dep_date = txn_date

    if net_deposit < MIN_DEPOSIT_THRESHOLD:
        return {
            "action": "skipped",
            "reason": f"Below threshold (${net_deposit} < ${MIN_DEPOSIT_THRESHOLD})",
        }

    logger.info(
        f"[REALIZER] Processing Stripe deposit: ${net_deposit:,.2f} "
        f"from {vendor} on {txn_date}"
    )

    # Run the detective
    match_result = find_reservation_matches(net_deposit, dep_date)

    response = {
        "action": None,
        "vendor": vendor,
        "net_deposit": float(net_deposit),
        "estimated_gross": float(match_result.estimated_gross),
        "estimated_fees": float(match_result.estimated_fees),
        "confidence": match_result.confidence,
        "match_count": len(match_result.matches),
        "message": match_result.message,
    }

    if match_result.confidence == "HIGH":
        # Single exact match — auto-confirm
        reservation = match_result.matches[0]
        res_id = reservation["res_id"]

        logger.info(
            f"[REALIZER] HIGH confidence match: {reservation['property_name']} "
            f"(res {res_id}) — auto-confirming"
        )

        realize_result = realize_revenue(
            net_deposit=net_deposit,
            reservation_id=res_id,
            plaid_txn_id=plaid_txn_id,
            deposit_date=dep_date,
            schema=schema,
        )

        response["action"] = "auto_confirmed"
        response["reservation_id"] = res_id
        response["property_name"] = reservation["property_name"]
        response["realize_result"] = realize_result
        match_result.auto_confirmed = True
        match_result.journal_entry_id = realize_result.get("journal_entry_id")

    elif match_result.confidence == "LOW":
        # Multiple candidates — ask the Sovereign
        clarification = create_clarification_request(
            match_result=match_result,
            deposit_date=str(dep_date),
            vendor=vendor,
            plaid_txn_id=plaid_txn_id,
        )

        response["action"] = "clarification_requested"
        response["clarification_id"] = clarification.request_id
        response["candidates"] = [
            {
                "res_id": c["res_id"],
                "property_name": c["property_name"],
                "total_revenue": float(c["total_revenue"]),
            }
            for c in match_result.matches[:5]
        ]

    else:
        # Zero matches — unforecasted windfall
        clarification = create_clarification_request(
            match_result=match_result,
            deposit_date=str(dep_date),
            vendor=vendor,
            plaid_txn_id=plaid_txn_id,
        )

        response["action"] = "flagged"
        response["clarification_id"] = clarification.request_id
        response["flag_reason"] = "Unforecasted deposit — no matching reservation found"

    return response


def resolve_clarification(
    clarification_id: str,
    reservation_id: str,
    plaid_txn_id: str = "",
    deposit_date: Optional[date] = None,
    schema: str = SCHEMA,
) -> Dict[str, Any]:
    """
    Called when the Sovereign resolves a clarification request.
    This is the "You reply: Booking #1042" step.

    Looks up the original deposit amount from the clarification,
    then calls realize_revenue().
    """
    conn = _connect()
    try:
        cur = conn.cursor()

        # Get the clarification details
        cur.execute("""
            SELECT entity_id, reason
            FROM ops_overrides
            WHERE entity_id = %s AND override_type = 'clarification_request'
        """, (clarification_id,))
        row = cur.fetchone()

        if not row:
            return {"success": False, "error": f"Clarification {clarification_id} not found"}

        # Extract deposit amount from reason text
        import re
        amount_match = re.search(r'\$([0-9,.]+)', row["reason"])
        net_deposit = Decimal(
            amount_match.group(1).replace(",", "")
        ) if amount_match else Decimal("0")

        # Mark clarification as resolved
        cur.execute("""
            UPDATE ops_overrides
            SET active = FALSE,
                reason = reason || %s
            WHERE entity_id = %s
        """, (
            f" | RESOLVED: res_id={reservation_id} at {datetime.now().isoformat()}",
            clarification_id,
        ))
        conn.commit()
        conn.close()

        # Now realize the revenue
        if net_deposit > 0:
            return realize_revenue(
                net_deposit=net_deposit,
                reservation_id=reservation_id,
                plaid_txn_id=plaid_txn_id,
                deposit_date=deposit_date,
                schema=schema,
            )
        else:
            return {
                "success": False,
                "error": "Could not extract deposit amount from clarification",
            }

    except Exception as e:
        logger.error(f"[REALIZER] Resolve clarification failed: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if conn and not conn.closed:
            conn.close()


# =============================================================================
# DETECTION HELPERS
# =============================================================================

def is_stripe_deposit(plaid_txn: Dict[str, Any]) -> bool:
    """
    Detect if a Plaid transaction is a Stripe deposit.

    Checks:
        - Amount is negative (Plaid: negative = money in)
        - Vendor/name contains "Stripe" or "STRIPE"
        - Category includes "Transfer" or "Deposit"
    """
    amount = plaid_txn.get("amount", 0)
    if amount >= 0:
        return False  # Not a deposit (Plaid: positive = outflow)

    name = (
        plaid_txn.get("merchant_name") or plaid_txn.get("name", "")
    ).lower()

    if "stripe" not in name:
        return False

    # Check categories if available
    categories = plaid_txn.get("category", [])
    if isinstance(categories, list):
        cat_str = " ".join(c.lower() for c in categories)
        if any(kw in cat_str for kw in ("transfer", "deposit", "payment")):
            return True

    # Even without category match, "Stripe" in vendor name + deposit = likely
    return True


# =============================================================================
# DATABASE HELPER
# =============================================================================

def _connect():
    import psycopg2
    import psycopg2.extras
    from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
