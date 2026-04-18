# streamline_reference — Canonical Streamline Reference Files

This directory holds the source-of-truth files from Streamline that Crog-VRS
PDF output is compared against. They are committed to git and must not be
modified except through the process described below.

## Files

```
knight_cherokee_sunrise_2026_02.pdf
    Real PDF from Streamline's GetMonthEndStatement API.
    Owner: Gary Knight / Cherokee Sunrise on Noontootla Creek / February 2026.
    Status: UNAPPROVED (pending_approval). Zero activity. Opening: $64,822.71.
    Fetched via Option B (real Streamline PDF, 63,218 bytes).

dutil_above_the_timberline_2026_01.txt
    Text reconstruction from product owner's reference (Option A).
    The actual Streamline PDF for this period was not returned by the API
    (Streamline does not generate a statement for periods with zero reservations
    when the account balance did not change — confirmed 2026-04-14).
    Owner: David Dutil / Above the Timberline / January 2026.
    Status: APPROVED. Two charges ($312.50 total). Payment $3,001.91.
    Closing balance: ($312.50).
```

## How to update these files

These files must NOT be regenerated automatically or overwritten by tests.
To update them:

1. Fetch the new PDF from Streamline via the admin API or GetMonthEndStatement
   directly using the Streamline integration in
   `backend/integrations/streamline_vrs.py`.
2. Verify the content manually before committing.
3. Commit with a clear message explaining why the reference changed.

If you need to compare the current Crog-VRS rendering against these files,
run the demonstration PDF regeneration script:

    .uv-venv/bin/python3 backend/scripts/regenerate_pdf_demos.py

This regenerates `backend/tests/fixtures/crog_output/` from live data and
prints verbatim extracted text for comparison.

## DO NOT

- Overwrite these files from any automated script or test.
- Modify `knight_cherokee_sunrise_2026_02.pdf` — it is a real Streamline PDF
  and is the ground truth for visual comparison.
- Delete `dutil_above_the_timberline_2026_01.txt` — it is the only record
  of the expected Dutil statement structure since the API returned no PDF.
