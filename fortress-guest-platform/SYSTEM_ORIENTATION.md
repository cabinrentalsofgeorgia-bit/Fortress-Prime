# SYSTEM_ORIENTATION.md
**Generated:** 2026-04-15  
**Author:** Claude Code — Phase G.0.5 read-only discovery  
**Status:** Source of truth for all subsequent phase work. Load this at the start of every session.

---

## 1. Executive Summary

Fortress Prime is a sovereign, on-premises short-term rental platform for `cabin-rentals-of-georgia.com`. It runs entirely on a local NVIDIA DGX Spark cluster with no cloud databases. The system has two Next.js frontends (public storefront at `cabin-rentals-of-georgia.com`, staff command center at `crog-ai.com`), a FastAPI backend on Python, and a PostgreSQL instance with two logically separate databases. It is mid-strangler-fig: most operational flows now run through the Crog-VRS system with Streamline as the data mirror for historical and channel distribution purposes. The AI surface is deep — 19 systemd services including concierge inference, recursive agent loops, SEO swarm, legal agents, and a nightly fine-tune pipeline.

**The single most important thing to know before any phase work:** The FastAPI application does **not** use `fortress_guest`. It uses `fortress_shadow`. The `DATABASE_URL` env var in `.env` pointing to `fortress_guest` is a legacy artefact and is ignored by the runtime. The G.1 cleanup phase investigated the wrong database; its "nothing to clean" conclusion applies only to `fortress_guest`. `fortress_shadow` — the real runtime DB — contains significant test data contamination from Phase A-F development that must be cleaned before G.2 produces meaningful output.

---

## 2. Two-Database Model

### The databases

| Database | Role | Alembic Owner | Alembic Current Head | FastAPI Uses? | Notes |
|---|---|---|---|---|---|
| `fortress_shadow` | **Primary runtime DB** | `fortress_admin` | `e6a1b2c3d4f5` | **YES** | 120 tables, all Phase A-F tables, 26 active connections |
| `fortress_guest` | Legacy/secondary DB | `fgp_app` (own branch) | `c4a8f1e2b9d0` | **NO** | 105 tables, real historical reservation data, 1 active connection |

### How the application connects

`backend/core/config.py` defines:
```python
@property
def database_url(self) -> str:
    return self._rewrite_database_driver(self.postgres_api_uri, async_driver=True)
```
`POSTGRES_API_URI` = `postgresql+asyncpg://fortress_api:fortress@127.0.0.1:5432/fortress_shadow`

So `settings.database_url` → `fortress_shadow`. Every SQLAlchemy session from `get_db()` writes to `fortress_shadow`.

Alembic uses `POSTGRES_ADMIN_URI` → `postgresql+asyncpg://fortress_admin:fortress@127.0.0.1:5432/fortress_shadow` (or as labelled in `alembic.ini`: `fortress_prod`, but env.py overwrites this at runtime).

The `DATABASE_URL=postgresql://fgp_app:...@localhost:5432/fortress_guest` in `.env` is read by legacy scripts and validation tools but **not** by the FastAPI runtime. The settings validator rejects `fortress_guest` as a database name (allowed set: `{"fortress_prod", "fortress_shadow", "fortress_db"}`).

### fortress_shadow — row counts for statement-related tables

| Table | Rows | Notes |
|---|---|---|
| `owner_balance_periods` | 17,692 | **17,492 are test fixtures** (period_start ≥ 2050); only **200 real** |
| `owner_payout_accounts` | 1,261 | **1,047 are @test.com**; only **92 real** (non-test email) |
| `owner_charges` | 311 | Mix of test and real; needs audit |
| `owner_statement_sends` | 55 | Mix of test and real |
| `owner_magic_tokens` | 401 | Mix; some from Phase A-F test runs |
| `payout_ledger` | 0 | Empty |
| `properties` | 98 | Real cabin names (same 14 active as fortress_guest, plus 84 inactive historical) |
| `reservations` | 100 | Small count — most real reservations live in fortress_guest |
| `guests` | 125 | Small count — same situation as reservations |
| `staff_users` | 5 | Real staff records |

### fortress_guest — row counts (historical/legacy)

| Table | Rows | Notes |
|---|---|---|
| `reservations` | 2,665 | Real historical bookings — NOT mirrored to fortress_shadow |
| `properties` | 14 | Only the 14 currently active cabins |
| `owner_payout_accounts` | 0 | Empty |
| `owner_magic_tokens` | 7 | 1 real owner (sl_owner_id=897648) who attempted onboarding in March but never completed |
| `owner_statements` (legacy) | 0 | Empty |
| `owner_statement_archive` | 9 | Real Streamline-imported PDFs (Jan/Dec/Nov 2025-26) |
| `payout_ledger` | 0 | Empty |

