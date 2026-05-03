# Wilson Pruitt Email Batch 001 Source-Drop Audit - 7IL Case II

Date: 2026-05-03
Batch ID: WPE-BATCH-001
Operator service status: not served as of 2026-05-03
Classification: Repo-safe source-drop control. No email bodies, privileged substance, or merits conclusions.

## Purpose

This audit is the bridge between the operator copying Wilson Pruitt exports into the NAS and Fortress Legal generating source manifests. It answers one question before hashing: are the Batch 001 source folders populated in a way that is ready to manifest?

## Command

Run from the repository root on spark-2:

```bash
python3 tools/wpe_batch_manifest.py --audit-drop --dry-run
```

When the dry run looks correct, write the audit TSV to NAS:

```bash
python3 tools/wpe_batch_manifest.py --audit-drop
```

The written TSV lands in:

```text
/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/incoming/wilson-pruitt-email-intake-20260503/00_README/
```

## Readiness Statuses

| Status | Meaning | Next Action |
|---|---|---|
| `EMPTY` | Folder exists but contains no source files. | Copy files there if that family exists, otherwise leave empty intentionally. |
| `READY_TO_MANIFEST` | Folder contains recognized native or fallback source formats. | Run the manifest generator after all intended drops are complete. |
| `REVIEW_UNKNOWN_FORMATS` | Folder contains files outside native/fallback formats. | Confirm the file is a source export or move non-source files out before manifesting. |
| `MISSING_FOLDER` | Expected Batch 001 folder is absent. | Recreate the folder before copying files. |

## Source Families

| Intake ID | Folder | Use |
|---|---|---|
| WPE-20260503-001 | `01_wilson_pruitt_pre_closing` | Pre-closing Wilson Pruitt emails. |
| WPE-20260503-002 | `02_wilson_pruitt_post_closing` | Post-closing Wilson Pruitt emails. |
| WPE-20260503-003 | `03_report_transmission` | Inspection report, notes, or comments transmission. |
| WPE-20260503-004 | `04_dee_mcbee_case_i` | Dee McBee surrendered Case I email set or copies. |
| WPE-20260503-005 | `05_terry_wilson_production` | Terry Wilson production/authentication materials. |
| WPE-20260503-006 | `06_easement_title_crossing` | Easement, title, crossing, DOT/GNRR-related emails. |
| WPE-20260503-999 | `99_unsorted_hold` | Relevant but not yet classified material. |

## Current Gate

As of the first audit on 2026-05-03, Batch 001 had zero source files in the frozen originals folder. The correct next operator action is to copy source exports into the proper Batch 001 folder, then rerun the audit before manifest generation.

## No-Go Rules

- Do not run merits review from a folder that has not passed the source-drop audit.
- Do not generate source manifests until all intended files for that drop are copied.
- Do not leave unrelated notes, drafts, or working files in frozen source folders.
- Do not use screenshots or PDFs as complete substitutes if native email exports are available.
- Do not put raw email bodies or privileged legal advice into repo documents.
