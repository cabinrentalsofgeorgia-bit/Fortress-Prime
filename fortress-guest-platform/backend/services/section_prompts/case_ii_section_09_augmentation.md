# Section 9 Prompt Augmentation — Case II Counsel-Search Materials

**For:** Wave 7 Case II briefing (Phase B v0.1 on `7il-v-knight-ndga-ii`)
**Target file on cluster:** `/home/admin/Fortress-Prime/fortress-guest-platform/backend/services/section_prompts/case_ii_section_09_augmentation.md` (or wherever section-specific prompt augmentations live in the orchestrator — verify path during pre-flight)
**Date drafted:** 2026-05-01
**Operator:** Gary Knight

---

## Critical context for incoming counsel

Resolved at orchestration time from the intel layer (`fortress.legal.intel_resolver`). Single highest-leverage injection — surfaces the same-judge insight directly into §9.

{{ judge:richard-w-story@operator_relevance.critical_context }}

---

## Why this augmentation exists

Case I §9 produced hindsight strategy on a closed matter. Case II §9 must produce a **counsel-evaluation package** — materials the operator hands prospective counsel so the counsel can quickly say "I want this case at price X" or "this isn't a fit."

The operator's posture is **sophisticated pro se with full data set and ability to self-represent if counsel terms aren't economical**. Counsel hire is value-driven, not necessity-driven. §9 must reflect this posture; it changes both substance and tone vs. a generic counsel-search section.

The package's job is to compress prospective counsel's case-evaluation time from 8 hours to 1 hour. That compression is what shrinks the retainer.

---

## Section 9 structural requirement

Generate §9 with these named subsections, in order. Each must be present.

### §9.1 Strategic Posture

State the operator's posture in 2-3 paragraphs:
- Defendant is named individually
- Defendant is sophisticated party with full data set, prepared filings, ability to self-represent through dispositive motion practice if cost-effective
- Counsel hire is **value-driven, not necessity-driven** — the right counsel at the right price reduces exposure more than self-representation does; if the math doesn't work, pro se stays viable
- Defendant has already curated case file, drafted answer, and prepared this briefing package — counsel inherits substantial prep work, not a cold case

This framing is non-negotiable. Do not soften it into "seeking counsel" generic language.

### §9.2 Engagement Tier Options

Present three tiers:

**Tier 1 — Full litigation through trial.** Counsel handles all phases including trial. Highest cost, lowest operator burden post-handoff.

**Tier 2 — Through dispositive motions, with consultation through trial.** Counsel handles answer, MTD response (if filed), discovery, summary judgment motion, and any related motion practice. If matter survives SJ, defendant continues pro se with consultation calls. **Operator preference.** Reasoning: NDGA federal practice resolves a meaningful fraction of cases at MTD or SJ; if counsel shapes the record through that gate, defendant has structural advantages going forward; if counsel loses at MTD or SJ, the case is effectively over anyway.

**Tier 3 — Consultation only.** Counsel reviews defendant's filings and advises on strategy without appearance. Defendant remains pro se. Cheapest. Highest risk during active motion practice cycles.

The brief should state Tier 2 as preferred, and surface Tiers 1 and 3 as alternatives that prospective counsel can react to during initial conversations.

### §9.3 Preferred Fee Structures

State explicitly:

**Avoid:** pure hourly billing with open-ended retainer. Produces inflated retainers ($50K–$100K) and creates no incentive for efficiency.

**Preferred:**
- **Flat-fee per stage.** Concrete numbers per phase: answer + early motions, MTD response, discovery, summary judgment. Prospective counsel does the math against expected hours; defendant does the math against exposure.
- **Hybrid.** Flat fee for predictable work; hourly for genuinely unpredictable work (depositions, expert engagement, novel motion practice) with soft cap.
- **Defense-side flat-fee with success kicker.** "$X flat through MTD outcome, with $Y bonus if claim count drops by 50% or case dismisses." Aligns counsel incentive with operator goal.

**Operator-side signaling intent:** the brief should communicate that defendant is a sophisticated party with prep work already done, not someone who can be milked. Counsel can earn fair value for skilled work; counsel cannot bill against operator naïveté.

### §9.4 Counsel Profile Sought

Required attributes (counsel must satisfy all):
- **NDGA federal court experience.** Local rules, judge rotation, and motion practice culture differ enough that out-of-state or state-court-only counsel adds friction.
- **Real estate litigation + transactional crossover.** Pure litigators may miss easement-recordation nuances; pure transactional may not litigate. Need both.
- **Conflict-clean** vs. all parties on the conflict list (§9.5).

Preferred attributes (any subset acceptable):
- **Senior associate at mid-tier firm** OR **solo/small-firm partner.** Often the right value point: experience without big-firm partner premium; flexible on fee structure; institutional pressure to bill hours is lower.
- **Fee-flexible** — willing to discuss flat-fee or hybrid structures.
- **Prior 8-count complex defense experience** (federal real estate fraud, breach of contract, easement claims, declaratory judgment).

Disfavored:
- **Big-firm partner-only relationships.** Generally too expensive for the matter's economics.
- **Plaintiff-side firms.** Posture mismatch; many will decline anyway.

### §9.5 Conflict Screening List

Before any substantive engagement conversation, prospective counsel must clear conflicts against:

