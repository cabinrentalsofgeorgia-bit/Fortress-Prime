# Immutable Runtime Migration Plan - 2026-05-07

Enterprise: Fortress Legal.
Worktree: `/home/admin/Fortress-Prime-runtime-migration`.
Branch: `feature/fortress-immutable-runtime-migration`.
Base: `origin/release/fortress-legal-canonicalization`.
Mode: planning, dry-run design, and safety validation only.

## Objective

Plan the migration from the current dirty-checkout runtime coupling to an immutable release runtime without deploying, building or replacing production artifacts, restarting services, changing systemd, switching symlinks, touching live `.next`, or mutating Cloudflare/DNS, DB/Supabase, auth, `.auth`, production data, CROG-VRS, Hedge Fund, or Market Club.

## Current Runtime

Certified current frontend runtime:

```text
/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center
```

Current service shape:

```ini
WorkingDirectory=/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center
ExecStart=/usr/bin/node server.js
```

Known current risks:

- runtime artifact is under the dirty canonical checkout,
- active BUILD_ID does not map cleanly to a single source commit,
- rollback artifacts exist but rollback execution is not certified,
- no active immutable `current` / `previous` symlink strategy exists.

## Target Runtime

Target release root:

```text
/home/admin/releases/fortress-legal/
  releases/
    <timestamp>-<commit>-<buildid>/
      server.js
      package.json
      .next/
      public/
      evidence.json
      hashes.sha256
  current -> releases/<active-release>
  previous -> releases/<previous-release>
  evidence/
  rollback/
  logs/
```

Future service shape:

```ini
WorkingDirectory=/home/admin/releases/fortress-legal/current
ExecStart=/usr/bin/node server.js
```

This target is not authorized by this document. It requires explicit production-mutation approval before any directory creation in production release paths, systemd change, symlink switch, or service restart.

## Phase A - Design And Dry-Run Validation

Allowed now:

1. Keep work in `/home/admin/Fortress-Prime-runtime-migration`.
2. Run read-only scaffolds:
   - `scripts/deployment/fortress-legal-preflight.sh --dry-run`
   - `scripts/deployment/fortress-legal-release-evidence.sh --dry-run`
   - `scripts/deployment/fortress-legal-rollback-plan.sh --dry-run`
3. Validate shell syntax with `bash -n`.
4. Update docs and risk registers.

Forbidden now:

- creating production release directories,
- building production artifacts,
- copying artifacts into `/home/admin/releases/fortress-legal`,
- editing systemd,
- switching symlinks,
- restarting services,
- touching live `.next`,
- reading `.auth`,
- mutating DB/Supabase, Cloudflare/DNS, auth, production data, CROG-VRS, Hedge Fund, or Market Club.

## Phase B - Future Release Directory Creation

Requires explicit approval if performed under `/home/admin/releases/fortress-legal`.

Future steps:

1. Verify clean source worktree and exact source commit.
2. Choose release id:

   ```text
   YYYYMMDD-HHMMSS-<12-char-commit>-<BUILD_ID>
   ```

3. Create parent layout if absent:

   ```text
   /home/admin/releases/fortress-legal/releases
   /home/admin/releases/fortress-legal/evidence
   /home/admin/releases/fortress-legal/rollback
   /home/admin/releases/fortress-legal/logs
   ```

4. Create candidate release directory under `releases/<release-id>`.
5. Do not point `current` at the release until HITL approval and smoke gates pass.

## Phase C - Future Immutable Artifact Build

Requires explicit approval before any production-facing artifact build or copy.

Future steps:

1. From `fortress-guest-platform`, run:

   ```bash
   npm ci
   npm test --workspace @fortress/command-center
   npm run build --workspace @fortress/command-center
   npm run lint --workspace @fortress/command-center
   ```

2. Record lint disposition:
   - pass,
   - non-blocking warnings with registry references,
   - or explicit operator-approved waiver.
3. Read generated BUILD_ID from the clean worktree artifact.
4. Copy the complete standalone artifact into the candidate release directory.
5. Copy required `.next/static` and `public` assets only through reviewed build tooling.
6. Generate `hashes.sha256` for:
   - `.next/BUILD_ID`,
   - `.next/required-server-files.json`,
   - `server.js`,
   - `package.json`,
   - `.next/static`,
   - `public`.

## Phase D - Evidence Capture

Future `evidence.json` must include:

- enterprise,
- source branch,
- source commit,
- worktree cleanliness,
- node version,
- npm version,
- package lock hash,
- package-manager root,
- package name,
- build command,
- BUILD_ID,
- artifact path,
- hash manifest path,
- lint disposition,
- pre-promotion smoke result,
- post-promotion smoke result,
- operator approval,
- timestamp,
- rollback target.

