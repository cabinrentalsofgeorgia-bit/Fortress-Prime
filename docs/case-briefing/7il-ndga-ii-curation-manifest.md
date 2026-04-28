# 7il-v-knight-ndga-ii — Curation Manifest

**Case slug**: `7il-v-knight-ndga-ii`
**Case number**: 2:26-cv-00113-RWS
**Court**: U.S. District Court, Northern District of Georgia, Gainesville Division
**Judge**: Hon. Richard W. Story
**Filed**: 2026-04-15
**Last updated**: 2026-04-27

Curated evidentiary set for attorney briefing. Each item carries source provenance, identification rationale, and OCR/text-extracted facts where applicable.

---

## Curation Scope

Case II covers **TWO** properties. Evidence curation must surface materials related to either or both:

- **92 Fish Trap Road, Blue Ridge GA** ("Fish Trap Property")
- **253 River Heights Road, Blue Ridge GA** ("River Heights Property")

5 of 8 counts implicate River Heights — the unauthorized easement claim is the centerpiece of this lawsuit, not the driveway encroachment at Fish Trap.

When re-bucketing remaining vault docs, search for both:
- **Fish Trap variants**: "fish trap", "92 fish trap", "fishtrap", "92-fish-trap"
- **River Heights variants**: "river heights", "253 river heights", "river-heights", "253 river"
- **Property records**: BK 1654 PG 230-231 (River Heights Warranty Deed) and BK 1654 PG 262-263 (Fish Trap Warranty Deed), Fannin County Clerk of Superior Court

---

## Curation Summary

- **12 Case II documents curated** (operative complaint + 10 exhibits + civil cover sheet)
- **1 Exhibit MISSING** (Exhibit G — 2025 River Heights Inspection) — outbound to Thor James pending
- **52 Case II emails curated** (recovered from `legal_vault/vanderburge-v-knight-fannin/` mis-routing)
- **70 Case I context documents curated** (pleadings, LOAs, dispositive motion practice, depo exhibits, transcripts)

**Grand total: 134 files curated.**

All curated PDFs sourced from a 5-email forward by co-defendant **Thor James** (`sigma.thorjames@gmail.com`) on **2026-04-23 12:38–12:47 EDT**, originating from federal court ECF Document 1 (the operative complaint and its 12 exhibits) for civil action `2:26-cv-00113-RWS`.

---

## Operative Pleadings (Case II)

### Complaint_7IL_v_Knight_James_NDGA-II.pdf

- **Source eml**: `_INBOX_PULL_20260424/20260423_164430_sigma-thorjames-gmail-com_lawsuit.eml`
- **Original attachment**: `01 a.pdf` (renamed `01_a.pdf` for filesystem safety)
- **ECF reference**: Document 1 (the operative complaint)
- **Pages**: 18
- **Size**: 225,836 bytes
- **Why curated**: Operative pleading served against operator. Defines parties, claims, exhibits, prayer for relief.
- **Key facts extracted** (full text in `/home/admin/Fortress-Prime/scratch/case-ii-source-docs/complaint.txt`):
  - 76 numbered paragraphs, 8 causes of action, jury trial demanded
  - Counts: I Breach of Contract (Knight only); II Slander of Title (both); III Declaratory Relief (both); IV Quiet Title / Quia Timet O.C.G.A. § 23-3-40 (both); V Injunctive Relief (both); VI Ejectment O.C.G.A. § 44-11-1 (Knight only, driveway encroachment); VII Breach of Warranty of Title (Knight only); VIII Attorneys' Fees O.C.G.A. § 13-6-11 (both)
  - Plaintiff's counsel: Brian S. Goldberg, GA Bar 128007, Andrew Pinter, **Buchalter LLP**, 3475 Piedmont Rd NE Suite 1100, Atlanta GA 30305, (404) 832-7667, bgoldberg@buchalter.com

---

## Complaint Exhibits (Case II)

### Exhibit_A_Case-I_Doc134_Specific_Performance_Order.pdf

- **Source eml**: `lawsuit.eml`
- **Original attachment**: `01-1.pdf`
- **ECF reference**: Document 1-1 (Exhibit A to complaint)
- **Pages**: 2
- **Size**: 120,085 bytes
- **Why curated**: Case I order [Doc 134] referenced in complaint ¶ 9 — establishes plaintiff's superior rights and triggers Case II's "post-judgment misconduct" framing.
- **Source case**: 2:21-cv-00226-RWS (Case I)

