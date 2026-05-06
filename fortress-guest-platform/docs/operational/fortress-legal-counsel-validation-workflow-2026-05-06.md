# Fortress Legal Counsel Validation Workflow - 2026-05-06

## Scope

This phase creates the workflow for Gary/operator and counsel to validate AI-generated litigation intelligence and Counsel Review Workbench outputs. It does not complete counsel review, does not create final legal conclusions, and does not authorize filing, serving, sending, or external submission.

All unreviewed or partially reviewed outputs remain `DRAFT / COUNSEL REVIEW REQUIRED`. Accepted items use `accepted_for_review_use`, not final legal conclusion.

## Baseline

- Production domain: `https://crog-ai.com`.
- Matter: Fortress Legal Production Review.
- Matter slug: `fortress-legal-production-review`.
- Workbench execution ID: `fortress-counsel-review-20260506-073330`.
- Source intelligence execution ID: `fortress-intel-20260506-041839`.
- Validation execution ID: `fortress-validation-20260506-081435`.
- Validation manifest: `/mnt/fortress_nas/audits/fortress-validation-20260506-081435.json`.
- Documents: `80`.
- Completed/analyzed: `78`.
- Locked/restricted: `2` metadata-only.
- Timeline events: `180`.
- Graph nodes: `448`.
- Graph edges: `1,227`.
- Contradiction candidates: `14`.
- Issues: `20`.
- Evidence binders: `17`.
- Entity dossier records: `40`.
- Counsel questions/actions: `24`.

## Hard Stop Evaluation

- Release worktree: correct current workbench release state; starting commit `022f1e05f266a50d0ac560a3de6ce6982d20460b`.
- Existing workbench commits present: `920a9a7c22c7f08a69a8c9713c00018ca7c5e865`, `23205586615a415621cf4aff7308f7c5a4b16113`, `187a2dc2a`.
- Production app smoke: root HTTP `200`; matter route HTTP `200`.
- Public exposure check: unauthenticated counsel validation API returned HTTP `401`.
- Existing workbench baseline reconciled: YES.
- Locked/restricted content required: NO.
- Confidential document contents printed in evidence: NO.
- Schema migration required: NO.
- RLS/policy change required: NO.
- Privilege grant required: NO.
- New ingestion/upload required: NO.
- Duplicate document/vector risk: NO.
- Rollback identifiers captured: YES, in validation manifest rollback block.
- Result: NO_HARD_STOP.

## Validation Store

- Store mechanism: file-backed validation manifest under `/mnt/fortress_nas/audits`.
- Reason: avoids schema/RLS/policy changes while preserving versioned validation state and rollback/delete identifiers.
- Backend service: `backend.services.legal_counsel_validation`.
- Protected API routes:
  - `GET /api/internal/legal/cases/{slug}/counsel-validation`.
  - `POST /api/internal/legal/cases/{slug}/counsel-validation/actions`.
- Auth model: existing staff manager/admin legal API gate.
- Unauthenticated behavior: `401`.
- List/summary payloads include metadata, statuses, source-reference counts, and safe item titles only.
- Locked/restricted handling: metadata-only validation records; locked content is not read or returned.

## Validation Records

- Total validation records: `299`.
- Issue validation records: `20`.
- Evidence binder validation records: `17`.
- Contradiction validation records: `14`.
- Entity dossier validation records: `40`.
- Counsel question/action validation records: `24`.
- Theory packet validation records: `2`.
- Timeline validation records: `180`.
- Locked metadata-only validation records: `2`.
- Initial statuses: unaccepted; seeded as `needs_counsel_review`, `needs_source_check`, or `privileged_locked_metadata_only`.
- Counsel signoff: pending.
- Progress label: `VALIDATION_NOT_STARTED`.

## Workflow Controls

Implemented controls:

- Accept item for review use.
- Reject item.
- Correct item.
- Mark needs source check.
- Mark needs more evidence.
- Mark counsel review required.
- Reopen item.
- Add operator/counsel note.
- Attach source-check status.
- Preserve audit/history for each action.

Status guardrails:

- Allowed accepted state: `accepted_for_review_use`.
- Forbidden states in this phase: `final_legal_conclusion`, `filed`, `served`, `counsel_signed_off`.
- Rejected items remain visible in audit/history.
- Corrections create a version increment and audit record.

## UI/API Summary

