#!/usr/bin/env python3
"""
Historical Lead Extraction & AI Benchmarking Dataset Builder
=============================================================

Connects to the Streamline VRS API, fetches historical quote/inquiry
records (status_code=5 and any reservation with client_comments), enriches
each with staff notes, sanitizes per Rule 6, and writes a clean JSONL
dataset to tests/fixtures/historical_leads.jsonl.

This dataset is used to benchmark and train the Agentic Sales Engine.

Usage:
    python tools/extract_historical_leads.py [--limit 50] [--days-back 365]
"""
import asyncio
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

_root = str(Path(__file__).resolve().parents[1])
if _root not in sys.path:
    sys.path.insert(0, _root)

from backend.integrations.streamline_vrs import StreamlineVRS
from backend.services.lead_sync import sanitize_phone, sanitize_email, sanitize_message

SEP = "=" * 72
OUTPUT_PATH = Path(_root) / "tests" / "fixtures" / "historical_leads.jsonl"


def _sanitize_lead(raw: dict) -> dict:
    """
    Rule 6 enforcement: sanitize every field before persisting.

    - Phone: strip non-digits, prepend +1 for 10-digit US numbers
    - Email: strip whitespace, lowercase
    - Guest message (client_comments): strip HTML tags
    - Staff notes: strip HTML from message bodies
    """
    guest_message = sanitize_message(raw.get("special_requests") or "")
    guest_email = sanitize_email(raw.get("guest_email") or "")
    guest_phone = sanitize_phone(raw.get("guest_phone") or "")

    first = (raw.get("guest_first_name") or "").strip()
    last = (raw.get("guest_last_name") or "").strip()
    guest_name = f"{first} {last}".strip() or None

    # Sanitize staff notes
    clean_notes = []
    for note in raw.get("staff_notes", []):
        clean_notes.append({
            "author": (note.get("processor_name") or "").strip(),
            "date": (note.get("creation_date") or "").strip(),
            "message": sanitize_message(note.get("message") or ""),
        })

    # Build price summary
    breakdown = raw.get("price_breakdown", {}) or {}

    return {
        "streamline_reservation_id": raw.get("streamline_reservation_id"),
        "is_quote_status": raw.get("is_quote_status", False),
        "status": raw.get("status"),
        "guest_name": guest_name,
        "guest_email": guest_email,
        "guest_phone": guest_phone,
        "guest_message": guest_message,
        "source": (raw.get("source") or "").strip(),
        "check_in_date": raw.get("check_in_date"),
        "check_out_date": raw.get("check_out_date"),
        "num_guests": raw.get("num_guests"),
        "num_pets": raw.get("num_pets"),
        "unit_id": raw.get("unit_id"),
        "property_name": raw.get("property_name"),
        "total_amount": str(raw.get("total_amount")) if raw.get("total_amount") else None,
        "nights_count": raw.get("nights_count"),
        "price_total": breakdown.get("price_total"),
        "staff_notes": clean_notes,
        "staff_response": _extract_staff_response(clean_notes),
    }


def _extract_staff_response(notes: list) -> str | None:
    """
    Pull the best staff response from notes — prefer the longest
    note that isn't just a system-generated status change.
    """
    candidates = []
    for n in notes:
        msg = (n.get("message") or "").strip()
        if len(msg) > 10:
            candidates.append(msg)
    if not candidates:
        return None
    return max(candidates, key=len)


async def main(limit: int, days_back: int):
    print(SEP)
    print("HISTORICAL LEAD EXTRACTION")
    print(SEP)

    client = StreamlineVRS()
    if not client.is_configured:
        print("ERROR: Streamline VRS not configured (missing API credentials)")
        print("Falling back to database extraction...")
        await _extract_from_database(limit)
        return

    start_date = date.today() - timedelta(days=days_back)
    end_date = date.today() + timedelta(days=30)

    print(f"  Source:     Streamline VRS API")
    print(f"  Date range: {start_date} to {end_date}")
    print(f"  Limit:      {limit}")
    print(f"  Output:     {OUTPUT_PATH}")
    print()

    try:
        raw_leads = await client.fetch_historical_leads(
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            include_notes=True,
        )
    except Exception as e:
        print(f"Streamline API error: {e}")
        print("Falling back to database extraction...")
        await _extract_from_database(limit)
        return
    finally:
        await client.close()

    if not raw_leads:
        print("No leads/inquiries found via Streamline API.")
        print("Falling back to database extraction...")
        await _extract_from_database(limit)
        return

    _process_and_save(raw_leads)


