# Fortress Prime — Full-Stack Audit Report
**Date:** 2026-04-22 | **Method:** 6 parallel Explore agents → shared NDJSON ledger  
**Ledger:** `wip-20260422/findings.ndjson` | **Evidence:** `wip-20260422/evidence/` (69 files)  
**Findings table:** [audit-findings.md](wip-20260422/audit-findings.md) (55 findings)

---

## 1. Executive Summary

**13 CRITICAL · 21 HIGH · 10 MED · 4 LOW · 7 INFO**

**Top 3 requiring immediate action:**
1. **No firewall (S-01 CRITICAL):** UFW inactive on spark-2. PostgreSQL (5432), Qdrant (6333-6334), and Portainer (8888) reachable from any LAN host with no ingress filtering.
2. **Stripe webhook double-settlement (A-01 CRITICAL):** `stripe_webhooks.py` calls `convert_hold_to_reservation()` unconditionally. A Stripe retry of any `payment_intent.succeeded` causes double-settlement. No `stripe_event_id` uniqueness constraint.
3. **Legal AI inference broken end-to-end (A-02 CRITICAL):** e3.1 Qwen-7B LoRA adapter trained and on NAS but served nowhere. `fortress-vllm-bridge.service` active but targets container `vllm-70b-captain` (does not exist). Legal AI routes to cloud LiteLLM (Anthropic/OpenAI). IRON_DOME claims sovereign inference; reality is cloud.

Other CRITICALs: protobufjs RCE vuln (npm), trust ledger immutability triggers missing on `trust_transactions` and `trust_ledger_entries`, spark-3 RAM at 69% (above 60% policy limit), IRON_DOME wrong on two NIM deployments, unattended-upgrades disabled with OpenSSL patches pending, 0 required PR reviewers, bus factor = 1.

---

## 2. Top 10 Prioritized Action List

| # | Action | Command / PR | Effort | Owner |
|---|--------|-------------|--------|-------|
| 1 | Enable UFW with allowlist — PostgreSQL, Qdrant, Portainer currently open to LAN | `sudo ufw enable && sudo ufw allow 22 && sudo ufw deny 5432 && sudo ufw deny 6333:6334/tcp && sudo ufw deny 8888` | S | Gary |
| 2 | Fix Stripe idempotency — add `stripe_event_id` unique constraint + pre-check before settlement | PR: `fix(stripe): idempotency guard on payment_intent.succeeded webhook` | M | Gary |
| 3 | Fix trust ledger triggers — `trust_transactions` and `trust_ledger_entries` lack the immutability triggers CLAUDE.md claims exist | `alembic upgrade head` then verify with `SELECT trigger_name FROM information_schema.triggers WHERE event_object_table='trust_transactions'` | S | Gary |
| 4 | Rotate NIM key; move to Docker --env-file — key accessible via `docker inspect` on spark-3 to any Docker-group user | Rotate at ngc.nvidia.com; update unit ExecStart to `--env-file /run/secrets/nim.env` | M | Gary |
| 5 | Resolve legal inference path — either stand up vLLM+e3.1 on spark-2 OR document cloud-LiteLLM as intentional and update IRON_DOME | PR: `fix(legal): document or restore e3.1 serving path` | L | Gary |
| 6 | Patch OpenSSL + enable unattended-upgrades — openssl has pending security updates, system up 14 days unpatched | `sudo apt-get upgrade -y openssl libssl3t64 libssl-dev && sudo apt-get install -y unattended-upgrades` | S | Gary |
| 7 | Fix npm critical vuln (protobufjs RCE) — 1 critical + 3 high in fortress-guest-platform | `cd fortress-guest-platform && npm audit fix` (review diff first) | S | automate |
| 8 | Require ≥1 PR approver on main — 0 required reviewers enabled the PR #129 admin bypass | GitHub → Settings → Branches → main → require 1 review | S | Gary |
| 9 | Run and document a restore drill — daily dumps exist back to Apr 18; none tested | `pg_restore -d fortress_shadow_restore /mnt/fortress_nas/backups/fortress_db_2026-04-22_02-00.sql.gz` | M | Gary |
| 10 | Kill orphaned Ollama processes on spark-2 — 3 instances running, one consuming excessive CPU | `systemctl status ollama` then kill duplicates | S | Gary |

---

## 3. Findings Table

> 55 findings — see **[wip-20260422/audit-findings.md](wip-20260422/audit-findings.md)**

| Agent | CRITICAL | HIGH | MED | LOW | INFO | Total |
|-------|----------|------|-----|-----|------|-------|
| security | 5 | 3 | 1 | 0 | 1 | 10 |
| repo | 1 | 4 | 3 | 2 | 4 | 14 |
| apps | 2 | 3 | 2 | 1 | 0 | 8 |
| infra | 1 | 4 | 3 | 1 | 0 | 9 |
| docs | 2 | 2 | 1 | 0 | 2 | 7 |
| data | 0 | 4 | 3 | 0 | 0 | 7 |
| **Total** | **13** | **21** | **10** | **4** | **7** | **55** |

