# Fortress Legal System Topology

Status: read-only discovery snapshot on 2026-05-07.

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

Read-only repository evidence shows:

- `fortress-guest-platform/infra/gateway/config.yml` documents Cloudflare Tunnel ingress for `crog-ai.com`, `www.crog-ai.com`, and `console.crog-ai.com` to `http://127.0.0.1:3005`.
- That same file states the active Cloudflare config lives outside the repo at `/etc/cloudflared/config.yml`; repo copy is documentation only.
- Historical operational audit `docs/operational/flos-frontend-audit-2026-04-27.md` records command-center production as a self-hosted Next.js standalone server on port `3005`.
- Historical docs also mention Vercel project metadata for `crog-ai-command-center`; this is treated as deployment metadata, not proof that the current live `crog-ai.com` path is Vercel.

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