### Exhibit_B_Case-I_Doc135_Final_Judgment.pdf

- **Source eml**: `lawsuit.eml`
- **Original attachment**: `01-2.pdf`
- **ECF reference**: Document 1-2 (Exhibit B to complaint)
- **Pages**: 1
- **Size**: 207,827 bytes
- **Why curated**: Case I final judgment from jury trial, Hon. Richard W. Story presiding. Anchor for Case II's enforcement and ancillary jurisdiction theory.
- **Source case**: 2:21-cv-00226-RWS (Case I)

### Exhibit_C_River_Heights_PSA.pdf

- **Source eml**: `lawsuit.eml`
- **Original attachment**: `01-3.pdf`
- **ECF reference**: Document 1-3 (Exhibit C)
- **Pages**: 21
- **Size**: 5,279,256 bytes
- **Why curated**: River Heights Property Purchase & Sale Agreement (signed via dotloop, JHT 03/13/21, Bates Knight 000082+). Operative contract whose post-judgment breach is alleged in Count I.

### Exhibit_D_Fish_Trap_PSA.pdf

- **Source eml**: `email-2.eml`
- **Original attachment**: `01-4.pdf`
- **ECF reference**: Document 1-4 (Exhibit D)
- **Pages**: 17
- **Size**: 3,675,561 bytes
- **Why curated**: Fish Trap Property PSA (signed via dotloop, JHT 04/01/21, Bates Knight 000065+). Companion contract to Exhibit C.

### Exhibit_E_2021_Inspection_River_Heights.pdf

- **Source eml**: `email-2.eml`
- **Original attachment**: `01-5.pdf`
- **ECF reference**: Document 1-5 (Exhibit E)
- **Pages**: 121
- **Size**: 9,400,358 bytes
- **Why curated**: Pre-closing inspection (April 2021) of River Heights, identifying deficiencies Knight allegedly agreed to repair under the PSA. Bates Knight 000184+. Compared against Exhibit G (missing — 2025 inspection) to establish Count I damages.

### Exhibit_F_2021_Inspection_Fish_Trap.pdf

- **Source eml**: `email-3.eml`
- **Original attachment**: `01-6.pdf`
- **ECF reference**: Document 1-6 (Exhibit F)
- **Pages**: 121
- **Size**: 11,281,802 bytes
- **Why curated**: Pre-closing inspection (April 2021) of Fish Trap by Pugh Home Inspections (Titus Pugh) for John Thatcher. Companion to Exhibit E.

### Exhibit_G — MISSING

- **Status**: NOT IN POSSESSION
- **ECF reference**: Document 1-7
- **Expected content**: 2025 Inspection — River Heights Property (May 2025 Pugh inspection, companion to Exhibit H)
- **Reason missing**: Thor James forwarded ECF docs 1-1 through 1-12 across 5 emails on 2026-04-23, with `01-7.pdf` absent from all 5. No copy in `_INBOX_PULL_20260424/`.
- **Action item**: Outbound request drafted at `outbound-thor-james-exhibit-g-draft.md` — operator to send from personal email. Alternative: pull from federal ECF directly (requires PACER account or attorney of record).

### Exhibit_H_2025_Inspection_Fish_Trap.pdf

- **Source eml**: `fwd-7-il-properties-llc-v-gary-knight-th.eml`
- **Original attachment**: `01-8.pdf`
- **ECF reference**: Document 1-8 (Exhibit H)
- **Pages**: 162
- **Size**: 18,551,171 bytes
- **Why curated**: 2025 inspection of Fish Trap (Pugh Home Inspections, Titus Pugh, May 14 2025, address listed as 92 Fish Trap Road, Mineral Bluff GA). Compared against Exhibit F to establish Count I damages.

### Exhibit_I_Unauthorized_Easement_2025-03-17.pdf