Evidence must not include secrets, cookies, tokens, auth headers, DB URLs, Supabase keys, service-role keys, `.auth` contents, or production data.

## Phase E - Staging Without Activation

Future staging is complete only when:

1. Candidate release directory exists.
2. `server.js`, `package.json`, `.next/BUILD_ID`, `evidence.json`, and `hashes.sha256` exist.
3. Hash verification passes.
4. Candidate BUILD_ID matches evidence.
5. Candidate is not referenced by `current`.
6. No production service has been restarted.
7. No symlink has been switched.

Recommended non-activation smoke options:

- run `node server.js` only on a non-production port after explicit local-only approval,
- or perform static artifact checks only when no port is approved.

Do not bind to port `3005` during staging.

## Phase F - Future Smoke Testing

Unauthenticated smoke:

- local candidate `/login` returns expected login shell,
- no response headers expose secrets,
- candidate BUILD_ID and evidence match.

Authenticated smoke requires separate approval and must use non-printed checker state. `.auth` must not be read or printed by default tooling.

Production smoke after activation:

- `https://crog-ai.com/login`,
- `http://127.0.0.1:3005/login`,
- known legal production review route only if approved,
- no DB writes,
- no legal/customer data ingestion.

## Phase G - Future Systemd Override Preparation

Future proposed override:

```ini
[Service]
WorkingDirectory=/home/admin/releases/fortress-legal/current
ExecStart=
ExecStart=/usr/bin/node server.js
```

Preparation requirements:

1. Preserve current unit content.
2. Draft override as a file in repo docs first.
3. Human review verifies exact service name: `crog-ai-frontend.service`.
4. Human review verifies rollback command and previous release.
5. Apply override only in an approved production mutation window.

This plan does not authorize `systemctl edit`, `daemon-reload`, or service restart.

## Phase H - Future Symlink Switch Approval

Before switching `current`, require:

1. release id,
2. source commit,
3. BUILD_ID,
4. hash manifest verification,
5. pre-promotion smoke pass,
6. rollback target,
7. rollback restore command,
8. operator approval,
9. explicit service restart approval,
10. incident window and responsible operator.

Future switch sequence after approval:

1. Set `previous` to old `current`.
2. Set `current` to approved release.
3. Restart only `crog-ai-frontend.service`.
4. Run post-promotion smoke.
5. Record evidence and resulting BUILD_ID.

## Phase I - Rollback Verification

Before activation:

1. Verify `previous` points to a known-good release.
2. Verify previous release has `evidence.json`, `hashes.sha256`, and `.next/BUILD_ID`.
3. Verify rollback command is written and reviewed.
4. Verify smoke checklist is written and reviewed.

Future rollback sequence after approval:

1. Capture current failed release id.
2. Switch `current` back to approved rollback target.
3. Restart only `crog-ai-frontend.service`.
4. Run smoke checks.
5. Record rollback evidence, reason, operator, timestamp, and resulting BUILD_ID.

## Required Future Scripts

Existing scaffolds are read-only and do not mutate production:

- `scripts/deployment/fortress-legal-preflight.sh`
- `scripts/deployment/fortress-legal-release-evidence.sh`
- `scripts/deployment/fortress-legal-rollback-plan.sh`

Future reviewed scripts needed:

- `scripts/deployment/fortress-legal-build-release.sh`
- `scripts/deployment/fortress-legal-promote-release.sh`
- `scripts/deployment/fortress-legal-smoke.sh`
- `scripts/deployment/fortress-legal-rollback-execute.sh`
- `scripts/deployment/fortress-legal-systemd-override-plan.sh`

All future mutating scripts must:

- require `--i-understand-this-mutates-runtime`,
- require exact release id,
- require approval reference,
- refuse dirty worktrees,
- refuse `.auth` reads by default,
- redact secrets,
- write evidence,
- support dry-run,
- fail closed on missing rollback target.

## Approval Gates

Required approval gates:

1. Build candidate approval.
2. Production release-directory creation approval.
3. Candidate smoke-test approval.
4. Systemd override approval.
5. Symlink switch approval.
6. Service restart approval.
7. Post-promotion smoke approval.
8. Rollback execution approval.

## Non-Mutation Statement

This plan was created without deploying, building or replacing production artifacts, restarting services, changing systemd, switching symlinks, touching live `.next`, cleaning the dirty canonical worktree, reading `.auth`, or mutating Cloudflare/DNS, DB/Supabase, auth, production data, CROG-VRS, Hedge Fund, or Market Club.
