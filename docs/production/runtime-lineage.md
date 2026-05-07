# Fortress Legal Runtime Lineage

Status: read-only discovery snapshot on 2026-05-07.

## Known Production Identity

- Production domain: `https://crog-ai.com`.
- Known matter: `Fortress Legal Production Review`.
- Known matter slug: `fortress-legal-production-review`.
- Production UI path: `/legal/cases/fortress-legal-production-review`.

## Current Runtime Finding

Read-only repository evidence points to this production lineage:

1. `crog-ai.com` is the staff Command Center surface.
2. The command-center app is the Next.js app at `fortress-guest-platform/apps/command-center`.
3. Repository tunnel documentation maps `crog-ai.com`, `www.crog-ai.com`, and `console.crog-ai.com` to local port `3005`.
4. Historical operational audit records port `3005` as a self-hosted Next.js standalone command-center server.
5. Command-center `/api/*` route handlers proxy to the backend and preserve or synthesize `fortress_session` authentication for backend calls.

## Vercel Evidence

Existing docs reference Vercel project `crog-ai-command-center`, but other operational docs state `crog-ai.com` is served by self-hosted Next.js standalone through Cloudflare Tunnel. Treat this as an active topology ambiguity:

- Vercel metadata exists.
- Cloudflare Tunnel to self-hosted Next.js is the documented live domain path.
- Do not deploy to Vercel or promote any deployment without explicit operator authorization and a fresh topology check.

## Runtime Boundaries

Agents must not:

- Deploy.
- Restart production services.
- Edit active Cloudflare config.
- Alter DNS.
- Mutate auth, RLS, storage, Supabase, or production data.
- Ingest real legal documents.
- Touch CROG-VRS, Hedge Fund, or Market Club systems.

## Required Future Update

Before any production-facing build or promotion, update this file with:

- exact source commit,
- exact package built,
- exact deployment target,
- exact promotion command,
- exact rollback target,
- explicit operator approval reference.
