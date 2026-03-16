"""
Sovereign Wealth Swarm API Bridge

Accepts OCR'd receipt text, routes it through the three-agent LangGraph
Wealth Swarm (Extractor -> Tax Strategist -> Compliance Inspector), and
publishes the enriched, tax-categorized payload to the Redpanda event bus.

Mount: /api/wealth
"""

import os
import sys
import asyncio
import logging
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# The wealth swarm graph lives at the project root (src/) and depends on the
# root config.py for NIM inference routing.  Ensure the project root is
# importable from the FGP backend process.
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.core.event_publisher import EventPublisher
from src.wealth_swarm_graph import wealth_swarm

log = logging.getLogger("wealth_api")

router = APIRouter(tags=["Wealth & Development"])


# ---------------------------------------------------------------------------
# Pydantic request / response schemas
# ---------------------------------------------------------------------------

class ReceiptSubmission(BaseModel):
    receipt_text: str = Field(..., min_length=1, max_length=50000)
    image_metadata: Optional[dict] = None


class ReceiptProcessedResponse(BaseModel):
    status: str
    vendor: str
    total: float
    compliance_warnings: int
    tax_strategy: str


class SwarmRejectedResponse(BaseModel):
    status: str = "rejected"
    audit_trail: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/receipts — Cognitive Swarm receipt processor
# ---------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/receipts",
    response_model=ReceiptProcessedResponse,
    responses={
        200: {"description": "Receipt processed and staged on the Redpanda ledger"},
        400: {"description": "Empty or invalid receipt text"},
        500: {"description": "Swarm execution failure"},
        502: {"description": "Message broker unavailable"},
    },
)
async def process_project_receipt(project_id: str, payload: ReceiptSubmission):
    """Route raw receipt text through the Cognitive Swarm and publish to the ledger."""
    log.info("Initiating Wealth Swarm for project %s", project_id)

    initial_state = {
        "project_id": project_id,
        "receipt_text": payload.receipt_text,
        "extracted_data": {},
        "tax_strategy": "",
        "compliance_flags": [],
        "ready_for_ledger": False,
        "audit_trail": [f"INIT: Receipt submitted for project {project_id}"],
    }

    try:
        final_state = await asyncio.to_thread(wealth_swarm.invoke, initial_state)
    except Exception as e:
        log.error("Wealth Swarm execution failed for project %s: %s", project_id, e)
        raise HTTPException(
            status_code=500,
            detail="Cognitive pipeline failure during receipt processing.",
        )

    if not final_state.get("ready_for_ledger"):
        log.warning("Swarm rejected ledger entry for project %s.", project_id)
        return SwarmRejectedResponse(
            audit_trail=final_state.get("audit_trail", []),
        )

    extracted = final_state.get("extracted_data", {})

    event_payload = {
        "project_id": project_id,
        "vendor": extracted.get("vendor", "UNKNOWN"),
        "total_amount": float(Decimal(str(extracted.get("total", 0.0)))),
        "categories": extracted.get("categories", []),
        "tax_classification": final_state.get("tax_strategy", "Unclassified"),
        "compliance_flags": final_state.get("compliance_flags", []),
        "audit_trail": final_state.get("audit_trail", []),
    }

    try:
        await EventPublisher.publish(
            topic="development.expenses.logged",
            payload=event_payload,
            key=project_id,
        )
        log.info("Published expense event for project %s (vendor=%s).", project_id, event_payload["vendor"])
    except Exception as e:
        log.error("Failed to publish to Redpanda for project %s: %s", project_id, e)
        raise HTTPException(status_code=502, detail="Message broker unavailable.")

    return ReceiptProcessedResponse(
        status="processed_and_staged",
        vendor=event_payload["vendor"],
        total=event_payload["total_amount"],
        compliance_warnings=len(event_payload["compliance_flags"]),
        tax_strategy=event_payload["tax_classification"],
    )
