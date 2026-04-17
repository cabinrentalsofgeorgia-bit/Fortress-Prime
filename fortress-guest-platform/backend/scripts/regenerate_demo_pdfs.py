#!/usr/bin/env python3
"""
Regenerate the demonstration PDFs in backend/tests/fixtures/crog_output/.

Usage (from the repo root):
    .uv-venv/bin/python3 backend/scripts/regenerate_demo_pdfs.py

Renders two reference statements from real production OPA/OBP data, writes them to
backend/tests/fixtures/crog_output/, and prints verbatim extracted text so the product
owner can verify content without opening a PDF viewer.

Prerequisites:
  - DB is up
  - OBP id=10907 exists (Gary Knight / Cherokee Sunrise on Noontootla Creek / Feb 2026)
  - OBP id=10908 exists (David Dutil / Above the Timberline / Jan 2026)

These OBP rows were created during Phase E.5 fixture setup. If they are missing, run
the Phase E.5 fixture setup steps from PHASE_E5_REPORT.md.
"""
import asyncio
import io
import sys
from pathlib import Path

# Ensure the package root is on the path when run directly
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import pypdf


OUTPUT_DIR = REPO_ROOT / "backend" / "tests" / "fixtures" / "crog_output"

FIXTURES = [
    {
        "obp_id":   10907,
        "filename": "knight_cherokee_sunrise_2026_02.pdf",
        "label":    "Gary Knight / Cherokee Sunrise on Noontootla Creek / Feb 2026",
        "expected": [
            "Gary Knight",
            "PO Box 982",
            "Morganton",
            "Aska Adventure Area",
            "Cherokee Sunrise on Noontootla Creek",
            "UNAPPROVED",
            "$64,822.71",
            "minimum required balance",
            "Your payment amount of $0.00 has been processed.",
        ],
    },
    {
        "obp_id":   10908,
        "filename": "dutil_above_timberline_2026_01.pdf",
        "label":    "David Dutil / Above the Timberline / Jan 2026",
        "expected": [
            "David Dutil",
            "Birmingham",
            "Aska Adventure Area",
            "Above the Timberline",
            "APPROVED",
            "$3,001.91",
            "($312.50)",
            "minimum required balance",
            "Your payment amount of $3,001.91 has been processed.",
            "HVAC service call",
            "Deep clean after owner stay",
        ],
    },
]


def _extract_text(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


async def _render_one(db, fixture: dict) -> bytes:
    from backend.services.statement_pdf import render_owner_statement_pdf
    return await render_owner_statement_pdf(db, fixture["obp_id"])


async def main() -> None:
    from backend.core.database import AsyncSessionLocal

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_ok = True

    for fix in FIXTURES:
        print(f"\n{'='*70}")
        print(f"Rendering: {fix['label']}")
        print(f"  OBP id : {fix['obp_id']}")
        print(f"  Output : {OUTPUT_DIR / fix['filename']}")

        async with AsyncSessionLocal() as db:
            try:
                pdf_bytes = await _render_one(db, fix)
            except Exception as exc:
                print(f"  ERROR: {exc}")
                all_ok = False
                continue

        out_path = OUTPUT_DIR / fix["filename"]
        out_path.write_bytes(pdf_bytes)
        print(f"  Written: {len(pdf_bytes):,} bytes")

        text = _extract_text(pdf_bytes)
        print(f"\n--- Extracted text ---\n{text}\n--- End ---")

        # Spot-check expected strings
        missing = [s for s in fix["expected"] if s not in text]
        if missing:
            print(f"\n  VERIFICATION FAILED — missing strings:")
            for s in missing:
                print(f"    · {s!r}")
            all_ok = False
        else:
            print(f"\n  Verification: all {len(fix['expected'])} expected strings present ✓")

    print(f"\n{'='*70}")
    if all_ok:
        print("All fixtures regenerated successfully.")
    else:
        print("One or more fixtures had errors or failed verification — see above.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
