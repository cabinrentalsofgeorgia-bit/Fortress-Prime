#!/usr/bin/env python3
"""
Pre-Flight Validation: SMTP Dispatcher & Quote Send Endpoint

Tests the full stack:
  1. TemplateEngine  — renders branded HTML with and without checkout_url
  2. CTA injection   — verifies Magic Link button appears only when URL is provided
  3. SMTPDispatcher  — attempts a live send (or reports SMTP not configured)
  4. Writes preview HTML for visual inspection

Run:  python3 tools/test_smtp_dispatcher.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DIVIDER = "=" * 60

MOCK_DRAFT = """\
Dear Sarah,

Thank you for your interest in our luxury mountain cabins for your Thanksgiving getaway!

**Your Personalized Quote:**

- **Above the Timberline** (4BR / 3BA): $2,847.00 for 5 nights
  - Base Rent: $2,250.00
  - Cleaning Fee: $225.00
  - Taxes: $372.00

- **Bear Creek Lodge** (3BR / 2BA): $1,995.00 for 5 nights
  - Base Rent: $1,550.00
  - Cleaning Fee: $175.00
  - Taxes: $270.00

Both cabins feature hot tubs, mountain views, and complimentary firewood. We'd love to help you secure the perfect retreat for your family.

Warm regards,
Cabin Rentals of Georgia
"""

MOCK_CHECKOUT_URL = "https://crog-ai.com/api/direct-booking/quote?property_id=abc-123&check_in=2026-11-25&check_out=2026-11-30"


async def main():
    from backend.services.template_engine import TemplateEngine
    from backend.services.smtp_dispatcher import SMTPDispatcher
    from backend.services.email_service import is_email_configured

    print(f"\n{DIVIDER}")
    print("  SMTP DISPATCHER PRE-FLIGHT VALIDATION")
    print(DIVIDER)

    engine = TemplateEngine()

    # ── 1. Template without CTA ──
    print("\n[1/5] Rendering template WITHOUT checkout_url...")
    html_no_cta = engine.wrap_email(MOCK_DRAFT)
    assert "<!DOCTYPE html>" in html_no_cta, "Missing DOCTYPE"
    assert "crog-logo.png" in html_no_cta, "Missing logo"
    assert "Above the Timberline" in html_no_cta, "Missing property name"
    assert "Secure Your Dates" not in html_no_cta, "CTA should NOT appear without checkout_url"
    print("       ✓ HTML rendered, CTA correctly absent")

    # ── 2. Template with CTA ──
    print("\n[2/5] Rendering template WITH checkout_url...")
    html_with_cta = engine.wrap_email(MOCK_DRAFT, checkout_url=MOCK_CHECKOUT_URL)
    assert "Secure Your Dates" in html_with_cta, "CTA button text missing"
    assert MOCK_CHECKOUT_URL in html_with_cta, "checkout_url not injected"
    assert "#4ade80" in html_with_cta, "CTA button color missing"
    print("       ✓ HTML rendered, CTA button injected with Magic Link")

    # ── 3. Write preview ──
    print("\n[3/5] Writing preview HTML...")
    preview_path = Path(__file__).parent / "preview_quote_email.html"
    preview_path.write_text(html_with_cta)
    print(f"       ✓ Saved to {preview_path}")
    print(f"       Open in browser: file://{preview_path.resolve()}")

    # ── 4. SMTPDispatcher (no-recipient guard) ──
    print("\n[4/5] Testing SMTPDispatcher guard (empty recipient)...")
    dispatcher = SMTPDispatcher()
    result = await dispatcher.send_quote(
        to_email="",
        subject="Test",
        text_content="test",
    )
    assert result["success"] is False
    assert result["error"] == "no_recipient_email"
    print("       ✓ Empty-recipient guard works (no crash, no send)")

    # ── 5. Live SMTP test (if configured) ──
    smtp_configured = is_email_configured()
    print(f"\n[5/5] SMTP configuration: {'CONFIGURED' if smtp_configured else 'NOT CONFIGURED'}")
    if smtp_configured:
        print("       Attempting live send to configured test address...")
        live_result = await dispatcher.send_quote(
            to_email="test@crog-ai.com",
            subject="[PRE-FLIGHT] SMTP Dispatcher Validation",
            text_content=MOCK_DRAFT,
            checkout_url=MOCK_CHECKOUT_URL,
        )
        print(f"       Result: success={live_result['success']}, error={live_result.get('error')}")
    else:
        result_unconfigured = await dispatcher.send_quote(
            to_email="test@example.com",
            subject="Test",
            text_content="test",
        )
        assert result_unconfigured["success"] is False
        assert result_unconfigured["error"] == "smtp_not_configured"
        print("       ✓ Unconfigured guard works correctly")

    # ── Summary ──
    print(f"\n{DIVIDER}")
    print("  SMTP DISPATCHER PRE-FLIGHT: ✓ ALL CHECKS PASSED")
    print(DIVIDER)
    print(f"  Template (no CTA)  : VERIFIED")
    print(f"  Template (with CTA): VERIFIED — Magic Link injected")
    print(f"  SMTPDispatcher     : VERIFIED — guards work")
    print(f"  SMTP Live Send     : {'TESTED' if smtp_configured else 'SKIPPED (not configured)'}")
    print(f"  Preview File       : tools/preview_quote_email.html")
    print(DIVIDER)
    print()


if __name__ == "__main__":
    asyncio.run(main())
