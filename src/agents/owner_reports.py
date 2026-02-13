"""
OWNER REPORTS AGENT — Strangler Fig Replacement for Streamline GetOwnerStatement
================================================================================
Fortress Prime | Sector S01 (CROG) — Cabin Rentals of Georgia

This agent replaces the legacy Streamline VRS owner statement flow with a
fully sovereign, local-only implementation. No data leaves the cluster.

Data Sources (all local):
    fin_owner_balances        — Per-property revenue, mgmt fee, owner payout
    fin_reservations          — Shadow bookings with nightly rates
    division_b.trust_ledger   — Trust fund deposits, payouts, refunds
    trust_balance             — Owner vs operating funds per property
    ops_properties            — Property metadata (bedrooms, names)

OODA Pattern (Constitution Article III):
    OBSERVE  — Query fin_owner_balances + trust_ledger for the property/period
    ORIENT   — Cross-reference revenue vs trust, detect anomalies
    DECIDE   — R1 audits the statement (TITAN mode) or auto-approve (SWARM mode)
    ACT      — Generate the owner statement (JSON + optional PDF)
    POST-MORTEM — Persist audit record to system_post_mortems

Feature Flag:
    config.FEATURE_FLAGS["owner_reports"] must be True to route here.
    When False, traffic falls through to legacy Streamline bridge.

Usage:
    # As a standalone script
    python3 -m src.agents.owner_reports --property-id 12345

    # As an API endpoint (mounted in gateway)
    GET /v1/crog/owners/{property_id}/statement?period_start=2026-01-01&period_end=2026-01-31

Governing Documents:
    CONSTITUTION.md  — Article I (Data Sovereignty), Article III (Self-Healing)
    REQUIREMENTS.md  — Section 3.2 (Strangler Fig), Section 3.4 (Pydantic)
    docs/STRANGLER_FIG_AUDIT.md — The audit that mandated this agent
"""

from __future__ import annotations

import os
import sys
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("agents.owner_reports")


# =============================================================================
# I. PYDANTIC MODELS (REQUIREMENTS.md Section 3.4)
# =============================================================================

class ReservationLine(BaseModel):
    """A single reservation contributing to the owner statement."""
    res_id: str
    check_in: date
    check_out: date
    nights: int = Field(..., gt=0, le=30)
    nightly_rate: float = Field(..., gt=0, le=100_000)
    base_rent: float = Field(..., ge=0)
    taxes: float = Field(..., ge=0)
    fees: float = Field(..., ge=0)
    total_revenue: float = Field(..., ge=0)
    confidence: str = Field(default="high")
    source: str = Field(default="shadow_calendar")


class RevenueBlock(BaseModel):
    """Revenue section of the owner statement."""
    gross_rent: float = Field(..., ge=0)
    taxes_collected: float = Field(..., ge=0)
    cleaning_fees: float = Field(..., ge=0)
    total_collected: float = Field(..., ge=0)


class DeductionBlock(BaseModel):
    """Deductions section of the owner statement."""
    mgmt_fee_pct: float = Field(..., ge=0, le=100)
    mgmt_fee_amount: float = Field(..., ge=0)
    maintenance: float = Field(default=0.0, ge=0)
    total_deductions: float = Field(..., ge=0)


class TrustBalanceBlock(BaseModel):
    """Trust balance section of the owner statement."""
    owner_funds: float = Field(default=0.0)
    operating_funds: float = Field(default=0.0)
    escrow: float = Field(default=0.0)


class AuditBlock(BaseModel):
    """R1 audit results (populated in TITAN mode)."""
    verified_by: str = Field(default="auto")
    confidence: float = Field(default=0.0, ge=0, le=1)
    discrepancies: list[str] = Field(default_factory=list)
    audited_at: Optional[datetime] = None


