# Fortress Legal Rollback Certification - 2026-05-06

Status: ROLLBACK_CERTIFICATION_ACTIVE

## Rollback Requirements

Every controlled pilot operations change must be git-revertable and, if deployed, have runtime rollback references.

## Rollback Procedure

1. Revert the certification commits.
2. Restore frontend runtime artifact if a runtime deploy occurred.
3. Restore backend service files if a runtime deploy occurred.
4. Restart affected services.
5. Run service status checks.
6. Run authenticated checker.
7. Run deployment verifier.
8. Confirm governance labels and unauthenticated API guards.

## Required Verification After Rollback

- authenticated checker
- deployment verifier
- unauthenticated API guards
- governance label check
- no final legal advice
- no external submission authority
- no schema/RLS/policy mutation

## Boundaries

Rollback must not upload documents, rerun ingestion, create vectors, mutate schema/RLS/policies, inspect locked/restricted content, or alter counsel signoff state.
