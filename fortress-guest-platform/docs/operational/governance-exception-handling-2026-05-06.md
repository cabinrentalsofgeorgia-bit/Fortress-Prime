# Governance Exception Handling - 2026-05-06

## Purpose

Define how controlled human reviewers should halt, escalate, and preserve evidence when governance boundaries are unclear or threatened.

## Exception Classes

- `unresolved_source_promotion_attempt`
- `restricted_content_visibility_concern`
- `contradiction_severity_escalation`
- `unauthorized_reviewer_access`
- `unexpected_api_visibility`
- `evidence_lineage_inconsistency`
- `rollback_verification_failure`
- `external_submission_control_visible`
- `signoff_shortcut_visible`
- `final_legal_conclusion_label_visible`

## Reviewer Halt Conditions

Reviewers must stop the active exercise and escalate if any exception suggests restricted-content exposure, unauthorized access, unresolved-source promotion, signoff automation, final legal advice, schema/RLS/policy change, or external submission authority.

## Escalation Procedure

1. Stop the affected review exercise.
2. Preserve the current standing labels.
3. Capture the safe exception class and affected panel or queue.
4. Avoid copying confidential document text.
5. Notify the queue manager or platform owner.
6. Run authenticated checker and deployment verifier if production state may be affected.
7. Use rollback artifacts only if a runtime change caused the exception.

## Rollback Triggers

- Checker fails governance assertions.
- Deployment verifier detects unexpected public access.
- Restricted-content boundary is uncertain.
- UI exposes signoff, final-advice, or external-submission controls.
- Evidence lineage becomes inconsistent after a runtime change.

## Final Standing Labels

Any governance exception keeps:

- `COUNSEL_SIGNOFF_PENDING`
- `NOT_AUTHORIZED`
- `NOT_CREATED`
- `NOT FINAL LEGAL ADVICE`
- `NOT_PERFORMED`