### Why the two DBs have different data

`fortress_guest` appears to be a mirror/replica or the pre-migration operational database that is no longer receiving writes from the application. `fortress_shadow` is the current-generation production DB. The reservation and guest data in fortress_guest represents the full historical record that has not been migrated to fortress_shadow, which only has a subset (likely synced via the Streamline sync worker from recent months).

**Open question for Gary:** Should the historical reservation data in fortress_guest be migrated to fortress_shadow? Are the two databases intended to coexist long-term, or is fortress_guest being wound down?

### Alembic state — fortress_shadow

Current applied head: `e6a1b2c3d4f5` — Phase A-F migrations fully applied.  
Single head (no branch divergence): `e6a1b2c3d4f5 (parity_audit, offline_buffer, property_tax_geo)`.

**The docs in `docs/alembic-reconciliation-plan.md` and `docs/alembic-prod-rollout-runbook.md` are stale.** They describe upgrading from `c7d8e9f0a1b2` to `e8b1c4d7f9a2`. The actual DB is already at `e6a1b2c3d4f5` — far beyond what the runbook describes. Those docs were written mid-migration and were never updated after Phase A-F landed.

---

## 3. Systemd Services (Production)

19 services total. The "four separate systemd processes" referenced in early planning is no longer accurate.

| Service | State | Port | What it does | Venv/Binary |
|---|---|---|---|---|
| `fortress-backend` | **running** | ~8100 (unix or TCP) | FastAPI application (`run.py`) | `.uv-venv/bin/python` |
| `fortress-arq-worker` | **running** | — | ARQ async job worker (`backend.core.worker.WorkerSettings`) | `.uv-venv/bin/python` |
| `fortress-console` | **running** | 9800 | Python `master_console.py` — internal ops tool, **NOT** the Next.js command center | `/home/admin/Fortress-Prime/venv/bin/python3` |
| `fortress-dashboard` | **running** | varies | Storefront Next.js app from `apps/storefront` | `run-fortress-dashboard.sh` |
| `fortress-sync-worker` | **running** | — | Streamline PMS full poll (`backend.sync`) | `.uv-venv/bin/python` |
| `fortress-event-consumer` | **running** | — | Automation event consumer | `.uv-venv/bin/python` |
| `fortress-channex-egress` | **running** | — | Channex availability push egress | `.uv-venv/bin/python` |
| `crog-concierge-worker` | **running** | — | Concierge inference daemon (`src.daemons.concierge_worker`) | `/home/admin/Fortress-Prime/venv` |
| `fortress-ray-head` | **running** | — | Ray distributed compute head node | — |
| `fortress-sentinel` | **running** | — | Continuous NAS document indexing | — |
| `fortress-telemetry` | **running** | — | Telemetry agent | — |
| `fortress-vllm-bridge` | **running** | — | vLLM bridge for GPU inference | — |
| `fortress-watcher` | **running** | — | File watcher | — |
| `litellm-gateway` | **running** | 8002 | LiteLLM sovereign model router | `~/.local/bin/litellm` |
| `ollama` | **running** | 11434 | Ollama inference server (qwen2.5:7b etc) | `/usr/local/bin/ollama` |
| `crog-hunter-worker` | inactive | — | Reactivation Hunter daemon | — |
| `fortress-deadline-sweeper` | inactive | — | Deadline sweep worker | — |
| `fortress-inference` | exited | — | Legal inference (DGX Sparks) | — |
| `fortress-nightly-finetune` | **FAILED** | — | Nightly LLM fine-tune job | — |

### Critical clarification: fortress-console vs Next.js command center

`fortress-console.service` description says "port 9800" and "crog-ai.com" — but it runs `master_console.py` (a Python tool), NOT the Next.js command center. The **actual Next.js command center** (`apps/command-center`) IS deployed and is the `next-server` process listening on **port 3001** (confirmed via `ss -tlnp`). The gateway routes `crog-ai.com` → port 3001, which correctly serves the Next.js app. The fortress-console/9800 Python tool is a separate internal management surface.

### Active ports confirmed

| Port | Process | Notes |
|---|---|---|
| 3001 | `next-server (v16)` | Next.js command center — crog-ai.com |
| 8002 | `litellm` | Sovereign model router |
| 9800 | `python3` master_console.py | Internal ops tool — NOT behind gateway |
| 11434 | ollama | Inference server (internal) |
| 5432 | postgres | Both DBs |

FastAPI (fortress-backend) port not observed via `ss` — may use a unix socket or port not captured.

---

## 4. Repository Directory Map

