# Wilson Pruitt Email Batch 001 Intake Kit - 7IL Case II

Date: 2026-05-03
Batch ID: WPE-BATCH-001
Operator service status: not served as of 2026-05-03
Classification: Repo-safe intake-control document. No email bodies, privileged substance, or merits conclusions.

## Purpose

This kit turns the Wilson Pruitt email intake protocol into a first executable batch. It tells the operator where to place source exports, which manifests to fill, and which gates must clear before any email can affect the answer, counterclaim posture, Wilson Pruitt claim-evaluation workbench, or evidence matrices.

## Batch Rule

Batch 001 is evidence preservation first. No one should summarize, quote, or argue from an email until the original is frozen, hashed, metadata-captured, attachment-linked, privilege-screened, issue-tagged, and routed through the proof matrix.

## NAS Batch Location

```text
/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/incoming/wilson-pruitt-email-intake-20260503/
```

Batch templates live inside that NAS folder:

| Template | NAS Path | Use |
|---|---|---|
| Operator drop instructions | `00_README/WPE_BATCH_001_OPERATOR_DROP_INSTRUCTIONS_20260503.md` | Human checklist before copying emails. |
| Source manifest template | `00_README/WPE_BATCH_001_SOURCE_MANIFEST_TEMPLATE_20260503.tsv` | One row per source export or frozen original. |
| Attachment manifest template | `03_attachments_native/WPE_BATCH_001_ATTACHMENT_MANIFEST_TEMPLATE_20260503.tsv` | Parent-child link between email and attachment. |
| Privilege screen queue | `04_privilege_screen/WPE_BATCH_001_PRIVILEGE_SCREEN_QUEUE_TEMPLATE_20260503.tsv` | Privilege/sensitivity routing before merits review. |
| Issue tagging queue | `05_issue_tagged_review/WPE_BATCH_001_ISSUE_TAGGING_QUEUE_TEMPLATE_20260503.tsv` | Issue tags and target workbenches after privilege screen. |

## Source Drop Folders

| Folder | What Goes There | Rule |
|---|---|---|
| `01_originals_frozen/WPE-BATCH-001/01_wilson_pruitt_pre_closing/` | Emails leading up to closings. | Preserve original export format and names. |
| `01_originals_frozen/WPE-BATCH-001/02_wilson_pruitt_post_closing/` | Emails after closings. | Preserve original export format and names. |
| `01_originals_frozen/WPE-BATCH-001/03_report_transmission/` | Emails attaching/discussing inspection reports, notes, or comments. | Attachments stay linked to parent emails. |
| `01_originals_frozen/WPE-BATCH-001/04_dee_mcbee_case_i/` | Dee McBee surrendered Case I email set or copies. | Keep Case I provenance visible. |
| `01_originals_frozen/WPE-BATCH-001/05_terry_wilson_production/` | Terry Wilson production/authentication materials. | Keep production context with source copy. |
| `01_originals_frozen/WPE-BATCH-001/06_easement_title_crossing/` | Easement, title, crossing, DOT/GNRR-related emails. | Route to privilege screen before use. |
| `01_originals_frozen/WPE-BATCH-001/99_unsorted_hold/` | Anything relevant but not yet classified. | Do not analyze until sorted and hashed. |

## Accepted Source Formats

| Format | Status | Handling Rule |
|---|---|---|
| `.eml` | Preferred | Preserve native file, hash each file. |
| `.msg` | Preferred | Preserve native file, hash each file. |
| `.mbox` | Accept | Preserve mailbox export, hash whole file, later split only from a copy. |
| `.pst` / `.ost` | Accept | Preserve export as received; do not mutate source file. |
| PDF print | Fallback | Mark as `PDF-fallback`; do not treat as complete if native export exists. |
| Screenshots | Emergency fallback | Mark as `screenshot-fallback`; use only to identify source to pull. |

## Batch 001 Gate Sequence

