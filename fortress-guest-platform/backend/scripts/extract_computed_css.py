#!/usr/bin/env python3
"""
Level 49 — The Computed CSS Sniper

Loads legacy cabin and activity pages via Playwright, injects JS to read
window.getComputedStyle() for every typographic element, and writes the
exact values to design_tokens.json.

Usage:
    python3 backend/scripts/extract_computed_css.py
"""

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

TARGETS = [
    {
        "label": "cabin_page",
        "url": "https://www.cabin-rentals-of-georgia.com/blue-ridge-cabins/above-the-timberline",
    },
    {
        "label": "activity_page",
        "url": "https://www.cabin-rentals-of-georgia.com/activity/fishing/fishing-the-toccoa-river",
    },
]

ELEMENTS = ["h1", "h2", "h3", "h4", "p", "a", "ul", "ol", "li", "strong", "em", "blockquote"]

PROPERTIES = [
    "fontFamily",
    "fontSize",
    "fontWeight",
    "fontStyle",
    "lineHeight",
    "color",
    "marginTop",
    "marginBottom",
    "paddingTop",
    "paddingBottom",
    "paddingLeft",
    "paddingRight",
    "letterSpacing",
    "textDecoration",
    "textTransform",
]

JS_EXTRACTOR = """
() => {
    const ELEMENTS = %s;
    const PROPERTIES = %s;
    const results = {};

    // Target the main article body — cabin-bottom-left for cabin pages,
    // cabin-content or the whole document for activity pages
    const containers = [
        document.querySelector('.cabin-bottom-left'),
        document.querySelector('.cabin-content'),
        document.querySelector('.body'),
        document.querySelector('#content'),
        document.querySelector('article'),
        document.body,
    ].filter(Boolean);
    const container = containers[0];

    for (const tag of ELEMENTS) {
        const els = container.querySelectorAll(tag);
        if (els.length === 0) continue;

        const samples = [];
        // Sample up to 5 instances of each tag for a representative average
        const limit = Math.min(els.length, 5);
        for (let i = 0; i < limit; i++) {
            const cs = window.getComputedStyle(els[i]);
            const entry = {};
            for (const prop of PROPERTIES) {
                entry[prop] = cs[prop];
            }
            // Also grab the tag's text for context (truncated)
            entry['_sampleText'] = (els[i].textContent || '').trim().substring(0, 60);
            entry['_parentClass'] = els[i].parentElement ? els[i].parentElement.className : '';
            samples.push(entry);
        }
        results[tag] = samples;
    }

    // Also extract body-level defaults
    const bodyCs = window.getComputedStyle(document.body);
    results['_body'] = [{
        fontFamily: bodyCs.fontFamily,
        fontSize: bodyCs.fontSize,
        fontWeight: bodyCs.fontWeight,
        lineHeight: bodyCs.lineHeight,
        color: bodyCs.color,
        backgroundColor: bodyCs.backgroundColor,
        letterSpacing: bodyCs.letterSpacing,
    }];

    // Extract link states - find an <a> in the article
    const articleLink = container.querySelector('a[href]');
    if (articleLink) {
        const linkCs = window.getComputedStyle(articleLink);
        results['_link'] = [{
            color: linkCs.color,
            textDecoration: linkCs.textDecoration,
            fontWeight: linkCs.fontWeight,
        }];
    }

    return results;
}
"""


def run_extraction():
    all_results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        for target in TARGETS:
            label = target["label"]
            url = target["url"]
            print(f"  Loading {label}: {url}")

            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)

            js = JS_EXTRACTOR % (json.dumps(ELEMENTS), json.dumps(PROPERTIES))
            result = page.evaluate(js)
            all_results[label] = result

            element_count = sum(len(v) for v in result.values())
            print(f"    Extracted {element_count} style samples across {len(result)} element types")

        browser.close()

    return all_results


def compute_consensus(all_results: dict) -> dict:
    """Merge samples from both pages into a single canonical token set."""
    consensus = {}

    # Collect all samples for each tag across both pages
    merged_samples: dict[str, list] = {}
    for page_label, page_data in all_results.items():
        for tag, samples in page_data.items():
            merged_samples.setdefault(tag, []).extend(samples)

    for tag, samples in merged_samples.items():
        if not samples:
            continue

        # For each CSS property, take the most common value (mode)
        all_props = set()
        for s in samples:
            all_props.update(k for k in s if not k.startswith("_"))

        token = {}
        for prop in sorted(all_props):
            values = [s.get(prop) for s in samples if s.get(prop)]
            if not values:
                continue
            # Mode: most frequent value
            from collections import Counter
            counter = Counter(values)
            token[prop] = counter.most_common(1)[0][0]

        consensus[tag] = token

    return consensus


def main():
    print("CSS Sniper: extracting computed styles from legacy site...")
    raw = run_extraction()

    print("\nComputing consensus tokens...")
    tokens = compute_consensus(raw)

    output = {
        "meta": {
            "source": "Legacy Drupal site (cabin-rentals-of-georgia.com)",
            "pages_sampled": [t["url"] for t in TARGETS],
            "extraction_method": "Playwright + window.getComputedStyle()",
        },
        "raw_samples": raw,
        "tokens": tokens,
    }

    out_path = Path(__file__).resolve().parent.parent.parent.parent / "cabin-rentals-of-georgia" / "design_tokens.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nDesign tokens written to: {out_path}")

    # Print a summary table
    print("\n=== CONSENSUS DESIGN TOKENS ===")
    for tag, props in sorted(tokens.items()):
        print(f"\n  {tag}:")
        for k, v in sorted(props.items()):
            print(f"    {k}: {v}")


if __name__ == "__main__":
    main()
