# Wilson Pruitt Email Intake Protocol - 7IL Case II

Date: 2026-05-03
Classification: Repo-safe email evidence intake control. Not a court filing, not legal advice, and not a merits summary.
Service status source: operator says not served as of 2026-05-03.

Purpose: control intake of Wilson Pruitt emails and attachments related to Case I, closings, post-closing conduct, inspection reports, easement/title issues, repair obligations, and communications leading up to and after the River Heights / Fish Trap closings.

## Control Rule

Email originals are evidence sources, not drafting material. Do not summarize, quote, or rely on an email until the original/export is saved, hashed, deduped, privilege-screened, attachment-linked, and mapped to an issue tag in the register.

## Intake Lanes

| Lane | Use | Repository Status |
|---|---|---|
| Originals | Raw `.eml`, `.msg`, mailbox export, PDF print, or source screenshots as received. | NAS only; hash before use. |
| Normalized exports | Searchable PDF/text version generated from originals for review. | NAS only unless sanitized excerpt is later promoted. |
| Attachments | Native attachments saved separately with parent email link. | NAS only; hash separately. |
| Privilege screen | Attorney-client/work-product risk, third-party waiver risk, counsel communications, settlement/protected communications. | NAS privileged review; repo gets only status labels. |
| Evidence register | Repo-safe metadata, issue tags, custody status, and next action. | Repo-safe, no email substance. |

## Required Folder Layout

Create or use this NAS layout:

```text
/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/incoming/wilson-pruitt-email-intake-20260503/
  00_README/
  01_originals_frozen/
  02_normalized_exports/
  03_attachments_native/
  04_privilege_screen/
  05_issue_tagged_review/
  06_promoted_evidence/
  07_rejects_duplicates_irrelevant/
```

## Intake Steps

1. Save original email exports without editing filenames or message bodies.
2. Hash every original before opening for substantive review.
3. Assign an intake ID: `WPE-YYYYMMDD-###`.
4. Extract metadata: source mailbox/account, sent date, from, to/cc/bcc if available, subject, attachment count, original path, hash.
5. Save attachments separately and record parent intake ID.
6. Generate normalized review copies only after originals are frozen.
7. Run privilege screen before issue analysis.
8. Tag by issue family and complaint/count relevance.
9. Promote only source-controlled, non-duplicate, non-privileged items into evidence workbenches.
10. Record all exclusions: duplicate, irrelevant, privileged, unreadable, incomplete, or needs operator context.

## Issue Tags

| Tag | Meaning | Example Use |
|---|---|---|
| `closing-delay` | Communications about timing, obstruction, readiness, conditions, closing logistics. | Closing chronology and waiver/reservation inventory. |
| `post-closing-conduct` | Communications after closing about conduct, demands, repairs, easement, access, or accusations. | Case II continuation / conduct theory mapping. |
| `inspection-report` | Inspection reports, notes, attachments, comments, summaries, or transmission emails. | River Heights / Fish Trap source control and Exhibit G/H analysis. |
| `psa-repair-scope` | PSA repair obligations, seller-fix lists, closing conditions, repair credits, amendment language. | PSA repair obligation matrix. |
| `easement-title` | Easement drafting, title exceptions, crossing, deed, survey, access, railroad/GDOT issues. | Easement validity and DOT/GNRR lanes. |
| `case-i-overlap` | Communications tying 2021 Case I evidence or productions to Case II allegations. | Case I-to-Case II overlap chart. |
| `opposing-accusation` | Plaintiff-side accusations or threat framing. | Answer matrix and count-to-evidence map. |
| `counsel-review` | High-sensitivity item requiring lawyer review before use. | Counterclaim or privilege-risk lane. |

## Privilege / Sensitivity Screen

| Screen | Hold If Yes | Repo-Safe Label |
|---|---|---|
| Attorney-client communication involving Gary, operator counsel, or legal advice | Hold in privileged NAS review. | `privileged-hold` |
| Work-product draft, strategy note, legal research, or counsel mental impressions | Hold in privileged NAS review. | `work-product-hold` |
| Settlement/compromise communication or mediation-sensitive content | Hold for counsel review. | `settlement-sensitive` |
| Third-party counsel email that may include protected content | Hold for counsel review. | `third-party-counsel-review` |
| Pure business/transaction email without legal advice | May proceed after source control. | `source-controlled` |

## Promotion Gate

An email may be promoted into an evidence matrix only if:

- Original/export is saved in `01_originals_frozen`.
- SHA256 hash is recorded.
- Parent/attachment links are recorded.
- Duplicate status is resolved.
- Privilege status is `source-controlled` or counsel-approved.
- Issue tags are assigned.
- Operator context needed is resolved or logged.
- The promoted use is phrased as a source lead, not a legal conclusion.

## No-Go Rules

- No copy/paste of email body into repo unless separately sanitized and approved.
- No privileged counsel communications in repo.
- No attachment used without parent email link.
- No PDF print treated as complete if native `.eml` / `.msg` exists and has not been captured.
- No timeline fact promoted from email without sent date and source hash.
- No inference that an email proves a legal element until counsel/operator review assigns that use.

## Immediate Intake Targets

| Target | Why It Matters | Status |
|---|---|---|
| Wilson Pruitt emails leading up to closings | Closing delay, readiness, conditions, repair scope, reservation/waiver evidence. | Pull / export pending. |
| Wilson Pruitt emails after closings | Post-closing conduct, demands, accusations, easement/title behavior, continuation theory. | Pull / export pending. |
| Emails attaching or discussing inspection reports | Establish origin, date, sender, recipients, report version, PSA/judgment scope. | Pull / export pending. |
| Dee McBee surrendered emails from Case I | Source-proven Case I overlap and 2021 inspection/report transmission lane. | Source locate / link pending. |
| Terry Wilson production emails or authentication materials | Amendment #2, repair reference, report origin, closing scope. | Existing source pins need email intake linkage. |

## Output Expectations

The first pass should produce:

- A frozen original export set.
- SHA256 manifest.
- Attachment parent-child manifest.
- Repo-safe register rows.
- Privilege hold list for counsel/operator review.
- Promotion candidates for closing delay, inspection-report origin, PSA repair scope, easement/title, and post-closing conduct workbenches.