| Step | Gate | Output | Promotion Allowed? |
|---:|---|---|---|
| 1 | Freeze originals | Original files copied to `01_originals_frozen/WPE-BATCH-001/` | No |
| 2 | Hash originals | Source manifest rows with SHA256 and bytes | No |
| 3 | Assign intake IDs | WPE IDs mapped to source rows | No |
| 4 | Attachment link | Attachment manifest rows | No |
| 5 | Privilege screen | Privilege queue status: source-controlled, privileged-hold, work-product-hold, settlement-sensitive, third-party-counsel-review | No, except source-controlled/counsel-approved |
| 6 | Issue tags | Issue tagging queue with target workbench and proof gate | No |
| 7 | Proof matrix route | Link to WP-GATE rows or existing evidence workbench | Maybe, only source-controlled facts |
| 8 | Promotion decision | `PROMOTE`, `HOLD`, or `REJECT` in register | Yes if `PROMOTE` and counsel/operator gates pass |

## Initial Issue Tag Map

| Source Family | Primary Tags | Target Workbench |
|---|---|---|
| Pre-closing Wilson Pruitt | `closing-delay`, `psa-repair-scope`, `professional-negligence-gate` | Closing delay chronology; PSA repair matrix; Wilson Pruitt proof matrix |
| Post-closing Wilson Pruitt | `post-closing-conduct`, `opposing-accusation`, `adverse-alignment`, `civil-conspiracy-gate` | Answer matrix; issue matrix; Wilson Pruitt proof matrix |
| Report transmission | `inspection-report`, `case-i-overlap`, `professional-negligence-gate` | Inspection source status; River Heights/Fish Trap addenda; Wilson Pruitt proof matrix |
| Dee McBee Case I | `inspection-report`, `case-i-overlap` | Case I-to-Case II overlap chart; inspection source status |
| Terry Wilson production | `psa-repair-scope`, `inspection-report`, `case-i-overlap`, `professional-negligence-gate` | Terry Wilson repair pin; PSA repair matrix; Wilson Pruitt proof matrix |
| Easement/title/crossing | `easement-title`, `post-closing-conduct`, `procedural-joinder-gate`, `privilege-waiver-gate` | Easement source map; DOT/GNRR source index; Wilson Pruitt proof matrix |

## Register Update Targets

Batch 001 should update these register rows when sources are available:

| Intake ID | Batch 001 Role | Current Expected Status After Source Copy |
|---|---|---|
| WPE-20260503-001 | Pre-closing Wilson Pruitt emails. | `FROZEN` after copy/hash. |
| WPE-20260503-002 | Post-closing Wilson Pruitt emails. | `FROZEN` after copy/hash. |
| WPE-20260503-003 | Inspection report transmission emails. | `FROZEN` after copy/hash. |
| WPE-20260503-004 | Dee McBee Case I email source set. | `FROZEN` after source copy/hash. |
| WPE-20260503-005 | Terry Wilson production/authentication lane. | `FROZEN` or `SOURCE-PENDING` depending on copy status. |
| WPE-20260503-006 | Easement/title/crossing emails. | `FROZEN` after copy/hash. |

## No-Go Rules

- Do not rename or edit originals after they are placed in `01_originals_frozen`.
- Do not generate review PDFs/text until the source hash exists.
- Do not detach attachments from parent emails without recording the parent WPE ID.
- Do not mix counsel communications into source-controlled rows until privilege screen labels them.
- Do not convert suspicion into pleading language. Convert it into a source row, issue tag, proof gate, or counsel question.
- Do not place email bodies in repo documents.


## Manifest Generator

After source exports are copied into the Batch 001 frozen folders, run:

```bash
python3 tools/wpe_batch_manifest.py
```

Use `--dry-run` first if you only want to confirm the source count and planned output paths. The generator writes timestamped source, privilege-screen, and issue-tagging TSVs on NAS; all generated privilege rows start as `PENDING` and issue rows start as `HOLD`.

## Completion Definition

Batch 001 is complete when:

- Each copied source file has path, bytes, SHA256, source family, and WPE ID.
- Attachments have parent-child links.
- Privilege status is marked for every source row.
- Issue tags are assigned only after privilege screen.
- Promotion candidates are routed to the evidence register and proof matrix.
- `HOLD` and `REJECT` rows explain why the item is not promoted.