- **Source eml**: `email-4.eml`
- **Original attachment**: `01-9.pdf`
- **ECF reference**: Document 1-9 (Exhibit I)
- **Pages**: 5
- **Size**: 391,483 bytes
- **Why curated**: The recorded "Unauthorized Easement" — central to Counts II–V. OCR-extracted facts:
  - Recorded **2026-03-17** at Fannin County Clerk of Superior Court (DANA CHASTAIN)
  - Title: "Easement Agreement"
  - Fee: $25.00
  - Image-only PDF (recorded instrument scan)
- **Note**: Per complaint ¶ 21, Knight executed and recorded this in favor of Thor James after the federal court ordered specific performance.

### Exhibit_J_Warranty_Deed_River_Heights_2025-06-02.pdf

- **Source eml**: `email-4.eml`
- **Original attachment**: `01-10.pdf`
- **ECF reference**: Document 1-10 (Exhibit J)
- **Pages**: 2
- **Size**: 1,557,328 bytes
- **Why curated**: Limited Warranty Deed conveying River Heights to plaintiff (per Count IV / Count VII). OCR-extracted facts:
  - Recorded **2025-06-02 11:02 AM**, Fannin County
  - BK 1654, PG 230-231
  - Fee Amt: $954.00, Transfer Tax: $929.00 (implies ~$929,000 consideration)
  - Closing attorney: Wilson Pruitt LLC, 316 Summit Street, Blue Ridge GA. File No. 25-0170.

### Exhibit_K_Warranty_Deed_Fish_Trap_2025-06-02.pdf

- **Source eml**: `email-4.eml`
- **Original attachment**: `01-11.pdf`
- **ECF reference**: Document 1-11 (Exhibit K)
- **Pages**: 2
- **Size**: 1,660,858 bytes
- **Why curated**: Warranty Deed conveying Fish Trap to plaintiff (per Count VI Ejectment). OCR-extracted facts:
  - Recorded **2025-06-02 1:23 PM**, Fannin County (same day, ~2 h after River Heights)
  - BK 1654, PG 262-263
  - Fee Amt: $875.00, Transfer Tax: $850.00 (implies ~$850,000 consideration)
  - Closing attorney: Wilson Pruitt LLC

---

## Civil Cover Sheet (Case II)

### Civil_Cover_Sheet_JS44.pdf

- **Source eml**: `email-4.eml`
- **Original attachment**: `01-12.pdf`
- **ECF reference**: Document 1-12 (JS44 NDGA civil cover sheet — not a complaint exhibit)
- **Pages**: 2
- **Size**: 344,612 bytes
- **Why curated**: Federal court initial cover sheet. Establishes Plaintiff (7 IL Properties LLC) and Defendants (Gary Knight + Thor James) as filed.

---

## Curation Notes

- **Two-property scope confirmed via complaint text** — `nas_layout` field in `legal.cases` only references one inbox path; should be expanded to acknowledge River Heights materials may live separately on NAS.
- **Closing date discovery**: complaint references "May 2025, immediately prior to closing" but never gives the actual date. Recorded deeds confirm **closing date 2026-06-02**.
- **Total transaction value**: ~$1.78M (River Heights $929K + Fish Trap $850K, derived from transfer tax × 1000).
- **Closing attorney**: Wilson Pruitt LLC (Blue Ridge GA) prepared both deeds. Not opposing counsel — was Knight-side closing counsel.
- **Counsel metadata drift**: `legal.cases.opposing_counsel` carries an outdated value pointing to Freeman Mathis & Gary LLP. Real plaintiff's counsel per signature block is Buchalter LLP. Tracked in issues-log T8.
- **Bates numbering**: plaintiff's exhibit production uses Bates `Knight 000065` through at least `Knight 000184+` — coordinated, comprehensive set, suggests pre-litigation discovery prep.
- **Email-as-service-vector observation**: operative pleading and exhibits arrived only via Thor James (co-defendant) personal Gmail forwards. No direct service to operator visible in the inbox dump. ECF/PACER pull would be the canonical alternative source.

---

## Case II Emails — Recovered from Vanderburge Mis-routing

52 emails substantively about Case II events (closing, easement drafting, repairs, counsel search) were stored under `legal_vault/vanderburge-v-knight-fannin/` instead of under a Case II case slug. Captain's classifier picked the wrong matter at ingest. Each item is preserved at its original path **and** copied here with a `.metadata.json` sidecar capturing original_path + relocation_reason + sha256 prefix + cluster + operator_confirmed_at timestamp.

