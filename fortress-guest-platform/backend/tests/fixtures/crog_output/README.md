# crog_output — Demonstration PDFs for Visual Review

This directory holds canonical PDF renderings for product owner comparison
against the Streamline reference PDFs in `../streamline_reference/`.

## Files

```
knight_cherokee_sunrise_2026_02.pdf
    Crog-VRS rendering of Gary Knight / Cherokee Sunrise on Noontootla Creek / Feb 2026.
    Compare against: ../streamline_reference/knight_cherokee_sunrise_2026_02.pdf
    OPA: id=176  (real production data, Streamline-sourced address)
    OBP: id=10907

dutil_above_timberline_2026_01.pdf
    Crog-VRS rendering of David Dutil / Above the Timberline / Jan 2026.
    Compare against: ../streamline_reference/dutil_above_the_timberline_2026_01.txt
    OPA: id=172  (real production data, Streamline-sourced address)
    OBP: id=10908
```

## How to regenerate

Run from the repository root (preferred — uses in-memory records, no DB writes):

```bash
.uv-venv/bin/python3 backend/scripts/regenerate_pdf_demos.py
```

This script fetches real owner mailing addresses from Streamline's `GetOwnerInfo`
endpoint and loads property data from the local DB, then calls the pure
`_build_pdf_bytes()` function directly — nothing is written to `owner_payout_accounts`
or `owner_balance_periods`. Each PDF is accompanied by a `.pdf.txt` companion file
containing the verbatim extracted text for inline comparison without a PDF viewer.

Alternative (DB-based, reads OBP ids 10907 and 10908):

```bash
.uv-venv/bin/python3 backend/scripts/regenerate_demo_pdfs.py
```

## Rules

- **Unit tests MUST NOT write to this directory.** Tests use `pytest`'s `tmp_path`
  fixture for any PDF output they produce. See `.gitignore` for the force-include rule.
- **PDFs and .txt files are tracked in git** (see `.gitignore`). They show up in PR
  diffs when the renderer changes.
- **This directory is manually regenerated on demand** — it is not produced by any
  CI step. Re-run `regenerate_pdf_demos.py` whenever the PDF renderer changes and
  the product owner needs to compare against Streamline.