```
fortress-guest-platform/
├── apps/
│   ├── command-center/src/app/      Next.js 16 staff dashboard (crog-ai.com)
│   │   ├── (dashboard)/             Protected route group — all staff pages
│   │   │   ├── admin/               Admin Ops Glass (payouts, disputes, contracts, onboarding)
│   │   │   ├── acquisition/         Property acquisition pipeline
│   │   │   ├── agreements/          Rental agreement management
│   │   │   ├── ai-engine/           Dispatch Radar AI interface
│   │   │   ├── analytics/           Operations dashboard + insights
│   │   │   ├── automations/         Rule Engine UI
│   │   │   ├── command/             Fortress Prime telemetry, parity, yield, settings
│   │   │   ├── damage-claims/       Damage claim desk
│   │   │   ├── email-intake/        Email triage inbox
│   │   │   ├── growth/              SEO copilot, redirect remaps, AB testing, SEM
│   │   │   ├── guestbooks/          Guestbook guide editor + extras
│   │   │   ├── guests/              Guest CRM with detail pages
│   │   │   ├── housekeeping/        Housekeeping dispatch
│   │   │   ├── intelligence/        Market intelligence + market-shadow
│   │   │   ├── iot/                 IoT device command
│   │   │   ├── legal/               Legal dockets, cases, council, e-discovery
│   │   │   ├── messages/            Guest communications
│   │   │   ├── nemo-command-center/ NeMo trust ledger view
│   │   │   ├── payments/            Virtual terminal
│   │   │   ├── prime/               Iron Dome Ledger
│   │   │   ├── properties/          Property fleet + detail pages
│   │   │   ├── reservations/        Tape chart + reservation detail
│   │   │   ├── seo/                 SEO review queue
│   │   │   └── vrs/                 Adjudication Glass, Hunter, Quotes
│   │   └── api/                     BFF route handlers (proxy to FastAPI)
│   └── storefront/src/app/          Next.js 16 public website
│       ├── (storefront)/            SEO-facing pages (availability, cabins, guides)
│       ├── (guest)/                 Guest itinerary portal
│       ├── (owner)/                 Owner portal (accept-invite, onboarding-complete)
│       ├── owner-login/             Owner magic-link login
│       ├── book/                    Direct booking flow
│       ├── sign/[token]/            Rental agreement signing
│       ├── cabins/[slug]/           Individual cabin pages
│       ├── reviews/                 Guest reviews archive
│       └── [...slug]/               Drupal legacy page fallback
├── backend/
│   ├── agents/                      Standalone agent classes (financial, grec, nemo)
│   ├── alembic/versions/            All migration files (e6a1b2c3d4f5 is head)
│   ├── api/                         FastAPI route handlers (124+ routers)
│   ├── core/                        Config, DB engine, security, queue
│   ├── integrations/                External API clients (Streamline, Stripe, etc.)
│   ├── models/                      SQLAlchemy ORM models (76+ models)
│   ├── orchestration/               Orchestration helpers
│   ├── schemas/                     Pydantic request/response models
│   ├── scripts/                     One-off scripts, migration helpers, SQL cleanup files
│   ├── services/                    Business logic, agent services, swarm services
│   │   └── agent_swarm/             Graph/nodes/state for LangGraph agent swarm
│   ├── sync/                        Streamline PMS sync worker
│   ├── tasks/                       ARQ async job definitions
│   ├── templates/                   Jinja2 email + PDF templates
│   ├── tests/                       Pytest test suite
│   ├── vrs/                         VRS domain (application, domain, infrastructure, seo)
│   └── workers/                     Long-running workers (hermes, finetune, recursive agent)
├── packages/
│   ├── config/                      @fortress/config — shared ESLint/TS baseline (stub, no exports)
│   └── ui/                          @fortress/ui — shared UI primitives (stub, no exports)
├── docs/                            Architecture docs and runbooks
├── infra/gateway/                   Cloudflare tunnel config
└── scripts/                         Build helpers (standalone asset sync)
```

---

## 5. Domain Enumeration

