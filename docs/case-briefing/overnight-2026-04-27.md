# Overnight Session — 2026-04-27 → 2026-04-28

**Started**: 2026-04-28T01:08:18Z (UTC)
**Constraint set**: no outbound emails, no PRs, no commits, read-only against vault/email_archive, write only under /home/admin/Fortress-Prime/docs/ and curated/.

---

## Summary

Stages 1–7 completed in approximately 30 minutes. Total of **6 brief sections drafted**, **5 email_archive queries run**, **6 NAS deep searches**, **3 quality-check audits**, **3 new spec notes**, and **1 assembled DRAFT brief** at 507 lines / 47 KB on NAS. Operator review burden is moderate — most decisions are clear yes/no/skip; main open items are privilege classification of email_archive results and whether to TITAN-enrich Section 2 timeline.

---

## Stages Completed

| Stage | Outcome | Notes |
|---|---|---|
| 1 — Brief skeleton (Sections 1, 3, 6, 9, 10) | ✅ | 5 mechanical sections drafted from curated set + LOA OCR; counsel timeline reconstructed |
| 2 — Critical Timeline (deterministic) | ✅ | 92 events extracted, all dated; no LLM synthesis (per spec) |
| 3 — email_archive deep search | ✅ | 5 queries, 1,528 raw hits with overlap; results CSVs + summary written |
| 4 — NAS round-2 search | ✅ | 2025 closing/PSA/inspection records confirmed absent; new candidates surfaced |
| 5 — Curated set quality check | ✅ | 0 broken refs, 0 dupes, 14 image-only PDFs identified |
| 6 — Spec note candidates | ✅ | 3 new dated notes appended |
| 7 — Final summary | ✅ | This file |

---

## Files Created/Modified

### NEW FILES on NAS

- `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/filings/outgoing/Attorney_Briefing_Package_7IL_NDGA_II_DRAFT_20260428.md` (47 KB, 507 lines) — **the assembled brief DRAFT**

### NEW FILES under docs/case-briefing/

- `overnight-2026-04-27.md` (this file)
- `email-archive-search-results.md` (full search summary + privilege caution + recommended morning sequence)
- `email-archive-query-A-prior-counsel.csv` (37 rows)
- `email-archive-query-B-parties-and-counsel.csv` (685 rows)
- `email-archive-query-C-third-parties.csv` (1 row — surface review needed)
- `email-archive-query-D-content-keywords.csv` (524 rows)
- `email-archive-query-E-2025-critical.csv` (281 rows)

### MODIFIED FILES

- `docs/case-briefing/case-briefing-tool-spec-notes.md` — appended 3 new dated sections (now 11 total spec notes)

### TEMPORARY (working dir, not for review)

- `/tmp/briefing-7il-ndga-ii/section-1.md` through `section-10.md` (assembled into the DRAFT)

---

## Questions for Morning Review

1. **Section 2 — accept deterministic table verbatim, or send to TITAN/BRAIN for narrative gloss?** (The 92-event chronological table is grounded and accurate; LLM enrichment would add prose flow but risks hallucination. Default recommendation: accept verbatim for the brief; ask Council for narrative summary in a separate run if a more readable Section 2 is desired.)

2. **Email_archive Query C returned only 1 hit** for Wilson Pruitt / Pugh / Alpha Surveying / dotloop / McBee / Ansley RE combined. Does operator have these third-party communications in personal email (Gmail / Mac), or is the 1 hit indicative of how scarce these comms ever were?

3. **Email_archive Query A (prior counsel) returned 37 hits** spanning Knight-side defense counsel (Underwood, Sanker) AND plaintiff-side counsel (Goldberg, Cashbaugh, Perry, Podesta). **Which subset is operator authorized to include in Section 7 (Email Intelligence)?**
   - Knight↔Underwood/Sanker = privileged work product. Sharing with new counsel may waive privilege. Default: EXCLUDE without explicit authorization.
   - Knight↔Goldberg/FMG/Buchalter/FGP = adversary correspondence. NOT privileged. Default: INCLUDE selectively.
   - Goldberg↔Podesta (plaintiff internal) = should not be in operator's archive; flag if seen.

4. **Image-only PDFs requiring OCR.** Stage 5.3 found 14 image-only PDFs in the curated set. Most-relevant for synthesis:
   - **Exhibit_E (2021 Inspection River Heights, 121 pp)** — image-only; would need OCR for any inspection-detail synthesis
   - **#63-9 through #63-13** (Case I MSJ exhibits H/I/J/K/L) — image-only
   - **Exh. I — 2021.05.31 Preliminary Survey** — ZERO text extractable, will need full OCR for citation
   
   Should I OCR these tonight on a follow-up run, or hold for operator-prioritized OCR queue?

