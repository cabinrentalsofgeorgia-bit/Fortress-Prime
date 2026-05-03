# Wilson Pruitt Public-Record Check Workbench - 7IL Case II

Date: 2026-05-03
Operator service status: not served as of 2026-05-03
Classification: Repo-safe public-record verification workflow. Not legal advice and not a litigation-history conclusion.

## Purpose

This workbench answers, in a repeatable way, whether Terry Wilson, Wilson Pruitt, or related entities have been sued, countersued, disciplined, or named in public litigation records from 2020-present. It prevents Fortress Legal from relying on search snippets, name collisions, or incomplete web-indexed results.

## Search Subjects

| Subject | Variants To Check | Notes |
|---|---|---|
| Terry Wilson | Terry Wilson; Terry Lee Wilson; Terry L. Wilson | Confirm exact bar/profile identity before treating a hit as responsive. |
| Wilson Pruitt LLC | Wilson Pruitt; Wilson Pruitt, LLC; Wilson Pruitt Law | Firm entity and trade-name variants. |
| Terry Lee Wilson LLC | Terry Lee Wilson, LLC; Terry Wilson LLC | Possible related entity/name variant; verify before use. |
| Wilson Hamilton LLC | Wilson Hamilton; Wilson Hamilton LLC | Possible related firm/name variant; verify before use. |
| Firm lawyers/staff | Only source-backed names | Do not broaden without a reason. |

## Source Checklist

| Priority | Source | What To Check | Capture Standard | Status |
|---:|---|---|---|---|
| P1 | Fannin County Superior Court / Clerk index | Civil suits, counterclaims, third-party complaints, malpractice, title/closing disputes. | Caption, docket number, filing date, role, outcome, document source. | Open. |
| P1 | PACER / N.D. Ga. | Federal cases naming any subject since 2020. | Docket number, party role, nature of suit, key pleadings, outcome. | Open. |
| P1 | Georgia appellate opinions/orders | Appeals involving any subject or firm. | Case name, citation/docket, court, disposition, issue. | Open. |
| P1 | State Bar of Georgia membership/discipline sources | Discipline history, public orders, membership status. | Official profile/order citation only. | Open. |
| P2 | Neighboring county Superior Court indexes | Gilmer, Pickens, Union, and other counties if name/venue facts point there. | Same as Fannin. | Open. |
| P2 | Georgia Secretary of State entity search | Exact legal names, entity status, registered agent, historical names. | Entity control number and status date. | Open. |
| P2 | CourtListener / Justia / other web-indexed dockets | Supplemental search, not final authority. | Treat as lead only until docket/source verified. | Initial web-indexed scan found no confirmed responsive hit. |

## Result Log Template

| Date Checked | Source | Search Term | Hit? | Caption / Matter | Docket / ID | Subject Role | Filing Date | Outcome | Counterclaim / Third-Party? | Verification Status | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-05-03 | Public web-indexed search | Terry Wilson / Wilson Pruitt variants | No confirmed responsive hit | N/A | N/A | N/A | N/A | N/A | No confirmed counterclaim found | Lead-only; official checks open | Do not treat as no-lawsuit clearance. |

## Outcome Codes

| Code | Meaning |
|---|---|
| `NO-CONFIRMED-HIT` | No responsive hit in the specific source checked; not a universal clearance. |
| `HIT-UNVERIFIED` | Possible name match; needs docket/profile/entity confirmation. |
| `FILED-PENDING` | Case appears active or unresolved. |
| `DISMISSED` | Case dismissed; capture with/without prejudice if available. |
| `SETTLED` | Settlement shown by docket or order; do not infer terms unless public. |
| `JUDGMENT` | Judgment entered; capture winner/loser and relief only from docket/order. |
| `COUNTERCLAIM-NAMED` | Subject was named in a counterclaim or crossclaim; capture pleading. |
| `THIRD-PARTY-NAMED` | Subject was impleaded or joined as third-party defendant. |
| `DISCIPLINE-HIT` | Public bar discipline/source hit; capture official order only. |

## Counterclaim-Specific Protocol

A case is not enough. To answer whether a subject was named in a countersuit, check the pleadings:

1. Complaint.
2. Answer.
3. Counterclaim.
4. Crossclaim.
5. Third-party complaint.
6. Amended pleadings.
7. Dismissal/settlement/judgment orders.

Record the exact pleading title and docket entry. Do not infer counterclaim status from case captions alone.

## Repo / NAS Handling

- Repo may store metadata, docket citations, official links, and hash values.
- NAS should store downloaded docket documents, courthouse exports, screenshots, and PDFs if obtained.
- Do not store raw privileged emails or counsel analysis in this public-record workbench.
- If a source is only a paid-access docket, record the access path and document ID without copying restricted content into repo.

## Initial Working Answer

As of 2026-05-03, there is no confirmed repo-safe public-record hit showing that Terry Wilson, Wilson Pruitt LLC, Terry Lee Wilson LLC, or Wilson Hamilton LLC was sued, countersued, or named in a counterclaim from 2020-present. That answer is provisional because official county/PACER/appellate/bar checks have not been completed.

Use this phrasing until the checklist is complete: `No confirmed hit in the sources checked so far; official record checks remain open.`

## Next Actions

1. Verify exact subject names through bar/profile/entity sources.
2. Check Fannin County first because the closing and property facts point there.
3. Check N.D. Ga. PACER because Case II is in federal court.
4. Check Georgia appellate and State Bar discipline sources.
5. If any hit appears, save source documents to NAS, hash them, and update the result log before using the fact in any workbench.
