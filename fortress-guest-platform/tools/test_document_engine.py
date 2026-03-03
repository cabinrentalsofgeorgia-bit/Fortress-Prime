#!/usr/bin/env python3
"""
Pre-flight validation for the Document Engine (Rule 7).

Generates both PDFs (receipt + agreement) with mock data,
writes them to tools/preview_receipt.pdf and tools/preview_agreement.pdf,
and validates the output by checking the %PDF magic bytes.
"""
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

TOOLS_DIR = Path(__file__).resolve().parent


def main() -> None:
    print("=" * 64)
    print("  DOCUMENT ENGINE — PRE-FLIGHT VALIDATION (Rule 7)")
    print("=" * 64)

    from backend.services.document_engine import DocumentEngine

    engine = DocumentEngine()

    mock_quote = {
        "quote_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "guest_name": "Jane & Michael Reynolds",
        "property_name": "Whisper Creek Lodge",
        "check_in": "2026-11-20",
        "check_out": "2026-11-27",
        "nights": "7",
        "base_rent": "2,450.00",
        "taxes": "318.50",
        "fees": "225.00",
        "total": "2,993.50",
        "payment_method": "stripe",
        "status": "paid",
    }

    # ── Generate Receipt ─────────────────────────────────────────
    print("\n[1/4] Generating receipt PDF...")
    receipt_bytes = engine.generate_receipt(mock_quote)
    receipt_path = TOOLS_DIR / "preview_receipt.pdf"
    receipt_path.write_bytes(receipt_bytes)
    print(f"  -> Written: {receipt_path} ({len(receipt_bytes):,} bytes)")

    assert receipt_bytes[:4] == b"%PDF", "Receipt does not start with %PDF magic bytes!"
    print("  -> PASS: %PDF magic bytes verified")

    # ── Generate Agreement ───────────────────────────────────────
    print("\n[2/4] Generating rental agreement PDF...")
    agreement_bytes = engine.generate_agreement(mock_quote)
    agreement_path = TOOLS_DIR / "preview_agreement.pdf"
    agreement_path.write_bytes(agreement_bytes)
    print(f"  -> Written: {agreement_path} ({len(agreement_bytes):,} bytes)")

    assert agreement_bytes[:4] == b"%PDF", "Agreement does not start with %PDF magic bytes!"
    print("  -> PASS: %PDF magic bytes verified")

    # ── Test pending status watermark ────────────────────────────
    print("\n[3/4] Generating receipt with PENDING VERIFICATION status...")
    pending_quote = {**mock_quote, "status": "pending_verification", "payment_method": "zelle"}
    pending_bytes = engine.generate_receipt(pending_quote)
    assert pending_bytes[:4] == b"%PDF", "Pending receipt does not start with %PDF!"
    print(f"  -> PASS: Pending receipt generated ({len(pending_bytes):,} bytes)")

    # ── Test confirmation template ───────────────────────────────
    print("\n[4/4] Testing booking confirmation HTML template...")
    from backend.services.template_engine import TemplateEngine
    tmpl = TemplateEngine()
    html = tmpl.wrap_confirmation(mock_quote)
    assert "Whisper Creek Lodge" in html, "Property name missing from confirmation template!"
    assert "2,993.50" in html, "Total missing from confirmation template!"
    assert "Booking Confirmed" in html, "Confirmation badge missing!"
    print("  -> PASS: Booking confirmation template renders correctly")

    # ── Summary ──────────────────────────────────────────────────
    print("\n" + "=" * 64)
    print("  ALL TESTS PASSED")
    print("=" * 64)
    print(f"\n  Receipt:   {receipt_path}")
    print(f"  Agreement: {agreement_path}")
    print("\n  Open the PDFs above to visually inspect the output.")
    print("=" * 64)


if __name__ == "__main__":
    main()
