# Fortress Legal Full Platform Capability Audit - 2026-05-06

## Classification

`COMPLETE_CAPABILITY_AUDIT`

This audit describes what Fortress Legal can currently do as a governed legal operations platform. It does not record counsel signoff, final legal conclusions, external submission authority, ingestion, schema/RLS/policy mutation, source promotion, or restricted-content review.

## Current Capability Thesis

Fortress Legal is now a controlled internal legal-review operations platform. It is strongest at guarded visibility, source-status separation, review queue governance, operational evidence capture, rollback discipline, and checker-backed production verification. It is not yet a world-class human-operated legal production system because durable reviewer action state, structured operational memory, reviewer attestations, source-remediation write workflows, and machine-readable cognition indexes remain limited or intentionally deferred.

## System Capability Map

| System | Purpose | Maturity | Dependencies | Risks | Governance Boundary | Rollback / Observability |
| --- | --- | --- | --- | --- | --- | --- |
| Matter/Vault visibility | Authenticated production matter access and document/vault visibility | Production-visible | Command Center, backend legal APIs, auth session | Auth/session drift, stale deploy | Authenticated only, locked/restricted metadata-only | Checker, deployment verifier |
| Counsel Review Workbench | Review issue matrix, chronology, binders, dossier, questions | Active review surface | Legal workbench APIs and manifests | Source uncertainty can overload reviewers | Draft/counsel-review labels required | Checker visibility and evidence docs |
| Counsel Validation Workflow | Preserve validation states and counsel review gates | Active | Validation manifests, UI panels | Human interpretation can be mistaken for signoff | No final legal conclusions | Evidence docs, UI labels |
| Strategy / Signoff Packet | Package review materials for counsel review | Active, signoff pending | Signoff packet manifests | Operator acknowledgment confused with counsel signoff | Explicit decision only | Decision workflow docs and checker |
| Source Integrity Validation | Classify source-backed and unsupported material | Active | Existing ingested records and chunks | False confidence if unresolved issues are hidden | Unsupported items stay visible/excluded | Source integrity docs, review panels |
| Source Remediation | Categorize unresolved source blockers | Mature governance, limited writes | Source remediation manifests | 232 unresolved issues remain | No auto-resolution, no source promotion | Remediation maturity checker |
| Source Link Repair | Repair existing source link references | Complete for previous phase | Existing non-locked sources | Broken link recurrence | No new ingestion/vectors | Operational docs and evidence |
| Targeted Source Completion | Expand verified subset without broad reanalysis | Complete/active | Existing verified subset and source records | Remaining blockers can be under-prioritized | Conservative inclusion only | Targeted source docs |
| Limited Signoff Candidate Packet | Scope a source-verified packet for counsel review | Active | Verified subset, unresolved register | Misread as final approval | `COUNSEL_SIGNOFF_PENDING` | UI/evidence docs |
| Counsel Signoff Decision Workflow | Allows explicit decision paths without inference | Active, no signoff recorded | Decision workflow UI/API/manifest | Accidental authority expansion | No auto-signoff or external authority | Decision workflow evidence |
| Autonomous Learning Loop | Observe/evaluate/propose bounded improvements | Active | Learning manifests, evals, proposal queues | Prompt memory can outrun structured memory | No external model training, no legal automation | Learning dashboard, evidence docs |
| Draft Work Product | Generate internal draft work product from verified subset | Active | Limited source-verified subset | Drafts could be overread | Not final legal advice, no external use | Draft work product evidence |
| Review Operations | Queue, contradiction, evidence, analytics, pilot readiness | Mature read model | `legal_remediation_maturity.py`, UI panel | Read-only state does not yet capture reviewer actions | No source promotion | Checker and deployment verifier |
| Review Scaling | Assignment framework, workload balancing, SLA/aging | Mature model, writes deferred | Review operations read model | No durable reviewer assignment state | No uncontrolled reviewer authority | Evidence summaries |
| Operational Certification | Pilot governance, onboarding, rollback, enforcement | Mature governance | Certification docs and panel | Certification language can overstate launch readiness | Internal pilot only | Checker gates |
| Internal Pilot | Read-only/synthetic pilot simulation and metrics | Active | Pilot simulation verifier | Simulation can diverge from real reviewer behavior | No production writes | Pilot simulation evidence |
| Human Operations | Onboarding, structured feedback, exceptions, drift, rehearsals | Active read-only maturity | Human operations read model and docs | Feedback not durable per reviewer | No freeform legal text, no assignment writes | Checker humanOperations gates |
| Deployment / Health | Routes, services, API guards, systemd state | Stabilized | Runtime services, deployment verifier | Runtime/source drift | No DB mutation | Deployment verifier |
| Rollback | Runtime artifacts and git-revert paths | Strong for recent phases | Captured `.next` and backend artifacts | Rollback history fragmented across evidence dirs | Must preserve governance labels | Evidence summaries |
| Observability | Checker errors, verifier output, service health, queue metrics | Strong for operator checks | Scripts and evidence docs | No centralized metrics store | No secrets/document body text | Sanitized JSON evidence |

