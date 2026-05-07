# Fortress Legal Promotion Gates

Status: read-only discovery snapshot on 2026-05-07.

## Default Position

No production promotion is authorized by default. Local build stability is not production approval.

## Minimum Local Gates

For command-center baseline work, the known good local gate sequence is:

```bash
npm ci
npm test
npm run lint
npm run typecheck
npm run build
```

Run these from `fortress-guest-platform` unless a newer doc updates the command surface.

## Current Known Good Checkpoint

As of the baseline stabilization work immediately preceding this audit:

- `npm ci` ran.
- `npm test` ran.
- `npm run lint` ran.
- `npm run typecheck` ran.
- `npm run build` ran.
- Lint passed with existing warnings retained.
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
