# Fortress Legal Governance Enforcement Verification

Status: GOVERNANCE_ENFORCEMENT_VERIFICATION_ACTIVE

## Required Checks

Every certification run must verify:

- COUNSEL_SIGNOFF_PENDING
- NOT_AUTHORIZED
- NOT FINAL LEGAL ADVICE
- NOT_CREATED final conclusions
- METADATA_ONLY restricted handling
- UNRESOLVED_SOURCE_EXCLUSION
- NO_SCHEMA_RLS_POLICY_MUTATION
- unauthenticated legal APIs return 401/403
- no secrets in committed artifacts
- no document contents in evidence

## Enforcement Surfaces

- authenticated production checker
- deployment verifier
- Strategy Packet / Controlled Review Operations panel
- review scaling panel
- operational certification panel
- evidence docs
- PR body governance checklist

## Failure Handling

Any enforcement failure is a hard stop. Do not continue into pilot usage until the failure is resolved, evidence is preserved, and rollback is verified.
