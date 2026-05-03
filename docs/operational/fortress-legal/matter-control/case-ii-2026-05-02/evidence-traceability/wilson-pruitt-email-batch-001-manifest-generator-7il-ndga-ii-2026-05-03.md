# Wilson Pruitt Email Batch 001 Manifest Generator - 7IL Case II

Date: 2026-05-03
Tool: `tools/wpe_batch_manifest.py`
Classification: Repo-safe operator utility. It hashes files and writes TSV control manifests only; it does not parse email bodies or decide privilege.

## Purpose

After source exports are copied into the Batch 001 frozen folders, run this tool to generate the source manifest, privilege-screen queue, and issue-tagging queue.

## Default Command

```bash
cd /home/admin/Fortress-Prime
python3 tools/wpe_batch_manifest.py
```

## Dry Run

```bash
python3 tools/wpe_batch_manifest.py --dry-run
```

## Source Family Mapping

| Folder | Intake ID | Primary Route |
|---|---|---|
| `01_wilson_pruitt_pre_closing` | `WPE-20260503-001` | Closing delay / PSA repair / professional-negligence gate |
| `02_wilson_pruitt_post_closing` | `WPE-20260503-002` | Post-closing conduct / adverse-alignment / civil-conspiracy gate |
| `03_report_transmission` | `WPE-20260503-003` | Inspection report source control / Case I overlap |
| `04_dee_mcbee_case_i` | `WPE-20260503-004` | Case I provenance / inspection source status |
| `05_terry_wilson_production` | `WPE-20260503-005` | Terry Wilson repair pin / PSA repair scope |
| `06_easement_title_crossing` | `WPE-20260503-006` | Easement/title/DOT/GNRR / privilege-waiver gate |
| `99_unsorted_hold` | `WPE-20260503-999` | Operator context required before analysis |

## No-Go Rules

- Do not run the tool against non-frozen folders.
- Do not treat generated privilege or issue queue rows as screened; they start as `PENDING` / `HOLD`.
- Do not promote a source fact until privilege status is `source-controlled` or counsel-approved.
- Do not place email bodies or legal advice in generated TSV notes.
