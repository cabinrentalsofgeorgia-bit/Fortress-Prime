# Division: CROG-VRS (Sector 01 — "Cabin Rentals of Georgia")

Owner: Gary Mitchell Knight (operator)
Status: **active** — operational property-management platform
Spark allocation:
- **Current:** **Spark 2 (`192.168.0.100`, control plane @ `100.80.122.100`) — ACTIVE.** Currently double-duty as CROG-VRS host AND temporary Financial-division (Market Club replacement scaffolding) tenant AND control plane.
- **Target:** Spark 2 remains CROG-VRS's permanent home. Once Spark 3 provisions and Financial migrates off, Spark 2 sheds the tenant role. The control-plane role (Captain / Council / Sentinel) is **OPEN per ADR-002** — may stay on Spark 2 permanently or move to a dedicated shared-infra spark.
Last updated: 2026-04-26

## Purpose

Short-term-rental (STR) property management for Cabin Rentals of Georgia. Public storefront at `cabin-rentals-of-georgia.com` for guest bookings; internal command-center at `crog-ai.com` for staff operations + AI agents. Integrates with Streamline (PMS), Stripe (payments), Channex (channel manager), Twilio (guest comms).

This is the platform's **public-facing** surface. Per CONSTITUTION.md, it must never cross-link to Fortress Legal data (Zone A vs Zone B isolation).

## Key data stores

### Postgres

- `public.properties` — listing inventory (cabins, rates, amenities, geom)
- `public.bookings`, `public.reservations` — guest stays
- `public.guests`, `public.guest_messages` — guest CRM + comms
- `public.email_archive` — archived guest correspondence (~42k rows)
- `public.streamline_*` — Streamline PMS mirror tables (parity-monitored)
- `public.channex_*` — Channex channel-manager state + ARI cache
- `public.trust_transactions`, `public.trust_ledger_entries` — sovereign immutable ledger (writes via `master-accounting`, reads from CROG)

### Qdrant

- `fortress_knowledge` — Sentinel-owned NAS-walker corpus including property documentation
- `email_embeddings` — guest correspondence embeddings (filtered by division)
- `fgp_sent_mail` — sent-mail subset (provenance unknown per 2026-04-25 audit)

### NAS

- `/mnt/fortress_nas/Business_Prime/` — property documents, listings, marketing assets
- `/mnt/fortress_nas/sectors/` — cross-sector shared documents

## Key services consumed

- [Captain](../shared/captain-email-intake.md) — inbound guest email capture
- [Sentinel](../shared/sentinel-nas-walker.md) — NAS document indexing (property docs → `fortress_knowledge`)
- [Auth + secrets](../shared/auth-and-secrets.md) — JWT for staff portal, Cloudflare Tunnel for ingress
- External: Streamline (PMS), Stripe (payments), Channex (channels), Twilio (SMS), CallRail (call tracking), Vrbo / HomeAway

## Key services exposed

- `apps/storefront/` — Next.js 16 public guest site (app router, ISR-enabled)
- `apps/command-center/` — Next.js 16 internal staff + AI dashboard
- `backend/api/` — 124+ FastAPI routers (channex, streamline, properties, bookings, etc.)
- `backend/services/` — 76+ SQLAlchemy models, business logic
- Channex egress worker: `fortress-channex-egress.service`
- Parity monitor: `fortress-parity-monitor.service`
- ARQ background workers: `fortress-arq-worker.service`

## Recent merged PRs

Many. See `git log --oneline origin/main` and [`../../CHANGELOG.md`](../../CHANGELOG.md). The 2026-04-25/26 changelog sections focus on legal; CROG-VRS development pre-dates that period and isn't in the changelog yet (legacy work).

## Open questions for operator

- Are there active SEO migration tasks under crog-vrs (the Drupal Strangler Fig per CLAUDE.md)?
- Does the legacy Drupal estate (2,514 nodes, 4,530 redirects) belong in this division doc or a separate `seo-migration.md`?
- Is BLOOM (Sector 04 — "Verses in Bloom" digital retail per `fortress_atlas.yaml`) part of CROG-VRS or its own division? It's not in the current architecture-foundation scope but appears in the runtime atlas.

## Cross-references

- Atlas entry: [`../../../fortress_atlas.yaml`](../../../fortress_atlas.yaml) Sector 01
- Storefront app: `apps/storefront/`
- Command-center app: `apps/command-center/`
- Sovereign ledger doctrine: [`../../../CONSTITUTION.md`](../../../CONSTITUTION.md) Article III
- Drupal migration: [`../IRON_DOME_ARCHITECTURE.md`](../IRON_DOME_ARCHITECTURE.md), [`../iron-dome-phase-4-nvidia-integration.md`](../iron-dome-phase-4-nvidia-integration.md)

Last updated: 2026-04-26