1. **7 IL Properties, LLC** (any iteration: "of Georgia," reversal name, member entities)
2. **Edward Thatcher** (7IL principal)
3. **Adversary firms (Case I + Case II including lateral movements):**
   - {{ firm:freeman-mathis-gary-llp#conflict_screening_notes }}
   - {{ firm:goldberg-PLACEHOLDER-firm#conflict_screening_notes }}
   - {{ firm:buchalter-PLACEHOLDER#conflict_screening_notes }}
   - {{ firm:cashbaugh-PLACEHOLDER#conflict_screening_notes }}
   - {{ firm:perry-PLACEHOLDER-firm#conflict_screening_notes }}
4. **Closing attorney for Thatcher's 7IL closings (operator-identified loss-causing actor):**
   - {{ attorney:terry-wilson#operator_relevance }}
5. **Titus Pugh** (home inspector; plaintiff-side fact witness)
6. **Thor James** (Case I co-defendant; potential subject of Exhibit G request)
7. **Knight individually** AND **closely-held Knight entities** (any current matter against the operator personally or against operator-owned entities is a conflict)

Surface this list as a one-page document fragment within §9 that the operator can copy directly into outreach emails.

### §9.6 Prospective Counsel Materials Package

§9 must specify the materials the operator can hand a prospective counsel during initial conversations to compress evaluation time:

- **Operative complaint + 10 exhibits** (already curated at `7il-v-knight-ndga-ii/curated/documents/01_operative_pleadings/` and `02_complaint_exhibits/`)
- **Operator's defense theory summary** (this brief's §5 — the Block A/B/C/D structure produced by Wave 4 §5 fix)
- **Evidence index** (this brief's §6)
- **Critical timeline** (this brief's §2 — the 92-event chronology)
- **Email intelligence summary** (this brief's §7 — categorized findings, plaintiff-side actors, adversary counsel, third parties)
- **Operator's draft answer** (if available; located by orchestrator under `curated/drafts/` or `working/`)

The framing should be: "Here is one hour of your time, structured. Tell me what you'd charge."

### §9.7 Outreach Order + Initial Contact Template

Synthesize from corpus retrieval:
- Candidate firms / attorneys identified by name in case correspondence, vault, or operator overnight notes
- Prior counsel relationships in Case I (Underwood/MHT, Podesta/FGP, Sanker, Argo/DRA) — note that these were defense counsel previously; some may still be available, some may have moved firms
- General-counsel referrals or operator-side network mentions

For each candidate, generate a one-line strategic note:
- **Why this candidate** (NDGA experience? Real estate specialization? Prior relationship?)
- **Why caution** (any conflict signal? Prior representation pattern? Fee posture if known?)

Provide a draft initial-contact email template the operator can adapt per candidate. Template should:
- Identify the case (NDGA 2:26-CV-00113-RWS)
- Note operator's posture (sophisticated pro se, value-driven counsel hire)
- Reference the materials package (§9.6) as available for review
- Request fee structure discussion not retainer quotes
- Offer 30-min initial call

---

## Tone requirements (override generic counsel-search prose)

Generic legal-AI counsel-search prose tends toward:
- "The defendant is searching for qualified counsel..."
- "The matter requires experienced representation..."
- "Counsel will need to review extensive case materials..."

This tone undercuts operator's negotiating posture. Replace with:
- "Defendant is evaluating counsel from a position of preparation..."
- "Counsel will inherit a curated case file with substantial pre-litigation work..."
- "Engagement terms will reflect the prep work already completed by defendant..."

The tone is **prepared sophisticated party**, not **distressed defendant seeking help**. This affects retainer math materially — counsel quotes against perceived sophistication, not just case complexity.

---

## What §9 should NOT include

- A finalized engagement letter (premature; comes after candidate selection)
- Specific dollar amounts for fees (fee benchmarks are useful as ranges; specific quotes are counsel's job)
- Trial strategy specifics (Tier 2 means counsel develops trial strategy if matter reaches that point; brief should not pre-determine)
- Pejorative characterization of plaintiff counsel (Goldberg/FMG/Buchalter/Perry/Cashbaugh)
- Pejorative characterization of opposing party (7IL / Thatcher) beyond what the §4 claims analysis warrants
- Settlement posture (separate strategic question; not a counsel-search artifact)

---

## How the orchestrator picks this up

Two integration paths; pre-flight verifies which the orchestrator supports:

**Path 1: Section-specific prompt augmentation file.** If `case_briefing_synthesizers.py` reads per-section prompt augmentations from a directory like `section_prompts/<case_slug>/section_<N>.md`, this file lands at:
`fortress-guest-platform/backend/services/section_prompts/7il-v-knight-ndga-ii/section_09.md`

**Path 2: Inline prompt edit.** If §9's prompt is hardcoded, edit the prompt to reference these subsection requirements and tone constraints. Augmentation file becomes a comment/reference doc.

**Path 3: CLI flag.** If `track_a_case_i_runner.py` accepts `--section-prompt-overrides <dir>`, point it at the augmentation directory.

Pre-flight enumeration (§4 of Wave 7 brief) should determine which path applies and surface to operator before §5 execution.

---

## Operator's checklist Saturday morning before Phase B kicks off

1. Confirm this augmentation file is in place at the path the orchestrator reads
2. Validate §9 prompt picks it up — quick smoke: print the assembled §9 prompt and verify subsection requirements appear
3. If the orchestrator can't find / load this augmentation, fall back to inline prompt edit before running

---

## Why this matters for the 7-day timeline

Without this augmentation, §9 produces generic counsel-search prose. Operator then spends Day 4-5 manually rewriting §9 to match negotiating posture. With this augmentation, §9 v1 is closer to operator-grade on first generation; v2 iteration scope shrinks; counsel outreach can begin Tuesday on time.

This is the single highest-leverage prompt augmentation in the Case II brief because it differs most from Case I's posture and most directly affects retainer math.

---

End of §9 augmentation.