async def _extract_from_database(limit: int):
    """
    Fallback: extract leads from the local reservations table.
    Pulls reservations that have special_requests (guest messages)
    or streamline_notes (staff responses).
    """
    print()
    print("  Source: Local fortress_guest database")
    print(f"  Output: {OUTPUT_PATH}")
    print()

    from backend.core.database import SyncSessionLocal
    from sqlalchemy import text

    db = SyncSessionLocal()
    try:
        result = db.execute(text("""
            SELECT
                r.confirmation_code,
                r.status,
                r.check_in_date::text AS check_in_date,
                r.check_out_date::text AS check_out_date,
                r.total_amount::text,
                r.nights_count,
                r.num_guests,
                r.num_pets,
                r.special_requests,
                r.streamline_notes,
                r.booking_source,
                g.first_name,
                g.last_name,
                g.email,
                g.phone_number AS phone,
                p.streamline_property_id AS unit_id,
                p.name AS property_name
            FROM reservations r
            LEFT JOIN guests g ON r.guest_id = g.id
            LEFT JOIN properties p ON r.property_id = p.id
            WHERE r.special_requests IS NOT NULL
              AND length(trim(r.special_requests)) > 0
            ORDER BY
                CASE WHEN r.streamline_notes IS NOT NULL
                     AND r.streamline_notes::text NOT IN ('null', '[]')
                THEN 0 ELSE 1 END,
                r.check_in_date DESC
            LIMIT :lim
        """), {"lim": limit})

        rows = result.fetchall()
        columns = result.keys()
    finally:
        db.close()

    if not rows:
        print("No reservations with guest messages found in the database.")
        print("Creating a minimal bootstrapped dataset from reservation notes...")
        await _extract_notes_only(limit)
        return

    raw_leads = []
    for row in rows:
        r = dict(zip(columns, row))

        # Parse streamline_notes JSONB for staff responses
        staff_notes = []
        raw_notes = r.get("streamline_notes")
        if raw_notes:
            if isinstance(raw_notes, list):
                for n in raw_notes:
                    staff_notes.append({
                        "processor_name": n.get("processor_name", ""),
                        "creation_date": n.get("creation_date", ""),
                        "message": n.get("message", ""),
                    })
            elif isinstance(raw_notes, str):
                staff_notes.append({
                    "processor_name": "staff",
                    "creation_date": "",
                    "message": raw_notes,
                })

        raw_leads.append({
            "streamline_reservation_id": r.get("confirmation_code"),
            "is_quote_status": r.get("status") == "pending",
            "status": r.get("status"),
            "guest_first_name": r.get("first_name") or "",
            "guest_last_name": r.get("last_name") or "",
            "guest_email": r.get("email") or "",
            "guest_phone": r.get("phone") or "",
            "special_requests": r.get("special_requests") or "",
            "source": r.get("booking_source") or "",
            "check_in_date": r.get("check_in_date"),
            "check_out_date": r.get("check_out_date"),
            "num_guests": r.get("num_guests"),
            "num_pets": r.get("num_pets"),
            "unit_id": r.get("unit_id"),
            "property_name": r.get("property_name"),
            "total_amount": r.get("total_amount"),
            "nights_count": r.get("nights_count"),
            "price_breakdown": {},
            "staff_notes": staff_notes,
        })

    _process_and_save(raw_leads)


