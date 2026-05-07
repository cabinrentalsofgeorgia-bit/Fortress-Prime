# Immutable Runtime Migration Risk Register - 2026-05-07

Enterprise: Fortress Legal.
Worktree: `/home/admin/Fortress-Prime-runtime-migration`.
Branch: `feature/fortress-immutable-runtime-migration`.
Mode: planning and risk classification only.

## Summary

The migration from dirty-checkout runtime coupling to immutable release runtime is necessary but production-sensitive. The current live `crog-ai.com` frontend runs from the canonical checkout `.next/standalone` directory. The target is `/home/admin/releases/fortress-legal/current`, but no production directory, systemd, symlink, artifact, or service mutation is authorized by this phase.

## Risk Register

| ID | Risk | Severity | Current Control | Required Mitigation |
| --- | --- | --- | --- | --- |
| R1 | Active runtime artifact is coupled to dirty canonical checkout. | High | Runtime lineage documented. | Move to immutable release root only after approved migration window. |
| R2 | Active BUILD_ID does not map cleanly to exact source commit. | High | Deployment lineage partially certified. | Capture source commit, package-lock hash, BUILD_ID, and hash manifest for every future release. |
| R3 | Systemd override mistake could break `crog-ai.com`. | High | No systemd mutation allowed in planning. | Draft override in docs, peer review, preserve current unit, require rollback command. |
| R4 | Symlink switch can activate incomplete artifact. | High | Symlink switching forbidden in planning. | Verify `server.js`, `package.json`, `.next/BUILD_ID`, static assets, evidence, and hashes before approval. |
| R5 | Rollback artifacts exist but rollback execution is uncertified. | High | Rollback gaps documented. | Require `previous` release verification, restore command, expected BUILD_ID, and smoke checklist. |
| R6 | Smoke tests could expose or require auth state. | Medium | `.auth` reads forbidden by default. | Keep unauthenticated smoke default; require separate approval for authenticated checker state. |
| R7 | Production release build could be generated from dirty worktree. | High | Clean worktree strategy exists. | Refuse dirty worktrees in future build script. |
| R8 | Lint debt could trigger unrelated cleanup across enterprise boundaries. | Medium | CI quality classification exists. | Treat lint warnings as scoped debt; no cross-enterprise mass cleanup. |
| R9 | DB/Supabase/auth mutation could be accidentally coupled to deployment. | High | Promotion gates forbid mutation. | Keep deployment scripts frontend-artifact-only; no migrations or auth changes. |
| R10 | Qdrant/VRS settings could cross enterprise boundaries. | High | Enterprise boundaries documented. | Do not change Qdrant/VRS flags or services in runtime migration. |
| R11 | Cloudflare/DNS could be modified unnecessarily. | High | Runtime topology certified as tunnel-to-local. | Do not change Cloudflare/DNS; migration changes only local frontend runtime after approval. |
| R12 | Candidate release may pass static checks but fail runtime startup. | Medium | Future smoke gate required. | Stage on non-production port only after approval, then run local smoke before activation. |
| R13 | Evidence could leak secrets. | High | Redaction rules documented. | Evidence schema must exclude secrets, cookies, auth headers, DB URLs, Supabase keys, and `.auth`. |
| R14 | Canonical dirty worktree cleanup could destroy unrelated operator work. | High | Cleanup forbidden. | Do not clean canonical worktree; use isolated worktree for migration. |
| R15 | Existing scripts are dry-run only and cannot perform migration. | Medium | Current scaffolds reject mutation flag. | Create reviewed mutating scripts in a future phase with explicit approval gates. |

## Blocking Conditions Before Migration

Do not proceed to production mutation until all are true:

- release directory plan reviewed,
- future build/promote/rollback scripts reviewed,
- candidate release built from clean worktree,
- evidence captured,
- hash manifest verified,
- rollback target verified,
- systemd override reviewed,
- smoke checklist approved,
- HITL approval recorded,
- maintenance/incident window assigned.

## Safe Next Step

The next safe phase is to implement dry-run-only migration script drafts in this isolated worktree. Those drafts must still avoid creating `/home/admin/releases/fortress-legal`, avoid systemd mutation, avoid symlink switches, avoid service restarts, and avoid live `.next`.

## Production Mutation Statement

No deploys, production artifact builds, artifact replacements, service restarts, systemd changes, symlink switches, Cloudflare/DNS changes, DB/Supabase mutations, auth mutations, `.auth` reads, production data mutations, CROG-VRS mutations, Hedge Fund mutations, Market Club mutations, live `.next` access, or dirty canonical cleanup were performed.