| Domain | Key Files | DB | Strangler-Fig Status | Live Today | Known Issues |
|---|---|---|---|---|---|
| **Owner Statements** | `api/admin_statements_workflow.py`, `api/admin_statements.py`, `services/statement_workflow.py`, `services/statement_computation.py`, `models/owner_balance_period.py`, `models/owner_charge.py` | fortress_shadow | **partial** — backend complete (Phase A-F), no frontend UI yet | Backend APIs live, cron exists, email send works | DB contaminated with test data; G.2 UI not built; no real owner enrolled |
| **Stripe Connect Payouts** | `api/admin_payouts.py`, `api/admin_charges.py`, `models/owner_payout.py` | fortress_shadow | **native** (never in Streamline) | Frontend page `/admin/payouts` fully built; sweep/schedule/manual payout work | `payout_ledger` empty in production |
| **Property Management** | `api/properties.py`, `models/property.py` | fortress_shadow | **partial** — Crog-VRS owns property metadata, Streamline owns availability/rates | Property CRUD in command center | Rate cards managed in Streamline |
| **Reservations** | `api/reservations.py`, `models/reservation.py`, `backend/sync/` | Both DBs | **partial** — Streamline is authority, sync-worker mirrors to fortress_shadow | Sync running; fortress_guest has 2,665 real reservations; fortress_shadow has 100 | Historical reservations not migrated to fortress_shadow |
| **Channel Manager (Channex)** | `api/channel_mgr.py`, `api/webhooks_channex.py`, `api/admin_channex.py`, `fortress-channex-egress.service` | fortress_shadow | **partial** — Channex signed webhook ingest built, egress worker running, downstream event contract is a no-op stub | Channex availability pushed to OTAs | Webhook handler is observability-only (explicit no-op per docs) |
| **Guest Messaging** | `api/messages.py`, `api/communications.py`, `services/crog_concierge_engine.py`, `crog-concierge-worker.service` | fortress_shadow | **partial** — AI concierge owns automated responses, human staff override in command center | Concierge worker running | — |
| **VRS Adjudication (Paperclip AI)** | `api/vrs.py`, `api/vrs_operations.py`, `vrs/` DDD structure, `services/hunter_service.py` | fortress_shadow | **native** | Hunter queue, approval flow, quotes, reactivation — all live | — |
| **Trust Ledger / Accounting** | `services/trust_ledger.py`, `api/stripe_webhooks.py`, `workers/hermes_daily_auditor.py`, `models/trust_ledger.py` | fortress_shadow | **native** | Append-only ledger with SHA-256 hash chain; Hermes audits daily at midnight | Immutability triggers active — never UPDATE/DELETE |
| **Work Orders / Housekeeping** | `api/workorders.py`, `api/housekeeping.py`, `services/housekeeping_agent.py` | fortress_shadow | **partial** — Streamline checklist is authority; work orders managed natively | Work order CRUD live | — |
| **SEO Operator** | `api/seo_remaps.py`, `api/seo_godhead.py`, `vrs/seo/`, `services/seo_rewrite_swarm.py`, `services/seo_grading_service.py`, `services/seo_deploy_consumer.py` | fortress_shadow | **native** | SEO patch queue, copilot, redirect remaps — live in command center | 4,530 Drupal 301 redirects must be preserved |
| **Legal (Fortress Legal)** | `api/legal_*.py` (8 files), `services/legal_agent_orchestrator.py` | fortress_shadow | **native** | Active dockets, e-discovery, council, deposition war room — live in command center | Legal inference service is `exited` state |
| **IoT** | `api/iot.py` | fortress_shadow | **native** | IoT page in command center | — |
| **Intelligence / Market** | `api/intelligence.py`, `api/intelligence_feed.py`, `api/intelligence_projection.py`, `workers/nightly_distillation_exporter.py` | fortress_shadow | **native** | Market intelligence feed live | — |
| **Acquisition Pipeline** | `api/acquisition_pipeline.py`, `api/admin_acquisition.py` | fortress_shadow | **native** | Acquisition pipeline page live | — |
| **Direct Booking / Checkout** | `api/direct_booking.py`, `api/checkout.py`, `api/fast_quote.py`, `services/agentic_sales.py` | fortress_shadow | **partial** — Crog-VRS owns checkout; Streamline PMS is final authority for booking | Storefront booking flow live | — |
| **Guest Portal** | `api/guest_portal_api.py`, `api/portal.py`, storefront `(guest)/itinerary` | fortress_shadow | **native** (capability-link portal) | Guest itinerary portal live | — |
| **Owner Portal** | `api/owner_portal.py` (only invite routes!), storefront `(owner)/` | fortress_shadow | **partial** — invite flow exists; portal views are stubs | Magic link flow works; onboarding completes to OPA row | No statement views; the owner_portal.py `/api/owner/statements/{id}` hook is a 404 |
| **NeMo / Recursive Agent** | `workers/recursive_agent_loop.py`, `agents/nemo_observer.py`, `services/swarm_policy_engine.py` | fortress_shadow | **native** | 3-vertical agent flywheel running every 30 min | — |
| **Hermes / Streamline Sync** | `workers/hermes_sync.py`, `workers/hermes_daily_auditor.py`, `backend/sync/` | fortress_shadow + Streamline API | **partial** | Sync worker running; daily auditor running as asyncio task inside FastAPI | — |
| **Damage Claims** | `api/damage_claims.py` | fortress_shadow | **native** | Damage claim desk live | — |
| **Agreements / Contracts** | `api/agreements.py`, `api/contracts.py` | fortress_shadow | **partial** — digital agreement generation native; Streamline approval separate | Contract management panel in admin | — |

---

## 6. Agent Map