- Matter page now includes a default `Validation` tab.
- Counsel Review Workbench remains available.
- Document/Vault, Master Chronology, Panopticon, Deliberation, Vanguard, and Graph Radar remain available.
- Validation dashboard shows:
  - validation item count,
  - progress percentage,
  - accepted-for-review-use count,
  - source-check count,
  - counsel signoff pending state.
- Validation queues are visible in the UI bundle.
- Item rows expose validation status, source-check status, source-reference count, metadata-only lock indicators, and action controls.
- Audit trail is visible or accessible from the validation panel.
- All panels preserve `DRAFT / COUNSEL REVIEW REQUIRED`.

Authenticated Gary/operator UI confirmation: PENDING.

## Tests And Checks

- Python syntax: PASS.
- Backend focused tests: PASS, `4 passed`.
- Frontend focused tests: PASS, `9 passed`.
- Focused ESLint: PASS.
- Frontend production build: PASS.
- `git diff --check`: PASS.
- Focused secret scan over changed diff: PASS.

Backend test note: the local test runner warned that `TEST_DATABASE_URL` was not set; the focused route tests used mocked loaders/actions and did not perform database writes.

## Deploy / Restart Evidence

- Code commit: `8b7874963` (`feat(legal): add counsel validation workflow`).
- Runtime-main cherry-pick: `5ad1ac35a`.
- Backend restart: `fortress-backend.service` restarted and active.
- Frontend restart: `crog-ai-frontend.service` restarted and active.
- Production root smoke: HTTP `200`.
- Production matter-route smoke: HTTP `200`.
- Public validation API exposure check: unauthenticated HTTP `401`.
- Public workbench API exposure check: unauthenticated HTTP `401`.
- Live bundle contains validation workflow code path: YES.

## Mutation Invariants

- New raw document upload: NO.
- New ingest: NO.
- New document rows: NO.
- New Qdrant document vectors: NO.
- New validation records: YES, file-backed validation manifest only.
- Duplicate workbench records: NO.
- Schema changes: NO.
- RLS/policy changes: NO.
- Privilege changes: NO.
- Locked/restricted content read or analyzed: NO.
- Secrets printed/exposed: NO.
- Document contents printed/exposed in evidence: NO.
- Unrelated dirty files touched: NO.

## Rollback / Delete

- Manifest path: `/mnt/fortress_nas/audits/fortress-validation-20260506-081435.json`.
- Validation record IDs captured: YES, in manifest rollback block.
- Rollback readiness: delete the validation manifest to remove this validation-initialization state; no raw document/vector/schema rollback required.
- Remaining risk: authenticated Gary/operator UI confirmation remains pending.

## Standing State

- Production status: `PRODUCTION_COUNSEL_VALIDATION_BACKEND_COMPLETE_UI_PENDING`.
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`.
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_COUNSEL_VALIDATION_WORKFLOW`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_ANALYZED_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_INTELLIGENCE_WORKBENCH_AND_VALIDATION_COMPLETE`.
- Product status: `COUNSEL_VALIDATION_BACKEND_READY_UI_PENDING`.
- Counsel status: `COUNSEL_REVIEW_REQUIRED`.

Remaining action: Gary/operator must authenticate to `https://crog-ai.com/legal/cases/fortress-legal-production-review`, verify the new `Validation` tab/section, validation queues, item statuses, accept/reject/correct/source-check controls, notes, audit/history, draft/counsel-review labeling, and locked metadata-only handling.

## Final Authenticated Counsel Validation UI Confirmation

- Confirmation timestamp: `2026-05-06T08:25:31-04:00`.
- Confirmation source: Gary/operator authenticated production UI observation.
- Route checked: `https://crog-ai.com/legal/cases/fortress-legal-production-review`.
- Counsel Validation tab visible as default matter tab: YES.
- Validation summary visible: YES.
- Validation queues visible: YES.
- Accept / reject / correct controls visible: YES.
- Source-check controls visible: YES.
- Notes capability visible or available through validation action payload: YES.
- Audit/history visible or accessible: YES.
- `DRAFT / COUNSEL REVIEW REQUIRED` labeling preserved: YES.
- Locked/restricted documents remain metadata-only: YES.
- Locked/restricted content displayed: NO.
- Unauthenticated validation API remains guarded: YES.
- Blocking UI/API errors preventing review: NO.

Final confirmation-step mutation invariants:

- New raw document upload: NO.
- New ingest: NO.
- New document rows: NO.
- New Qdrant document vectors: NO.
- Duplicate workbench records: NO.
- Schema changes: NO.
- RLS/policy changes: NO.
- Privilege changes: NO.
- Production deploy/restart: NO.
- Secrets printed/exposed: NO.
- Document contents printed/exposed in evidence: NO.
- Locked/restricted content analyzed or exposed: NO.
- Unrelated dirty files touched: NO.