**Destination**: `curated/emails/from-vanderburge-misroute/`

**By cluster** (all 2025-04 unless noted):
- **Closing-cycle** (9): `closing-for-92-fishtrap-and-253-riverhei` + 8 fwd/re variants
- **Easement drafting** (12): `easement-draft`, `easement-agreement` (2024 + 2025), `revised-easement-agreement-between-thor-`, `new-easement-agreement-for-lots-14-15-16`, `water-easement-agreement-needs-some-refi`, `re-water-easement-agreement-needs-some-r`, `word-doc-for-easement-agreement`, `easements-2`, `addresses-and-easement-agreement` (2024), `creating-an-easement-agreement` (2024), `easement-agreement-for-180-or-290-river-` (2022)
- **Outstanding repairs + easement issues** (5): all fwd/re variants of the same thread
- **7IL request to confirm closing / 7-IL-properties-LLC-Gary-Knight-purch** (11): fwd/re variants
- **Strategy / counsel search** (8): `re-williams-teusink-attorney-referral`, `re-possible-representation-versus-7-il-p`, `would-you-handle-a-seller-side-of-a-tran`, `part-2-federal-case-for-specific-perform`, `re-is-this-the-smoking-gun`, `re-dismissal-form`, `re-conflict-notice` (×2 representative)
- **Summary** (3): `92-fishtrap-and-253-riverheights` + 2 re-
- **Older context** (4): `100-fish-trap-road-closing` (2021), `re-7il-properties-v-knight` (2022), `re-spam-re-river-heights` (2021), `fwd-branch-knight-100-fish-trap-road-blu` (2022)

**Why curated**: these emails establish (a) operator's contemporaneous role in pre-closing easement drafting (relevant to Counts II–V), (b) operator's repair-issue communications (relevant to Count I), (c) operator's pro-se / counsel-search posture pre-suit, (d) historical PSA + closing context.

**Original files preserved** in `legal_vault/vanderburge-v-knight-fannin/` — do not delete. Phase 11 systematic re-routing remains pending.

---

## Case I Counsel Continuity — Findings (T8 mystery resolved)