| Agent/Service | Purpose | DB Reads | DB Writes | Other Services Called | Triggered By |
|---|---|---|---|---|---|
| `workers/hermes_daily_auditor.py` | Daily parity audit of active reservations; SHA-256 hash-chain verification | `reservations`, `trust_transactions`, `parity_audits` | `financial_approvals`, `parity_audits` | Streamline API, NeMo Observer | `asyncio.create_task` in FastAPI lifespan (daily at midnight UTC) |
| `workers/hermes_sync.py` | Retry failed Streamline PMS pushes from `pending_sync`; runs parity audit after success | `pending_sync`, `reservations` | `pending_sync`, `parity_audits`, `financial_approvals` | Streamline API, trust_ledger service | ARQ job queue (every 60s) |
| `workers/recursive_agent_loop.py` | Cross-vertical intelligence flywheel (V1=VRS, V2=RE-DEV, V3=AI-FACTORY) — 3 verticals feed each other | `intelligence_ledger`, `distillation_queue`, `reservations`, `leads` | `intelligence_ledger`, `distillation_queue`, `rlhf_telemetry` | LiteLLM gateway, Hunter service, SEO services | Cron-like loop every 1800s |
| `workers/nightly_distillation_exporter.py` | Exports training distillations nightly | `intelligence_ledger`, `distillation_queue` | NAS filesystem | — | Nightly (systemd timer or internal loop) |
| `agents/financial/grec_auditor.py` | GREC Trust Accounting audit of proposed double-entry transactions | (none — receives proposals) | (none — returns audit reports) | OpenAI/LiteLLM (GPT-4o) | Called by trust_ledger service |
| `agents/nemo_observer.py` | NeMo command center observer — escalates anomalies | `trust_transactions`, `trust_ledger_entries` | `openshell_audit_logs` | LiteLLM (local models) | Called from hermes_daily_auditor, trust posting paths |
| `services/hunter_service.py` | Reactivation Hunter — sweeps abandoned quotes and orphaned holds | `quotes`, `reservation_holds`, `hunter_queue`, `guests` | `hunter_queue`, `hunter_queue_entries`, `hunter_recovery_ops` | Email/SMS dispatch, LiteLLM | HTTP endpoint (`/api/vrs/hunter/*`), ARQ jobs |
| `services/hunter_reactivation.py` | Hunter reactivation message generation | `guests`, `properties` | `hunter_queue_entries` | LiteLLM | Called by hunter_service |
| `services/email_ingest.py` | Gmail IMAP poll → LLM triage → damage claim routing | (external Gmail) | `damage_claims` | Ollama (qwen2.5:7b) | Standalone daemon or lifespan task |
| `services/legal_agent_orchestrator.py` | Legal council and strategy orchestration | `legal_case_statements`, `knowledge_base_entries` | `legal_hive_mind_feedback_events` | LiteLLM (TITAN/DeepSeek-R1) | HTTP endpoint (`/api/internal/legal/*`) |
| `services/statement_workflow.py` | Monthly statement lifecycle management | `owner_balance_periods`, `owner_payout_accounts`, `owner_charges` | `owner_balance_periods` | `statement_computation` | HTTP endpoints + cron job (Phase F) |
| `services/statement_computation.py` | Compute owner statement from ledger data | `reservations`, `owner_payout_accounts`, `owner_charges` | (read-only — returns StatementResult) | — | Called by statement_workflow, admin API |
| `services/seo_rewrite_swarm.py` | SEO content rewrite agent swarm | `seo_patches`, `seo_patch_queue`, `intelligence_ledger` | `seo_patches` | LiteLLM, SEO grading | HTTP endpoint, ARQ job |
| `services/fireclaw_runner.py` | Fireclaw extraction runner | `knowledge_base_entries` | `knowledge_base_entries` | LiteLLM | HTTP endpoint |
| `services/housekeeping_agent.py` | AI housekeeping task scheduler | `housekeeping_tasks`, `reservations`, `properties` | `housekeeping_tasks` | — | HTTP endpoint, ARQ job |
| `services/agentic_orchestrator.py` | Top-level agent orchestration | Multiple | Multiple | All vertical agents | HTTP endpoints |
| `services/the_captain.py` | Swarm task captain / coordinator | `agent_queue`, `agent_registry` | `agent_queue`, `agent_runs` | Agent swarm nodes | Called by orchestrator |
| `services/shadow_mode_observer.py` | Shadow Parallel parity observation | `shadow_discrepancies` | `shadow_discrepancies` | Streamline API | ARQ job, conditional on `AGENTIC_SYSTEM_ACTIVE` |
| `services/revenue_chain_of_custody.py` | Revenue chain verification | `trust_transactions`, `journal_entries` | `openshell_audit_logs` | — | Called by hermes auditor |

---

## 7. Frontend Orientation