---

## 4. Per-Application Audit

### 4.1 CROG-VRS

**State:** Live. FastAPI :8000 on spark-2. Next.js 16.1.6 / React 19.2.3.

**Integrations:** Stripe (live), Channex (live, egress service running), Streamline PMS (live, sync worker active), Twilio (configured), Cloudflare Tunnel (active, Atlanta PoP, 10 days uptime).

**CRITICAL — Stripe double-settlement (A-01):** `stripe_webhooks.py` has no idempotency guard. No `stripe_event_id` uniqueness constraint. A Stripe retry of `payment_intent.succeeded` → double reservation + double charge. CLAUDE.md:idempotency-section describes this invariant but code does not implement it. Evidence: `evidence/vrs-stripe-idempotency.txt`.

**VRS AI concierge:** Not running on spark-4. Deployment A blocked (ARM64 NIM packaging defect for 9B model). VRS traffic falls to Ollama fallback.

**Test coverage:** 118 pytest files present, zero coverage artifacts. CI runs Playwright `@integration`-excluded subset only. No coverage gate. Evidence: `evidence/test-count.txt`.

**Failure modes:** Stripe retry → double-settlement (no guard). NAS unmount → NIM weights lost, app degrades. PostgreSQL down → full outage (no replica).

---

### 4.2 Fortress Legal

**State:** NIM running on spark-1 (Llama 3.1 8B, Up 3 days). Legal inference broken — adapter not served.

**Inference path:**
```
Request → LiteLLM gateway (:8002) → cloud: Anthropic / OpenAI / Gemini / XAI
          (local vLLM bridge: ACTIVE but DEAD — targets container that does not exist)
```

`fortress-vllm-bridge.service` is `active` in systemd but `ExecStart` targets `vllm-70b-captain` container — confirmed NOT in `docker ps`. Evidence: `evidence/vllm-bridge.txt`.

**e3.1 adapter:** Exists at `models/legal-instruct-production` (symlink → `legal-instruct-20260421-e3_1`, Qwen 7B LoRA). No systemd unit references it. `judge_runtime.py` marks legal judges `is_active: False`. Evidence: `evidence/legal-adapter.txt`.

**LiteLLM config:** Cloud-only routes: GPT-4o, Claude Sonnet 4, Gemini 2.5 Pro, Grok 3. One NVIDIA NIM entry (`nemotron-3-super-120b`) via cloud NIM API, not local. No local Qwen or LoRA route. Evidence: `evidence/litellm-config.txt`.

**IRON_DOME v6.1 claims sovereign Legal inference. Reality: 100% cloud routing. All legal document content passes through Anthropic/OpenAI APIs.**

**Model family mismatch:** spark-1 NIM serves `meta/llama-3.1-8b-instruct`. e3.1 was trained on `Qwen2.5-7B-Instruct`. Different families — adapter cannot load into Llama base. Two distinct serving paths are required; currently only the NIM path is live.

---

### 4.3 Master Accounting

**State:** Semi-automated scripts (`src/`). Not a web service.

**CRITICAL path mismatch (A-03 HIGH):** `src/analyze_spend.py` hardcodes `INVOICE_DIR = "/mnt/fortress_data/invoices"`. Path does not exist (NAS is at `/mnt/fortress_nas`). Script processes zero invoices every run. Evidence: `evidence/accounting-paths.txt`.

**Components:** `analyze_spend.py`, `extract_trade_signals_v2.py`, `map_real_estate.py`, `quant_revenue.py` (cron 05:30). No alerting if scripts fail silently.

---

### 4.4 Acquisitions Pipeline

**State:** Active. Automated ingestion via `universal_intelligence_hunter.py` (cron 05:45). `crog-hunter-worker.timer` active.

**Components:** `acquisition_pipeline.py`, `acquisition_ingestion.py` (1,170 lines), `acquisition_advisory.py`, `acquisition_foia.py`. CourtListener API + FOIA pipeline (assumed live).

**Risk:** `NotImplementedError` in `owner_emails.py:153` with no caller guard — any code path reaching this raises an unhandled exception. Evidence: `evidence/broken-impls.txt`.

---

## 5. Infrastructure Baseline

### Node State

| Node | IP | RAM % | Disk % | Key Services |
|------|----|-------|--------|-------------|
| spark-1 | 192.168.0.104 | 56% (68/121 GB) | 25% (882G/3.7T) | fortress-nim-sovereign (Llama 3.1 8B, Up 3d) ✅ |
| spark-2 | 192.168.0.100 | 21% (25/121 GB) | **58%** (2.1T/3.7T) | Control plane: 15 services, 12 timers, 3 Ollama instances |
| spark-3 | 192.168.0.105 | **69%** (84/121 GB) | 17% (583G/3.7T) | Vision NIM (Up 13h) ✅ healthy |
| spark-4 | 192.168.0.106 | 10% (12/121 GB) | 7% (221G/3.7T) | Qdrant VRS, SenseVoice |

