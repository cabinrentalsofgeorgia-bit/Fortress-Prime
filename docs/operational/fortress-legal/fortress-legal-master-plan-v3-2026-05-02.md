# Fortress Legal Master Plan v3

Date: 2026-05-02
Matter: 7IL Properties, LLC v. Knight / James, N.D. Ga. Case II
Source package: Attorney_Briefing_Package_7IL_NDGA_II_v2_20260502T173909Z.md
Operator posture update: Gary Knight has not been served as of 2026-05-02.

This is an operating plan, not legal advice. Every filing decision should be verified against the live docket, service proof, applicable local rules, and retained counsel if counsel is engaged.

## 1. North Star

Fortress Legal operates as a disciplined legal command system: deadline-safe, evidence-traceable, privilege-aware, counsel-ready, and operator-controlled. The goal is not merely to generate legal documents. The goal is to control a matter with the same rigor a top white-shoe litigation team would expect: facts, deadlines, pleadings, evidence, exposure, counsel strategy, and decision history all connected.

For Case II, the immediate priority remains counsel-hire and first-response readiness. Because the operator has not been served as of 2026-05-02, this is a preparation window, not a panic window. The operator should prepare as if self-representing through the initial answer or Rule 12 response may be necessary, while still seeking counsel review before the first responsive filing if the economics and fit are acceptable.

## 2. Current Case Clock

Known posture as of 2026-05-02:

- Complaint filing date used by current package: 2026-04-15.
- Operator service status: not served as of 2026-05-02.
- FRCP 4(m) rough service deadline if counted from 2026-04-15: 2026-07-14.
- If formal service occurs, the ordinary answer deadline is generally 21 days after service unless waiver, court order, statute, or another rule changes the calculation.
- If a waiver of service is requested and accepted, response timing may change; do not sign or ignore any service/waiver paper without updating the matter clock.

Immediate clock rule: the first new fact that matters is service. The system should treat any service attempt, waiver request, summons, proof of service, or docket service entry as a P0 event.

## 3. Strategic Posture

The operator posture is pro-se-capable, counsel-enhanced, and never counsel-dependent.

Defensive posture:

- Prepare an answer and preserve Rule 12 posture.
- Evaluate claim preclusion, collateral estoppel, and facial unenforceability arguments.
- Avoid waiver of jurisdiction, venue, Rule 12 defenses, affirmative defenses, and counterclaims through careless early filing.

Offensive posture:

- Prepare abuse-of-process counterclaim theory.
- Evaluate individual-capacity theory against John Thatcher.
- Preserve punitive damages theory under the willful-misconduct frame identified in the attorney package.
- Evaluate Terry Wilson exposure without prematurely overcommitting if counsel review is pending.

Counsel posture:

- Begin conflict checks now.
- Send names/entities first, not the full evidence package.
- After conflict clearance, send the v2 attorney briefing package and curated evidence index.
- Ask counsel to price specific scopes rather than quote an undefined litigation engagement.

## 4. P0 Priorities

1. Confirm service posture daily until served or until the Rule 4(m) window changes.
2. Run conflict checks with priority counsel targets.
3. Maintain first-response workbench so the operator can answer or move without waiting on counsel.
4. Build allegation-by-allegation response matrix from the complaint.
5. Build issue matrix for defenses and counterclaims.
6. Keep all counsel communications and legal strategy in privileged channels only.
7. Keep Qdrant/vector cutover cleanup separate from case-clock work unless retrieval failure blocks a filing.

## 5. Immediate 72-Hour Plan

Day 0 / Day 1:

- Confirm not served as of the current date.
- Create or update the matter command center record.
- Start conflict-check emails or calls using the conflict-check email document.
- Build the answer matrix shell from the complaint: every numbered allegation gets a row.
- Confirm all evidence paths in the v2 package point to curated Case II sources only.

Day 2:

- Score counsel responses.
- Prepare the first-response workbench: answer outline, Rule 12 issue list, affirmative defenses, counterclaim hooks, evidence references.
- Identify which allegations need more factual confirmation.
- Decide Phase 1 budget range and acceptable fee structures.

Day 3:

- Send full package only to counsel who cleared conflicts.
- Ask for a scoped quote: answer/MTD/counterclaim review, not open-ended litigation.
- Prepare operator fallback plan for filing without counsel if service occurs before counsel is retained.

## 6. First-Response Workbench

Fortress Legal must create and maintain a pleading matrix with these columns:

- Complaint paragraph number
- Allegation text
- Response posture: admit / deny / lack knowledge / qualified admission
- Evidence supporting response
- Defense implicated
- Counterclaim hook
- Waiver risk
- Counsel review needed
- Filing-ready language

This is the core self-representation enhancement. It converts the complaint into a controlled response system and prevents rushed drafting.

## 7. Counsel Engagement Strategy

Preferred engagement: Tier 1 full litigation through trial if pricing and fit are strong.

Acceptable fallback: Tier 2 through dispositive motions, but only if the written scope includes counterclaim discovery and counterclaim summary-judgment work.

Avoid:

- Undefined hourly engagement without a Phase 1 cap.
- Counsel who wants to discard the curated package and restart from zero.
- Counsel who treats the counterclaim as a distraction without reviewing the Case I contempt history and easement evidence.
- Counsel who cannot clear conflicts quickly.

Ask for:

- Conflict clearance first.
- Phase 1 fixed or capped scope.
- Hybrid or staged fee structure if counsel is interested in offensive recovery.
- A precise deliverable: answer/MTD/counterclaim posture memo or redline within a defined time.

## 8. White-Shoe Operating Enhancements

Fortress Legal should evolve from document generation into matter control. The next build enhancements are:

1. Matter Command Center: service status, deadlines, counsel status, evidence status, exposure, open decisions, and today's next action.
2. Docket and Service Sentinel: daily docket checks, service detection, and automatic deadline recalculation.
3. First-Response Builder: allegation-by-allegation answer matrix with defenses and counterclaim hooks.
4. Issue Matrix: each claim, defense, and counterclaim gets facts, law, evidence, risks, and next action.
5. Evidence-to-Pleading Traceability: every filing paragraph ties back to evidence.
6. Privilege Firewall: separates privileged strategy, counsel communications, public filings, and raw evidence.
7. Counsel Packet Mode: conflict-check email, full attorney packet, call script, fee-scope ask, scorecard.
8. Red-Team Review: hostile review before every filing or attorney packet release.
9. Operator Decision Log: date, decision, reason, risk accepted, next review date.
10. Retrieval Health Monitor: Qdrant collection/alias health, case_slug counts, and source-scope validation.

## 9. Technical System Priorities

P0 technical items:

- Preserve PR #366/#367 schema and ingest-run stability.
- Keep legal.cases and legal.ingest_runs aligned across fortress_db and fortress_prod.
- Keep Case II corpus clean: curated Corporate_Legal paths only, no legacy legal_vault mixed dump.
- Do not allow pending/failed ingest rows to silently poison retries.

P1 technical items:

- Build Matter Command Center data model and UI.
- Build answer matrix schema and document generator.
- Build conflict-check tracker.
- Add docket/service sentinel.
- Add privileged/public artifact classification.

P2 technical items:

- Qdrant alias cleanup: legal_ediscovery_active points to v2, but v2 Case II count is zero while runtime currently uses legacy legal_ediscovery. Do not cut runtime over until v2 is populated and verified.
- Build vector collection health reports by case_slug.
- Add retrieval regression tests for Case I and Case II.

## 10. Governance Rules

- Service status beats everything.
- Deadlines beat drafting polish.
- Privilege boundaries beat convenience.
- Evidence traceability beats narrative confidence.
- Counsel packets go out only after conflict clearance.
- No full package is sent to counsel until the conflict screen clears.
- No filing leaves Fortress without red-team review.
- If the system cannot explain the evidence basis for a pleading paragraph, that paragraph is not filing-ready.

## 11. Next Operator Decisions

- Confirm service status daily.
- Decide Phase 1 counsel budget ceiling.
- Decide whether to mention pro se fallback externally or keep it internal.
- Decide whether Wilson claim evaluation is framed as active pursuit or reserved issue.
- Decide top 5 counsel targets for initial conflict checks.
- Decide whether to build answer matrix immediately from complaint text as the next technical sprint.
