# Section 7 BRAIN Prompt Draft

**Status:** UNCOMMITTED — operator review before sending. Edit in place.
**Generated:** 2026-04-28 (spark-2)
**Target endpoint:** `http://spark-5:8100/v1/chat/completions` (NIM BRAIN, OpenAI-compatible)
**Model:** `nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8` (BRAIN tier on spark-5)
**Context window:** 32k tokens (confirmed via /v1/models probe 2026-04-28)

> **Reviewer notes:**
> - Per CLAUDE.md, BRAIN requires a non-empty system prompt. `"detailed thinking on"` is the documented-canonical value.
> - The manifest table below is inlined verbatim from `docs/case-briefing/section-7-source-manifest.md`. Edits made here will only affect this single BRAIN call; if you want changes persisted to the source-manifest, edit there too.
> - All 4 subsection headings are required (7.1, 7.2, 7.3, 7.4). Trim or expand any of them in the "Output specification" block before sending.

---

## System message

```
detailed thinking on
```

---

## User message

````markdown
You are drafting Section 7 (Email Intelligence) of an attorney briefing package for incoming counsel evaluating Case II (7 IL Properties LLC v. Knight, NDGA docket 2:26-CV-00113-RWS, post-judgment matter currently in counsel_search posture).

## Case landscape (background — do not summarize in output)

- **Case I** — "7 IL Properties of Georgia, LLC v. Knight" (NDGA, 2:21-CV-00226-RWS). Status: closed_judgment_against. Knight's defense was led by MHT Legal (Ethan Underwood, Stanton Kincaid) and MSP-Lawfirm (Jason Sanker). Plaintiff was represented by Frank G. Podesta of FGP Law, LLC (fgplaw.com). Brian S. Goldberg of Buchalter (buchalter.com) appears separately as plaintiff-side counsel — distinct firm from FGP Law.
- **Case II** — "7 IL Properties, LLC v. Knight" (NDGA, 2:26-CV-00113-RWS). Status: active, counsel_search. Post-judgment matter primarily about easement disputes, property-boundary issues, and the closing of the River Heights and Fish Trap properties. Plaintiff seeks specific performance.
- **Vanderburge** — "Vanderburge v. Knight" (Fannin County GA). Status: closed_settled. Separate easement matter; not the subject of this briefing. Captain (the email classifier) mis-routed Case II correspondence to Vanderburge's case_slug, surfacing privileged Case II material in the wrong bucket — relevant to 7.2's privilege scope discussion.

## Source manifest (42 entries, sorted by date)

The table below is the curated, deduplicated set of emails relevant to Case II Section 7. Each row was extracted via one of three paths: (a) counsel-domain whitelist against `email_archive` (Query A v3), (b) keyword + counsel-domain match in the vanderburge-misroute curated folder, or (c) qwen2.5:7b body-inspection at ≥0.85 case-ii confidence (with 2 operator-accepted strong-prompt verifications and 1 forced inclusion).