Final standing state:

- Production status: `PRODUCTION_COUNSEL_VALIDATION_WORKFLOW_ACTIVE`.
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`.
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_COUNSEL_VALIDATION_WORKFLOW`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_ANALYZED_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_INTELLIGENCE_WORKBENCH_AND_VALIDATION_COMPLETE`.
- Product status: `COUNSEL_VALIDATION_WORKFLOW_READY_FOR_GARY_AND_COUNSEL`.
- Counsel status: `COUNSEL_REVIEW_IN_PROGRESS`.

Governance note: this confirms the validation workflow is production-visible and ready for Gary/counsel use. It does not mean counsel review is complete, does not mark counsel signoff complete, and does not convert AI outputs into final legal conclusions.

## Counsel Signoff + Reviewed Strategy Packet - 2026-05-06

- Evidence timestamp: `2026-05-06T08:42:21-04:00`.
- Signoff packet execution ID: `fortress-signoff-packet-20260506-084028`.
- Signoff packet manifest: `/mnt/fortress_nas/audits/fortress-signoff-packet-20260506-084028.json`.
- Source validation execution ID: `fortress-validation-20260506-081435`.
- Packet version: `1`.
- Packet checksum/hash: `34e942c10aed757ae31491b3d05c9c3ee951834dc2f50c0a40741d3bf0d8f892`.
- Packet sections: `18`.
- Readiness status: `SIGNOFF_PACKET_READY_WITH_UNRESOLVED_ITEMS`.
- Signoff status: `COUNSEL_SIGNOFF_PENDING`.
- Explicit signoff recorded: NO.
- Automatic signoff created: NO.
- Strategy Packet UI/API deployed: YES.
- Authenticated Gary/operator UI confirmation: PENDING.

Mutation invariants:

- New raw document upload: NO.
- New ingest: NO.
- New document rows: NO.
- New Qdrant document vectors: NO.
- Duplicate validation records: NO.
- Duplicate workbench records: NO.
- Schema changes: NO.
- RLS/policy changes: NO.
- Privilege changes: NO.
- Locked/restricted content analyzed: NO.
- Document contents printed/exposed in evidence: NO.
- Counsel signoff complete: NO.

Updated standing state:

- Production status: `PRODUCTION_COUNSEL_SIGNOFF_PACKET_BACKEND_COMPLETE_UI_PENDING`.
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`.
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_COUNSEL_SIGNOFF_PACKET_REVIEW`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_REVIEW_PACKET_READY_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_INTELLIGENCE_WORKBENCH_VALIDATION_AND_SIGNOFF_PACKET_COMPLETE`.
- Product status: `REVIEWED_STRATEGY_PACKET_BACKEND_READY_UI_PENDING`.
- Counsel status: `COUNSEL_SIGNOFF_PENDING`.

## Final Strategy Packet UI Confirmation - 2026-05-06

- Confirmation timestamp: `2026-05-06T08:50:45-04:00`.
- Confirmation source: Gary/operator authenticated production UI observation.
- Route checked: `https://crog-ai.com/legal/cases/fortress-legal-production-review`.
- Strategy Packet / Signoff tab or section visible: YES.
- Signoff Readiness Dashboard visible: YES.
- Strategy Packet visible/reviewable: YES.
- Source Integrity Matrix visible: YES.
- Unresolved Items Register visible: YES.
- Signoff Capture panel visible: YES.
- `DRAFT / COUNSEL REVIEW REQUIRED` posture preserved: YES.
- `COUNSEL_SIGNOFF_PENDING` preserved: YES.
- Explicit signoff performed: NO.
- Counsel Validation remains available: YES.
- Locked/restricted documents remain metadata-only: YES.
- Source-check unresolved count: `297`.

Final standing state:

- Production status: `PRODUCTION_COUNSEL_SIGNOFF_PACKET_ACTIVE`.
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`.
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_COUNSEL_SIGNOFF_PACKET_REVIEW`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_REVIEW_PACKET_READY_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_INTELLIGENCE_WORKBENCH_VALIDATION_AND_SIGNOFF_PACKET_COMPLETE`.
- Product status: `REVIEWED_STRATEGY_PACKET_READY_FOR_COUNSEL_SIGNOFF`.
- Counsel status: `COUNSEL_SIGNOFF_PENDING`.