### Command Center (`apps/command-center`) — served at crog-ai.com port 3001

**Route groups:**
- `(dashboard)/` — protected; all staff pages; auth-gated by JWT + role helpers
- `api/` — BFF proxy routes to FastAPI; some specialized SSE/stream endpoints

**Page inventory and status:**

| Path | Status | Notes |
|---|---|---|
| `/admin` | **Live** | Admin Ops Glass — links to payouts, disputes, contracts, onboarding |
| `/admin/payouts` | **Live** | Stripe Connect disbursements — fully built (Phase D prior work) |
| `/analytics` | **Live** | Operations dashboard |
| `/analytics/insights` | **Live** | Growth deck |
| `/automations` | **Live** | Rule Engine |
| `/command` | **Live** | Fortress Prime telemetry |
| `/command/checkout-parity` | **Live** | Checkout parity view |
| `/command/parity` | **Live** | Parity dashboard |
| `/command/settings/staff` | **Live** | Staff management |
| `/command/yield` | **Live** | Yield controls |
| `/damage-claims` | **Live** | Damage claim desk |
| `/email-intake` | **Live** | Email triage |
| `/growth/seo-copilot` | **Live** | SEO copilot |
| `/growth/redirect-remaps` | **Live** | Redirect remap queue |
| `/guests` | **Live** | Guest CRM |
| `/guests/[id]` | **Live** | Guest detail |
| `/housekeeping` | **Live** | Housekeeping dispatch |
| `/intelligence` | **Live** | Market intelligence feed |
| `/iot` | **Live** | IoT command |
| `/legal` | **Live** | Active dockets |
| `/legal/cases/[slug]` | **Live** | Full case detail with all legal components |
| `/legal/council` | **Live** | Legal council interface |
| `/messages` | **Live** | Guest communications |
| `/nemo-command-center` | **Live** | NeMo trust ledger command center |
| `/payments` | **Live** | Virtual terminal |
| `/prime` | **Live** | Iron Dome Ledger |
| `/properties` | **Live** | Property fleet |
| `/properties/[id]` | **Live** | Property detail |
| `/reservations` | **Live** | Tape chart + reservations |
| `/settings/agreement-templates` | **Live** | Agreement template management |
| `/vrs` | **Live** | Adjudication Glass |
| `/vrs/hunter` | **Live** | Reactivation Hunter |
| `/vrs/quotes` | **Live** | Quote management |
| `/acquisition/pipeline` | **Live** | Acquisition pipeline |
| `/admin/statements` | **MISSING** | Target of Phase G.2 — not yet built |
| `/owner` | **BROKEN** — nav links here but no page exists | STAKEHOLDERS nav item links to `/owner` which has no `page.tsx` |
| `/seo-review` | **Live** | SEO review queue (duplicate of `/seo/review`) |
| `/growth/ab-testing` | Stub? | Unclear |

### Storefront (`apps/storefront`) — served at cabin-rentals-of-georgia.com

| Path | Status |
|---|---|
| `(storefront)/cabins/[slug]` or `/cabins/[slug]` | **Live** — individual cabin pages |
| `(storefront)/availability` | **Live** — availability calendar |
| `/book` | **Live** — booking flow |
| `(guest)/itinerary` | **Live** — guest itinerary portal (capability-link) |
| `(owner)/owner/accept-invite` | **Live** — owner magic-link acceptance flow |
| `(owner)/owner/onboarding-complete` | **Live** — post-onboarding confirmation |
| `/owner-login` | **Live** — owner portal login |
| `(storefront)/quote/[id]` | **Live** — guest quote landing page |
| `/sign/[token]` | **Live** — rental agreement signing |
| `/reviews` | **Live** — guest reviews |
| `[...slug]` | **Live** — Drupal legacy page fallback |

### Packages (`packages/`)

| Package | Name | Status |
|---|---|---|
| `packages/config` | `@fortress/config` | **Stub** — `package.json` only, no exports, no source files |
| `packages/ui` | `@fortress/ui` | **Stub** — `package.json` only, no exports, no source files |

Both packages are empty stubs. Shared UI is achieved by shadcn/ui components installed per-app.

---

## 8. Auth and Permissions

### Roles (backend)

The backend defines these role identifiers (from `core/security.py` and the auth classification doc):
- `super_admin` — full access to all surfaces
- `admin` — admin-grade access (financial, dispute, contracts, staff)
- `manager` — manager-grade access (communications, payments, legal workflows)
- `reviewer` / `operator` — read-only operational surfaces (Hunter view)
- `staff` — basic staff access

Navigation config (`navigation.ts`) uses: `super_admin`, `ops_manager`, `legal`, `staff` — **different names from the backend**. The `normalizeRole()` function maps them: `"admin"` → `"super_admin"`, `"manager"` → `"ops_manager"`.

