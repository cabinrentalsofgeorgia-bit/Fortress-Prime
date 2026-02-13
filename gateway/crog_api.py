# CROG API - Flagship interface for Next.js developer
# Mounted at /v1/crog
#
# Strangler Fig Pattern (REQUIREMENTS.md Section 3.2):
#   - owner_reports:  FF_OWNER_REPORTS  → src/agents/owner_reports.py
#   - guest_comms:    FF_GUEST_COMMS    → src/agents/guest_comms.py
# See docs/STRANGLER_FIG_AUDIT.md and docs/STRANGLER_FIG_GUEST_COMMS.md

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Query, Depends
from gateway.db import get_pool
from gateway.auth import require_auth, require_role

logger = logging.getLogger("gateway.crog_api")

router = APIRouter(tags=["CROG"])


@router.get("/properties/{property_id}/pricing")
def get_property_pricing(property_id: str):
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT property_id, internal_name, address FROM ops_properties WHERE property_id = %s",
            (property_id,),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(404, detail="Property not found")
        return {
            "property_id": row[0],
            "internal_name": row[1],
            "address": row[2],
            "pricing": {"endpoint": "/v1/quant/quote", "note": "Use POST /v1/quant/quote for rates"},
        }
    finally:
        pool.putconn(conn)


@router.get("/calendar/availability")
def get_calendar_availability(property_id: str = None, from_date: str = None, to_date: str = None):
    return {
        "message": "Wire to groundskeeper_shadow or Streamline for full calendar.",
        "property_id": property_id,
        "from": from_date,
        "to": to_date,
        "availability": [],
    }


# =============================================================================
# OWNER REPORTS — Strangler Fig Endpoint (REQUIREMENTS.md Section 3.2)
# =============================================================================
# Feature flag FF_OWNER_REPORTS controls whether this routes to the new
# local agent or falls through to legacy Streamline.
# Classification: SOVEREIGN — this endpoint returns financial data that
# NEVER leaves the cluster (Constitution Article I).

@router.get(
    "/owners/{property_id}/statement",
    dependencies=[Depends(require_role("admin"))],
    summary="Owner Statement (Sovereign — zero cloud)",
    description=(
        "Generate an owner statement for a property. "
        "Data classification: SOVEREIGN. "
        "Requires admin role. "
        "Uses local data only (fin_owner_balances, trust_ledger, fin_reservations)."
    ),
)
def get_owner_statement(
    property_id: str,
    period_start: date = Query(default=None, description="Start of period (YYYY-MM-DD)"),
    period_end: date = Query(default=None, description="End of period (YYYY-MM-DD)"),
    user: dict = Depends(require_auth),
):
    """
    Strangler Fig: Owner Reports Agent.

    When FF_OWNER_REPORTS is True → routes to local OODA agent.
    When FF_OWNER_REPORTS is False → returns a 501 pointing to legacy Streamline.
    """
    try:
        from config import FEATURE_FLAGS
    except ImportError:
        FEATURE_FLAGS = {"owner_reports": False}

    if not FEATURE_FLAGS.get("owner_reports", False):
        # Legacy path — not yet migrated
        raise HTTPException(
            status_code=501,
            detail={
                "message": "Owner reports not yet migrated from Streamline VRS",
                "legacy_method": "GetOwnerStatement via src/bridges/streamline_total_recall.py",
                "migration_status": "Phase 1 — agent built, pending parallel validation",
                "feature_flag": "FF_OWNER_REPORTS=true to enable",
            },
        )

    # Sovereign path — local OODA agent
    try:
        from src.agents.owner_reports import generate_owner_statement

        statement = generate_owner_statement(
            property_id=property_id,
            period_start=period_start,
            period_end=period_end,
        )

        if not statement:
            raise HTTPException(
                status_code=404,
                detail=f"No owner balance data found for property {property_id}",
            )

        return statement.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Owner reports agent failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Owner reports agent failed",
                "error": str(e),
                "fallback": "Use legacy: GetOwnerStatement via Streamline bridge",
            },
        )


# =============================================================================
# GUEST COMMS — Strangler Fig Endpoint (REQUIREMENTS.md Section 3.2)
# =============================================================================
# Feature flag FF_GUEST_COMMS controls whether this routes to the new
# local OODA agent or returns a 501.
# Classification: RESTRICTED — contains guest email text (PII).
# This endpoint NEVER leaves the cluster (Constitution Article I).

@router.post(
    "/guests/reply",
    dependencies=[Depends(require_role("operator"))],
    summary="Guest Reply Agent (OODA — zero cloud)",
    description=(
        "Generate an AI draft reply to a guest email. "
        "Data classification: RESTRICTED (guest PII). "
        "Requires operator role or above. "
        "Uses local inference only (Ollama SWARM or R1 TITAN). "
        "NEVER auto-sends — drafts only."
    ),
)
def post_guest_reply(
    request: dict,
    user: dict = Depends(require_auth),
):
    """
    Strangler Fig: Guest Comms Agent.

    Wraps the existing guest_reply_engine in the OODA Reflection Loop.
    Adds guest lead enrichment, audit trail, and optional R1 quality review.

    Request body:
        {
            "cabin_slug": "rolling_river",
            "guest_email": "Can I charge my Tesla at the cabin?",
            "guest_email_address": "guest@example.com",  (optional — for history lookup)
            "model_override": null,
            "dry_run": false
        }

    When FF_GUEST_COMMS is True → routes to local OODA agent.
    When FF_GUEST_COMMS is False → returns 501.
    """
    try:
        from config import FEATURE_FLAGS
    except ImportError:
        FEATURE_FLAGS = {"guest_comms": False}

    if not FEATURE_FLAGS.get("guest_comms", False):
        raise HTTPException(
            status_code=501,
            detail={
                "message": "Guest comms not yet migrated — use gmail_watcher.py directly",
                "legacy_tool": "python -m src.gmail_watcher --cabin <slug>",
                "migration_status": "Phase 1 — OODA agent built, pending parallel validation",
                "feature_flag": "FF_GUEST_COMMS=true to enable",
            },
        )

    # Validate required fields
    cabin_slug = request.get("cabin_slug")
    guest_email = request.get("guest_email")
    if not cabin_slug or not guest_email:
        raise HTTPException(
            status_code=422,
            detail="cabin_slug and guest_email are required",
        )

    try:
        from src.agents.guest_comms import generate_guest_reply

        response = generate_guest_reply(
            cabin_slug=cabin_slug,
            guest_email=guest_email,
            guest_email_address=request.get("guest_email_address"),
            model_override=request.get("model_override"),
            dry_run=request.get("dry_run", False),
        )

        return response.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Guest comms agent failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Guest comms agent failed",
                "error": str(e),
                "fallback": "Use: python -m src.gmail_watcher --cabin <slug>",
            },
        )
