# Wilson Pruitt Email Evidence Register - 7IL Case II

Date: 2026-05-03
Classification: Repo-safe metadata register. Do not paste email bodies or privileged substance here.
Service status source: operator says not served as of 2026-05-03.

Purpose: track Wilson Pruitt email intake from raw export through custody, privilege screen, issue tagging, and evidence promotion.

## Status Codes

| Code | Meaning |
|---|---|
| `PULL` | Source still needs to be exported or collected. |
| `FROZEN` | Original saved in NAS originals folder and hashed. |
| `NORMALIZED` | Review copy generated from original. |
| `ATTACH-LINKED` | Attachments saved and linked to parent email. |
| `PRIV-SCREEN` | Privilege/sensitivity screen completed. |
| `TAGGED` | Issue tags assigned. |
| `PROMOTE` | Candidate for evidence matrix promotion. |
| `HOLD` | Privileged, sensitive, incomplete, duplicate, or needs counsel/operator review. |
| `REJECT` | Duplicate, irrelevant, corrupt, or outside scope. |


## Batch Control

| Batch ID | Source Families | NAS Intake Kit | Current Status | Next Action |
|---|---|---|---|---|
| WPE-BATCH-001 | Pre-closing, post-closing, report transmission, Dee McBee Case I, Terry Wilson production, easement/title/crossing | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/incoming/wilson-pruitt-email-intake-20260503/00_README/WPE_BATCH_001_OPERATOR_DROP_INSTRUCTIONS_20260503.md` | Ready for operator source drop | Copy source exports into Batch 001 folders, then hash and fill source manifest. |

## Intake Register

| Intake ID | Source Set | Date Range | From / Custodian | Subject / Descriptor | Attachments | SHA256 / Manifest | Privilege Status | Issue Tags | Target Workbench | Status | Next Action |
|---|---|---|---|---|---:|---|---|---|---|---|---|
| WPE-20260503-001 | Wilson Pruitt export | pre-closing | TBD | Closing lead-up emails | TBD | Pending | Pending | `closing-delay`, `psa-repair-scope`, `professional-negligence-gate` | Closing delay chronology; PSA repair scope; Wilson Pruitt proof matrix | PULL | Export originals and hash. |
| WPE-20260503-002 | Wilson Pruitt export | post-closing | TBD | Post-closing conduct emails | TBD | Pending | Pending | `post-closing-conduct`, `opposing-accusation`, `adverse-alignment`, `civil-conspiracy-gate` | Case II issue matrix; answer matrix; Wilson Pruitt proof matrix | PULL | Export originals and hash. |
| WPE-20260503-003 | Wilson Pruitt export | report transmission | TBD | Inspection-report transmission emails | TBD | Pending | Pending | `inspection-report`, `case-i-overlap`, `professional-negligence-gate` | River Heights inspection source status; inspection addenda; Wilson Pruitt proof matrix | PULL | Export originals and hash. |
| WPE-20260503-004 | Dee McBee Case I emails | 2021 / Case I | TBD | Surrendered Case I report emails | TBD | Pending | Pending | `inspection-report`, `case-i-overlap` | Inspection source status; overlap chart | PULL | Locate source copies and link. |
| WPE-20260503-005 | Terry Wilson production / authentication | 2021-2025 | TBD | Amendment #2 / repair-reference email lane | TBD | Pending | Pending | `psa-repair-scope`, `inspection-report`, `case-i-overlap`, `professional-negligence-gate` | Terry Wilson repair pin; PSA matrix; Wilson Pruitt proof matrix | PULL | Link existing source pins to parent emails if available. |
| WPE-20260503-006 | Wilson Pruitt export | easement/title | TBD | Easement/title/crossing emails | TBD | Pending | Pending | `easement-title`, `post-closing-conduct`, `procedural-joinder-gate`, `privilege-waiver-gate` | Easement source map; DOT/GNRR lanes; Wilson Pruitt proof matrix | PULL | Export originals and hash. |

## Attachment Manifest Placeholder

| Parent Intake ID | Attachment ID | Attachment Filename | Native Path | Bytes | SHA256 | Review Copy Path | Status |
|---|---|---|---|---:|---|---|---|
|  |  |  |  |  |  |  |  |

## Promotion Candidates

| Intake ID | Candidate Use | Evidence Workbench | Promotion Status | Required Before Promotion |
|---|---|---|---|---|
| WPE-20260503-001 | Closing delay / readiness / condition facts | Closing delay chronology | Pending | Original hash, privilege screen, date/source confirmation. |
| WPE-20260503-002 | Post-closing conduct / demand / accusation facts | Issue matrix / answer matrix | Pending | Original hash, privilege screen, source context. |
| WPE-20260503-003 | Inspection report origin and transmission | Inspection source status | Pending | Original hash, attachment hash, report-version match. |
| WPE-20260503-004 | Case I overlap / 2021 report provenance | Case I-to-Case II overlap chart | Pending | Source path, hash, production context. |
| WPE-20260503-005 | Amendment #2 repair-reference linkage | Terry Wilson repair pin / PSA matrix | Pending | Parent email link or production-authentication citation. |
| WPE-20260503-006 | Easement/title/crossing conduct and knowledge | Easement source map / DOT-GNRR source index | Pending | Privilege screen and source corroboration. |
| WPE-20260503-001 through WPE-20260503-006 | Wilson Pruitt professional-liability / adverse-alignment gates | Wilson Pruitt adverse-alignment proof matrix | Pending | Original hashes, privilege screen, duty/scope classification, procedural-route review, causation/damages proof. |

## Open Questions For Operator

| Question | Why It Matters | Status |
|---|---|---|
| What mailbox/export format is available: `.eml`, `.msg`, MBOX, PST, PDF print, Gmail/Outlook export? | Determines preservation path and metadata completeness. | Open |
| Are emails already copied on NAS? | Avoids duplicate export and lets us hash existing originals first. | Open |
| Are any emails from or to operator counsel mixed into the Wilson Pruitt set? | Privilege screen and segregation. | Open |
| Do attachments include inspection reports, repair lists, closing statements, title docs, or easement drafts? | Attachment issue tagging and promotion targets. | Open |
| Are Dee McBee and Terry Wilson email sets already separated by Case I source? | Needed for provenance and Case I-to-Case II overlap mapping. | Open |
