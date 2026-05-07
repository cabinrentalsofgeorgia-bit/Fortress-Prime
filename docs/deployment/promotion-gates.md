# Fortress Legal Promotion Gates

Status: deployment-lineage certification snapshot on 2026-05-07.

## Default Position

No production promotion is authorized by default. Local build stability is not production approval.

## Minimum Local Gates

For command-center baseline work, the known good local gate sequence is:

```bash
npm ci
npm test --workspace @fortress/command-center
npm run build --workspace @fortress/command-center
```

Run these from `fortress-guest-platform` unless a newer doc updates the command surface.

Command-center lint currently has unrelated existing debt outside the legal test fix scope. Treat lint as a tracked blocker, not a reason to mass-fix unrelated zones during Fortress Legal stabilization.

## Current Known Good Checkpoint

As of the baseline stabilization work immediately preceding this audit:

- `npm ci` ran from `fortress-guest-platform`.
- `npm test --workspace @fortress/command-center` passed.
- `npm run build --workspace @fortress/command-center` passed.
- Lint was blocked by unrelated existing lint debt in yield, trust-review, VRS, and tape-chart areas.
- No production deploy occurred.
- No production, auth, Supabase, DNS, Cloudflare, CROG-VRS, `.auth`, Hedge Fund, or Market Club mutation occurred.

## Production Promotion Gates

Before any production mutation, require all of the following:

1. Operator explicitly authorizes production mutation.
2. `docs/production/runtime-lineage.md` is current.
3. `docs/auth/auth-boundaries.md` is current.
4. `docs/database/supabase-classification.md` is current.
5. Rollback path is identified and documented.
6. Secrets are loaded only from approved secret stores and never printed.
7. Authenticated checker state is protected; `.auth/crog-ai-gary.json` is never exposed.
8. Legal data ingestion is explicitly authorized with exact filenames/counts if ingestion is in scope.

## Artifact Promotion Gates

The active `crog-ai.com` frontend currently runs from the canonical checkout's mutable `.next/standalone` output. Before any future production promotion, require all of the following evidence:

1. Source branch and source commit are recorded.
2. Build command and package-manager root are recorded.
3. Generated `BUILD_ID` is recorded before promotion.
4. Hash manifest covers `.next/BUILD_ID`, `.next/required-server-files.json`, standalone `server.js`, standalone `package.json`, and synced static/public assets.
5. Promotion target is recorded.
6. Promotion command is recorded.
7. Rollback artifact path is created and recorded before replacement.
8. Rollback restore command is recorded and dry-reviewed.
9. Post-promotion smoke checks are recorded.
10. Operator approval is explicit and tied to the exact artifact.

Future target layout:

```text
/home/admin/releases/fortress-legal/
  releases/
    <timestamp>-<commit>-<buildid>/
  current -> releases/<active-release>
  previous -> releases/<previous-release>
  evidence/
  rollback/
  logs/
```

Future target service shape:

```ini
WorkingDirectory=/home/admin/releases/fortress-legal/current
ExecStart=/usr/bin/node server.js
```

The target layout is design-only until an operator explicitly authorizes production mutation. Do not create these production directories, change systemd, switch symlinks, restart services, or replace artifacts during read-only certification phases.

## Immutable Promotion Flow

The future promotion flow must be executed only after explicit production authorization:

1. Verify clean source worktree.
2. Record source branch and commit.
3. Run local gates from the package-manager root.
4. Document lint disposition.
5. Build into a new immutable release directory.
6. Capture evidence and artifact hashes.
7. Run pre-promotion smoke against the candidate artifact without replacing production.
8. Obtain human-in-the-loop approval tied to the exact release directory and BUILD_ID.
9. Update `previous` to the old `current` target.
10. Switch `current` to the approved release directory.
11. Restart only the approved frontend service.
12. Run post-promotion smoke checks.
13. Retain rollback evidence.

Required evidence fields:

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

## Rollback Requirements

Rollback artifacts alone are not sufficient. A rollback-ready promotion must include:

- timestamped rollback artifact path,
- exact restore command,
- exact service action that would be required,
- expected `BUILD_ID` after rollback,
- unauthenticated smoke checks,
- authenticated smoke checks using approved non-printed checker state,
- operator decision log.

Do not execute rollback, restart services, or replace artifacts without explicit production-mutation authorization.

## Immutable Rollback Flow

The future rollback flow must be executed only after explicit production authorization:

1. Identify the `previous` release or an explicitly approved rollback target.
2. Verify the rollback target directory exists.
3. Verify rollback target evidence and BUILD_ID.
4. Capture pre-rollback state.
5. Switch `current` back to the approved rollback target.
6. Restart only the approved frontend service.
7. Run unauthenticated and approved authenticated smoke checks.
8. Capture rollback evidence.
9. Record operator decision, timestamp, reason, and resulting BUILD_ID.

Rollback must not use dirty checkout state as the target artifact.

## Forbidden Without Fresh Approval

- `vercel deploy`
- Supabase migrations, database reset, or schema push
- DNS or Cloudflare changes
- auth model refactors
- RLS/storage policy changes
- production data writes
- real legal document ingestion
- CROG-VRS, Hedge Fund, or Market Club changes

## Deployment Topology Ambiguity

Existing docs contain both Vercel project evidence and self-hosted Cloudflare Tunnel runtime evidence. Treat the live `crog-ai.com` attachment as Cloudflare Tunnel to self-hosted Next.js until a read-only runtime check proves otherwise.

## Current Deployment-Lineage Gaps

- Active artifact source commit is only partially certified.
- Active `BUILD_ID` is not mapped to a single source commit.
- Active artifact is directly coupled to the dirty canonical checkout.
- No symlink-based immutable release strategy was observed for the frontend.
- Exact promotion command was not certified.
- Exact rollback restore command was not certified.

## Dry-Run Release Tooling

These scaffolds are available for read-only release planning:

- `scripts/deployment/fortress-legal-release-evidence.sh`
- `scripts/deployment/fortress-legal-preflight.sh`
- `scripts/deployment/fortress-legal-rollback-plan.sh`

Each script defaults to dry-run/read-only behavior, refuses `.auth` path arguments, redacts secret-like output, emits evidence paths and recommended next action, and does not deploy, restart services, switch symlinks, mutate systemd, replace artifacts, or mutate DB/Supabase, Cloudflare/DNS, auth, CROG-VRS, Hedge Fund, or Market Club.

The scripts recognize `--i-understand-this-mutates-runtime` only as a hard stop in the current scaffold. A future mutating implementation must be reviewed separately and must require explicit operator approval tied to a release id, BUILD_ID, rollback target, and smoke-test plan.
