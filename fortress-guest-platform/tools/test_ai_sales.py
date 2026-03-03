#!/usr/bin/env python3
"""
Pre-Flight Validation — Agentic Sales Copywriter (Rule 7)

Creates a test Lead with a realistic guest inquiry, runs it through
the full quoting pipeline (pricing math + AI sales copywriter), and
prints the AI-generated email draft to the terminal.

Uses FastAPI TestClient (no running server required).
"""
import sys
import json
from pathlib import Path
from uuid import uuid4

_root = str(Path(__file__).resolve().parents[1])
if _root not in sys.path:
    sys.path.insert(0, _root)

from backend.core.database import SyncSessionLocal
from backend.models.lead import Lead
from backend.models.property import Property
from backend.services.lead_sync import sanitize_phone, sanitize_email

SEP = "=" * 72


def run_test():
    db = SyncSessionLocal()
    try:
        lead = Lead(
            streamline_lead_id=f"AISALES-{uuid4().hex[:8].upper()}",
            guest_name="David Mitchell",
            email=sanitize_email("  DAVID.MITCHELL@gmail.com  "),
            phone=sanitize_phone("(678) 555-4412"),
            guest_message=(
                "Hi, looking for a weekend getaway for my wife's 40th birthday. "
                "Needs to have a nice view and a hot tub. Are there any good "
                "restaurants nearby?"
            ),
            source="test_ai_sales",
            status="new",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        lead_id = str(lead.id)

        props = db.query(Property).filter(Property.is_active.is_(True)).limit(2).all()
        if len(props) < 2:
            print("ERROR: Need at least 2 active properties")
            return
        prop_ids = [str(p.id) for p in props]
    finally:
        db.close()

    print(SEP)
    print("AGENTIC SALES COPYWRITER TEST")
    print(SEP)
    print(f"  Guest: {lead.guest_name}")
    print(f"  Inquiry: {lead.guest_message}")
    print(f"  Properties: {', '.join(p.name for p in props)}")
    print(f"  Dates: 2026-10-10 to 2026-10-14 (4 nights)")
    print(SEP)
    print()

    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.core.security import create_access_token

    token = create_access_token(user_id="test-operator", role="operator", email="test@crog.com")
    headers = {"Authorization": f"Bearer {token}"}

    client = TestClient(app)
    payload = {
        "property_ids": prop_ids,
        "check_in_date": "2026-10-10",
        "check_out_date": "2026-10-14",
    }

    print("Calling POST /api/leads/{lead_id}/quotes/build ...")
    print("(This may take 15-60s depending on the LLM ...)")
    print()

    resp = client.post(f"/api/leads/{lead_id}/quotes/build", json=payload, headers=headers)

    print(f"HTTP Status: {resp.status_code}")
    print()

    if resp.status_code != 200:
        print(f"ERROR: {resp.text}")
        _cleanup(lead_id)
        return

    data = resp.json()

    # ── Print pricing summary ──
    print(SEP)
    print("PRICING SUMMARY")
    print(SEP)
    for opt in data.get("options", []):
        print(f"  {opt['property_name']} ({opt['bedrooms']}BR) — "
              f"{opt['nights']} nights — ${opt['total_price']} total")
    print()

    # ── Print the AI-drafted email ──
    print(SEP)
    print(f"AI SALES EMAIL DRAFT  (model: {data.get('ai_draft_model', 'unknown')})")
    print(SEP)
    email_body = data.get("ai_drafted_email_body")
    if email_body:
        print(email_body)
    else:
        print("[No email draft was generated]")
    print()

    # ── Cleanup ──
    _cleanup(lead_id)

    print(SEP)
    print("AGENTIC COPYWRITER ONLINE")


def _cleanup(lead_id: str):
    from uuid import UUID
    db = SyncSessionLocal()
    try:
        lead = db.query(Lead).filter(Lead.id == UUID(lead_id)).first()
        if lead:
            db.delete(lead)
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    run_test()