## What The System Can Actually Do Now

- Present a production authenticated legal matter workbench for internal review.
- Keep legal review surfaces behind auth and return 401/403 for internal APIs when unauthenticated.
- Separate source-verified material from unresolved or unsupported material.
- Generate and display limited-scope draft internal work product from the verified subset.
- Display remediation, contradiction, review, scaling, pilot, certification, and human-operations maturity views.
- Run bounded autonomous learning over metadata/manifests and proposal queues.
- Verify production UI state with authenticated Playwright storage state without printing auth material.
- Verify deployment routes, unauthenticated API guards, and service health.
- Simulate controlled pilot operations using non-destructive checks.
- Preserve rollback artifacts and evidence summaries per operational phase.

## What The System Cannot Safely Do Yet

- It cannot treat the 232 unresolved source issues as relied-upon facts.
- It cannot record counsel signoff unless an explicit human decision workflow action occurs.
- It cannot produce final legal advice or court-ready filings.
- It cannot authorize filing, service, email, sending, or external submission.
- It cannot safely persist reviewer assignment/disposition writes without a separately governed write path.
- It cannot use locked/restricted content beyond metadata-only handling.
- It cannot scale to unmanaged reviewers because attestation, accountability, and exception ledgers are not durable.

## Emerging Architecture Pattern

The dominant architecture is a governed read-model platform:

1. File-backed or manifest-backed operational phase records.
2. Backend services that summarize legal/review state into safe aggregate read models.
3. Authenticated Command Center panels that render dense operational dashboards.
4. Verification scripts that turn visible UI and API guards into non-sensitive evidence.
5. Evidence directories that become the practical audit trail.

This pattern is intentional and pragmatic. The accidental part is that operational memory is spread across Git docs, wiki pages, evidence JSON, PR bodies, local worktree names, and AI chat history.

## Fragility Under Scale

- Reviewer state is modeled but not durable.
- Feedback capture is aggregate/read-only rather than a governed ledger.
- Exception handling is visible but not yet a transactional register.
- Source remediation remains backlog-heavy.
- Knowledge indexing is still document-centric, not graph-centric.
- Verification depends on authenticated storage state and text selectors.
- Wiki/app/docs divergence can reappear without a synchronization model.

## World-Class Signals Already Present

- Governance labels are persistent and checked repeatedly.
- Unauthenticated API behavior is routinely verified.
- Runtime rollback artifacts are captured per phase.
- Human operations explicitly reject freeform confidential feedback.
- Source uncertainty is surfaced instead of hidden.
- AI assistance is bounded by checker/evidence loops instead of trusted implicitly.

## Audit Result

`PLATFORM_CAPABLE_FOR_CONTROLLED_INTERNAL_HUMAN_REVIEW_OPERATIONS_PENDING_COUNSEL_SIGNOFF_AND_DURABLE_REVIEWER_STATE`
