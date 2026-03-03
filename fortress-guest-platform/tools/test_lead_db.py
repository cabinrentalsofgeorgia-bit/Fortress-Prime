#!/usr/bin/env python3
"""
Pre-Flight Validation — Lead & Quote Data Models (Rule 7)

Creates a Lead with dirty contact data, sanitizes per Rule 6,
saves Lead + Quote + 2 QuoteOptions, then re-queries and prints
the full sanitized record to prove the pipeline works.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta, date
from decimal import Decimal
from uuid import uuid4

# Ensure project root is on path
_root = str(Path(__file__).resolve().parents[1])
if _root not in sys.path:
    sys.path.insert(0, _root)

from backend.core.database import SyncSessionLocal, sync_engine
from backend.models.lead import Lead
from backend.models.quote import Quote, QuoteOption
from backend.models.property import Property
from backend.services.lead_sync import sanitize_phone, sanitize_email, sanitize_message

SEP = "=" * 60


def run_test():
    db = SyncSessionLocal()
    try:
        # ── Dirty inputs ──
        raw_phone = "(404) 555 - 1234"
        raw_email = "  Gary.Knight@CROG.COM  "
        raw_message = "<b>Interested</b> in <a href=\"#\">your cabins</a> for a fall getaway!"

        print(SEP)
        print("RULE 6 SANITIZATION TEST")
        print(SEP)
        print(f"  phone  IN:  {raw_phone!r}")
        print(f"  phone OUT:  {sanitize_phone(raw_phone)!r}")
        print(f"  email  IN:  {raw_email!r}")
        print(f"  email OUT:  {sanitize_email(raw_email)!r}")
        print(f"  msg    IN:  {raw_message!r}")
        print(f"  msg   OUT:  {sanitize_message(raw_message)!r}")
        print()

        # ── Create Lead ──
        lead = Lead(
            streamline_lead_id=f"TEST-{uuid4().hex[:8].upper()}",
            guest_name="Gary Knight",
            email=sanitize_email(raw_email),
            phone=sanitize_phone(raw_phone),
            guest_message=sanitize_message(raw_message),
            source="test_script",
            status="new",
            ai_score=82,
        )
        db.add(lead)
        db.flush()

        # ── Fetch two real properties for QuoteOptions ──
        props = db.query(Property).filter(Property.is_active.is_(True)).limit(2).all()
        if len(props) < 2:
            print("WARNING: Fewer than 2 active properties found; using mock UUIDs.")
            prop_ids = [uuid4(), uuid4()]
            prop_names = ["Mock Cabin A", "Mock Cabin B"]
        else:
            prop_ids = [p.id for p in props]
            prop_names = [p.name for p in props]

        # ── Create Quote ──
        quote = Quote(
            lead_id=lead.id,
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        db.add(quote)
        db.flush()

        # ── Create QuoteOptions ──
        check_in = date(2026, 10, 1)
        check_out = date(2026, 10, 5)
        nights = (check_out - check_in).days

        option_1 = QuoteOption(
            quote_id=quote.id,
            property_id=prop_ids[0],
            check_in_date=check_in,
            check_out_date=check_out,
            base_rent=Decimal("1200.00"),
            taxes=Decimal("156.00"),
            fees=Decimal("250.00"),
            total_price=Decimal("1606.00"),
        )
        option_2 = QuoteOption(
            quote_id=quote.id,
            property_id=prop_ids[1],
            check_in_date=check_in,
            check_out_date=check_out,
            base_rent=Decimal("1500.00"),
            taxes=Decimal("195.00"),
            fees=Decimal("300.00"),
            total_price=Decimal("1995.00"),
        )
        db.add_all([option_1, option_2])
        db.commit()

        # ── Re-query and print ──
        saved_lead = db.query(Lead).filter(Lead.id == lead.id).one()
        saved_quote = db.query(Quote).filter(Quote.id == quote.id).one()
        saved_opts = db.query(QuoteOption).filter(QuoteOption.quote_id == quote.id).all()

        print(SEP)
        print("LEAD RECORD (from DB)")
        print(SEP)
        print(f"  id:                 {saved_lead.id}")
        print(f"  streamline_lead_id: {saved_lead.streamline_lead_id}")
        print(f"  guest_name:         {saved_lead.guest_name}")
        print(f"  email:              {saved_lead.email}")
        print(f"  phone:              {saved_lead.phone}")
        print(f"  guest_message:      {saved_lead.guest_message}")
        print(f"  status:             {saved_lead.status}")
        print(f"  ai_score:           {saved_lead.ai_score}")
        print(f"  source:             {saved_lead.source}")
        print(f"  created_at:         {saved_lead.created_at}")
        print()

        print(SEP)
        print("QUOTE RECORD")
        print(SEP)
        print(f"  id:         {saved_quote.id}")
        print(f"  lead_id:    {saved_quote.lead_id}")
        print(f"  expires_at: {saved_quote.expires_at}")
        print(f"  created_at: {saved_quote.created_at}")
        print()

        for i, opt in enumerate(saved_opts, 1):
            pname = prop_names[i - 1] if i <= len(prop_names) else "Unknown"
            print(SEP)
            print(f"QUOTE OPTION {i}: {pname}")
            print(SEP)
            print(f"  property_id:   {opt.property_id}")
            print(f"  check_in:      {opt.check_in_date}")
            print(f"  check_out:     {opt.check_out_date}")
            print(f"  base_rent:     ${opt.base_rent}")
            print(f"  taxes:         ${opt.taxes}")
            print(f"  fees:          ${opt.fees}")
            print(f"  total_price:   ${opt.total_price}")
            print()

        # ── Cleanup test data ──
        db.delete(saved_lead)
        db.commit()
        print(SEP)
        print("Test data cleaned up (Lead + cascade deleted Quote/Options).")
        print(SEP)
        print()
        print("PHASE 2 COMPLETE: LEAD DB ONLINE")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_test()
