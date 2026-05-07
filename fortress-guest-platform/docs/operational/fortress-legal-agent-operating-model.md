# Fortress Legal Agent Operating Model

Last updated: `2026-05-06`

## Purpose

This document defines how AI agents and human operators may work on Fortress Legal now that Fortress-Prime is the canonical production repository.

## Session Start Requirements

Every future Codex or agent session must begin by recording:

- `pwd`
- `git branch --show-current`
- `git status --short`
- `git remote -v`
- `git log --oneline --decorate -10`
- Current production standing labels.
- Whether `.auth/` is ignored if authenticated UI checks are needed.

Do not assume `fortress-legal-app` is production canonical unless a later decision document supersedes this model.

## Allowed Agent Workstreams

Recommended workstreams:

- `REPO_AGENT`: repo state, branch, remotes, dirty files, unpushed commits.
- `CHECKER_AGENT`: authenticated checker path assumptions and UI verification status.
- `ARCHITECTURE_AGENT`: frontend/backend/API/script/doc mapping.
- `GOVERNANCE_AGENT`: signoff, draft, external-use, locked-content, and evidence boundaries.
- `VALIDATION_AGENT`: tests, lint, build, compile, checker, and environment blockers.
- `WIKI_AGENT`: wiki evidence and decision updates.
- `CLEANUP_AGENT`: drift inventory and unrelated dirty file avoidance.

Agents may inspect and report in parallel. Only the final integrator may stage, commit, push, or open PRs.

## What Agents May Inspect

Allowed:

- Source code.
- Tests.
- Operational docs.
- Manifest metadata.
- Git state.
- Package scripts.
- Route/API declarations.
- UI labels and component structure.
- File metadata for auth state, without opening auth contents.

Forbidden:

- Auth storage contents.
- Secrets or env files.
- Cookies, tokens, passwords, auth headers, service keys, DB URLs, or session values.
- Confidential legal document body text.
- Locked/restricted document contents.
- Production data bodies not already exposed in governed metadata manifests.

## What Agents May Mutate

Agents may propose but not directly mutate unless they are the final integrator.

The final integrator may mutate only explicitly scoped files:

- Fortress Legal source code.
- Fortress Legal tests.
- Fortress Legal operational docs.
- Fortress Legal architecture/runbook docs.
- Verification scripts.
- Wiki docs in approved phases.

Forbidden mutations:

- Upload or ingest documents.
- Create duplicate document rows or vectors.
- Mutate schema, RLS, policies, or privileges.
- Unlock restricted documents.
- Change auth protections unless explicitly scoped and reviewed.
- Record signoff without explicit human action.
- Create final legal conclusions.
- Authorize external submission.
- Touch unrelated dirty files.

## Single-Integrator Commit Rule

Only one final integrator may stage and commit. The integrator must:

- Stage paths explicitly.
- Run `git diff --cached --name-only`.
- Confirm no `.auth/` paths are staged.
- Run a focused staged secret-pattern scan.
- Keep commits small and phase-specific.
- Avoid staging unrelated dirty files.

## Evidence Requirements

Every production-facing phase must record:

- Execution ID if a manifest or workflow is generated.
- Evidence path.
- Tests/checks.
- Checker result when applicable.
- Hard-stop evaluation.
- Mutation invariants.
- Rollback/revert instructions.
- Final standing labels.

Evidence must not include confidential document contents or secrets.

## Hard Stops

Stop immediately if:

- Auth state or secrets might be exposed.
- A required step would inspect locked/restricted content.
- A required step would expose confidential document text.
- A required step would mutate schema, RLS, policies, or privileges.
- A required step would upload/ingest documents or create vectors.
- A required step would auto-sign, create final legal conclusions, or authorize external submission.
- Rollback identifiers cannot be captured for a production write.
- The repository source of truth is ambiguous for a code change.

## Branch Discipline

Canonical branch for this phase:

- `release/fortress-legal-canonicalization`

Base branch:

- `safety/foundation-audit-snapshot`

Do not merge or rebase unrelated work during canonicalization. Do not push until SSH/remote access is verified and staged secret checks pass.

## Commit Discipline

Preferred commit sequence:

1. Checker infrastructure.
2. Source-of-truth decision docs.
3. Architecture index.
4. Operational runbook index.
5. Agent operating model.
6. Drift inventory.
7. Validation evidence.
8. Wiki updates.

## Standing Labels

All work under this model preserves:

- `COUNSEL_SIGNOFF_PENDING`
- `DRAFT / COUNSEL REVIEW REQUIRED`
- `EXTERNAL SUBMISSION NOT AUTHORIZED`
- `NOT FINAL LEGAL ADVICE`
- Locked/restricted metadata-only handling

## Current Blockers

- Production checker reports Draft Work Product and Autonomous Learning not yet visible.
- 232 source issues remain unresolved and excluded.
- Fortress-Prime remote SSH fetch/push is blocked by public-key denial on this host.
- Existing unrelated dirty files must remain untouched.