Backend auth dependencies (from `docs/permission-matrix.md`):
- `require_admin` — `super_admin`, `admin` — financial, ownership, disputes, staff management
- `require_manager_or_admin` — adds `manager` — comms, charging, legal workflows, telemetry
- `require_operator_manager_admin` — adds `reviewer`, `operator` — read-only views

### Auth flow end-to-end

1. **Staff login:** `POST /api/auth/login` → returns `{ access_token, user }` — stored in `localStorage["fgp_token"]`
2. **Token type:** RS256 JWT (asymmetric); `jwt_accept_legacy_hs256=True` for backwards compat
3. **Token inclusion:** Every `api.*` call in `src/lib/api.ts` adds `Authorization: Bearer {token}` header; also sends `credentials: "include"` for cookie passthrough
4. **Verification:** Global FastAPI JWT middleware on every request; route-level dependencies layer additional role checks
5. **401 handling:** Token cleared, `fortress:auth-expired` event fired, redirect to `/login?expired=1`
6. **Owner auth:** Separate magic-link flow via `POST /api/auth/owner/request-magic-link` and `POST /api/auth/owner/verify-magic-link`; owner sessions use `get_current_owner` dependency (not staff JWT)

### Auth classification buckets (from `docs/api-surface-auth-classification.md`)

1. **Public guest-facing** — `/api/guest-portal/*`, `/api/direct-booking/*`, `/api/checkout/*`, etc.
2. **Provider-signed webhook** — `/api/webhooks/stripe`, `/api/webhooks/channex`, Twilio SMS — all fail-closed when secrets unset
3. **Machine-to-machine** — `/api/email-bridge/ingest` (X-Swarm-Token), paperclip bridge, rule engine emitters
4. **Staff-role protected** — `/api/admin/*`, `/api/vrs/hunter/*`, `/api/internal/legal/*`, etc.

---

## 9. Phase A-F Retroactive Assessment

### What Phase A-F built

- `OwnerBalancePeriod` model + table `owner_balance_periods`
- `OwnerCharge` model + table `owner_charges`
- `owner_statement_sends` audit table
- `commission_rate` + `streamline_owner_id` + 6 mailing address columns added to `owner_payout_accounts`
- Address columns added to `properties` (city, state, postal_code)
- Statement workflow service (`statement_workflow.py`) — full state machine
- Statement computation service (`statement_computation.py`) — ledger-based computation
- Statement PDF renderer (`statement_pdf.py`)
- Phase F email cron + send
- Admin workflow API (`admin_statements_workflow.py`) — 9 endpoints
- Admin statement computation API (`admin_statements.py`) — 1 endpoint
- `admin_charges.py` — owner charge CRUD

### What Phase A-F missed

1. **Did not update docs** — `docs/alembic-reconciliation-plan.md`, `docs/alembic-prod-rollout-runbook.md`, `docs/permission-matrix.md` were not updated to reflect the new state. They describe a world from before Phase A-F.

2. **Did not clean test data** — Wrote extensive test fixtures to `fortress_shadow` (1,047 @test.com OPA rows, 17,492 future-dated balance periods) and did not clean them. The G.1 cleanup phase operated on `fortress_guest` (wrong DB).

3. **Did not build frontend** — Phase G.2 (admin statement UI) was not started.

4. **Phase A-F migrations target fortress_shadow** — all migration files in `backend/alembic/versions/` with Phase A-F revisions (d1e2f3a4b5c6, c9e2f4a7b1d3, f1e2d3c4b5a6, e7c3f9a1b5d2, e6a1b2c3d4f5) are applied to `fortress_shadow`, not `fortress_guest`. The G.1 investigation was based on a false assumption about which DB to check.

5. **No real owner enrolled in fortress_shadow** — The 92 non-test OPA rows in fortress_shadow are all from previous dev/test runs. No real production owner has been onboarded to the new system.

### Alembic chain correctness

The Phase A-F migrations are on a continuous chain terminating at `e6a1b2c3d4f5` — the current single head. No orphaned revisions. The merge revision `e5merge01` correctly converges the parity_audit and offline_buffer branches. The chain is sound.

However: the chain's `down_revision` references (`b2c4d6e8f0a1`, `a3b5c7d9e1f2`, etc.) trace back through legitimate ancestry. The Phase A-F additions extend the main chain, they are not floating branches.

---

## 10. Open Questions for Gary

1. **Which database is the canonical production DB?** `fortress_shadow` has the FastAPI runtime data (owner statements, staff, recent activity) but only 100 reservations. `fortress_guest` has 2,665 real historical reservations and the 14 active properties — but the application doesn't write to it. Is there a migration plan for the historical reservation data?

