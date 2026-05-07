# Immutable Release And Rollback Design - 2026-05-07

Enterprise: Fortress Legal.
Worktree: `/home/admin/Fortress-Prime-legal-next`.
Branch: `feature/fortress-legal-next`.
Mode: design-only and docs-only.

## Objective

Define a future immutable release and rollback model for the `crog-ai.com` Fortress Legal command-center runtime without deploying, rebuilding production artifacts, restarting services, changing systemd, replacing `.next`, changing Cloudflare/DNS, mutating auth, touching `.auth`, or mutating DB/Supabase.

## Current Risk

The certified live runtime currently starts from:

```text
/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center
```

That path is inside the dirty canonical checkout. The active BUILD_ID does not map cleanly to a single source commit. Rollback artifacts exist, but rollback execution is not certified.

## Target Layout

Future releases should be staged under:

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

Release directory naming:

```text
YYYYMMDD-HHMMSS-<12-char-commit>-<BUILD_ID>
```

The release directory must be complete, immutable after evidence capture, and independent of the source checkout.

## Future Systemd Target

The future frontend unit should point at the immutable `current` symlink:

```ini
WorkingDirectory=/home/admin/releases/fortress-legal/current
ExecStart=/usr/bin/node server.js
```

This is a proposed future target only. This phase does not change systemd.

## Evidence Format

Each release must include `evidence.json` with:

```json
{
  "enterprise": "Fortress Legal",
  "source_branch": "feature/fortress-legal-next",
  "source_commit": "<git sha>",
  "worktree_clean": true,
  "node_version": "<node -v>",
  "npm_version": "<npm -v>",
  "package_lock_sha256": "<sha256>",
  "package_manager_root": "fortress-guest-platform",
  "package": "@fortress/command-center",
  "build_command": "npm run build --workspace @fortress/command-center",
  "build_id": "<BUILD_ID>",
  "artifact_path": "/home/admin/releases/fortress-legal/releases/<release>",
  "hash_manifest": "hashes.sha256",
  "pre_promotion_smoke": "<pass|fail|not-run>",
  "post_promotion_smoke": "<pass|fail|not-run>",
  "lint_disposition": "<passed|blocked-by-existing-debt|waived-with-approval>",
  "operator_approval": "<approval id or human decision log>",
  "timestamp": "<UTC timestamp>",
  "rollback_target": "<previous release id>"
}
```

Do not store secrets, cookies, auth headers, DB URLs, tokens, or `.auth` contents in evidence.

## Promotion Flow

Promotion requires explicit human approval because it mutates production. Proposed flow:

1. Start from a clean Fortress Legal worktree.
2. Confirm branch and source commit.
3. Confirm no unrelated dirty files.
4. Run `npm ci` from `fortress-guest-platform`.
5. Run `npm test --workspace @fortress/command-center`.
6. Run `npm run build --workspace @fortress/command-center`.
7. Record lint disposition. Do not mass-fix unrelated lint debt.
8. Copy the complete standalone artifact into a new immutable release directory.
9. Capture BUILD_ID, hashes, versions, source metadata, and rollback target.
10. Run pre-promotion smoke against the candidate release without replacing production.
11. Obtain HITL approval tied to release id, source commit, BUILD_ID, and rollback target.
12. Update `previous` to the old `current` target.
13. Switch `current` to the approved release.
14. Restart only the approved frontend service.
15. Run post-promotion smoke checks.
16. Retain release evidence and rollback evidence.

Steps 12 through 15 are production mutations and are forbidden until explicitly authorized.

## Rollback Flow

Rollback requires explicit human approval because it mutates production. Proposed flow:

1. Identify `previous` or an explicitly approved rollback release.
2. Verify rollback artifact exists and contains `server.js`, `package.json`, `.next/BUILD_ID`, `evidence.json`, and `hashes.sha256`.
3. Verify hashes.
4. Record current release and rollback reason.
5. Switch `current` back to the rollback target.
6. Restart only the approved frontend service.
7. Run unauthenticated smoke checks.
8. Run authenticated smoke checks only with approved non-printed checker state.
9. Capture rollback evidence with timestamp, operator approval, resulting BUILD_ID, and smoke results.

Steps 5 through 8 are production mutations and are forbidden until explicitly authorized.

## Smoke-Test Gate

Smoke tests must avoid exposing secrets and must not ingest real legal/customer data.

Minimum unauthenticated smoke:

- `https://crog-ai.com/login` returns the expected Next.js login shell through Cloudflare.
- `http://127.0.0.1:3005/login` returns the expected local Next.js login shell.
- Response headers do not reveal secrets.

Minimum authenticated smoke, only when approved checker state exists:

- Legal case detail route loads for the known non-ingestion production review matter.
- Command-center API proxy behavior is checked without printing cookies or auth headers.
- No DB writes, document ingestion, or auth mutation occurs.

## Dry-Run Tooling Scaffolds

Initial dry-run scaffolds:

- `scripts/deployment/fortress-legal-release-evidence.sh`
- `scripts/deployment/fortress-legal-preflight.sh`
- `scripts/deployment/fortress-legal-rollback-plan.sh`

Script requirements:

- default to dry-run/read-only mode,
- reject the explicit mutation flag until a reviewed mutating implementation exists,
- emit evidence paths and recommended next action,
- redact secrets,
- refuse arguments that reference `.auth`,
- avoid `.auth` reads,
- avoid service restarts,
- avoid symlink changes,
- avoid deploy commands,
- avoid artifact replacement,
- never mutate DB/Supabase, Cloudflare/DNS, auth, CROG-VRS, Hedge Fund, or Market Club,
- avoid writing evidence files until an approved release flow exists.

Deferred mutating scripts, requiring separate review and explicit production authorization:

- `scripts/deployment/fortress-legal-build-release.sh`
- `scripts/deployment/fortress-legal-promote-release.sh`
- `scripts/deployment/fortress-legal-smoke.sh`
- `scripts/deployment/fortress-legal-rollback-execute.sh`

## Migration Path

1. Design scripts and review them in a clean worktree.
2. Run dry-run evidence capture against a non-production release path.
3. Build a candidate immutable artifact in a non-active release directory.
4. Compare candidate artifact against the active runtime without replacement.
5. Document operator approval requirements.
6. Schedule an approved production mutation window.
7. Change systemd target only after approval.
8. Preserve the canonical checkout runtime until immutable rollback is proven.

## Risks

- Dirty-worktree runtime coupling may hide uncommitted artifact provenance.
- BUILD_ID cannot currently prove source commit by itself.
- Direct `.next` runtime replacement is error-prone.
- Rollback artifacts may be incomplete without restore commands.
- Smoke checks can become unsafe if they print auth state or mutate data.
- A systemd change without a verified release directory could take the site down.

## Non-Mutation Statement

This document is design-only. No deploys, builds of production artifacts, runtime restarts, systemd changes, Cloudflare/DNS changes, DB/Supabase mutations, auth mutations, `.auth` access, `.next` replacement, rollback directory removal, dirty worktree cleanup, or cross-enterprise changes were performed.
