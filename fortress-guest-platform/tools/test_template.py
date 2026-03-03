#!/usr/bin/env python3
"""
Pre-Flight Validation — Brand Aesthetic Template Engine (Rule 7)

Passes a mock AI-drafted email through TemplateEngine.wrap_email() and
writes the rendered HTML to tools/preview_email.html for visual review.

Usage:
    cd fortress-guest-platform && python3 tools/test_template.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.template_engine import TemplateEngine

MOCK_DRAFT = """\
Subject: Luxury Cabin Getaway for Your Wife's 40th Birthday!

Hi David,

Happy early 40th birthday to your wife! What an exciting celebration you're planning! We're thrilled to help you find the perfect luxury cabin getaway in Blue Ridge.

We've handpicked two stunning properties that fit your criteria: both have breathtaking views and a private hot tub for ultimate relaxation.

**Option 1: Aska Escape Lodge**
- **Dates:** November 24th to November 29th (5 nights)
- **Total Price:** $1,923.94
This beautiful cabin offers a serene escape with panoramic mountain views, perfect for celebrating such a special milestone. The hot tub is situated on the deck, where you can soak under the stars.

**Option 2: Cohutta Sunset**
- **Dates:** November 24th to November 29th (5 nights)
- **Total Price:** $1,923.94
Cohutta Sunset boasts a stunning sunset view and a private hot tub, creating the ultimate retreat for relaxation and celebration.

Both cabins are in close proximity to excellent dining options! Some of our top recommendations include The Black Sheep Restaurant, Harvest on Main, and Fightingtown Tavern.

David, we'd love to help you make this weekend unforgettable. Please let us know which cabin you prefer, or if you have any other questions.

Warm regards,
Cabin Rentals of Georgia Reservations Team"""


def main():
    print("=" * 60)
    print("  TEMPLATE ENGINE PRE-FLIGHT (Rule 7)")
    print("=" * 60)

    engine = TemplateEngine()
    html = engine.wrap_email(MOCK_DRAFT)

    assert "<html" in html, "Output is not HTML"
    assert "Cabin Rentals of Georgia" in html, "Footer brand missing"
    assert "<strong>Option 1: Aska Escape Lodge</strong>" in html, "Bold conversion failed"
    assert "$1,923.94" in html, "Pricing not preserved"
    assert "crog-logo.png" in html, "Logo reference missing"

    out_path = Path(__file__).parent / "preview_email.html"
    out_path.write_text(html, encoding="utf-8")

    print(f"\n  Assertions:  ALL PASS")
    print(f"  HTML length: {len(html):,} chars")
    print(f"  Output:      {out_path.resolve()}")
    print(f"\n  Open in browser to verify:")
    print(f"    file://{out_path.resolve()}")
    print(f"\n{'=' * 60}")
    print(f"  TEMPLATE ENGINE PRE-FLIGHT: PASS")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
