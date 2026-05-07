# Fortress Legal System Topology

Status: runtime topology certification snapshot on 2026-05-07.

This file is permanent operational memory. Future agents must update it when topology facts change, and must not rely on chat context as the source of truth.

## Canonical Source

- Canonical repository for Fortress Legal operational work: `cabinrentalsofgeorgia-bit/Fortress-Prime`.
- Canonical local subtree: `fortress-guest-platform`.
- Canonical branch observed for current Fortress Legal work: `release/fortress-legal-canonicalization`.
- Existing architecture index: `fortress-guest-platform/docs/architecture/fortress-legal-architecture-index.md`.
- Existing runbook index: `fortress-guest-platform/docs/operational/fortress-legal-operational-runbook-index.md`.

The split repositories `fortress-legal-app` and `fortress-legal-wiki` exist locally, but the current Fortress Legal architecture index says `fortress-legal-app` is not feature-equivalent and must not be treated as production source without a deliberate migration project.

## Runtime Surfaces

- Production domain: `https://crog-ai.com`.
- Known production matter: `Fortress Legal Production Review`.
- Known production matter slug: `fortress-legal-production-review`.
- Command Center package owner: `fortress-guest-platform/apps/command-center`, package name `@fortress/command-center`.
- Command Center framework: Next.js App Router.
- Backend owner for Fortress Legal APIs and ingestion services: `fortress-guest-platform/backend`.
- Primary BFF path: command-center Next.js `/api/*` routes proxy to the backend and bridge the `fortress_session` cookie.

## Host And Network Topology

Read-only live inspection on Spark-2 certifies:

- Active Cloudflare config lives at `/etc/cloudflared/config.yml`.
- `cloudflared.service` is active and reads `/etc/cloudflared/config.yml`.
- Active ingress maps `crog-ai.com`, `www.crog-ai.com`, and `console.crog-ai.com` to `http://127.0.0.1:3005`.
- Port `3005` is owned by `crog-ai-frontend.service`.
- `crog-ai-frontend.service` runs `next-server (v16.1.6)` from `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center`.
- `fortress-guest-platform/infra/gateway/config.yml` is a documentation copy, not the loaded config.
- Active `/etc/cloudflared/config.yml` also maps `fortress.crog-ai.com` and `api.crog-ai.com` to `http://127.0.0.1:9800`, and `api.cabin-rentals-of-georgia.com` to `http://127.0.0.1:8000`.
- Active `/etc/cloudflared/config.yml` includes `staging-api.crog-ai.com -> http://127.0.0.1:8026`; the repo documentation copy currently lacks that active mapping.
- Historical operational audit `docs/operational/flos-frontend-audit-2026-04-27.md` correctly records command-center production as a self-hosted Next.js standalone server on port `3005`.
- Historical docs and dirty canonical worktree metadata mention Vercel project `crog-ai-command-center`; this is deployment/provider metadata, not proof that the live `crog-ai.com` path is Vercel.

Certified runtime path:

```text
crog-ai.com
  -> Cloudflare edge
  -> cloudflared.service on Spark-2
  -> /etc/cloudflared/config.yml
  -> http://127.0.0.1:3005
  -> crog-ai-frontend.service
  -> Next.js standalone command-center
```

## Data Plane

- PostgreSQL database names documented in architecture: `fortress_prod`, `fortress_db`, `fortress_shadow`, and `fortress_shadow_test`.
- Legal runtime and ingest code reference `POSTGRES_API_URI`, `POSTGRES_ADMIN_URI`, `DATABASE_URL`, and `TEST_DATABASE_URL`. Secret values must never be printed.
- Qdrant legal collections documented and referenced in code: `legal_ediscovery` and `legal_privileged_communications`.
- Supabase production provider/project evidence is documented in existing operational reports as `Fortress Legal Production`, with the project ref redacted in operational use as `hms...liap`. Do not print database URLs or service keys.

## UI Routes

Fortress Legal UI routes live under:

- `/legal`
- `/legal/cases/[slug]`
- `/legal/cases/[slug]/war-room`
- `/legal/cases/[slug]/deposition/[targetId]/print`
- `/legal/council`
- `/legal/email-intake`

The known production matter route is:

- `https://crog-ai.com/legal/cases/fortress-legal-production-review`

## Checker Scripts

- Known authenticated checker: `scripts/verification/check-crog-fortress-ui.mjs`.
- This checker depends on local auth state; agents must not print, copy, commit, or weaken `.auth/crog-ai-gary.json`.

## Agent Rule

Any change to runtime topology, deployment path, auth behavior, database classification, or route ownership must update this file and the relevant specialized docs in `docs/production`, `docs/deployment`, `docs/auth`, and `docs/database`.
