# 7IL Properties v. Knight — Readiness Audit

**Date:** 2026-04-24
**Repo/Infra HEAD:** `main` at `fb19316481` (post-PR #164; nim-brain stopped 15:07 EDT; ingest_complete 15:12 EDT).
**Method:** Read-only. Filesystem enumeration via `find`/`du`, PDF text-extractability via `pdftotext -l 3`, Qdrant REST scroll (`/collections/*/points/scroll`, no vector reads, no writes), `systemctl`/`journalctl` inspection. No frontier-model calls, no Qdrant mutations, no service restarts.

**Redaction:** Personal names other than Brian Goldberg, Judge Story, and Gary Knight masked as `<NAME>`; email addresses other than opposing-counsel-identifying Goldberg email masked as `<EMAIL>`; no $ figures or SSNs surfaced in this report.

---

## One-paragraph bottom line

The 7IL Properties LLC v. Gary Knight case is the **Northern District of Georgia** civil action tried to jury verdict before **Hon. Richard W. Story, Senior U.S. District Judge**, with opposing counsel **Brian S. Goldberg, Esq.** of Freeman Mathis & Gary LLP (`brian.goldberg@fmglaw.com`). The complete case file — **196 pleadings through at least docket #131, 147 deposition artifacts (PDF + .ptx + video), 367 discovery items (~1.5 GB), 18 correspondence items, plus a 60-file / 0.6 GB sub-folder of trespass evidence videos** — sits on the NAS under `/mnt/fortress_nas/Corporate_Legal/Business_Legal/` (3.83 GB total) and is **mirror-duplicated** in `/mnt/fortress_nas/Business_Prime/Legal/` (6.65 GB; drifted). **Zero points of this case are in Qdrant** — the `legal_ediscovery` collection's 866 points are all for the unrelated Generali v. CROG Fannin County state insurance matter (slug `fish-trap-suv2026000013`). PDF text-extractability runs **70% on pleadings/depositions** but only **45% on discovery**, meaning approximately 200+ case PDFs need OCR before ingest. `legal_caselaw` has **2,711 chunks / 1,185 unique Georgia state-court opinions** — but **zero NDGA, zero 11th Circuit, zero SCOTUS**, so the precedent tier for this federal case is effectively absent. Single biggest gap: **the case file exists, but none of it is retrievable by the Fortress Legal weapon system today** — no vectors, no NDGA precedent, no judge-authored opinion corpus for Judge Story, no prior-case map for Goldberg beyond what sits inside this matter's own filings.

---

## Corpus 1 — 7IL v. Knight case file

**Primary path:** `/mnt/fortress_nas/Corporate_Legal/Business_Legal/`
**Mirror (drifted, not dedup'd):** `/mnt/fortress_nas/Business_Prime/Legal/` (+2.82 GB delta; 825 vs 823 files)

**Case identity (from pleading content):**
- Caption: **7IL Properties, LLC v. Gary Knight** (plus counterclaims/third-party practice involving `<NAME>` (Thatcher/Thacker) and others)
- Court: U.S. District Court, Northern District of Georgia ("GAND")
- Presiding: **Hon. Richard W. Story, Senior U.S. District Judge** (standing order at #0 Richard Story Standing Order.pdf; Electronics Order at #118 signed "RICHARD W. STORY, United States District Judge")
- Plaintiff counsel: **Brian S. Goldberg**, Freeman Mathis & Gary LLP, signature `/s/ Brian S. Goldberg`, `brian.goldberg@fmglaw.com` (LOAs at #19, #43, #72, #83)
- Case phase: **Tried to verdict** — docket includes #122 Jury Verdict Form, #116/117/119/120 Minute Entries, #121 Jury Charges, #125–128 exhibit lists (admitted/trial), post-trial through at least #131

### A. FILES (by type, primary path)

| Subdir | Files | Bytes | Notable types |
|---|---|---|---|
| `# Pleadings - GAND/` | **196** | **288 MB** | All PDFs (196 pleading PDFs #0–#131) |
| `Depositions/` | **147** | **792 MB** | 116 PDF, 8 txt, 7 ptx (Summation), 5 zip, 5 jpg, 3 heic, 2 docx, 1 .mov (2022.10.25 Video.mov) |
| `Discovery/` | **367** | **1.5 GB** | 205 PDF, 18 .msg, 12 PNG, 8 docx, 7 zip, 7 .eml, 4 rtf, 3 csv, 1 xlsx *(no mp4 in Discovery root — see "John Thacker Lawsuit" subfolder)* |
| `Correspondence/` | **18** | **39 MB** | 18 PDF |
| `attroney fees/` *(sic)* | **1** | **1.3 MB** | 1 PDF |
| `John Thacker Lawsuit/` | **60** | **904 MB** | 113 mp4 trespass evidence videos (dir dated Mar–Jul 2022) |
| `THATCHER LAWSUIT/` | **33** | **117 MB** | Image evidence (jpg/jpeg/heic/mov) |
| **TOTAL** | **823** | **3.83 GB** | |

Whole-tree extension histogram: `pdf 536, mp4 113, png 60, jpeg 31, msg 18, zip 12, docx 11, txt 8, ptx 7, jpg 7, eml 7, rtf 4, heic 3, csv 3, mov 2, xlsx 1`.

Key pleading anchors visible in filenames:
- **#0 Richard Story Standing Order.pdf** (judge's standing order)
- **#1 Complaint.pdf**, **#1-1 Civil Cover Sheet.pdf**, **#2 Summons.pdf**
- **#12 Defendant's Initial Disclosures.pdf**, **#13 Joint Preliminary Statement.pdf**, **#14 Scheduling Order.pdf**
- **#19, #43, #72, #83 LOA - Goldberg.pdf** (four letters of appearance)
- **#21, #28, #36 LOA - Underwood.pdf** (co-counsel or prior counsel — `<NAME>` masked)
- Discovery extension chain: **#25, #29, #33, #37 Joint Motions to Extend Discovery** with corresponding **#26, #30, #34, #38 Orders** by Judge Story
- **#49 Motion for Contempt.pdf**
- **#64-2 Knight Depo.pdf** (Gary Knight's deposition in the case) plus #64-5/6/7 Knight's responses to RFAs, Roggs, Supp. Roggs
- **#65 7IL's MSJ.pdf** + #65-1 BIS MSJ + #65-2 SOUF, answered by **#71 7 IL RIOT Knight MSJ.pdf** + #71-1 SOUF; **#76 Knight Reply Brief.pdf**
- **#101 Referral Order.pdf**, **#102 Minute Entry from PTC.pdf**, **#103 Order Setting Mediation.pdf**, **#104 Mediation Minute Entry.pdf**
- Trial phase: **#105–#128** — witness lists, exhibit lists, jury charges, admitted exhibits, verdict form
- **#129 Notice Knight Counsel.pdf**, **#131 Response to Notice at Doc. 129.pdf** (post-trial counsel-of-record changes)

Deposition artifacts (Depositions/ root):
- **Branch** dep (`9178716 Branch.Gary 012723` — full/index/mini/rsletter/AMICUS renderings + .ptx Summation file)
- **Walker** dep (`9227538 Walker.Adam 020723` — same multi-format rendering)
- **Knight** dep exhibits (`Knight Deposition/` subfolder — exhibits 1–24+ as separate PDFs, `5464474_*` + `GaryKnight_*`)
- **Thatcher** dep (referenced in `2023.07.31 7IL Thatcher Depo@SynoResource`, content subdir removed but Syno eaDir marker remains — **flag: resource file may be present only as Synology-sidecar metadata, content may have been deleted or moved**)

### B. SIZE + COUNT
Totals above. **3.83 GB across 823 files on the primary path; 6.65 GB / 825 on the drifted mirror.** The 2.82 GB delta between the two copies needs reconciliation before treating either as canonical.

### C. OCR STATUS (per-dir, 20-PDF random sample each)

| Subdir | Sample | Text-extractable | OCR-needed | % extractable |
|---|---|---|---|---|
| Whole case | 20/536 | 14 | 6 | **70%** |
| Depositions | 20/116 | 14 | 6 | **70%** |
| Discovery | 20/205 | 9 | 11 | **45%** |

Extrapolated: **~163 case PDFs need OCR** (30% of 536) with Discovery as the concentration (~113 of those in Discovery alone). Example image-only PDFs from sample: `Exh. K - 2021.05.31 92 Fishtrap Emails.pdf`, `Exh. I - 2021.05.31 Preliminary Survey.pdf`, `2021.06.18 Rec Not of K 92 Fish Trap Book1435 P131.pdf`, `Plaintiff_000431.pdf`, `CFS - Unit Response Times 4.pdf`.

### D. EXISTING INGESTION

**Zero.** `legal_ediscovery` (866 points) distribution:

| case_slug | points |
|---|---|
| `fish-trap-suv2026000013` (**Generali v. CROG**, Fannin County Superior Court — different case) | 859 |
| `smoke-test-case` | 5 |
| `live-curl-case` | 1 |
| `affidavit-filing` | 1 |
| **7IL v. Knight** | **0** |

`legal_library` (3 points) also covers the Generali matter. `legal_hive_mind_memory` (4 points), `legal_headhunter_memory` (0 points) are effectively empty. **No part of the 7IL v. Knight corpus is vectorized.**

### E. GAPS
- **200+ PDFs need OCR** before ingest (see C). Largest gap in Discovery (~113 files).
- **113 mp4 trespass evidence videos** under `John Thacker Lawsuit/` — no ASR transcription has been run; retrieval over video evidence is impossible until audio is transcribed. Same for the 1 `.mov` in Depositions (`2022.10.25 Video.mov`).
- **18 .msg + 7 .eml emails in Discovery** — not yet parsed into structured text chunks.
- **.ptx Summation-format deposition exhibits (7 files)** — need a converter or parallel PDF to ingest.
- **Thatcher deposition resource file**: Synology eaDir sidecar present (`2023.07.31 7IL Thatcher Depo@SynoResource`), but the referenced content file may not be in the enumerated tree — needs verification.
- **PACER pull** of the official NDGA docket to cross-check completeness against #0–#131 (any missing documents? sealed filings?).
- Missing: **expert reports** (not obviously labeled in the file list — may be inside deposition exhibit bundles or absent).

---

## Corpus 2 — Brian Goldberg (opposing counsel)

**Status:** identified and well-sampled *within this case* only. Essentially no externally-sourced data.

### A. FILES

Direct filename hits:
- `# Pleadings - GAND/#19, #43, #72, #83 LOA - Goldberg.pdf` — four Letters of Appearance (likely bracketing scheduling changes)
- `Correspondence/2021.07.02 Goldberg Letter to Underwood (1).PDF` — single pre-litigation or early correspondence

Content hits across the 196 Pleadings PDFs:
- **72 of 196 pleadings (37%) mention "Brian Goldberg" / "Brian S. Goldberg" / "B. Goldberg"**
- Signature block `/s/ Brian S. Goldberg` appears on joint motions (e.g., `#84 Jt. Mtn. to Ext. Time.pdf`)
- `#64-2 Knight Depo.pdf` identifies him conducting the deposition: `BY MR. GOLDBERG`
- Email: **`brian.goldberg@fmglaw.com`**
- Firm: **Freeman Mathis & Gary LLP** (FMGlaw)

### B. SIZE + COUNT
5 explicit-name files on NAS (~small — LOAs and a single letter). Beyond that, Goldberg is a *property* of 72 pleading PDFs that belong to Corpus 1.

### C. OCR STATUS
The 5 named files are all PDFs; at Pleadings' 70% extractability rate, ~1–2 likely need OCR. The correspondence file (`2021.07.02 Goldberg Letter to Underwood (1).PDF`) is the most likely candidate for OCR (pre-litigation letter often scanned).

### D. EXISTING INGESTION
**Zero.** `legal_caselaw` has 10 chunks where the token `goldberg` appears, but those are incidental references inside unrelated Georgia state opinions — not this Brian Goldberg.

### E. GAPS (high — this is a mostly-empty corpus)
- **No bar number** (GA/11th Cir admission)
- **No firm profile** (FMGlaw offices, practice groups, leadership)
- **No prior-case list** for Goldberg in NDGA or any other federal court
- **No state-court history** (Fulton, DeKalb, Gwinnett, Cobb, Cherokee, Fannin, Union — none)
- **No opposing-counsel behavioral profile**: motion tendencies, typical filing cadence, discovery strategies, settlement patterns
- Intended future fill: PACER judge/attorney search by his bar number; Westlaw/Lexis or CourtListener lookup on `attorney:"Brian S. Goldberg"` federal-wide.

---

## Corpus 3 — Judge Story

**Status:** identified within this case only; no external opinion corpus on NAS.

### A. FILES

Direct filename hit:
- `# Pleadings - GAND/#0 Richard Story Standing Order.pdf`

Content hits across the 196 Pleadings PDFs:
- **34 of 196 pleadings (17%) mention "Richard W. Story" / "Judge Story" / "J. Story"**
- Judicial officer full identity: **Hon. Richard W. Story, Senior U.S. District Judge, Northern District of Georgia** (Senior status)
- Orders authored by him in this case: at minimum #0 (Standing Order), #14 (Scheduling Order), #30 (Order Extending Discovery), #34 (Order Granting Motion to Extend Discovery), #38 (Order Granting Jt. Mtn.), #103 (Order Setting Mediation), #115 (Order for Electronics), **#118 (Electronics Order)** — the latter signed block reads verbatim: `RICHARD W. STORY, United States District Judge`.
- Courtroom deputy reference: `#60 LOA - FGP.pdf` — `Courtroom Deputy for Hon. Richard W. Story, Senior Judge`.

### B. SIZE + COUNT
1 named file (#0 Standing Order). Beyond that, Judge Story is a *property* of 34 pleading PDFs in Corpus 1.

### C. OCR STATUS
All orders sampled from the Pleadings set were text-extractable. #0 Standing Order is a native PDF. No Story-specific OCR backlog.

### D. EXISTING INGESTION
**Zero.** `legal_caselaw` has 230 chunks where the token `story` appears, all incidental (sentence-fragment use of "story" in unrelated Georgia state opinions); **zero** `case_name` entries contain "Story" as a judge or litigant. No Judge-Story-authored opinions from any federal reporter are in any Fortress collection.

### E. GAPS (the entire judge-corpus is missing)
- **Judge Story's full opinion history** is absent — his NDGA and 11th Circuit sitting-by-designation opinions are not in `legal_caselaw` (which is all Georgia state courts).
- **Scheduling-order style profile**: typical discovery deadline windows, MSJ briefing schedules, dispositive motion disposition rates, trial scheduling patterns.
- **Ruling tendencies on MSJs, Daubert motions, motions to exclude, motions in limine, contempt motions, electronics-in-court orders**.
- **Local rules cross-reference** (N.D. Ga. local rules) tagged to Story's interpretive opinions.
- Intended future fill: CourtListener pull with `judge:"Richard W. Story"` (or the equivalent PACER Judge Story opinion list); requires federal-court ingest-path build.

---

## Corpus 4 — Precedent (NDGA / 11th Cir)

### Current state of `legal_caselaw`

| Metric | Value |
|---|---|
| Total chunks | 2,711 |
| Unique opinions | 1,185 |
| Indexed vectors (HNSW) | 0 (index builds on threshold; retrieval still works via HNSW lazy) |
| Vector dim | 768 (nomic-embed-text) |

### Court distribution (actual)

| Court | Chunks |
|---|---|
| Court of Appeals of Georgia | 2,014 |
| Supreme Court of Georgia | 429 |
| `ga` (Supreme Court of Georgia, short code) | 169 |
| `gactapp` (Court of Appeals of Georgia, short code) | 99 |
| **NDGA (Northern District of Georgia)** | **0** |
| **11th Circuit** | **0** |
| **US Supreme Court** | **0** |
| Any other federal court | **0** |

### What's actually there
The `legal_caselaw` corpus is **100% Georgia state courts** — the Georgia insurance/contract precedent set referenced in the original 1,854-opinion plan. As of today's `ingest_complete` run, **1,185 of the planned 1,854 unique opinions (64%)** landed, suggesting the CourtListener ingest drained one queued batch in ~31 seconds and exited — more scope may require a re-run or higher batch cap.

### What's missing for a federal NDGA case
Everything federal. For a 7IL v. Knight defense or appeal posture, the retrieval system currently cannot return:
- **NDGA** opinions on FRCP procedure, discovery sanctions, MSJ standards under NDGA local rules
- **11th Circuit** opinions controlling in the Northern District of Georgia (binding authority — this is the highest-value missing tier)
- **SCOTUS** federal-procedure, summary-judgment, evidentiary, and substantive-law opinions
- **Judge Story-authored** opinions specifically (see Corpus 3)
- Any **Georgia diversity-jurisdiction** case law from federal courts applying Georgia substantive law (critical for a state-claim case in federal court)

### E. GAPS
- **Finish the Georgia state ingest**: 669 more opinions to hit the 1,854 target.
- **Add NDGA federal ingest pipeline** (CourtListener has NDGA opinions indexed — needs a separate ingest script analogous to `ingest_courtlistener.py` but scoped to `court__jurisdiction=N.D. Ga.`).
- **Add 11th Circuit ingest** (binding authority in NDGA) — arguably the highest-leverage single addition.
- **Add SCOTUS ingest** — lower-volume, highest-gravity.
- Precedent retrieval path needs to be **wired into `legal_council.py` context-freeze** — today the Council freezes `legal_ediscovery` only and does not currently include `legal_caselaw` (separate connectivity audit item, 2026-04-24).

---

## Infrastructure snapshot

**Running services (relevant to Fortress Legal):**

| Service | State | Role |
|---|---|---|
| `fortress-backend` | running | FastAPI guest platform + legal APIs |
| `fortress-arq-worker` | running | Captain loop, Legal Email Intake, Recursive Agent Loop, Legal Council dispatch |
| `fortress-sentinel` | running | Continuous NAS document indexing daemon |
| `fortress-sync-worker` | running | PMS poll (hospitality, tangential to legal) |
| `fortress-channex-egress` | running | OTA egress (hospitality) |
| `fortress-console` | running | Command center UI |
| `fortress-ray-head` | running | Ray cluster head |
| `litellm-gateway` | running | Frontier model router (Legal Council's fan-out path) |
| `ollama` | running | Local inference + nomic embeddings (ingest path) |
| `postgresql@16-main` | running | Primary DB (fortress_guest + other fortress_*) |
| `redis-server` | running | Cache + ARQ queue |
| `fortress-nim-brain` | stopped (enabled) | Nemotron 49B on this box — deliberately stopped 15:07 EDT post-GPU-handoff to spark-5 |

**Qdrant legal collections (point counts):**

| Collection | Points | Indexed | Dim | Status | Notes |
|---|---|---|---|---|---|
| `legal_library` | 3 | 0 | 768 | green | All for Generali matter (not 7IL) |
| `legal_ediscovery` | 866 | 0 | 768 | green | Generali matter (859) + test (7) |
| `legal_hive_mind_memory` | 4 | 0 | 768 | green | Effectively empty |
| `legal_headhunter_memory` | 0 | 0 | 768 | green | Empty |
| `legal_caselaw` | 2,711 | 0 | 768 | green | Georgia state courts only |

**Captain throughput (last ~6h, from `fortress-arq-worker` journal):**
- Patrol cadence: every ~2m 15s (24 cycles sampled)
- Per-cycle: ~24 messages processed / 4 mailboxes
- Per-cycle outcomes (median / observed range): `junk 21 (17–25)`, `allow 1–9`, `block 0–2`, `restricted 0–1`, `executive tag ~24/25`
- No errors observed other than a single `captain_imap_fetch_error error='unknown encoding: unknown-8bit'` at 15:25:43 (one email decode failure, non-fatal).
- Captain is healthy and live. No 7IL-case mail volume spike observed in the sampled window (would surface as `allow` or `restricted` tagged with legal personas).

---

## Prioritized work to reach case-ready

### Tier 1 — Data ingest (prerequisite; no code required beyond existing paths)

1. **Canonicalize the case tree** — pick `Corporate_Legal/Business_Legal/` OR `Business_Prime/Legal/` as the single source of truth; diff the 2.82 GB delta and reconcile. (Blocks any subsequent ingest.)
2. **OCR the ~163 image-only PDFs** (30% of 536) — Discovery is the biggest concentration. Tesseract or a Vercel Sandbox–isolated OCR pipeline will convert them to text-extractable form. ETA: hours on existing hardware.
3. **Ingest the canonicalized 7IL v. Knight case into `legal_ediscovery`** under a dedicated `case_slug=7il-v-knight-ndga` (or the actual docket slug `1:21-cv-XXXXX` if the civil cover sheet gives it). Existing Fortress Sentinel / `ingest_courtlistener.py`-style worker can be adapted; embedding pipeline (nomic) is healthy on GPU as of 15:10 EDT.
4. **Ingest all 196 Pleadings** first (fastest win — 288 MB, high extractability, dense legal signal).
5. **Ingest Depositions** (792 MB but 70% extractable; .txt AMICUS files are pre-converted transcripts already and can bypass OCR).
6. **Ingest Correspondence + letters** (only 39 MB, 18 files).

### Tier 2 — Video/audio evidence

7. **ASR-transcribe** the 113 mp4 trespass videos in `John Thacker Lawsuit/` + the 2 `.mov` files. Whisper on local GPU is adequate. This unlocks retrieval over the underlying conduct evidence.
8. **Parse** the 18 `.msg` + 7 `.eml` Discovery emails → structured text + headers chunks. No OCR needed.

### Tier 3 — External corpora (unblocks the "weapon system" tier)

9. **Finish the Georgia state case-law ingest** — re-run `ingest_courtlistener.py` until the 1,854-opinion target is reached (669 remaining).
10. **Add an NDGA federal ingest path** (CourtListener `court__jurisdiction=N.D. Ga.`) into a new `legal_caselaw_federal` collection or into `legal_caselaw` with a `jurisdiction` field.
11. **Add an 11th Circuit ingest** — highest-leverage missing precedent tier for this case.
12. **Pull Judge Story's authored opinions** (via CourtListener `judge:"Richard W. Story"` filter) into `legal_caselaw_federal` with a `authored_judge` field.
13. **Pull Brian Goldberg's federal case history** (via PACER or CourtListener attorney search) — feeds `legal_headhunter_memory` for opposing-counsel modeling.

### Tier 4 — Code wiring (depends on #10–12 landing)

14. **Wire `legal_council.py` context-freeze** to include `legal_caselaw` (state) and `legal_caselaw_federal` (NDGA/11th Cir) in addition to `legal_ediscovery`. (Cross-reference: Fortress Legal Connectivity Audit 2026-04-24 §Wiring Gap 3.)
15. **Add judge-profile + opposing-counsel-profile retrieval surfaces** — separate retrieval APIs (`/legal/judge/{name}` and `/legal/counsel/{name}`) that pull from `legal_headhunter_memory` and the judge's opinion set.
16. **Fix `fortress-nightly-finetune` bnb 4-bit GPU-RAM error** (cross-reference: Connectivity Audit §Wiring Gap 1) so that training captures → adapter closes. Not case-critical in the short term, but the flywheel is broken until this lands.

---

## Questions requiring Gary's answer

1. **Canonical case-file path.** `/mnt/fortress_nas/Corporate_Legal/Business_Legal/` (3.83 GB, 823 files) and `/mnt/fortress_nas/Business_Prime/Legal/` (6.65 GB, 825 files) appear to be near-mirrors with a 2.82 GB delta. Which is authoritative, and should the ingest worker dedup them on content hash or pick one canonical root?

2. **John Thacker Lawsuit / THATCHER LAWSUIT subfolders.** Two subfolders inside the 7IL case tree are named "John Thacker Lawsuit" (60 files incl. 113 mp4 trespass videos) and "THATCHER LAWSUIT" (33 files, image evidence). `<NAME>` (Thatcher/Thacker) appears in multiple 7IL pleadings as a co-party or witness. Are these (a) evidence folders for the 7IL case, (b) a separately-litigated matter, or (c) a different matter that *inspired* 7IL? The ingest strategy changes accordingly (separate case_slug vs 7IL exhibit attachments).

3. **Case slug.** Shall the 7IL v. Knight case_slug be `7il-v-knight-ndga`, `ndga-1-21-cv-XXXXX` (once the civil cover sheet gives us the actual case number), or your preferred convention? Cross-matter consistency matters because the Connectivity Audit flagged that `legal_council.py` already reads `case_slug` from payloads.

4. **Thatcher deposition presence.** A Synology eaDir sidecar at `Depositions/@eaDir/2023.07.31 7IL Thatcher Depo@SynoResource` references a resource file that is not in the enumerated tree. Was the Thatcher deposition transcript deleted, moved, or is it the same as one of the 8 `.txt` AMICUS files I counted in Depositions (which I did not open)? Worth confirming before ingest so we don't miss it.

5. **Deposition videos.** I found `Depositions/2022.10.25 Video.mov` (1 file) but no mp4 videos inside Depositions proper — all 113 mp4s are in `John Thacker Lawsuit/`. Were the deposition videos (Branch, Walker, Knight, Thatcher) recorded and stored elsewhere, or were they audio-only / transcript-only depositions?

6. **External-corpus ingest priority.** Tier 3 items #9–#13 form the "weapon system" tier. Preference order: **finish Georgia state** → **11th Cir (binding)** → **NDGA (persuasive + judge-specific)** → **Judge Story's opinions** → **Goldberg's prior cases**? Or do you want 11th Cir first because of its binding status?

7. **Brian Goldberg bar / firm confirmation.** I inferred Freeman Mathis & Gary LLP from the `@fmglaw.com` domain. Do you want me to pull his State Bar of Georgia record / PACER attorney-search record before ingesting, or leave that to a later "headhunter" phase that runs against the `legal_headhunter_memory` collection?

8. **OCR policy.** 163 PDFs need OCR. Preferred tool and destination format: (a) Tesseract in-place PDF upgrade with text layer added, (b) Tesseract producing sidecar `.txt` files, or (c) a Vercel Sandbox-isolated pipeline that returns ChatML chunks ready for direct Qdrant upsert?

---

*Audit generated 2026-04-24 ~16:45 EDT. No mutations. No Qdrant writes. No frontier-model calls. CourtListener ingest was not running concurrently (completed 15:12 EDT; 2,711-chunk corpus stable during audit).*
