# Immutable Release Design Gap Analysis - 2026-05-07

Enterprise: Fortress Legal.
Worktree: `/home/admin/Fortress-Prime-legal-next`.
Branch: `feature/fortress-legal-next`.
Mode: design-only and docs-only.

## Summary

The current live `crog-ai.com` runtime is certified as Cloudflare Tunnel to a self-hosted Next.js standalone process on port `3005`. The deployment model is not yet release-grade because the active standalone runtime starts directly from the dirty canonical checkout, and the active BUILD_ID does not map cleanly to a source commit.

## Current Gaps

- Runtime artifact is mutable in place under the canonical repo checkout.
- Active artifact path is not an immutable release directory.
- No `current` or `previous` symlink strategy was observed.
- BUILD_ID provenance is incomplete.
- No release evidence file was certified for the active artifact.
- No artifact hash manifest was certified for the active artifact.
- Rollback artifacts exist, but rollback restore commands are not certified.
- No approved post-promotion smoke checklist is tied to artifact evidence.
- No HITL approval record is tied to active BUILD_ID.

## Target State

Fortress Legal should move toward:

```text
/home/admin/releases/fortress-legal/
  releases/
  current -> releases/<active-release>
  previous -> releases/<previous-release>
  evidence/
  rollback/
  logs/
```

The future service target should be:

```ini
WorkingDirectory=/home/admin/releases/fortress-legal/current
ExecStart=/usr/bin/node server.js
```

## Required Evidence

Each immutable release must preserve:

- source commit,
- source branch,
- worktree cleanliness,
- npm version,
- node version,
- package lock hash,
- build command,
- BUILD_ID,
- artifact path,
- smoke-test result,
- operator approval,
- timestamp,
- rollback target.

## Migration Risks

- Moving systemd too early could break the live runtime.
- Copying artifacts without a hash manifest could preserve the current provenance gap.
- Switching symlinks without verified rollback could increase recovery time.
- Authenticated smoke checks can expose sensitive state if not redacted.
- Existing dirty canonical worktree state must not be cleaned or normalized as part of this migration.
- CROG-VRS, Hedge Fund, Market Club, DB/Supabase, auth, Cloudflare/DNS, and `.auth` boundaries must remain isolated.

## Recommended Next Design Tasks

1. Draft release scripts in dry-run mode only.
2. Add a release evidence schema.
3. Add a hash-manifest procedure.
4. Add smoke-test runbook language with secret redaction.
5. Add an operator approval template.
6. Rehearse the full flow in a non-active directory.
7. Request explicit authorization before any service, symlink, or artifact mutation.

## Production Mutation Statement

No deploys, production artifact builds, service restarts, systemd changes, Cloudflare/DNS changes, DB/Supabase mutations, auth mutations, `.auth` access, `.next` replacement, rollback cleanup, dirty canonical worktree cleanup, or cross-enterprise mutations were performed.