**Spark-3 RAM 69% (I-01 CRITICAL):** Violates Iron Dome ≤60% steady-state rule. Vision NIM requires ~71 GB. Accept as exception or reduce `NIM_KVCACHE_PERCENT=0.65` in the unit file.

**PostgreSQL swap:** 113 MB swapped. `shared_buffers=128MB` on 121 GB RAM = 0.1% utilization. Recommend 8 GB minimum.

### Network

Two ConnectX ports DOWN (`enp1s0f1np1`, `enP2p1s0f1np1`), Speed: Unknown. Active ConnectX ports at MTU 9000. No iperf3 run (would impact live inference). Tailscale active with 14 registered nodes.

### Backups

Daily gzip dumps confirmed running. `fortress_db_2026-04-22_02-00.sql.gz` (10.2 GB compressed) present. 7-day rotation visible. **No tested restore documented anywhere.** RPO = 24h. RTO = unknown.

### PostgreSQL

`pg_stat_statements` not enabled — cannot produce slow query top-20. Enable before next audit:
```
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```
`archive_mode=on, wal_level=replica` — WAL archiving configured but no `archive_command` set. PITR not functional despite settings suggesting otherwise.

### Redis

Hit rate: 12.7% (269K hits / 2.12M ops). 64K error replies. Cache is mostly miss-through — investigate TTL strategy and WRONGTYPE errors.

---

## 6. Docs-vs-Reality Diff

### WRONG (production behavior differs from claim)

| Doc | Claim | Reality | Finding |
|-----|-------|---------|---------|
| CLAUDE.md | `trust_transactions` and `trust_ledger_entries` have append-only immutability triggers | Neither table has any triggers in `information_schema.triggers`. Only `journal_line_items` has `trg_immutable_line_items`. | D-02 HIGH |
| IRON_DOME v6.1 | spark-4 runs VRS NIM concierge | No NIM on spark-4. 9B image was x86-64 mislabeled, removed. VRS falls to Ollama. | C-03 CRITICAL |
| IRON_DOME v6.1 | spark-2 serves Fortress Legal e3.1 (Qwen 7B LoRA) | vLLM bridge targets dead container. Legal routes to cloud LiteLLM only. | C-05 CRITICAL |
| IRON_DOME v6.1 | ≤60% RAM steady-state headroom rule | spark-3 at 69% | I-01 CRITICAL |
| CLAUDE.md | 4,530 legacy Drupal 301 redirects | Blueprint records 2,617 `url_alias` entries — ~1,900 discrepancy | C-01 MED |

### STALE

| Doc | Claim | Reality |
|-----|-------|---------|
| IRON_DOME v6.1 | Vision NIM pending (Deployment C) | **Now deployed and healthy** — Up 13h, health endpoint OK ✅ (positive stale) |
| IRON_DOME v6.1 | NIM-first principle enforced | Violated on spark-4 (no NIM), legal path is cloud | C-06 HIGH |

### VERIFIED

CLAUDE.md: FastAPI :8000 ✅, PostgreSQL 16 ✅, 124+ routers (actual: 666 decorators) ✅, 76+ models (actual: 86) ✅, 2,514 Drupal nodes ✅, Cloudflare Tunnel ✅. IRON_DOME: spark-1 NIM identity ✅, Vision NIM image hash ✅.

---

## 7. Quick Wins Executed This Pass

**PR opened: `audit: housekeeping sweep`**

1. `.gitignore` additions: `*.env.bak`, `.env.backup`, `.env.telemetry_backup`, `litellm_config.yaml.bak` — prevent future accidental tracking of backup env files
2. CLAUDE.md:redirect-count — added footnote noting blueprint records 2,617 url_aliases vs claimed 4,530 (conservative: flagged discrepancy, did not change the number)
3. `deploy/systemd/fortress-vllm-bridge.service` — added comment `# TARGET CONTAINER vllm-70b-captain: NOT RUNNING (service currently non-functional)`

**Not changed (needs Gary approval):** UFW rules, trust ledger migration, Stripe idempotency, key rotation, IRON_DOME rewrite, npm audit fix, PostgreSQL tuning, Ollama cleanup.

---

## Appendix — Open PRs (10), Undocumented Services, NIM Cache State

**Stale PR:** #6 (feat: sovereign hardware telemetry, 4 weeks old) — triage or close.

**Undocumented services running:** Ray cluster (spark-2/1/3), Kubernetes (port 6443 on spark-2), Redpanda Console (:18080), SenseVoice (spark-4:8000), docling-shredder (spark-3:5001), Open WebUI, fortress-sentinel (NAS indexer).

**NIM cache:** llama-nemotron-embed-1b-v2 (2.5 GB, ARM64 ELF verified ✅), nemotron-nano-12b-v2-vl (35 GB, ARM64 ELF verified ✅, in use spark-3), nemotron-nano-12b-v2 text (present, Stage-2 ELF unverified ⚠️). Duplicate `nim_cache/` directory (108 GB) — contents not enumerated.

*Generated 2026-04-22 from 55 NDJSON findings across 69 evidence files.*
