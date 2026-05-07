# CLI Agent Operating Rules

Status: active as of 2026-05-07.

## Operating Mode

1. Plan first.
2. Perform read-only system discovery before build work.
3. Use clean branches or clean worktrees for docs or code changes.
4. Keep scope narrow.
5. Report blockers instead of guessing through production ambiguity.

## Security Rules

Never print, copy, commit, expose, weaken, or modify:

- `.auth/crog-ai-gary.json`
- cookies
- tokens
- auth headers
- passwords
- Supabase keys
- database URLs
- private keys
- service-role keys

Keep `.auth` ignored. Do not remove `.auth` from `.gitignore`.

## Forbidden Actions Without Explicit Operator Approval

- Production deploys.
- Supabase schema pushes, migrations, resets, RLS changes, storage changes, or data writes.
- DNS or Cloudflare changes.
- Vercel production mutation.
- Auth refactors.
- Real legal document ingestion.
- CROG-VRS changes.
- Hedge Fund changes.
- Market Club changes.
- Force pushes.
- Destructive git commands.
- Runtime service restarts.
- Systemd changes.
- Production symlink switches.
- Production artifact replacement.

## Safe Discovery Commands

Preferred read-only commands:

- `pwd`
- `ls`
- `find`
- `rg`
- `git status -sb`
- `git branch -vv`
- `git log`
- `git remote -v`
- `git diff`
- `npm audit`
- `node --check`

Build verification commands are allowed only when local and non-mutating:

- `npm ci`
- `npm test`
- `npm run lint`
- `npm run typecheck`
- `npm run build`

Dry-run release planning commands are allowed when they remain non-mutating:

- `scripts/deployment/fortress-legal-release-evidence.sh --dry-run`
- `scripts/deployment/fortress-legal-preflight.sh --dry-run`
- `scripts/deployment/fortress-legal-rollback-plan.sh --dry-run`

These scripts must not read `.auth`, print secrets, deploy, restart services, switch symlinks, mutate systemd, replace artifacts, or mutate DB/Supabase, Cloudflare/DNS, auth, CROG-VRS, Hedge Fund, or Market Club.

Read-only health commands are allowed when they remain unauthenticated and non-mutating:

- `scripts/ops/fortress-legal-health.sh`
- `scripts/ops/spark2-control-plane-health.sh`

Health scripts may inspect hostname, uptime, disk, memory, git status, operational doc presence, service active state, listening ports, and unauthenticated local HTTP endpoints. They must not read `.auth`, print secrets, deploy, restart services, change systemd, switch symlinks, replace artifacts, or mutate DB/Supabase, Cloudflare/DNS, auth, production data, CROG-VRS, Hedge Fund, or Market Club.

## Documentation Rule

Update operational memory when discovering or changing:

- canonical repo or branch,
- runtime host/domain/path,
- deployment target,
- Vercel project link,
- Supabase project/database classification,
- auth model,
- Fortress Legal UI routes,
- checker scripts,
- CI/test/build gates,
- required env var names,
- forbidden files,
- repo status classification.

## CI And Quality Gate Rule

For Fortress Legal command-center stabilization, the current package-level gates are:

```bash
cd /home/admin/Fortress-Prime-legal-next/fortress-guest-platform
npm test --workspace @fortress/command-center
npm run build --workspace @fortress/command-center
npm run lint --workspace @fortress/command-center
```

Quality gate discipline:

- Treat passing tests and passing build as required for legal-platform merge readiness.
- Treat lint warnings as debt only when `eslint` exits 0.
- Do not mass-fix lint during Fortress Legal work.
- Do not edit unrelated VRS, Market Club, Hedge Fund, yield, trust-review, tape-chart, or shared component files unless the task explicitly owns that area.
- Classify lint output by enterprise/domain before recommending cleanup.
- Keep a debt registry with file path, warning rule, owner/domain, and blocking status.
- A PR may be merge-safe despite unrelated lint warnings when tests/build pass, lint exits 0, and the changed files are scoped to the approved enterprise.

## Commit Rule

Docs-only commits are allowed only when:

- canonical repo is clear,
- worktree is clean or a clean worktree is created,
- staged files are documentation only,
- no `.auth`, `.env*`, `.next`, rollback artifact, build artifact, secret, or production data file is staged.

Suggested branch:

```bash
docs/operational-memory-topology-audit
```

Suggested commit:

```bash
docs: establish Fortress Legal operational memory
```