2. **G.1 cleanup was on the wrong DB.** The test data (1,047 @test.com OPA rows, 17,492 future-dated balance periods) lives in `fortress_shadow`. A new G.1.5 cleanup pass needs to be run against `fortress_shadow` using `fortress_api` or `fortress_admin` credentials before G.2 will show meaningful data.

3. **Is the fortress_nightly_finetune failure a priority?** The `fortress-nightly-finetune.service` is in `failed` state. Needs investigation.

4. **Owner onboarding for G.2 testing:** No real owner is enrolled in `fortress_shadow`'s OPA table. The owner with `sl_owner_id=897648` (`mkbuquoi0912@gmail.com`) exists in `fortress_guest`'s magic_tokens but has no OPA row. For G.2's statement UI to display real data, at least one owner needs to be onboarded to the fortress_shadow OPA. Who should that be?

5. **`/owner` nav entry is broken.** The STAKEHOLDERS nav in `navigation.ts` has "Owner Portal & Statements" linking to `/owner`. That page doesn't exist in command-center. Should this route be the new admin statement page (`/admin/statements`) or should a separate owner-facing hub be built?

6. **fortress_guest role going forward.** Is `fortress_guest` being wound down, kept as a read-only historical archive, or used for something else? This affects whether historical reservations are available to the statement system.

7. **The `fortress-console` service.** The service description says "crog-ai.com — port 9800" but runs `master_console.py`. The gateway routes `crog-ai.com` to port 3001 (Next.js). What is `master_console.py`? Is it an internal admin tool not meant to be public-facing? Should its systemd description be corrected?

8. **`pg` in command-center deps.** `apps/command-center/package.json` lists `"pg": "^8.20.0"` as a runtime dependency. This violates the sovereign data rule (frontend must never import DB drivers). Is this intentional (perhaps used in a BFF route for something specific), or a stale dependency?

9. **Channex webhook downstream.** The auth and ingest are solid but the downstream event contract is a no-op stub. When is this being activated?

10. **`crog_statements_parallel_mode` env var.** The send-test endpoint references `CROG_STATEMENTS_PARALLEL_MODE`. What are its values and what does each mode do?

---

## 11. Recommended Next Phase

### Immediate: G.1.5 — Cleanup fortress_shadow test data (new scope)

The G.1 cleanup must be repeated against `fortress_shadow`. Run as `fortress_admin` or `fortress_api` with DELETE permissions. Test data to remove:
- `owner_payout_accounts` WHERE `owner_email ILIKE '%@test.com'` (1,047 rows) — requires CASCADE on owner_balance_periods/charges first
- `owner_balance_periods` WHERE `period_start >= '2050-01-01'` (17,492 rows)
- Related orphaned `owner_charges` and `owner_statement_sends`

This is the prerequisite for G.2's UI showing real data.

### Then: G.2 — Admin Statement Workflow UI

Once fortress_shadow test data is cleaned and at least one real owner is enrolled:
1. Add TypeScript types for `OwnerBalancePeriod` to `hooks.ts`
2. Add 8 hooks targeting `/api/admin/payouts/statements/*`
3. Build `apps/command-center/src/app/(dashboard)/admin/statements/page.tsx`
4. Update `navigation.ts` — add "Owner Statements" nav entry, fix `/owner` broken link
5. Add "Owner Statements" button to `/admin` hub page

The Phase A-F backend is complete and ready. G.2 is purely frontend work.

---

## 12. Confidence Ratings

| Section | Confidence | Basis |
|---|---|---|
| Two-database model (which DB is which) | **VERY HIGH** | Config source code + live connection count + table presence verified |
| Alembic state (fortress_shadow at e6a1b2c3d4f5) | **HIGH** | `alembic current` against the admin URI confirms this |
| Test data contamination in fortress_shadow | **VERY HIGH** | Direct SQL queries showing @test.com, sendtest-*, future dates |
| G.1 investigated wrong DB | **CERTAIN** | fortress_guest has 0 OPA rows; fortress_shadow has 1,261 |
| Systemd service inventory | **HIGH** | Direct `systemctl` output; port scan confirmed |
| fortress-console = Python tool, not Next.js | **CERTAIN** | Script reads `master_console.py`; port 3001 is `next-server` |
| Frontend page inventory | **HIGH** | Directory scan; some stubs vs live not fully verified |
| Phase A-F migration chain is sound | **HIGH** | Single head, no orphaned revisions |
| fortress_guest role | **MEDIUM** | Inference from data patterns; not confirmed by Gary |
| Alembic state of fortress_guest (c4a8f1e2b9d0) | **HIGH** | Direct `SELECT version_num FROM alembic_version` |
| Domain strangler-fig status | **MEDIUM-HIGH** | Based on code reading + data; some domains need Gary confirmation |
| Agent DB touch map | **MEDIUM** | Sampled, not exhaustive — docstrings read, imports not fully traced |
