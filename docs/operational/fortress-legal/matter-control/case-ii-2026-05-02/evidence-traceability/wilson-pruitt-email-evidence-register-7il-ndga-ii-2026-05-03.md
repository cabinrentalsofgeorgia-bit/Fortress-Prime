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

## Intake Register

| Intake ID | Source Set | Date Range | From / Custodian | Subject / Descriptor | Attachments | SHA256 / Manifest | Privilege Status | Issue Tags | Target Workbench | Status | Next Action |
|---|---|---|---|---|---:|---|---|---|---|---|---|
| WPE-20260503-001 | Wilson Pruitt export | pre-closing | TBD | Closing lead-up emails | TBD | Pending | Pending | `closing-delay`, `psa-repair-scope` | Closing delay chronology; PSA repair scope | PULL | Export originals and hash. |
| WPE-20260503-002 | Wilson Pruitt export | post-closing | TBD | Post-closing conduct emails | TBD | Pending | Pending | `post-closing-conduct`, `opposing-accusation` | Case II issue matrix; answer matrix | PULL | Export originals and hash. |
| WPE-20260503-003 | Wilson Pruitt export | report transmission | TBD | Inspection-report transmission emails | TBD | Pending | Pending | `inspection-report`, `case-i-overlap` | River Heights inspection source status; inspection addenda | PULL | Export originals and hash. |
| WPE-20260503-004 | Dee McBee Case I emails | 2021 / Case I | TBD | Surrendered Case I report emails | TBD | Pending | Pending | `inspection-report`, `case-i-overlap` | Inspection source status; overlap chart | PULL | Locate source copies and link. |
| WPE-20260503-005 | Terry Wilson production / authentication | 2021-2025 | TBD | Amendment #2 / repair-reference email lane | TBD | Pending | Pending | `psa-repair-scope`, `inspection-report`, `case-i-overlap` | Terry Wilson repair pin; PSA matrix | PULL | Link existing source pins to parent emails if available. |
| WPE-20260503-006 | Wilson Pruitt export | easement/title | TBD | Easement/title/crossing emails | TBD | Pending | Pending | `easement-title`, `post-closing-conduct` | Easement source map; DOT/GNRR lanes | PULL | Export originals and hash. |

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

## Open Questions For Operator

| Question | Why It Matters | Status |
|---|---|---|
| What mailbox/export format is available: `.eml`, `.msg`, MBOX, PST, PDF print, Gmail/Outlook export? | Determines preservation path and metadata completeness. | Open |
| Are emails already copied on NAS? | Avoids duplicate export and lets us hash existing originals first. | Open |
| Are any emails from or to operator counsel mixed into the Wilson Pruitt set? | Privilege screen and segregation. | Open |
| Do attachments include inspection reports, repair lists, closing statements, title docs, or easement drafts? | Attachment issue tagging and promotion targets. | Open |
| Are Dee McBee and Terry Wilson email sets already separated by Case I source? | Needed for provenance and Case I-to-Case II overlap mapping. | Open |
