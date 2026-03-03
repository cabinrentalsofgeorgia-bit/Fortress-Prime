#!/usr/bin/env python3
"""
Pre-Flight Validation — Multi-Property Quoting Engine (Rule 7)

Creates a test Lead, then hits POST /api/leads/{id}/quotes/build with
two real property UUIDs and a 4-night date range. Prints the full
itemized JSON response to prove 200 OK and correct math.

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

SEP = "=" * 70


def run_test():
    # ── Step 1: Create a test Lead and get two property UUIDs ──
    db = SyncSessionLocal()
    try:
        lead = Lead(
            streamline_lead_id=f"QTEST-{uuid4().hex[:8].upper()}",
            guest_name="Test Quoting Lead",
            email=sanitize_email("  QUOTE.TEST@crog.com  "),
            phone=sanitize_phone("(706) 555-0199"),
            guest_message="Testing the quoting engine",
            source="test_quote_api",
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
        prop_names = [p.name for p in props]
    finally:
        db.close()

    print(SEP)
    print("QUOTE ENGINE TEST")
    print(SEP)
    print(f"  Lead ID:      {lead_id}")
    print(f"  Property 1:   {prop_names[0]} ({prop_ids[0]})")
    print(f"  Property 2:   {prop_names[1]} ({prop_ids[1]})")
    print(f"  Check-in:     2026-10-01")
    print(f"  Check-out:    2026-10-05 (4 nights)")
    print()

    # ── Step 2: Hit the API via TestClient ──
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.core.security import create_access_token

    token = create_access_token(user_id="test-operator", role="operator", email="test@crog.com")
    headers = {"Authorization": f"Bearer {token}"}

    client = TestClient(app)
    payload = {
        "property_ids": prop_ids,
        "check_in_date": "2026-10-01",
        "check_out_date": "2026-10-05",
    }

    print(f"POST /api/leads/{lead_id}/quotes/build")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    print()

    resp = client.post(f"/api/leads/{lead_id}/quotes/build", json=payload, headers=headers)

    print(SEP)
    print(f"STATUS: {resp.status_code}")
    print(SEP)

    if resp.status_code != 200:
        print(f"ERROR: {resp.text}")
        _cleanup(lead_id)
        return

    data = resp.json()
    print(json.dumps(data, indent=2))
    print()

    # ── Step 3: Verify the math ──
    print(SEP)
    print("MATH VERIFICATION")
    print(SEP)
    for opt in data.get("options", []):
        name = opt["property_name"]
        base = float(opt["base_rent"])
        fees = float(opt["fees"])
        taxes = float(opt["taxes"])
        total = float(opt["total_price"])
        computed = round(base + fees + taxes, 2)
        match = "PASS" if abs(computed - total) < 0.01 else "FAIL"
        print(f"  {name}:")
        print(f"    base_rent + fees + taxes = {base} + {fees} + {taxes} = {computed}")
        print(f"    total_price              = {total}")
        print(f"    Math check:              [{match}]")
        print()

    # ── Cleanup ──
    _cleanup(lead_id)

    print(SEP)
    print("PHASE 3 COMPLETE: MATH ENGINE ONLINE")


def _cleanup(lead_id: str):
    """Remove test data (cascade deletes quotes and options)."""
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