| # | Date | Source | Sender | Subject | Case | Role | Privilege | Why it matters |
|---|---|---|---|---|---|---|---|---|
| 1 | 2019-03-27 | `email_archive id=6562` | "Jason Sanker (via Dropbox)" <no-reply@dropbox.com | Jason Sanker shared "VANDERBURGH DOCS" with you | case-i-or-ii-prior-counsel | defense | privileged | Query A v3 hit: counsel-domain whitelist match (role=defense). |
| 2 | 2021-06-09 | `08c5b3ff-541e-4845-bfdf-4b05286c16a8_20210401_gary_re-spam-r` | Gary CROG <gary@cabin-rentals-of-georgia.com> | Re: ***SPAM***  Re: River heights | case-ii | defense | privileged | Case II keyword in subject (river heights) + counsel domain (mhtlegal.com). |
| 3 | 2021-06-11 | `31bd7a88-b202-4abc-889b-15a65a55e52f_20210401_gary_100-fish-` | Gary Knight <gary@cabin-rentals-of-georgia.com> | 100 Fish Trap Road Closing | case-ii | unknown | unknown | Case II keyword in subject (fish trap); no counsel domain on this hop. |
| 4 | 2022-03-10 | `14159c34-b833-4e4b-8b20-d12cda5c9742_20220401_gary_re-7il-pr` | Gary CROG <gary@cabin-rentals-of-georgia.com> | Re: 7IL Properties v. Knight | case-ii | defense | privileged | Case II keyword in subject (7IL) + counsel domain (mhtlegal.com). |
| 5 | 2022-11-08 | `8e266503-b33e-45b9-8875-82826d1be203_20221001_gary_easement-` | "Gary@CROG" <gary@cabin-rentals-of-georgia.com> | Easement agreement for 180 or 290 River Heights road to Thor James | case-ii | unknown | unknown | Case II keyword in subject (river heights); no counsel domain on this hop. |
| 6 | 2022-11-22 | `11d358cf-c1d8-4415-b0b5-0903a6467d4f_20221001_gary_fwd-branc` | Gary Knight <gary@garyknight.com> | Fwd: Branch / Knight - 100 Fish Trap Road, Blue Ridge | case-ii | unknown | unknown | Case II keyword in subject (fish trap); no counsel domain on this hop. |
| 7 | 2023-02-07 | `email_archive id=20978` | "Frank Podesta (via Dropbox)" <no-reply@dropbox.co | Frank Podesta shared "Knight Video Folder" with you | case-i-or-ii-prior-counsel | adversary | not-privileged | Query A v3 hit: counsel-domain whitelist match (role=adversary). |
| 8 | 2023-05-15 | `email_archive id=65391` | Jason Sanker <jsanker@msp-lawfirm.com> | RE: Normans testimony  | case-i-or-ii-prior-counsel | defense | privileged | Query A v3 hit: counsel-domain whitelist match (role=defense). |
| 9 | 2023-08-10 | `email_archive id=25218` | "Frank Podesta (via Dropbox)" <no-reply@dropbox.co | Frank Podesta shared "Knight Deposition Transcripts" with you | case-i-or-ii-prior-counsel | adversary | not-privileged | Query A v3 hit: counsel-domain whitelist match (role=adversary). |
| 10 | 2024-09-22 | `162eef34-deff-4eaf-850e-f464d01422a5_20241001_gary_easement-` | Gary Knight <gary@cabin-rentals-of-georgia.com> | Easement agreement | case-ii | adversary | not-privileged | LLM body-inspect: The email discusses changes to an easement agreement and mentions paragraph 7, which runs with the land, but does not clearly indicate which specific case it is related to. [STRONG-P |
| 11 | 2025-02-13 | `86a7237f-5cc5-4820-8dd4-fcc66334dbf0_20250401_gary_would-you` | Gary Knight <gary@garyknight.com> | Would you handle a seller side of a transaction? | ambiguous | defense | privileged | LLM body-inspect: The email mentions '2 closings coming up' and refers to a property as '253 River heights', but does not explicitly state which case it is related to. [INCLUDED PER OPERATOR INSTRUCTI |
| 12 | 2025-03-11 | `bce5e825-8125-4924-abd6-2aa6fafd14d3_20250401_gary_revised-e` | Gary Knight <gary@garyknight.com> | Revised Easement agreement between Thor James and gary Knight | case-ii | adversary | not-privileged | LLM body-inspect: The email does not explicitly mention any specific case, but it discusses an easement agreement and legal review, which could relate to any of the cases mentioned. [STRONG-PROMPT VER |
| 13 | 2025-04-03 | `885b6a8a-e9a1-402a-a8e7-9c3f4e1f7cf2_20250401_gary_re-possib` | Gary Knight <gary@garyknight.com> | Re: Possible Representation versus  7 IL Properties, LLC, Et Al. | case-ii | unknown | unknown | Case II keyword in subject (7 IL); no counsel domain on this hop. |
| 14 | 2025-04-24 | `4fcd6695-8cc6-458b-9e5c-a8851c471d9d_20250401_gary_re-7-il-v` | Gary Knight <gary@cabin-rentals-of-georgia.com> | Re: 7 IL v. Knight // Request to Confirm Closing Date for 253 River Heights and  | case-ii | adversary | not-privileged | Case II keyword in subject (7 IL, fish trap, river heights) + counsel domain (fgplaw.com). |
| 15 | 2025-04-25 | `2016aaca-638e-4dce-a4e4-d351829accd4_20250401_gary_92-fishtr` | Gary Knight <gary@garyknight.com> | 92 FishTrap and 253 RiverHeights | case-ii | unknown | unknown | Case II keyword in subject (FishTrap, RiverHeights); no counsel domain on this hop. |
| 16 | 2025-04-26 | `401e34f5-2b36-4b71-a8da-14b2bc30423b_20250401_gary_re-92-fis` | Gary Knight <gary@garyknight.com> | Re: 92 FishTrap and 253 RiverHeights | case-ii | unknown | unknown | Case II keyword in subject (FishTrap, RiverHeights); no counsel domain on this hop. |
| 17 | 2025-04-28 | `0ef88433-62c5-4678-81eb-a7dee43d5266_20250401_gary_re-7-il-v` | Gary Knight <gary@garyknight.com> | Re: 7 IL v. Knight // Request to Confirm Closing Date for 253 River Heights and  | case-ii | adversary | not-privileged | Case II keyword in subject (7 IL, fish trap, river heights) + counsel domain (fgplaw.com). |
| 18 | 2025-04-28 | `37cc68ee-0917-4f6d-a528-cc5425bbe0e7_20250401_gary_re-7-il-v` | Gary Knight <gary@cabin-rentals-of-georgia.com> | Re: 7 IL v. Knight // Request to Confirm Closing Date for 253 River Heights and  | case-ii | adversary | not-privileged | Case II keyword in subject (7 IL, fish trap, river heights) + counsel domain (fgplaw.com). |
| 19 | 2025-04-28 | `58be5d90-3ee1-4218-8b0d-5fe70f3f7495_20250401_gary_re-7-il-v` | Gary Knight <gary@cabin-rentals-of-georgia.com> | Re: 7 IL v. Knight // Request to Confirm Closing Date for 253 River Heights and  | case-ii | adversary | not-privileged | Case II keyword in subject (7 IL, fish trap, river heights) + counsel domain (fgplaw.com). |
| 20 | 2025-04-29 | `84cc8ca1-7183-46e5-a4cb-ffd1979e8170_20250401_gary_closing-f` | Gary Knight <gary@garyknight.com> | Closing for 92 FishTrap and 253 RiverHeights | case-ii | adversary | not-privileged | Case II keyword in subject (FishTrap, RiverHeights) + counsel domain (fgplaw.com). |
| 21 | 2025-05-01 | `04220b4c-01a0-434e-9a6a-78dc6ed394e8_20250401_gary_fwd-closi` | Gary Knight <gary@cabin-rentals-of-georgia.com> | Fwd: Closing for 92 FishTrap and 253 RiverHeights | case-ii | adversary | not-privileged | Case II keyword in subject (FishTrap, RiverHeights) + counsel domain (fgplaw.com). |
| 22 | 2025-05-01 | `4502bee2-06b8-48bd-922d-f50c9651e385_20250401_gary_re-closin` | Gary Knight <gary@garyknight.com> | Re: Closing for 92 FishTrap and 253 RiverHeights | case-ii | unknown | unknown | Case II keyword in subject (FishTrap, RiverHeights); no counsel domain on this hop. |
| 23 | 2025-05-01 | `82896b59-c70e-4bc8-9c77-479863d0a1ad_20250401_gary_re-closin` | Gary Knight <gary@garyknight.com> | Re: Closing for 92 FishTrap and 253 RiverHeights | case-ii | unknown | unknown | Case II keyword in subject (FishTrap, RiverHeights); no counsel domain on this hop. |
| 24 | 2025-05-06 | `5cefaef5-e5a9-4012-bf72-ee299f83aee7_20250401_gary_re-closin` | Gary Knight <gary@garyknight.com> | Re: Closing for 92 FishTrap and 253 RiverHeights | case-ii | unknown | unknown | Case II keyword in subject (FishTrap, RiverHeights); no counsel domain on this hop. |
| 25 | 2025-05-07 | `6d859437-8454-49b6-bd14-017d9d7b4eda_20250401_gary_re-closin` | Gary Knight <gary@garyknight.com> | Re: Closing for 92 FishTrap and 253 RiverHeights | case-ii | unknown | unknown | Case II keyword in subject (FishTrap, RiverHeights); no counsel domain on this hop. |
| 26 | 2025-05-09 | `844ae4b3-1a61-45f4-acd9-6130c7a7eb62_20250401_gary_re-92-fis` | Gary Knight <gary@garyknight.com> | Re: 92 FishTrap and 253 RiverHeights | case-ii | unknown | unknown | Case II keyword in subject (FishTrap, RiverHeights); no counsel domain on this hop. |
| 27 | 2025-05-11 | `27a21ead-8d90-4cab-90b7-8c654c3ea1ce_20250401_gary_fwd-closi` | Gary Knight <gary@garyknight.com> | Fwd: Closing for 92 FishTrap and 253 RiverHeights | case-ii | adversary | not-privileged | Case II keyword in subject (FishTrap, RiverHeights) + counsel domain (fgplaw.com). |
| 28 | 2025-05-21 | `3e6b1564-3fd8-4c08-a6c2-efa6b178ca43_20250401_gary_fwd-closi` | Gary Knight <gary@garyknight.com> | Fwd: Closing for 92 FishTrap and 253 RiverHeights | case-ii | adversary | not-privileged | Case II keyword in subject (FishTrap, RiverHeights) + counsel domain (fgplaw.com). |
| 29 | 2025-05-21 | `e60c8242-41bf-4142-a792-3778ad76a345_20250401_gary_fwd-closi` | Gary Knight <gary@garyknight.com> | Fwd: Closing for 92 FishTrap and 253 RiverHeights | case-ii | adversary | not-privileged | Case II keyword in subject (FishTrap, RiverHeights) + counsel domain (fgplaw.com). |
| 30 | 2025-05-21 | `3a9d098d-337b-4f4f-818f-11dc2a3f7beb_20250401_gary_re-outsta` | Gary Knight <gary@garyknight.com> | Re: Outstanding Repairs and Easement Issue – Urgent | case-ii | adversary | not-privileged | LLM body-inspect: The email mentions '1031 exchange' which is relevant to Case II, as it pertains to post-judgment matters involving property transactions. |
| 31 | 2025-05-21 | `90a53040-ab8c-469d-8204-c61ad47a4e77_20250401_gary_re-outsta` | Gary Knight <gary@garyknight.com> | Re: Outstanding Repairs and Easement Issue – Urgent | case-ii | adversary | not-privileged | LLM body-inspect: The email mentions '1031 exchange' and refers to a 'post-judgment matter, currently active', which aligns with Case II details provided. |
| 32 | 2025-05-21 | `ffec66c0-d132-43a2-94a1-f9402f314090_20250401_gary_re-outsta` | Gary Knight <gary@garyknight.com> | Re: Outstanding Repairs and Easement Issue – Urgent | case-ii | adversary | not-privileged | LLM body-inspect: The correspondence mentions '1031 exchange' and 'motion for contempt', which are relevant to post-judgment matters, indicating Case II. |
| 33 | 2025-05-23 | `2d011472-128b-405c-93c1-9b41ebc61392_20250401_gary_fwd-7-il-` | Gary Knight <gary@garyknight.com> | Fwd: 7 IL Properties LLC & Gary Knight Purchases | case-ii | unknown | unknown | Case II keyword in subject (7 IL); no counsel domain on this hop. |
| 34 | 2025-05-25 | `e4fa2ffc-9832-45d2-8a9b-4a17025640a3_20250401_gary_fwd-7-il-` | Gary Knight <gary@garyknight.com> | Fwd: 7 IL Properties LLC & Gary Knight Purchases | case-ii | adversary | not-privileged | Case II keyword in subject (7 IL) + counsel domain (fgplaw.com). |
| 35 | 2025-05-25 | `ef7eaae2-ed2c-47cd-8b95-93dd2d03bbcf_20250401_gary_fwd-7-il-` | Gary Knight <gary@garyknight.com> | Fwd: 7 IL Properties LLC & Gary Knight Purchases | case-ii | unknown | unknown | Case II keyword in subject (7 IL); no counsel domain on this hop. |
| 36 | 2025-05-29 | `5037fbcc-e9bf-466e-8a96-e96632fe3c70_20250401_gary_fwd-7-il-` | Gary Knight <gary@garyknight.com> | Fwd: 7 IL Properties LLC & Gary Knight Purchases | case-ii | unknown | unknown | Case II keyword in subject (7 IL); no counsel domain on this hop. |
| 37 | 2025-05-30 | `2748cb8c-56d2-4316-8f78-d54f82dee4d1_20250401_gary_re-7-il-p` | Gary Knight <gary@garyknight.com> | Re: 7 IL Properties LLC & Gary Knight Purchases | case-ii | unknown | unknown | Case II keyword in subject (7 IL); no counsel domain on this hop. |
| 38 | 2025-05-30 | `4eeca69f-32b3-4e3c-963e-d3406a4b3cc1_20250401_gary_fwd-7-il-` | Gary Knight <gary@garyknight.com> | Fwd: 7 IL Properties LLC & Gary Knight Purchases | case-ii | adversary | not-privileged | Case II keyword in subject (7 IL) + counsel domain (fgplaw.com). |
| 39 | 2025-05-30 | `ed866213-3a9d-445f-ae95-467a1194a3c6_20250401_gary_re-7-il-p` | Gary Knight <gary@garyknight.com> | Re: 7 IL Properties LLC & Gary Knight Purchases | case-ii | unknown | unknown | Case II keyword in subject (7 IL); no counsel domain on this hop. |
| 40 | 2025-05-30 | `email_archive id=43413` | "Frank G. Podesta" <fpodesta@fgplaw.com> | Re: FW: 92 Fish Trap | case-i-or-ii-prior-counsel | adversary | not-privileged | Query A v3 hit: counsel-domain whitelist match (role=adversary). |
| 41 | 2025-06-08 | `6f6ddb8f-bf88-458f-848b-dc63dc8a3116_20250401_gary_re-confli` | Gary Knight <gary@garyknight.com> | Re: Conflict Notice | case-ii | adversary | not-privileged | LLM body-inspect: The correspondence discusses ongoing issues with an easement agreement and mentions a post-judgment matter, which aligns with Case II '7 IL Properties, LLC v. Knight' (NDGA, docket 2 |
| 42 | 2025-09-02 | `email_archive id=46752` | "Frank Podesta (via Dropbox)" <no-reply@dropbox.co | Frank Podesta shared "Knight Case Closing File" with you | case-i-or-ii-prior-counsel | adversary | not-privileged | Query A v3 hit: counsel-domain whitelist match (role=adversary). |

## Output specification

Produce **only** Section 7 content, ready to paste into the briefing package. Use `## 7.` markdown heading. Required subsections:

- **`## 7.1 Methodology`** — describe how the manifest was assembled (counsel-domain whitelist queries against `email_archive`; LLM body-inspection of medium-confidence vanderburge-misroute files; manual operator override for one ambiguous bridge email). Cite v1 → v2/v3 noise reduction (37 rows with ~85% surname-collision noise → 6 verified counsel rows). Stay at the level a counsel needs to evaluate evidentiary chain-of-custody — not implementation detail.
- **`## 7.2 Privilege Classification Summary`** — characterize the manifest by role (defense / adversary / unknown / ambiguous) and case attribution (Case II direct, Case I prior counsel, cross-cutting). Distinguish work-product privileged (defense correspondence with MHT Legal, MSP-Lawfirm) from adversary correspondence (FGP Law / Podesta — not privileged but discoverable) and items requiring operator review before production. A small inline table is acceptable for the count breakdown.
- **`## 7.3 High-Significance Correspondence`** — narrative discussion of the highest-value entries. Cover at minimum:
  (a) the **2 MHT Legal threads** (Ethan Underwood 2021-06-09 "Re: ***SPAM*** Re: River heights"; Stanton Kincaid 2022-03-10 "Re: 7IL Properties v. Knight") — the only located defense-counsel correspondence in the corpus, resolving the missing-Underwood gap from Query A v1;
  (b) the **2025-06-08 Podesta "Re: Conflict Notice"** — adversary, post-judgment timing, signals plaintiff-counsel disclosed a conflict;
  (c) the **2025-02-13 jknight@msp-lawfirm seller-side email** — explicitly bridges Case I (Sanker reference) and Case II (River Heights / Fish Trap closings);
  (d) the **easement-cluster threads with Frank G. Podesta** in 2024–2025.
  Quote subjects and dates only — do not paraphrase body content.
  Do NOT construct a timeline narrative connecting the threads. Surface each correspondence set as discrete evidence; let counsel draw their own connections. The brief's job is to surface; not story-tell.
- **`## 7.4 Privilege Caution`** — operator/counsel guidance on production. End the subsection with three explicit entry-number lists in exactly this format:
    - **Producible:** entries #N, #N, #N, ...
    - **Withhold (privileged):** entries #N, #N, #N, ...
    - **Operator decision required:** entries #N, #N, #N, ...
  Every entry #1 through #42 must appear in exactly one of the three buckets — no entry omitted, no entry in two buckets. Specifically address the jknight email's ambiguity (operator-forced inclusion despite ambiguous LLM verdict; defense-firm contact pre-engagement; privilege scope unclear) — it belongs in the operator-decision bucket. The Case I vs Case II attribution question for cross-cutting easement threads should also surface here.

## Constraints

- Cite each email by **(date, sender, subject)** only. Do NOT invent or paraphrase email body content beyond what the manifest's "Why it matters" column already states.
- Mark any sentence with `[NEEDS-OPERATOR-REVIEW]` if it asserts ANY of the following beyond what the manifest's "Why it matters" column states explicitly: procedural posture, deposition status, claim theories, counsel's strategic intent, characterization of any inter-party relationship, or causal/temporal inference connecting two or more entries. Default to marking when uncertain. Marking is cheaper than overreach.
- **Prose form, not bullet lists.** Inline table in 7.2 only is permitted.
- **Word target: 600–1000 words total** across all four subsections combined.
- Output is markdown ready to paste — start with `## 7.`; no preamble, no echoed thinking, no trailing commentary.
- Do not echo this prompt or the manifest table back in your output.
````

---

## Open framing decisions (operator review before send)

1. **Temperature** — proposed 0.2 (slight prose room). Drop to 0.0 for max determinism if you want strict reproducibility.
2. **`detailed thinking on`** — straight from CLAUDE.md's required-system-prompt example. Switch to `"detailed thinking off"` for shorter output (lower quality risk).
3. **No few-shot examples.** Going zero-shot to keep manifest within Nemotron's optimal context. If output quality is poor, falling back to a 1-shot example for 7.3 is the cheapest mitigation.
4. **Citation format** — strict `(date, sender, subject)` only. No file paths, no `email_archive id`s — counsel sees a clean evidentiary trail.
5. **Production-vs-withhold table in 7.4** — currently allowed as prose-only. Toggle to "small table required" if you want it tabular.
6. **`[NEEDS-OPERATOR-REVIEW]` markers** — currently inline in prose. Could convert to numbered footnote-style list at end of Section 7 if you prefer.

When you're ready, say "send to BRAIN with this draft" and I'll probe `http://192.168.0.104:8100/v1/models` first, then call.
