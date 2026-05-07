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
