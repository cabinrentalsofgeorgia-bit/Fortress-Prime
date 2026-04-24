# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

Fortress Prime is a sovereign, on-premises short-term rental platform for `cabin-rentals-of-georgia.com` and its internal command center at `crog-ai.com`. The system runs entirely on a local NVIDIA DGX Spark cluster — no cloud databases, no managed services for sensitive data.

**Two isolated zones must never be cross-linked:**
- **Zone A (Public):** `cabin-rentals-of-georgia.com` — the `storefront` Next.js app, guest-facing and SEO-optimized
- **Zone B (Internal):** `crog-ai.com` — the `command-center` Next.js app, staff and AI agents only

## Commands

### Frontend (from `fortress-guest-platform/`)
```bash
npm run dev        # Start all apps concurrently via Turbo
npm run build      # Build all apps (runs sync-next-standalone-assets.mjs post-build)
npm run lint       # ESLint across all apps
npm run test       # Vitest unit tests across all apps
```

### Individual apps (from their respective directories)
```bash
# storefront
npm run dev        # Next.js dev server (auto port)
npm run test:e2e   # Playwright E2E headless
npm run test:e2e:ui # Playwright with browser UI

# command-center
npm run dev        # Next.js on 0.0.0.0:3000
npm run test:e2e   # Playwright E2E
```

### Backend (from `fortress-guest-platform/backend/`)
```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
alembic upgrade head                              # Apply migrations
alembic revision --autogenerate -m "description" # Generate migration from model changes
arq backend.tasks.jobs                            # Start async job worker
```

### Root-level Python scripts
```bash
python src/analyze_spend.py           # Invoice/vendor spend analysis
python src/extract_trade_signals_v2.py # Market signal extraction from emails
python src/map_real_estate.py         # Property territory mapping
```

## Architecture

### The Sovereign Stack

```
Next.js (Vercel edge / local)  ──→  Cloudflare Tunnel  ──→  FastAPI :8000 (DGX Spark-01)
                                                                   ↓
                                                        PostgreSQL 16 (127.0.0.1:5432)
                                                        + pgvector + Redis
```

The **only authorized data path** is: Next.js → Cloudflare Tunnel API call → FastAPI router → PostgreSQL. The frontend must never import `pg`, `asyncpg`, `psycopg2`, or any database driver. All external calls (Stripe, Twilio, OpenAI) originate from the FastAPI backend only.

### Monorepo layout (`fortress-guest-platform/`)
- `apps/storefront/` — public guest website (Next.js 16, App Router)
- `apps/command-center/` — internal staff/AI dashboard (Next.js 16, App Router)
- `packages/config/` — shared ESLint/Tailwind config
- `packages/ui/` — shared component library
- `backend/` — FastAPI server (124+ routers, 76+ SQLAlchemy models)
  - `core/` — config (Pydantic settings), database (async session factory), queue (arq)
  - `models/` — SQLAlchemy ORM models
  - `schemas/` — Pydantic request/response models
  - `api/` — route handlers
  - `services/` — business logic and external integrations
  - `tasks/jobs.py` — arq background job definitions
  - `alembic/` — migration history and env
- `scripts/` — deployment helpers and build artifact sync

### Root-level directories
- `src/` — standalone Python scripts (Streamlit dashboards, data processing, signal extraction)
- `crog-gateway/` — lightweight gateway service
- `docs/` — architecture docs including strangler fig migration guides
- `logs/` — daily briefings and revenue reports

### AI Inference (DEFCON Modes)
- **DEFCON 5 / SWARM:** Ollama LB → qwen2.5:7b on Spark-02 (fast routing, guest comms)
- **DEFCON 3 / BRAIN (Tier 2 sovereign reasoning):** `fortress-nim-brain.service` on spark-1 — `nvidia/Llama-3.3-Nemotron-Super-49B-v1.5-FP8` via generic `nvcr.io/nim/nvidia/llm-nim:latest`, vLLM backend, port 8100, 32k context. HF weights staged at `/mnt/fortress_nas/nim-cache/hf/nvidia-Llama-3_3-Nemotron-Super-49B-v1_5-FP8/`. All callers MUST supply a system prompt (e.g. `"detailed thinking on"`) — the model returns garbled output without one.
- **DEFCON 1 / TITAN:** DeepSeek-R1 on Spark-01 via llama.cpp RPC (deep reasoning, legal, finance)
- **ARCHITECT:** Google Gemini (planning only — no PII or sovereign data)

> **spark-1 memory pressure (2026-04-23):** The BRAIN service currently uses ≥99% of spark-1's 121 GiB unified memory after load. Track B workload migration (Qdrant, fortress-event-console / redpanda, RAG retriever, chromadb, open-webui → spark-4) is required-before-production to restore the ≥15% headroom rule. Do not put production traffic on BRAIN until Track B completes.

## Non-Negotiable Rules

### Sovereign Ledger Immutability
`trust_transactions` and `trust_ledger_entries` are **append-only**. DB triggers (`trg_immutable_trust_transactions`, `trg_immutable_trust_ledger_entries`) raise a Postgres exception on any `UPDATE` or `DELETE`. To correct an error, post a **reversal entry** (new offsetting debit/credit pair) — never mutate the original row.

All financial entries must route through the posting functions in `backend/services/trust_ledger.py`:
- `post_checkout_trust_entry`
- `post_invoice_clearing_entry`
- `post_variance_trust_entry`

Never insert directly into these tables via raw SQL or ORM — this breaks the SHA-256 hash chain and triggers a `CRITICAL BREACH` alert from `backend/workers/hermes_daily_auditor.py`.

### Stripe is the Source of Truth
Trust ledger payment entries are triggered **exclusively** by Stripe webhook events (`payment_intent.succeeded`, `invoice.paid`). Never create payment entries from Streamline (PMS) data alone. Streamline is used only for payload vaulting, reservation metadata upserts, and variance reconciliation.

### Webhook Idempotency
All webhook handlers must catch `sqlalchemy.exc.IntegrityError` on the `uq_trust_transactions_streamline_event_id` constraint and return **HTTP 200 OK** — a duplicate event is a success, not an error. Never re-raise `IntegrityError` from an idempotent trust posting path.

### Feature Development Order
When building a new feature, always execute in this order:
1. DB model / Alembic migration
2. FastAPI route + Pydantic schema
3. Next.js types + hooks
4. Next.js UI component

Never create a UI component that requires data without first defining the database schema and FastAPI route.

## Code Standards

- **TypeScript:** Zero `any` types. Strict mode.
- **Python:** Complete type hints. Must pass `mypy --strict`.
- **File naming:** React components use `kebab-case.tsx`, Python files use `snake_case.py`.
- **All backend route handlers must be `async def`.**
- All DB access uses `async with async_session() as session:`.

## Legacy SEO Migration

The platform is executing a Strangler Fig migration from a 2018 Drupal estate (2,514 nodes):
- `drupal_granular_blueprint.json` is the single source of truth for legacy nodes
- Legacy routes fall back to `GET /api/v1/history/restore/{path:path}`
- SEO metadata overrides use the `seo_patch_queue` polymorphic table (`target_type`, `target_slug`)
- The 4,530 legacy Drupal 301 redirects must always be preserved

## Security & Networking

- All ingress via Cloudflare Tunnels; UFW denies all public inbound
- JWT RS256 (asymmetric keys) for auth between frontend and FastAPI
- All internal telemetry and audit events write to `openshell_audit_logs`
- Sovereign data (financials, legal, PII) never leaves the DGX cluster hardware