5. **Wilson Pruitt + Pugh + dotloop records confirmed absent from NAS.** This is now confirmed across both Phase 9 (broad) and Stage 4 (date-bounded). The 2025-cycle records exist only in operator's personal sources. **Should the brief's Section 6 evidentiary gap list explicitly recommend a personal-records sweep before counsel retention?** (Currently the section flags these as gaps but doesn't prescribe operator action sequence.)

6. **`#100 Limited Waiver of Appeal Rights.pdf`** is in `# Pleadings - GAND/` but NOT in the curated `case-i-context/` set yet. **Pull into curated/ tonight or hold for morning?** Important for Case II defense theory because Case I's appeal status affects collateral estoppel arguments. Plus 4 mis-routed `7-il-v-knight-appeals-waiver` emails in `legal_vault/vanderburge-v-knight-fannin/` from 2024-10-01 — same pattern as the 52 already recovered.

7. **Section 3.4 counsel continuity for Knight (defense) has a 2023 gap.** Underwood's last LOA is #36 (2022-09-22). Sanker's first EOA is #87 (2024-03-25). Was there counsel between Underwood and Sanker? The curated LOAs don't show it; may be in the un-curated discovery folders, OR Knight was pro se mid-Case-I, OR represented by counsel who never filed a formal LOA. Worth resolving for Section 3.

8. **Plaintiff entity name reversal.** Case I caption became "7 IL Properties of Georgia, LLC" by 2024-03-12 (per #83 LOA), but Case II (2026-04-15 complaint) reverts to "7 IL Properties, LLC". Could be (a) GA SoS filing reverted/reorganized, (b) clerical inconsistency in Case II caption, (c) different LLC entirely. Worth a brief due-diligence query (GA SoS lookup) — flag for Section 9 strategy decisions.

---

## Anomalies / Surprises

1. **Stage 3 Query C only 1 hit.** Wilson Pruitt + Pugh + Alpha Surveying + dotloop + McBee + Ansley RE — six third-party domains/names — produced exactly one hit in `email_archive`. This is striking. Either (a) these third parties almost never emailed operator, (b) operator's third-party comms went through a different mailbox not in Captain's source list, (c) Captain has a domain-blocklist that filters these out. Worth a follow-up audit of Captain's source-mailbox enumeration vs operator's actual personal email accounts.

2. **Stage 4 NAS searches confirmed `Real_Estate_Assets/` and multiple `Real estate Sales Contract/` directories exist on NAS** but contain ZERO 7IL/Fish Trap/River Heights material from 2025 cycle. The directory pattern suggests historical cycles ARE preserved (RiverView Lodge "closing statement for Tony Cash" from a different transaction is there). The 2025 cycle apparently bypassed this canonical save-path. May be a data-loss event worth investigating — or simply that the 2025 cycle was operated entirely through dotloop without manual export.

3. **Higginbotham appeal records found** in NAS searches (4.5). Different prior matter (2010-2011 era), unrelated to 7IL. Surfaces for completeness; not relevant to Case II.

4. **Defendant-counsel firm: MHT Legal** (Underwood) — appears in Case I LOAs as Cumming + Alpharetta GA based on https://www.mhtlegal.com letterhead. Worth recording in case re-engagement is contemplated.

5. **Plaintiff-counsel Cashbaugh's withdrawal** (#32, 2022-08-22) was due to leaving Freeman Mathis & Gary, not due to conflict or strategy. The withdrawal notice explicitly says "Mr. Cashbaugh is no longer with the firm." Confirms the lateral-movement pattern in Goldberg's later FMG → Buchalter move.

6. **Email_archive search overlap.** Queries B + D + E likely have substantial overlap (e.g., a 2025-04 email about easements would hit B for "Goldberg" if cc'd, D for "easement" content, and E for 2025 critical period). Surfacing top-20 unique per query gave 81 unique IDs in the surface but the actual unique-set size across all queries is much smaller. Recommendation: dedupe-via-id before operator review burden estimation.

---

## Recommended Next Actions (morning sequence)

1. **Read the DRAFT brief** at `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/filings/outgoing/Attorney_Briefing_Package_7IL_NDGA_II_DRAFT_20260428.md`. Sections 1, 2, 3, 6, 9, 10 are present; sections 4, 5, 7, 8 are stubs awaiting later drafting.

2. **Decide on Section 2 disposition** (Question 1). Default: accept verbatim and move on.

3. **Privilege-review Query A results** at `docs/case-briefing/email-archive-query-A-prior-counsel.csv`. Mark each row "include" / "exclude" / "needs-decision" so Section 7 can be drafted on a clean privilege-cleared subset.

4. **Process the morning open questions** (numbered 1–8 above) — most are quick yes/no calls.

5. **Send the 3 outbound drafts** (Thor James, Wilson Pruitt, Pugh) — already drafted from prior turns, held pending operator approval. Stage 4 confirmed these third-party records are unreachable through internal sources, so the outbounds are now the only path.

6. **Curate `#100 Limited Waiver of Appeal Rights.pdf` + the 4 vanderburge appeals-waiver emails** if Question 6 answer is "yes". Quick batch: ~5 file copies.

7. **Optionally: TITAN narrative gloss for Section 2** if operator wants prose timeline. Background ~15 minutes.

8. **Optionally: OCR pass on the 14 image-only PDFs** if Question 4 answer authorizes it. Background ~30 minutes (ocrmypdf pipeline).

9. **Day 4 work** per build plan: draft Sections 4 (Claims Analysis) and 5 (Key Defenses Identified). These need counsel input or Council deliberation; not appropriate for autonomous overnight.

---

## End-of-Stage Vital Statistics

- **Time elapsed (overnight)**: ~30 minutes
- **Curated set status**: 186 files (unchanged from end of 2026-04-27 day session)
- **Brief draft sections**: 6 of 10 drafted (1, 2, 3, 6, 9 placeholder, 10) → 47 KB markdown
- **Email_archive search**: 5 CSVs + 1 summary written
- **Spec notes**: 11 dated sections (3 new tonight)
- **Open questions for operator**: 8
- **GitHub issues open**: 5 (T1 #257, T3 #259, T4 #260, T5 #261, T8 #262); T9 (cross-case mis-routing) still TBD
- **Outbound emails**: 3 drafted, 0 sent