class OwnerStatement(BaseModel):
    """
    Complete owner statement — the Strangler Fig replacement for
    Streamline's GetOwnerStatement.

    Classification: SOVEREIGN (Constitution Article I)
    This data NEVER leaves the local cluster.
    """
    property_id: str = Field(..., min_length=1)
    property_name: str = Field(..., min_length=1)
    owner_name: str = Field(default="(from fin_owner_balances)")
    period: dict = Field(...)                  # {"start": date, "end": date}
    revenue: RevenueBlock
    deductions: DeductionBlock
    owner_payout: float = Field(..., ge=0)
    trust_balance: TrustBalanceBlock
    reservations: list[ReservationLine] = Field(default_factory=list)
    audit: AuditBlock = Field(default_factory=AuditBlock)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = Field(default="fortress_local")
    classification: str = Field(default="SOVEREIGN")

    @field_validator("classification")
    @classmethod
    def must_be_sovereign(cls, v: str) -> str:
        """Owner statements are always SOVEREIGN data."""
        if v != "SOVEREIGN":
            raise ValueError("Owner statements MUST be classified as SOVEREIGN")
        return v


# =============================================================================
# II. DATA LAYER (Local Postgres — Zero Cloud)
# =============================================================================

def _get_db():
    """Get a database connection using config.py topology."""
    import psycopg2
    import psycopg2.extras
    try:
        from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
    except ImportError:
        DB_HOST = os.getenv("DB_HOST", "192.168.0.100")
        DB_NAME = os.getenv("DB_NAME", "fortress_db")
        DB_USER = os.getenv("DB_USER", "miner_bot")
        DB_PASS = os.getenv("DB_PASS", "")
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def fetch_owner_balance(property_id: str) -> Optional[dict]:
    """Fetch the owner balance record for a property."""
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT property_id, property_name, owner_name, bedrooms,
               estimated_rate, total_booked_nights, gross_revenue,
               mgmt_fee_pct, mgmt_fee_amount, owner_payout, last_calculated
        FROM fin_owner_balances
        WHERE property_id = %s
    """, (property_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def fetch_reservations(property_id: str, start: date, end: date) -> list[dict]:
    """Fetch shadow reservations for a property within a date range."""
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT res_id, property_id, property_name, check_in, check_out,
               nights, nightly_rate, base_rent, taxes, fees, total_revenue,
               confidence, source
        FROM fin_reservations
        WHERE property_id = %s
          AND check_in >= %s
          AND check_out <= %s
        ORDER BY check_in
    """, (property_id, start, end))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_trust_balance(property_id: str) -> Optional[dict]:
    """Fetch trust balance for a property (CF-04 Audit Ledger)."""
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT property_id, owner_funds, operating_funds,
               escrow_funds, security_deps, last_updated
        FROM trust_balance
        WHERE property_id = %s
    """, (property_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


# =============================================================================
# III. OODA CYCLE FUNCTIONS
# =============================================================================

def observe(state: dict) -> dict:
    """
    OBSERVE: Gather all local data for the owner statement.
    Zero cloud calls. All data from fortress_db.
    """
    from datetime import date as dt_date

    property_id = state.get("query", "").strip()
    period_start = state.get("_period_start", dt_date.today().replace(day=1))
    period_end = state.get("_period_end", dt_date.today())

    # Fetch from local database
    balance = fetch_owner_balance(property_id)
    reservations = fetch_reservations(property_id, period_start, period_end)
    trust = fetch_trust_balance(property_id)

    state["observation"] = (
        f"Property {property_id}: "
        f"balance={'found' if balance else 'MISSING'}, "
        f"reservations={len(reservations)}, "
        f"trust={'found' if trust else 'MISSING'}"
    )
    state["_balance"] = balance
    state["_reservations"] = reservations
    state["_trust"] = trust
    state["_period_start"] = period_start
    state["_period_end"] = period_end

    state["audit_trail"].append(
        f"[{datetime.now(timezone.utc).isoformat()}] OBSERVE: "
        f"Fetched {len(reservations)} reservations, "
        f"balance={'yes' if balance else 'no'}, trust={'yes' if trust else 'no'}"
    )
    return state


def orient(state: dict) -> dict:
    """
    ORIENT: Cross-reference revenue vs trust balance, detect anomalies.
    """
    balance = state.get("_balance")
    trust = state.get("_trust")
    reservations = state.get("_reservations", [])
    anomalies = []

    if not balance:
        anomalies.append("CRITICAL: No owner balance found for this property")
        state["confidence"] = 0.1
    else:
        # Cross-check: sum of reservation revenue vs reported gross
        res_gross = sum(float(r.get("base_rent", 0)) for r in reservations)
        bal_gross = float(balance.get("gross_revenue", 0))

        if bal_gross > 0 and abs(res_gross - bal_gross) / bal_gross > 0.1:
            anomalies.append(
                f"Revenue mismatch: reservations sum ${res_gross:,.2f} "
                f"vs balance reports ${bal_gross:,.2f} "
                f"(delta: {abs(res_gross - bal_gross) / bal_gross * 100:.1f}%)"
            )

        # Cross-check: trust balance vs owner payout
        if trust:
            owner_funds = float(trust.get("owner_funds", 0))
            owner_payout = float(balance.get("owner_payout", 0))
            if owner_payout > 0 and abs(owner_funds - owner_payout) / owner_payout > 0.2:
                anomalies.append(
                    f"Trust imbalance: trust shows ${owner_funds:,.2f} owner funds "
                    f"vs calculated payout ${owner_payout:,.2f}"
                )

    state["orientation"] = (
        f"Anomalies detected: {len(anomalies)}. "
        + (" | ".join(anomalies) if anomalies else "All checks passed.")
    )
    state["_anomalies"] = anomalies

    if not anomalies and balance:
        state["confidence"] = 0.9
    elif anomalies and balance:
        state["confidence"] = 0.6

    state["audit_trail"].append(
        f"[{datetime.now(timezone.utc).isoformat()}] ORIENT: "
        f"{len(anomalies)} anomalies, confidence={state['confidence']:.2f}"
    )
    return state


def decide(state: dict) -> dict:
    """
    DECIDE: In TITAN mode, submit to R1 for deep audit.
    In SWARM mode, auto-approve if confidence > 0.7.
    """
    defcon = os.getenv("FORTRESS_DEFCON", "SWARM").upper()
    confidence = state.get("confidence", 0.0)
    anomalies = state.get("_anomalies", [])

    if defcon == "TITAN" and anomalies:
        # Deep reasoning: R1 audits the anomalies
        try:
            from config import get_inference_client
            client, model = get_inference_client("TITAN")

            prompt = (
                "You are the Sovereign Auditor for Cabin Rentals of Georgia.\n"
                "Review the following owner statement anomalies and provide:\n"
                "1. Root cause analysis for each anomaly\n"
                "2. Recommended corrective action\n"
                "3. Whether the statement should be APPROVED or HELD\n\n"
                f"Anomalies:\n" + "\n".join(f"- {a}" for a in anomalies) + "\n\n"
                f"Property: {state.get('query')}\n"
                f"Observation: {state.get('observation')}\n"
            )

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
                temperature=0.1,
            )
            r1_decision = response.choices[0].message.content
            state["decision"] = f"[R1 Audit] {r1_decision}"

        except Exception as e:
            logger.warning(f"R1 audit failed (falling back to auto): {e}")
            state["decision"] = (
                f"[Auto-Decide] R1 unavailable. "
                f"Confidence={confidence:.2f}. "
                f"{'APPROVED' if confidence > 0.7 else 'HELD for manual review'}."
            )
    else:
        # SWARM mode or no anomalies: auto-decide
        if confidence > 0.7:
            state["decision"] = f"[Auto-Decide] APPROVED. Confidence={confidence:.2f}."
        else:
            state["decision"] = (
                f"[Auto-Decide] HELD for manual review. "
                f"Confidence={confidence:.2f}. Anomalies: {len(anomalies)}."
            )

    state["audit_trail"].append(
        f"[{datetime.now(timezone.utc).isoformat()}] DECIDE: "
        f"Mode={defcon}, result={'APPROVED' if 'APPROVED' in state['decision'] else 'HELD'}"
    )
    return state


def act(state: dict) -> dict:
    """
    ACT: Generate the OwnerStatement model from gathered data.
    This is the deliverable — a complete, Pydantic-validated statement.
    """
    balance = state.get("_balance")
    reservations = state.get("_reservations", [])
    trust = state.get("_trust")
    period_start = state.get("_period_start", date.today().replace(day=1))
    period_end = state.get("_period_end", date.today())

    if not balance:
        state["action_result"] = (
            "FAILED: No owner balance data found. Cannot generate statement."
        )
        state["_statement"] = None
        return state

    try:
        # Build reservation lines
        res_lines = []
        for r in reservations:
            res_lines.append(ReservationLine(
                res_id=r["res_id"],
                check_in=r["check_in"],
                check_out=r["check_out"],
                nights=r["nights"],
                nightly_rate=float(r["nightly_rate"]),
                base_rent=float(r["base_rent"]),
                taxes=float(r["taxes"]),
                fees=float(r["fees"]),
                total_revenue=float(r["total_revenue"]),
                confidence=r.get("confidence", "high"),
                source=r.get("source", "shadow_calendar"),
            ))

        gross = float(balance["gross_revenue"])
        mgmt_pct = float(balance["mgmt_fee_pct"])
        mgmt_amt = float(balance["mgmt_fee_amount"])
        payout = float(balance["owner_payout"])

        taxes_total = sum(float(r.get("taxes", 0)) for r in reservations)
        fees_total = sum(float(r.get("fees", 0)) for r in reservations)

        statement = OwnerStatement(
            property_id=balance["property_id"],
            property_name=balance["property_name"],
            owner_name=balance.get("owner_name", "(not set)"),
            period={"start": str(period_start), "end": str(period_end)},
            revenue=RevenueBlock(
                gross_rent=gross,
                taxes_collected=taxes_total,
                cleaning_fees=fees_total,
                total_collected=gross + taxes_total + fees_total,
            ),
            deductions=DeductionBlock(
                mgmt_fee_pct=mgmt_pct,
                mgmt_fee_amount=mgmt_amt,
                maintenance=0.0,
                total_deductions=mgmt_amt,
            ),
            owner_payout=payout,
            trust_balance=TrustBalanceBlock(
                owner_funds=float(trust["owner_funds"]) if trust else 0.0,
                operating_funds=float(trust["operating_funds"]) if trust else 0.0,
                escrow=float(trust.get("escrow_funds", 0)) if trust else 0.0,
            ),
            reservations=res_lines,
            audit=AuditBlock(
                verified_by="sovereign_r1" if "R1" in state.get("decision", "") else "auto",
                confidence=state.get("confidence", 0.0),
                discrepancies=state.get("_anomalies", []),
                audited_at=datetime.now(timezone.utc),
            ),
        )

        state["_statement"] = statement
        state["action_result"] = (
            f"SUCCESS: Owner statement generated for {balance['property_name']}. "
            f"Payout: ${payout:,.2f}. Reservations: {len(res_lines)}."
        )

    except Exception as e:
        state["action_result"] = f"FAILED: {e}"
        state["_statement"] = None
        logger.error(f"Owner statement generation failed: {e}")

    state["audit_trail"].append(
        f"[{datetime.now(timezone.utc).isoformat()}] ACT: {state['action_result'][:100]}"
    )
    return state


# =============================================================================
# IV. AGENT ASSEMBLY (LangGraph OODA)
# =============================================================================

def build_owner_report_agent():
    """
    Build the Owner Reports OODA agent.

    Returns a compiled LangGraph agent ready for .invoke().
    """
    from src.sovereign_ooda import build_ooda_graph
    graph = build_ooda_graph(
        observe_fn=observe,
        orient_fn=orient,
        decide_fn=decide,
        act_fn=act,
    )
    return graph.compile()


def generate_owner_statement(
    property_id: str,
    period_start: date = None,
    period_end: date = None,
) -> Optional[OwnerStatement]:
    """
    High-level API: generate an owner statement for a property.

    This is the function called by the FastAPI endpoint and CLI.

    Args:
        property_id: The property ID to generate a statement for.
        period_start: Start of the reporting period (default: 1st of current month).
        period_end: End of the reporting period (default: today).

    Returns:
        An OwnerStatement Pydantic model, or None if generation failed.
    """
    from src.sovereign_ooda import make_initial_state

    if period_start is None:
        period_start = date.today().replace(day=1)
    if period_end is None:
        period_end = date.today()

    # Build and run the OODA agent
    agent = build_owner_report_agent()
    initial = make_initial_state(sector="crog", query=property_id)
    initial["_period_start"] = period_start
    initial["_period_end"] = period_end

    result = agent.invoke(initial)

    return result.get("_statement")


# =============================================================================
# V. CLI ENTRY POINT
# =============================================================================

def main():
    """CLI: Generate an owner statement for a specific property."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Owner Reports Agent — Sovereign owner statement generator"
    )
    parser.add_argument("--property-id", required=True, help="Property ID")
    parser.add_argument("--period-start", type=date.fromisoformat, default=None)
    parser.add_argument("--period-end", type=date.fromisoformat, default=None)
    parser.add_argument("--format", choices=["json", "summary"], default="summary")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    print("=" * 65)
    print("  OWNER REPORTS AGENT — SOVEREIGN STATEMENT GENERATOR")
    print(f"  Property: {args.property_id}")
    print(f"  Classification: SOVEREIGN (zero cloud)")
    print("=" * 65)

    statement = generate_owner_statement(
        property_id=args.property_id,
        period_start=args.period_start,
        period_end=args.period_end,
    )

    if not statement:
        print("\n  FAILED: Could not generate owner statement.")
        print("  Check that fin_owner_balances has data for this property.")
        sys.exit(1)

    if args.format == "json":
        print(json.dumps(statement.model_dump(), indent=2, default=str))
    else:
        print(f"\n  Property:       {statement.property_name}")
        print(f"  Owner:          {statement.owner_name}")
        print(f"  Period:         {statement.period['start']} to {statement.period['end']}")
        print()
        print(f"  Gross Rent:     ${statement.revenue.gross_rent:>12,.2f}")
        print(f"  Taxes:          ${statement.revenue.taxes_collected:>12,.2f}")
        print(f"  Fees:           ${statement.revenue.cleaning_fees:>12,.2f}")
        print(f"  Total:          ${statement.revenue.total_collected:>12,.2f}")
        print()
        print(f"  Mgmt Fee ({statement.deductions.mgmt_fee_pct}%): ${statement.deductions.mgmt_fee_amount:>12,.2f}")
        print(f"  OWNER PAYOUT:   ${statement.owner_payout:>12,.2f}")
        print()
        print(f"  Trust Balance:  owner=${statement.trust_balance.owner_funds:,.2f} "
              f"/ ops=${statement.trust_balance.operating_funds:,.2f}")
        print(f"  Reservations:   {len(statement.reservations)}")
        print(f"  Audit:          {statement.audit.verified_by} "
              f"(confidence={statement.audit.confidence:.2f})")
        if statement.audit.discrepancies:
            print(f"  Discrepancies:")
            for d in statement.audit.discrepancies:
                print(f"    - {d}")
        print()
        print(f"  Source:          {statement.source}")
        print(f"  Classification:  {statement.classification}")
    print()


if __name__ == "__main__":
    main()