async def _extract_notes_only(limit: int):
    """
    Last-resort fallback: pull reservations that have streamline_notes
    (even without special_requests) to get staff response examples.
    """
    from backend.core.database import SyncSessionLocal
    from sqlalchemy import text

    db = SyncSessionLocal()
    try:
        result = db.execute(text("""
            SELECT
                r.confirmation_code,
                r.status,
                r.check_in_date::text AS check_in_date,
                r.check_out_date::text AS check_out_date,
                r.total_amount::text,
                r.nights_count,
                r.num_guests,
                r.num_pets,
                r.special_requests,
                r.streamline_notes,
                r.booking_source,
                g.first_name,
                g.last_name,
                g.email,
                g.phone_number AS phone,
                p.streamline_property_id AS unit_id,
                p.name AS property_name
            FROM reservations r
            LEFT JOIN guests g ON r.guest_id = g.id
            LEFT JOIN properties p ON r.property_id = p.id
            WHERE r.streamline_notes IS NOT NULL
              AND r.streamline_notes::text != 'null'
              AND r.streamline_notes::text != '[]'
            ORDER BY r.check_in_date DESC
            LIMIT :lim
        """), {"lim": limit})

        rows = result.fetchall()
        columns = result.keys()
    finally:
        db.close()

    if not rows:
        print("No reservations with staff notes found either.")
        print("Dataset will be empty — populate via Streamline sync first.")
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text("")
        return

    raw_leads = []
    for row in rows:
        r = dict(zip(columns, row))

        staff_notes = []
        raw_notes = r.get("streamline_notes")
        if raw_notes:
            if isinstance(raw_notes, list):
                for n in raw_notes:
                    staff_notes.append({
                        "processor_name": n.get("processor_name", ""),
                        "creation_date": n.get("creation_date", ""),
                        "message": n.get("message", ""),
                    })
            elif isinstance(raw_notes, str):
                staff_notes.append({
                    "processor_name": "staff",
                    "creation_date": "",
                    "message": raw_notes,
                })

        raw_leads.append({
            "streamline_reservation_id": r.get("confirmation_code"),
            "is_quote_status": r.get("status") == "pending",
            "status": r.get("status"),
            "guest_first_name": r.get("first_name") or "",
            "guest_last_name": r.get("last_name") or "",
            "guest_email": r.get("email") or "",
            "guest_phone": r.get("phone") or "",
            "special_requests": r.get("special_requests") or "",
            "source": r.get("booking_source") or "",
            "check_in_date": r.get("check_in_date"),
            "check_out_date": r.get("check_out_date"),
            "num_guests": r.get("num_guests"),
            "num_pets": r.get("num_pets"),
            "unit_id": r.get("unit_id"),
            "property_name": r.get("property_name"),
            "total_amount": r.get("total_amount"),
            "nights_count": r.get("nights_count"),
            "price_breakdown": {},
            "staff_notes": staff_notes,
        })

    _process_and_save(raw_leads)


def _process_and_save(raw_leads: list):
    """Sanitize all records and write to JSONL."""
    sanitized = [_sanitize_lead(r) for r in raw_leads]

    # Filter out records with neither guest message nor staff response
    useful = [
        s for s in sanitized
        if (s.get("guest_message") or s.get("staff_response"))
    ]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        for record in useful:
            f.write(json.dumps(record, default=str) + "\n")

    print(f"  Records fetched (raw):     {len(raw_leads)}")
    print(f"  Records after sanitize:    {len(useful)}")
    print(f"  Saved to:                  {OUTPUT_PATH}")
    print()

    # Count stats
    with_message = sum(1 for s in useful if s.get("guest_message"))
    with_response = sum(1 for s in useful if s.get("staff_response"))
    with_both = sum(
        1 for s in useful if s.get("guest_message") and s.get("staff_response")
    )
    quote_status = sum(1 for s in useful if s.get("is_quote_status"))

    print(f"  With guest message:        {with_message}")
    print(f"  With staff response:       {with_response}")
    print(f"  With BOTH (training pairs):{with_both}")
    print(f"  Quote-status records:      {quote_status}")
    print()

    # Print first record as proof
    if useful:
        first = useful[0]
        print(SEP)
        print("FIRST SANITIZED RECORD")
        print(SEP)
        print(f"  Reservation ID:  {first.get('streamline_reservation_id')}")
        print(f"  Guest:           {first.get('guest_name')}")
        print(f"  Email:           {first.get('guest_email')}")
        print(f"  Phone:           {first.get('guest_phone')}")
        print(f"  Property:        {first.get('property_name')}")
        print(f"  Status:          {first.get('status')} (quote={first.get('is_quote_status')})")
        print(f"  Dates:           {first.get('check_in_date')} → {first.get('check_out_date')}")
        print(f"  Total:           ${first.get('total_amount')}")
        print(f"  Source:          {first.get('source')}")
        print()
        print("  GUEST MESSAGE:")
        msg = first.get("guest_message") or "(none)"
        for line in msg.split("\n"):
            print(f"    {line}")
        print()
        print("  STAFF RESPONSE:")
        resp = first.get("staff_response") or "(none)"
        for line in resp.split("\n"):
            print(f"    {line}")
        print()

        print(SEP)
        print("FULL JSON (first record):")
        print(SEP)
        print(json.dumps(first, indent=2, default=str))
    else:
        print("  [No useful records found]")

    print()
    print(SEP)
    print("HISTORICAL DATA EXTRACTED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract historical leads from Streamline")
    parser.add_argument("--limit", type=int, default=50, help="Max records to extract")
    parser.add_argument("--days-back", type=int, default=365, help="How far back to look")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.days_back))