Reading Case I LOAs (Letters of Appearance) explains the `legal.cases.opposing_counsel` drift documented in T8 (GH #262):

| Case I LOA | Date | Counsel | Firm | Email |
|---|---|---|---|---|
| #19 | 2022-02-16 | Brian S. Goldberg (GA Bar 128007) | **Freeman Mathis & Gary, LLP** | brian.goldberg@fmglaw.com |
| #43 | 2023-01-13 | Brian S. Goldberg | (still FMG, unchanged) | brian.goldberg@fmglaw.com |
| #60 | 2023-10-11 | F. Podesta | **FGP Law, LLC** (Roswell GA) | fpodesta@fgplaw.com |
| #72 | 2024 | Brian S. Goldberg | (FMG era) | brian.goldberg@fmglaw.com |
| #83 | 2024-03-12 | Brian S. Goldberg | (FMG era) | brian.goldberg@fmglaw.com — caption: **"7 IL Properties of Georgia, LLC"** (renamed from 7 IL Properties LLC) |
| #88 | 2024+ | Sanker | (firm tbd) | — |

**Resolution**: The DB row for `7il-v-knight-ndga-ii.opposing_counsel` was populated from Goldberg's Case I-era affiliation (FMG / fmglaw.com) — likely copy-pasted when the Case II row was first created. The 2026-04-15 Case II complaint signature shows Goldberg moved to **Buchalter LLP** (bgoldberg@buchalter.com) — a firm move sometime between 2024 and 2026. T8 (#262) covers correcting this drift + JSONB schema migration.

**Plaintiff entity rename**: at some point between 2022 and 2024, "7 IL Properties, LLC" became "7 IL Properties of Georgia, LLC". Case II's complaint caption uses "7 IL Properties, LLC" again — possibly reverted, possibly an oversight in the complaint. Worth verifying via Georgia Secretary of State entity records.

---

## Case I Context — Pleadings

`curated/documents/case-i-context/01_pleadings/` (6 files)

| File | Original | Why curated |
|---|---|---|
| `01_Complaint.pdf` | `# Pleadings - GAND/#1 Complaint.pdf` | Case I operative complaint (2:21-cv-226) — establishes the prior litigation Case II builds on |
| `05_Affidavit_of_Service.pdf` | `#5 Affidavit of Service.pdf` | Service-of-process template (Case II's missing service record will likely follow this format) |
| `07_Answer_and_Counterclaim.pdf` | `#7 Answer & Counterclaim.pdf` | **Knight's Case I answer — direct template for Case II response** |
| `08_First_Amended_Complaint.pdf` | `#8 First Amended Complaint.pdf` | 7IL's amended pleading — establishes how plaintiff reframed claims |
| `11_Answer_to_FAC.pdf` | `#11 Answer to First Amended Complaint.pdf` | Knight's amended answer — secondary template |
| `13_Joint_Preliminary_Statement.pdf` | `#13 Joint Preliminary Statement.pdf` | Joint discovery plan — shows scope of Case I discovery |

## Case I Context — LOAs (Counsel Continuity)

`curated/documents/case-i-context/01_pleadings/loas/` (20 files)

All Letters of Appearance, Entry/End-of-Appearance, Notices of Withdrawal, Conflict Notices, and post-trial counsel notices from the Case I docket. Used to (a) reconstruct counsel timeline for both sides, (b) verify firm/email of opposing counsel at any point in time, (c) feed T8 corrections.

LOA filenames preserved (with `#` prefix stripped + spaces normalized): `19_LOA_-_Goldberg`, `21_LOA_-_Underwood`, `28_LOA_-_Underwood`, `36_LOA_-_Underwood`, `40_LOA_-_Podesta`, `43_LOA_-_Goldberg`, `47_LOA_-_Podesta`, `52_LOA_-_Podesta`, `60_LOA_-_FGP`, `72_LOA_-_Goldberg`, `83_LOA_-_Goldberg`, `88_LOA_-_Sanker`, `80_EOA_-_ACP`, `87_EOA_-_Sanker`, `32_Notice_of_Withdrawal_-_Cashbaugh`, `98_Conflict_Notice_-_FGP`, `114_Conflict_Notice_-_Sanker`, `129_Notice_Knight_Counsel`, `130_Notice_7_IL_Counsel`, `131_Response_to_Notice_at_Doc._129`.

## Case I Context — Dispositive Motion Practice

`curated/documents/case-i-context/02_dispositive_motions/` (29 files)

Full Case I summary judgment record:
- **Knight's MSJ** (`63_GK_s_MSJ.pdf` + SOUF + 13 exhibits A–M including Thatcher Depo, Branch Depo, Wilson Depo, both 253 and 92 property packages, emails, texts)
- **7IL's MSJ** (`65_7IL_s_MSJ.pdf` + BIS + SOUF + 4 exhibits A–D including both deals + P&L)
- **Cross-RIOTs** (`70_RIOT_7_IL_MSJ`, `71_7_IL_RIOT_Knight_MSJ`, plus SOUF/ASOUF responses)
- **Reply briefs** (`75_7_IL_Reply_Brief`, `76_Knight_Reply_Brief`)
- `77_Mtn._for_Oral_Argument.pdf`

**Why curated**: Case II's complaint (Counts I, VI, VII especially) re-litigates issues that Knight's Case I MSJ + 7IL's responses already addressed. The MSJ briefing is a roadmap of what was decided vs what remained for trial — both relevant to Case II's ancillary-jurisdiction theory and Knight's potential res judicata / collateral estoppel defenses.

## Case I Context — Judgment & Orders

`curated/documents/case-i-context/03_judgment_and_orders/` (2 files)

| File | Why curated |
|---|---|
| `14_Scheduling_Order.pdf` | Case I scheduling — sets baseline for what Case II's scheduling will look like |
| `78_Order_on_MSJs.pdf` | **The dispositive ruling that disposed of summary-judgment claims and shaped what went to trial.** Likely contains the legal reasoning about Knight's repair obligations / easement claims that Case II now invokes via "ancillary jurisdiction to enforce". |

> Doc 134 (specific performance order) and Doc 135 (final judgment) from Case I are already in the curated set as Case II's **Exhibit A** and **Exhibit B** (`02_complaint_exhibits/`). Not duplicated here.

## Case I Context — 7IL Deposition Exhibits

`curated/documents/case-i-context/04_deposition_exhibits_7il/` (8 files)

The high-relevance exhibits from the Case I 7IL deposition (the deponent was John Thatcher, 7IL's principal):

| File | Original | Why curated |
|---|---|---|
| `Exh._B_2021.03.07_Thor_James_Easement.pdf` | depo Exh. B | **The original 2021 Thor James easement** — likely the model / pattern for Case II's disputed 2025 unauthorized easement |
| `Exh._C_2021.03.07_Thor_James_Water_Easement.pdf` | depo Exh. C | Companion water easement to Exh. B |
| `Exh._F_2021.04.02_92_Fishtrap_Deal_Complete.pdf` | depo Exh. F | Full 2021 92 Fish Trap deal package |
| `Exh._H_2009.10.30_Toccoa_Heights_Plat.pdf` | depo Exh. H | Subdivision plat — context for the boundary / encroachment dispute |
| `Exh._I_2021.05.31_Preliminary_Survey.pdf` | depo Exh. I | Survey identifying driveway encroachment (Count VI ejectment foundation) |
| `Exh._K_2021.05.31_92_Fishtrap_Emails.pdf` | depo Exh. K | Pre-closing email thread (2021 cycle) |
| `Exh._L_2021.05.31_Easement_Emails.pdf` | depo Exh. L | Easement-specific email thread |
| `Exh._M_2021.06.01_Proposed_HUD-1.pdf` | depo Exh. M | First-cycle HUD-1 (closing artifact, Count I baseline) |

## Case I Context — Deposition Transcripts

`curated/documents/case-i-context/09_depositions/`

`thatcher/` (2 files):
- `Thatcher_John_2023-07-31.ptx` — vendor ASCII transcript of plaintiff principal John Thatcher
- `Thatcher_Depo_Original_Vendor_Download.zip` — full vendor bundle (multiple format variants, exhibits)

`knight/` (2 files):
- `Knight_Gary_Deposition_Transcript.pdf` — operator's own Case I deposition (PDFTran format)
- `Knight_Depo_Exhibits_Original_Bundle.zip` — full vendor bundle of Knight depo exhibits

**Why curated**: Knight's own Case I testimony is reusable as factual context for Case II. Thatcher's testimony is the plaintiff principal's prior sworn statements — invaluable for impeachment if Case II goes to deposition / trial.

## Case I Context — PSAs (2021 cycle)

`curated/documents/case-i-context/05_psas_2021/` (1 file)

| File | Why curated |
|---|---|
| `2021-07-02_Notice_of_Seller_Breach_of_PSA.pdf` | Establishes that PSA-breach communication pattern existed in 2021 — shows opposing-counsel didn't issue this notice (operator did, alleging buyer breach) — useful for context on which side has historically claimed breach. |

> The 2021 signed PSAs themselves (Exhibits C, D in Case II's complaint) are already in `02_complaint_exhibits/` from Phase 5. Not duplicated here.

---

## Subdirectories Pending Population

These directories were created but are empty pending operator-selected content from the larger Case I record:

- `06_easements_2021/` — 17+ candidates in `legal_vault/7il-v-knight-ndga/` (Foot Path, Recorded Easement, Recorded Water Easement, Proposed Easement #64-10/#64-13, etc.) — not auto-curated; brief generator will primarily reference Case II's Exhibit I (the 2025 unauthorized easement) and Case I depo Exh. B/C (already curated).
- `07_surveys/` — 10+ candidates (#64-9 Preliminary Plat, Padrutt Plat, Toccoa Heights Plat, Survey Invoice, Alpha Surveying); 1 already curated as depo Exh. I (Preliminary Survey 2021.05.31).
- `08_discovery/` — Case I has 14 discovery subdirs (`2023.01.24 7IL Production`, `2024.03.22 Knight Production`, `Documents Produced by Dee McBee`, `Documents Produced by Terry Wilson`, `Records - GAND`, etc.) — not curated; selectively pull in if Case II discovery scope grows.
- `10_findings_conclusions/` — Doc 134/135 already curated as Case II Exhibits A/B; if Case I had separate written findings of fact / conclusions of law (typically embedded in Order on MSJs at #78 or in a post-trial order), they're inside files already curated.
