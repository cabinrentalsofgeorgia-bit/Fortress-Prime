#!/usr/bin/env python3
"""
clone_checkout_dom.py — Level 55: Stateful DOM Extraction

Uses Playwright to load the legacy cabin page, interact with the calendar
to select dates, follow the booking flow to its final checkout state, and
extract the sequential DOM layout map + computed CSS for reconstruction
in the Next.js checkout page.

Usage:
    python3 backend/scripts/clone_checkout_dom.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

TARGET_URL = "https://www.cabin-rentals-of-georgia.com/cabin/blue-ridge/above-the-timberline"

JS_EXTRACT_FULL_PAGE = r"""
() => {
    const results = {
        url: window.location.href,
        page_title: document.title,
        sections: [],
        forms: [],
        computed_styles: {},
        travelex: null,
        terms: null,
        all_text_sections: [],
    };

    // Collect ALL visible sections in DOM order
    const allElements = document.querySelectorAll(
        'h1, h2, h3, h4, form, table, .field, .block, .panel, .pane, ' +
        '.region, .zone, .view, img[src*="travelex"], img[src*="separator"]'
    );

    const seen = new Set();
    allElements.forEach((el, idx) => {
        const rect = el.getBoundingClientRect();
        if (rect.height === 0 && rect.width === 0) return;
        const key = `${el.tagName}-${Math.round(rect.top)}`;
        if (seen.has(key)) return;
        seen.add(key);

        const style = window.getComputedStyle(el);
        const entry = {
            index: idx,
            tag: el.tagName.toLowerCase(),
            id: el.id || '',
            classes: el.className || '',
            text: el.textContent?.trim().substring(0, 200) || '',
            y_position: Math.round(rect.top + window.scrollY),
            rect: {
                top: Math.round(rect.top),
                left: Math.round(rect.left),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
            },
        };

        if (['h1','h2','h3','h4'].includes(entry.tag)) {
            entry.css = {
                fontFamily: style.fontFamily,
                fontSize: style.fontSize,
                fontWeight: style.fontWeight,
                fontStyle: style.fontStyle,
                lineHeight: style.lineHeight,
                color: style.color,
                marginTop: style.marginTop,
                marginBottom: style.marginBottom,
                textAlign: style.textAlign,
            };
        }

        results.sections.push(entry);
    });

    results.sections.sort((a, b) => a.y_position - b.y_position);

    // Extract ALL forms with their fields
    document.querySelectorAll('form').forEach(form => {
        const rect = form.getBoundingClientRect();
        const fields = [];
        form.querySelectorAll('input, select, textarea').forEach(el => {
            if (el.type === 'hidden') return;
            const label = form.querySelector(`label[for="${el.id}"]`);
            const elStyle = window.getComputedStyle(el);
            fields.push({
                tag: el.tagName.toLowerCase(),
                type: el.type || '',
                name: el.name || '',
                id: el.id || '',
                label: label ? label.textContent.trim() : '',
                placeholder: el.placeholder || '',
                required: el.required,
                css: {
                    fontSize: elStyle.fontSize,
                    fontFamily: elStyle.fontFamily,
                    color: elStyle.color,
                    backgroundColor: elStyle.backgroundColor,
                    borderColor: elStyle.borderColor,
                    borderWidth: elStyle.borderWidth,
                    borderRadius: elStyle.borderRadius,
                    padding: `${elStyle.paddingTop} ${elStyle.paddingRight} ${elStyle.paddingBottom} ${elStyle.paddingLeft}`,
                    height: elStyle.height,
                    width: elStyle.width,
                },
            });
        });
        if (fields.length > 0 || form.id) {
            results.forms.push({
                id: form.id || '',
                action: form.action || '',
                method: form.method || '',
                classes: form.className || '',
                y_position: Math.round(rect.top + window.scrollY),
                fields: fields,
            });
        }
    });

    // Content + sidebar column widths
    const contentSelectors = [
        '.column.content', 'td.column.content', '.region-content',
        '#content', '.content-area', '[role="main"]'
    ];
    const sidebarSelectors = [
        '.column.sidebar', 'td.column.sidebar', '.region-sidebar-second',
        '#sidebar', '.sidebar'
    ];

    for (const sel of contentSelectors) {
        const el = document.querySelector(sel);
        if (el) {
            const s = window.getComputedStyle(el);
            results.computed_styles.content_column = {
                selector: sel,
                width: s.width,
                maxWidth: s.maxWidth,
                float: s.cssFloat,
                display: s.display,
                padding: `${s.paddingTop} ${s.paddingRight} ${s.paddingBottom} ${s.paddingLeft}`,
            };
            break;
        }
    }
    for (const sel of sidebarSelectors) {
        const el = document.querySelector(sel);
        if (el) {
            const s = window.getComputedStyle(el);
            results.computed_styles.sidebar_column = {
                selector: sel,
                width: s.width,
                maxWidth: s.maxWidth,
                float: s.cssFloat,
                display: s.display,
                padding: `${s.paddingTop} ${s.paddingRight} ${s.paddingBottom} ${s.paddingLeft}`,
            };
            break;
        }
    }

    // Overall page container
    const pageContainer = document.querySelector('.page, #page, .container, .wrapper');
    if (pageContainer) {
        const s = window.getComputedStyle(pageContainer);
        results.computed_styles.page_container = {
            width: s.width,
            maxWidth: s.maxWidth,
            margin: `${s.marginTop} ${s.marginRight} ${s.marginBottom} ${s.marginLeft}`,
            padding: `${s.paddingTop} ${s.paddingRight} ${s.paddingBottom} ${s.paddingLeft}`,
            backgroundColor: s.backgroundColor,
        };
    }

    // Body styles
    const bodyStyle = window.getComputedStyle(document.body);
    results.computed_styles.body = {
        fontFamily: bodyStyle.fontFamily,
        fontSize: bodyStyle.fontSize,
        fontWeight: bodyStyle.fontWeight,
        color: bodyStyle.color,
        backgroundColor: bodyStyle.backgroundColor,
        lineHeight: bodyStyle.lineHeight,
    };

    // Form label styles
    const formLabel = document.querySelector('.form-item label, label');
    if (formLabel) {
        const s = window.getComputedStyle(formLabel);
        results.computed_styles.form_label = {
            fontFamily: s.fontFamily,
            fontSize: s.fontSize,
            fontWeight: s.fontWeight,
            fontStyle: s.fontStyle,
            color: s.color,
            lineHeight: s.lineHeight,
        };
    }

    // Travelex
    const travelexImgs = document.querySelectorAll('img[src*="travelex" i]');
    const travelexLinks = document.querySelectorAll('a[href*="travelex" i]');
    if (travelexImgs.length > 0 || travelexLinks.length > 0) {
        results.travelex = {
            images: Array.from(travelexImgs).map(img => ({
                src: img.src,
                alt: img.alt,
                width: img.width,
                height: img.height,
            })),
            links: Array.from(travelexLinks).map(a => ({
                href: a.href,
                text: a.textContent.trim().substring(0, 200),
            })),
        };
        // Get surrounding text
        const travelexParent = (travelexImgs[0] || travelexLinks[0])?.closest('div, td, p, section');
        if (travelexParent) {
            results.travelex.surrounding_text = travelexParent.textContent.trim().substring(0, 2000);
            const ps = window.getComputedStyle(travelexParent);
            results.travelex.css = {
                fontFamily: ps.fontFamily,
                fontSize: ps.fontSize,
                fontStyle: ps.fontStyle,
                color: ps.color,
                lineHeight: ps.lineHeight,
            };
        }
    }

    // Terms and conditions
    const allAnchors = document.querySelectorAll('a');
    allAnchors.forEach(a => {
        const text = a.textContent.toLowerCase();
        if (text.includes('terms') || text.includes('rental polic') || text.includes('cancellation')) {
            if (!results.terms) results.terms = [];
            results.terms.push({
                href: a.href,
                text: a.textContent.trim(),
                parent_text: a.parentElement?.textContent?.trim().substring(0, 500) || '',
            });
        }
    });

    // Extract text blocks in order (for layout reconstruction)
    const textBlocks = document.querySelectorAll('p, .field-item, .field-label, blockquote');
    textBlocks.forEach(el => {
        const rect = el.getBoundingClientRect();
        if (rect.height === 0 || !el.textContent.trim()) return;
        const text = el.textContent.trim().substring(0, 300);
        if (text.length < 5) return;
        const style = window.getComputedStyle(el);
        results.all_text_sections.push({
            y_position: Math.round(rect.top + window.scrollY),
            tag: el.tagName.toLowerCase(),
            text: text,
            css: {
                fontFamily: style.fontFamily,
                fontSize: style.fontSize,
                fontStyle: style.fontStyle,
                color: style.color,
                fontWeight: style.fontWeight,
            },
        });
    });
    results.all_text_sections.sort((a, b) => a.y_position - b.y_position);

    return results;
}
"""


def run_extraction():
    out_path = Path("/home/admin/cabin-rentals-of-georgia/checkout_layout_map.json")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # --- Phase 1: Extract the cabin page (pre-booking state) ---
        print(f"[1/5] Loading cabin page: {TARGET_URL} ...")
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(5000)

        print("[2/5] Extracting cabin page layout ...")
        cabin_layout = page.evaluate(JS_EXTRACT_FULL_PAGE)

        # --- Phase 2: Find and navigate to the booking page ---
        print("[3/6] Finding booking page URL ...")
        
        booking_url = None
        booking_triggers = [
            'a:has(img[src*="instant_quote"])',
            'a:has(img[src*="btn_book"])',
            'a:has-text("Book Now")',
            'a:has-text("Instant Quote")',
        ]
        
        for selector in booking_triggers:
            try:
                el = page.query_selector(selector)
                if el:
                    href = el.get_attribute("href")
                    if href:
                        booking_url = href
                        print(f"  Found booking trigger: {selector} -> {href}")
                    break
            except Exception:
                continue

        # --- Phase 3: Navigate to the actual booking/checkout page ---
        booking_page_layout = None
        if booking_url:
            full_url = booking_url
            if booking_url.startswith("/"):
                full_url = f"https://www.cabin-rentals-of-georgia.com{booking_url}"
            print(f"[4/6] Loading booking page: {full_url} ...")
            page.goto(full_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(5000)

            print("[5/6] Extracting booking page layout ...")
            booking_page_layout = page.evaluate(JS_EXTRACT_FULL_PAGE)

            # Take a screenshot
            screenshot_path = out_path.parent / "checkout_legacy_screenshot.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            print(f"  Screenshot saved to: {screenshot_path}")
        else:
            print("  No booking URL found, skipping booking page extraction")

        # --- Phase 4: Try filling dates on the booking page ---
        print("[6/6] Attempting to fill dates on booking page ...")
        post_submit_url = page.url
        post_submit_layout = None

        # Check if the booking page has a reservation form
        reservation_form = page.query_selector(
            "form.crog-reservations, form#crog-reservations-book-form, "
            "form#crog-reservations-quote-form"
        )
        reservation_form_detail = None
        if reservation_form:
            print("  Found reservation form after date submission!")
            reservation_form_detail = page.evaluate("""
            () => {
                const form = document.querySelector(
                    'form.crog-reservations, form#crog-reservations-book-form'
                );
                if (!form) return null;
                const fields = [];
                form.querySelectorAll('.form-item').forEach(item => {
                    const label = item.querySelector('label');
                    const input = item.querySelector('input, select, textarea');
                    if (!input) return;
                    const labelStyle = label ? window.getComputedStyle(label) : null;
                    const inputStyle = window.getComputedStyle(input);
                    fields.push({
                        label: label ? label.textContent.trim() : '',
                        input_name: input.name || '',
                        input_type: input.type || input.tagName.toLowerCase(),
                        input_id: input.id || '',
                        required: input.required || (label && label.textContent.includes('*')),
                        visible: input.type !== 'hidden' && inputStyle.display !== 'none',
                        label_css: labelStyle ? {
                            fontFamily: labelStyle.fontFamily,
                            fontSize: labelStyle.fontSize,
                            fontWeight: labelStyle.fontWeight,
                            fontStyle: labelStyle.fontStyle,
                            color: labelStyle.color,
                        } : null,
                        input_css: {
                            fontSize: inputStyle.fontSize,
                            fontFamily: inputStyle.fontFamily,
                            color: inputStyle.color,
                            backgroundColor: inputStyle.backgroundColor,
                            borderColor: inputStyle.borderColor,
                            borderRadius: inputStyle.borderRadius,
                            padding: `${inputStyle.paddingTop} ${inputStyle.paddingRight} ${inputStyle.paddingBottom} ${inputStyle.paddingLeft}`,
                            height: inputStyle.height,
                            width: inputStyle.width,
                        },
                    });
                });
                return {
                    form_id: form.id,
                    form_action: form.action,
                    form_method: form.method,
                    total_fields: fields.length,
                    visible_fields: fields.filter(f => f.visible).length,
                    fields: fields,
                };
            }
            """)

        browser.close()

    output = {
        "meta": {
            "source": TARGET_URL,
            "booking_url": booking_url,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "viewport": "1280x900",
            "post_submit_url": post_submit_url,
        },
        "cabin_page_layout": cabin_layout,
        "booking_page_layout": booking_page_layout,
        "post_date_submit_layout": post_submit_layout,
        "reservation_form_detail": reservation_form_detail,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))
    
    print(f"\n{'='*60}")
    print(f"Layout map saved to {out_path}")
    print(f"{'='*60}")
    print(f"  Cabin page sections: {len(cabin_layout.get('sections', []))}")
    print(f"  Cabin page forms: {len(cabin_layout.get('forms', []))}")
    print(f"  Booking URL: {booking_url}")
    if booking_page_layout:
        print(f"  Booking page sections: {len(booking_page_layout.get('sections', []))}")
        print(f"  Booking page forms: {len(booking_page_layout.get('forms', []))}")
    print(f"  Reservation form found: {reservation_form_detail is not None}")
    if reservation_form_detail:
        print(f"    Fields: {reservation_form_detail.get('total_fields', 0)}")
        print(f"    Visible: {reservation_form_detail.get('visible_fields', 0)}")

    for key, layout in [
        ("Cabin Page", cabin_layout),
        ("Booking Page", booking_page_layout),
    ]:
        if not layout:
            continue
        print(f"\n--- {key} Section Order ---")
        for s in layout.get("sections", [])[:40]:
            label = s.get("text", "")[:80].replace("\n", " ")
            print(f"  y={s['y_position']:5d}  {s['tag']:<6s}  id={s.get('id',''):<30s}  {label}")
        print(f"  Travelex: {'found' if layout.get('travelex') else 'not found'}")
        print(f"  Terms: {'found' if layout.get('terms') else 'not found'}")
        if layout.get("forms"):
            print(f"  Forms:")
            for f in layout["forms"]:
                vf = [fld for fld in f.get("fields", []) if fld.get("visible", True)]
                print(f"    id={f['id']}  action={f.get('action','')}  visible_fields={len(vf)}")
                for fld in vf[:15]:
                    print(f"      {fld.get('label',''):<20s}  name={fld.get('input_name',''):<25s}  type={fld.get('input_type','')}")


if __name__ == "__main__":
    run_extraction()
