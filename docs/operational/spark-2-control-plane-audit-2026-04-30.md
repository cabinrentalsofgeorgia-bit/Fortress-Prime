# spark-2 → MS-01 Control Plane Migration Audit

**Date:** 2026-04-30
**Branch:** `chore/spark-2-control-plane-audit-2026-04-30`
**Audit type:** Read-only inventory (no service touches, no migrations)
**Driver:** Operator plans to migrate Fortress-Prime control plane from
spark-2 (DGX Spark, 128GB RAM, ARM64) to a new MS-01 mini workstation
(32GB RAM, 3TB storage, x86_64). Architectural shift requires a baseline
inventory before drafting the migration brief.

> **Status:** This audit is a snapshot. Service membership, port bindings,
> and DB sizes are accurate as of 2026-04-30 ~08:00 EDT. Do not act on
> anything in this doc without re-verifying the specific row first —
> spark-2 is a live, busy host.

---

## 0. Host facts

| Item | Value |
|---|---|
| Hostname | `spark-node-2` |
| LAN IP | `192.168.0.100` |
| Tailscale IP | `100.80.122.100` |
| Architecture | aarch64 (ARM64) |
| Kernel | `6.17.0-1014-nvidia` |
| Uptime at audit | 21 days 23 hours |
| Total RAM | 121 GiB |
| Used / available | 40 GiB used, 81 GiB available |
| Swap used | **8.5 GiB / 15 GiB** (high — flag) |
| Root FS | `/dev/nvme0n1p2` 3.7 TiB (65% used, 1.3 TiB free) |

---

## 1. Service inventory

### 1.1 Hot-path systemd services (active)

| Service | RSS | CPU% | Listening | Class | Notes |
|---|---|---|---|---|---|
| `postgresql@16-main` | ~1 GiB shared | low | `0.0.0.0:5432` | CONTROL_PLANE | Cluster main; 5 user dbs + 4 system. **5432 bound to 0.0.0.0** (no UFW per audit-20260422). |
| `redis-server` | small | low | `127.0.0.1:6379` | CONTROL_PLANE | Loopback only. |
| `redpanda` (PID 3010929) | **8.5 GiB** | 3.8% | `0.0.0.0:8081/8082/9644/19092/33145` | CONTROL_PLANE | Heaviest single process. Kafka-compatible bus. |
| `litellm-gateway` | 1.7 GiB | 2.8% | `127.0.0.1:8002` | CONTROL_PLANE | Sovereign router; config at `/home/admin/Fortress-Prime/litellm_config.yaml`. |
| `fortress-backend` | 0.5 GiB | 0.4% | `0.0.0.0:8000` | CONTROL_PLANE | FastAPI guest platform `run.py`. |
| `fortress-arq-worker` | 0.5 GiB | 2.7% | n/a | CONTROL_PLANE | `arq backend.core.worker.WorkerSettings`. |
| `fortress-sync-worker` | 0.2 GiB | 3.7% | n/a | CONTROL_PLANE | Streamline PMS poll. |
| `fortress-channex-egress` | n/a | low | n/a | CONTROL_PLANE | Availability egress. |
| `fortress-console` | 0.5 GiB | low | `0.0.0.0:9800` | CONTROL_PLANE | Command Center (`crog-ai.com`). |
| `fortress-sentinel` | 0.4 GiB | low | n/a | CONTROL_PLANE | NAS document indexer (`tools/fortress_sentinel.py`). |
| `crog-ai-frontend` | 0.2 GiB | low | `0.0.0.0:3005` | APP_TIER | Next.js (CROG-VRS owner UI). |
| `crog-concierge-worker` | n/a | low | n/a | APP_TIER | VRS concierge inference daemon. |
| `fortress-ray-head` | 1 GiB+ (split across procs) | low | `*:6390/8265/10001/39377/40449` | INFRASTRUCTURE | Ray head; node_id pinned to `192.168.0.100`. |
| `ollama` (serve + runners) | 1.5 GiB + 1.2 GiB | 15% / 72% | `127.0.0.1:33221/37277` | INFERENCE_TIER | At least 2 runners; one is hot (72% CPU). Relocate. |
| `k3s.service` (k3s-server) | 1.3 GiB | 6.8% | `192.168.0.100:6443/10250`, lots of `127.0.0.1:1024x` | INFRASTRUCTURE | k3s control plane. Etcd-replaceable. |
| `cloudflared` | small | low | `127.0.0.1:20241` | INFRASTRUCTURE | 4 tunnel JSONs in `/etc/cloudflared/`. |
| `pm2-admin` | small | 2.2% | n/a | APP_TIER | God Daemon for whatever PM2-managed apps. |
| `redpanda` (Console UI assumed) | docker | n/a | n/a | APP_TIER | Console image present in `docker images`. |
| `dgx-dashboard*`, `nvidia-dgx-telemetry`, `dcgm-exporter` | small | low | `127.0.0.1:11000` | DGX-ONLY | Drop on MS-01 (x86, no DGX hardware). |
| `iperf3` (×2) | tiny | 0 | `*:5201/5202` | INFRASTRUCTURE | Test/benchmarking only. Drop on MS-01. |

### 1.2 Active docker containers (7)

| Container | Image | Ports | Class |
|---|---|---|---|
| `fortress-qdrant` | `qdrant/qdrant:v1.13.2` | `0.0.0.0:6333-6334` | CONTROL_PLANE |
| `fortress-chromadb` | `chromadb/chroma:1.5.3` | `127.0.0.1:8004` | CONTROL_PLANE (legacy) |
| `fortress-chroma` | `chromadb/chroma:latest` | `0.0.0.0:8020` | CONTROL_PLANE (review — duplicate of 8004?) |
| `fortress-rag-retriever` | `yzy-retriever` | `0.0.0.0:8010` | CONTROL_PLANE |
| `fortress_mission_control` | `ghcr.io/open-webui/open-webui:main` | n/a (network published) | APP_TIER |
| `fortress_portainer` | `portainer/portainer-ce:lts` | `0.0.0.0:8888 → 9000` | INFRASTRUCTURE |
| `fortress_portainer-agent` | `portainer/agent:lts` | n/a | INFRASTRUCTURE |

Total docker storage on host: 140 GiB (`/var/lib/docker`). Notable cached
images: `nvcr.io/nim/.../llama-3.3-nemotron-super-49b-v1.5` (24 GiB),
`vllm/vllm-openai` (23 GiB), `nvcr.io/nim/.../llm-nim` (19 GiB),
`nvcr.io/nim/.../llama-3.3-nemotron-super-49b-v1` (15 GiB),
`fortress-hermes:cuda13` (6.5 GiB). These are ARM64 and **will not pull
on x86 MS-01** — they belong on the DGX Sparks anyway.

### 1.3 Enabled-at-boot but not currently active (review)

`fortress-nim-brain.service`, `fortress-watcher.service`,
`fortress-telemetry.service`, `fortress-vllm-bridge.service`,
`fortress-apex.service`, `fortress-event-consumer.service`,
`fortress-vanguard.service`, `fortress-deadline-sweeper.service`,
`fortress-nightly-finetune.service`, `fortress-nightly-labeling.service`,
`fortress-weekly-judge-training.service`, `chroma-server.service`,
`fortress-parity-monitor.service` (timer-driven), `fortress-drift-alarm.service`
(timer-driven), `crog-hunter-worker.service` (timer-driven),
`fortress-inference.service` (oneshot — currently `exited`, normal),
`crog-command-center.service`, `dgxstation-desktop.service`.

> **Open question:** several of these (`vllm-bridge`, `nim-brain`,
> `apex`, `event-consumer`) appear to be partly-deployed or retired.
> Per `fortress-prime-audit-20260422.md`, vLLM bridge targets a dead
> container. Migration brief should classify each as keep/retire.

### 1.4 Unknown / unaccounted listeners (flag for next audit pass)

| Port | Bind | Process | Question |
|---|---|---|---|
| 3100 | `0.0.0.0:3100` | `MainThread` python (PID 40533) | Loki? Some metrics shipper? |
| 9876 | `0.0.0.0:9876` | python (PID 2395935) | Unidentified app. |
| 18180 | `0.0.0.0:18180` | `MainThread` python (PID 41523) | Possibly `crog-ai-backend`. |
| 8888 | `0.0.0.0:8888` | docker-proxy → portainer | Confirmed portainer. |
| 7946 | `*:7946` | dockerd | Docker swarm membership. |
| 44217 / 44227 / 34521 / 38981 / 39343 / 52365 | various | Ray runtime/dashboard | Internal Ray ports. |

---

## 2. Storage inventory

| Path | Size | Owner | Contents |
|---|---|---|---|
| `/var/lib/postgresql/16/main` | **1.1 TiB** on-disk | postgres | 5 user dbs (logical sum **~46 GiB**). Discrepancy = WAL / dead tuples / pg_xlog inflation. **Recommend pg_dump/pg_restore over file copy.** |
| `/var/lib/docker` | 140 GiB | root | Image cache (mostly ARM64 NIM/vLLM that won't move). |
| `/home/admin/Fortress-Prime` | 113 GiB | admin | Repo + venv + `.git` + adapters. Re-clone on MS-01 + selective `rsync` of large local artifacts. |
| `/home/admin/fortress_qdrant_data` | 51 GiB | admin | Bind mount for fortress-qdrant container. 29 collections. **Use Qdrant snapshot API**, not file copy. |
| `/var/lib/redis` | 24 MiB | redis | Trivial. |
| `/etc/fortress` | 32 KiB | root:admin | `admin.env`, `nim.env`, `secrets.env`, `secrets.manifest` + backups. **Plain-text secrets present** — see §6. |
| `/etc/cloudflared` | <100 KiB | root | 2 tunnel JSONs, `cert.pem`, current+legacy `config.yml`. |
| NFS mounts to 192.168.0.113 | 63 TiB shared (used 9.6 TiB) | NAS | Shared across cluster — no migration. MS-01 will mount the same exports. |

### 2.1 Postgres database sizes (logical)

| DB | Size | Owner |
|---|---|---|
| `fortress_db` | 24 GB | miner_bot |
| `fortress_prod` | 22 GB | fortress_admin |
| `fortress_guest` | 397 MB | fgp_app |
| `fortress_guest_restore_probe` | 349 MB | postgres |
| `fortress_shadow` | 113 MB | fortress_admin |
| `paperclip_db` | 20 MB | paperclip_admin |
| `fortress_shadow_test` | 17 MB | admin |
| `fortress_telemetry` | 7.6 MB | miner_bot |
| **Logical total** | **~46 GiB** | |

**Roles:** `admin` (super), `crog_ai_app`, `fgp_app`, `fortress_admin`
(super), `fortress_api`, `miner_bot`, `paperclip_admin`, `postgres`
(super), `trader_bot`. All must migrate; Postgres role passwords are in
`/etc/fortress/secrets.env` (verified present, contents not committed).

### 2.2 Qdrant collections (29)

`legal_caselaw`, `legal_caselaw_v2`, `legal_caselaw_federal_v2`,
`legal_headhunter_memory`, `legal_headhunter_memory_v2`,
`legal_hive_mind_memory`, `legal_library`, `legal_library_v2`,
`legal_privileged_communications`, `legal_privileged_communications_v2`,
`legal_ediscovery`, `sound_money_intel`, `lyn_intel`,
`fortress_documents`, `fortress_knowledge`, `fgp_sent_mail`,
`fgp_knowledge`, `fgp_golden_claims`, `market_intelligence`,
`historical_quotes`, `permabear_intel`, `vol_trader_intel`,
`guest_golden_responses`, `email_embeddings`, `jordi_intel`,
`real_estate_intel`, `black_swan_intel`, `raoul_intel`,
`fed_watcher_intel`.

Several of these are `_v2` shadow collections from in-flight legal
re-embed work — migration brief should decide whether to migrate the
`_v1` legacy or only `_v2`. (Reference: PR #311 caller cutover.)

### 2.3 Cloudflared tunnels

`/etc/cloudflared/` contains 2 tunnel credential JSONs:
`aa7222a3-c1c9-4ee3-97c8-fb46b41a654e.json` (symlink to `~/.cloudflared/`)
and `c8eeb603-9fa6-4305-9048-9b0ca99f9079.json`. Plus `cert.pem`,
current `config.yml` (Apr 12), and 3 legacy backups. Tunnel ingress
config will need updating to point at MS-01 host instead of 192.168.0.100
loopback services.

---

## 3. Configuration scope

### 3.1 systemd unit drop-ins (`/etc/systemd/system/*.service.d/`)

11 fortress/crog/litellm/ollama services have drop-ins, all of the form
`secrets.conf` or `override.conf`. Each is a small file pointing at
`/etc/fortress/secrets.env`, `/etc/fortress/admin.env`, or service-specific
env (e.g., GPU pinning for ollama). All drop-ins must move with the
unit files. Migration brief should bundle these as a single
`/etc/systemd/system/` tar.

Drop-in inventory:
- `fortress-apex.service.d/secrets.conf`
- `fortress-arq-worker.service.d/00-secrets.conf`
- `fortress-backend.service.d/override.conf`
- `fortress-sentinel.service.d/secrets.conf`
- `fortress-sync-worker.service.d/secrets.conf`
- `fortress-vanguard.service.d/secrets.conf`
- `crog-ai-frontend.service.d/secrets.conf`
- `crog-concierge-worker.service.d/secrets.conf`
- `crog-hunter-worker.service.d/secrets.conf`
- `litellm-gateway.service.d/secrets.conf`
- `ollama.service.d/{gpu-override.conf, override.conf}`

### 3.2 Cron (admin) — large surface

User crontab is the busiest scheduler on the host. Highlights:
- `0 3 * * *` `lockdown_cluster.sh` (security sweep)
- `0 1 * * *` `night_shift.sh` (Vision indexing)
- `0 6 * * *` `market_watcher --email`
- `0 6 * * *` `watchtower_briefing` (R1 morning interrogation)
- `0 4 * * *` `backup_code.sh` (Fortress-Prime tar to NAS)
- `0 2 * * *` `scripts/backup_db.sh` (Postgres → NAS, 7-day retention)
- `0 3 * * *` `chroma_db_mirror` rsync
- `*/5 * * * *` `email_bridge` (IRON DOME compliance archiver)
- `*/10 8-22 * * *` `ingest_reservations_imap`
- `0 5-21/2 * * *` `ingest_market_imap`
- `30 6 * * *` `nvidia_sentinel.py` (NGC/Ollama supply chain watch)
- `0 9 * * *` `reactivation_hunter` (sales outreach)
- `15 6 * * *` `ops_heartbeat.sh` (Division 3)
- `0 5 * * *` `streamline_property_sync`
- `30 5 * * *` `quant_revenue` (30-day rate cards)
- `0 2 * * *` `classification_janitor.py --mode hydra`
- `0 */2 * * *` `kyc_watchdog.py` (Case 23-11161-JKS)
- `0 4 * * *` `update_intelligence.sh`
- `45 5 * * *` `universal_intelligence_hunter.py --all`
- `*/10 8-22 * * *` `gmail_watcher` — **disabled** (broken, see PR #248)
- `0 0 1 * *` log purge (NAS logs >30d)
- `0 3 * * 0` `data_hygiene.py --execute` (weekly)
- `30 3 * * 0` `vector_gc.py --execute` (weekly)
- `0 4 * * 0` `VACUUM ANALYZE` (weekly Postgres)
- `0 4 * * *` `janitor_stale_markers.sh` (NAS gating)
- `@reboot` `revenue_consumer_daemon.py`

> All crons reference `/home/admin/Fortress-Prime` paths and depend on
> `./venv/bin/python` or `/usr/bin/python3` and `/etc/fortress/*.env`.
> A working clone + venv + secrets must exist on MS-01 before crontab
> is installed.

### 3.3 Active systemd timers (7 fortress + system)

| Timer | Cadence | Last run |
|---|---|---|
| `fortress-parity-monitor.timer` | hourly | 07:08 today |
| `crog-hunter-worker.timer` | 09:00 daily | yesterday |
| `fortress-drift-alarm.timer` | 11:43 daily | this morning 05:43 |
| `fortress-deadline-sweeper.timer` | 06:00 daily | this morning |
| `fortress-nightly-labeling.timer` | 01:45 daily | last night |
| `fortress-nightly-finetune.timer` | 02:01 daily | last night |
| `fortress-weekly-judge-training.timer` | Sun 03:00 | 2026-04-26 |

### 3.4 root crontab

Empty (`no crontab for root`). All scheduled work runs as `admin`.

### 3.5 TLS

System-wide CA bundle in `/etc/ssl/certs/`. Snake-oil cert at
`/etc/ssl/certs/ssl-cert-snakeoil.pem`. **No service-issued
Let's Encrypt or custom certs found on host** — all public TLS is
terminated upstream by Cloudflare via cloudflared. Migration carries no
TLS material besides the cloudflared tunnel `cert.pem`.

---

## 4. spark-2 identity references in repo

**Total matches:** 616 across 397 markdown + 219 code/config files.
Code-only matches: 219 lines across **82 unique files**.

### 4.1 Hot-path config / source (will break on cutover unless updated)

| File | What it pins |
|---|---|
| `config.py` | `DB_HOST` default `"192.168.0.100"`; `SPARK_01_IP` default `"192.168.0.100"` |
| `src/sovereign_ooda.py` | `DB_HOST` default `"192.168.0.100"` |
| `src/active_vision.py` / `src/active_vision_nas.py` | `DB_HOST = "192.168.0.100"` (no env override) |
| `src/agents/owner_reports.py`, `src/agents/guest_comms.py` | `DB_HOST` default `"192.168.0.100"` |
| `src/pulse_agent.py` | `DB_HOST` default `"192.168.0.100"` |
| `src/watchtower_briefing.py` | hardcoded Command Center URLs `http://192.168.0.100:9800/...` and `http://192.168.0.100:8005` in email body |
| `src/rag/migrate_fgp_to_vrs.py` | `SOURCE_URL = "http://192.168.0.100:6333"` |
| `src/rag/verify_dual_write_parity.py` | `SOURCE_URL`, `EMBED_URL` defaults `192.168.0.100` |
| `src/validate_reindex_quality.py` | `QDRANT_URL`, `OLLAMA_URL` hardcoded |
| `src/ingest_taylor_sent_tarball.py` | comment + uses `192.168.0.106:11434` (workaround when "spark-2 GPU busy") |
| `fortress_atlas.yaml` | spark-2 listed as `id`, `management_ip`, `ollama_url`; routing tables `fast: ["spark-2", "spark-1"]`, `vrs_fast`, `embed` lanes pin spark-2 |
| `docker-compose.local.yml` | `NODE_NAME=spark-2-refinery` |
| `deploy/compute/v1.0_paperclip_manifest.yaml` | `owner: spark-node-2`, `node_id: spark-node-2` |
| `fortress-guest-platform/backend/**` | many references — config.py, services/*.py, api/*.py, workers/vectorizer.py, tests/* — most are env-sourced but defaults point at spark-2 |
| `src/operational/validate-fabric-cutover.sh` | hardcoded IP list including `192.168.0.100` |

### 4.2 Doc references (non-blocking, but stale on cutover)

`REQUIREMENTS.md`, `COMMAND_CODES.md`, `CODEBASE_OVERVIEW.md`, the
prior `fortress-prime-audit-20260422.md`, runbooks under
`docs/operational/`, brief files in repo root — all describe spark-2 /
192.168.0.100 as Captain. Migration brief will need a doc-sweep PR.

### 4.3 By extension

| Ext | Lines (code-filter) |
|---|---|
| `.py` | 151 (across 219-line code filter — many in fortress-guest-platform) |
| `.yaml` | 36 |
| `.sh` | 25 |
| `.md` | 397 (excluded from "code" subset) |
| `.yml` | 3 |
| `.json` | 3 |
| `.env` | 1 |

> **Dominant strategy:** parameterize via env (the codebase already
> supports `DB_HOST`, `QDRANT_URL`, etc. via env), then ship a single
> rewriter PR for the 10–15 hardcoded files. Atlas + manifests need
> hand-edits.

---

## 5. Per-service migration class

### 5.1 CONTROL_PLANE → must move to MS-01

| Service | Data state | Migration mechanism |
|---|---|---|
| PostgreSQL 16 | 1.1 TiB on-disk, 46 GiB logical | `pg_dumpall` → restore on MS-01; carries roles + dbs. **Do not bit-copy `/var/lib/postgresql`.** |
| Qdrant 1.13.2 | 51 GiB, 29 collections | Qdrant snapshot API per collection → SCP → restore. |
| Redis | 24 MiB, ephemeral | `BGSAVE` + copy `dump.rdb`, or rebuild from sources. |
| Redpanda | unknown topic-data size; uses `/var/lib/redpanda` | Drain consumers, snapshot, restore. **Largest RAM consumer (8.5 GiB)** — verify x86 image, MS-01 RAM headroom. |
| LiteLLM gateway | `litellm_config.yaml` only | Move config + secrets; service is stateless. |
| ChromaDB ×2 (`fortress-chromadb` 8004 legacy, `fortress-chroma` 8020 latest) | unknown size (within docker volumes) | Volume export / re-ingest. **Decide whether both are still needed before migration.** |
| RAG retriever (`yzy-retriever` :8010) | stateless if Qdrant is the store | Re-deploy container. |
| `fortress-backend` (FastAPI :8000) | stateless | Service unit + venv + secrets. |
| `fortress-arq-worker` | stateless (Redis queue) | Service unit. |
| `fortress-sync-worker` | stateless | Service unit. |
| `fortress-channex-egress` | stateless | Service unit. |
| `fortress-console` (:9800) | stateless | Service unit + frontend bundle. |
| `fortress-sentinel` (NAS indexer) | reads NAS only | Service unit. |
| `crog-concierge-worker` | stateless (consumes Redpanda) | Service unit. |
| All admin crontab entries (~30 jobs) | reference repo paths | Re-install crontab after Fortress-Prime + venv exist. |

### 5.2 INFERENCE_TIER → relocate elsewhere in cluster

| Service | Where to move | Why not MS-01 |
|---|---|---|
| Ollama (qwen2.5 runner) | spark-3, spark-4 (already run Ollama per memory `project_cluster_ollama_topology.md`) | MS-01 has no GPU; ARM64 NIM images won't pull on x86. |
| `fortress-nim-brain` (enabled but inactive) | spark-1 (Phase 5b destination) | ARM64 NIM. |
| `fortress-vllm-bridge` | retire (per audit-20260422 it targets a dead container) | n/a |
| `fortress-inference` (oneshot, exited) | retire / re-evaluate | n/a |

### 5.3 APP_TIER → co-tenant decision per ADR-004

| Service | Rec |
|---|---|
| `crog-ai-frontend` (Next.js :3005) | Move to MS-01 with control plane (lightweight, cohabits with Console). |
| `fortress_mission_control` (open-webui) | Decide: keep, retire, or move to dedicated app host. Currently shares spark-2. |
| Open WebUI on `:8080` | Same as above. |
| `pm2-admin` | Drop unless an active PM2 app is identified. |
| `fortress-deadline-sweeper`, `*-nightly-finetune`, `*-nightly-labeling`, `*-weekly-judge-training` | Move with control plane (timers + scripts under repo). |

### 5.4 INFRASTRUCTURE → re-register or replace on MS-01

| Service | Rec |
|---|---|
| k3s server | **MS-01 takes over as control-plane node.** Workers (spark-1/3/4/5) re-register against new API endpoint. Requires etcd snapshot or re-init. |
| Ray head | Re-launch on MS-01 (tools/cluster/run_ray_head.sh) — node IP changes. |
| cloudflared | Move both tunnel JSONs + cert + config; update ingress map. |
| Portainer (server + agent) | Re-deploy; swarm membership re-init. |
| Docker Swarm membership (port 7946) | Re-init swarm on MS-01 if portainer needs it. |
| Ray worker discovery | Atlas update + worker re-bootstrap. |

### 5.5 DGX-ONLY → drop on MS-01

`dgx-dashboard.service`, `dgx-dashboard-admin.service`,
`dgxstation-desktop.service`, `nvidia-dgx-telemetry.service`,
`dcgm-exporter`, `nvidia-persistenced.service`,
`nvidia-nvme-interrupt-coalescing.service`, RDMA/InfiniBand modules,
`fortress-telemetry.service` (if DGX-specific). All are tied to DGX
hardware that MS-01 doesn't have.

### 5.6 REMOVABLE / RETIRED

- `fortress-vllm-bridge.service` (dead container per audit-20260422)
- `gmail_watcher` cron (already disabled in crontab comment)
- Nginx LB on :80 (REQUIREMENTS.md says "stopped")
- Duplicate Ollama runners (audit-20260422 flagged 3 instances; today shows 2)
- Legacy postgres backup files (verify before purge)
- ChromaDB duplicate (`fortress-chroma` :8020 vs `fortress-chromadb` :8004 — pick one)
- `iperf3.service` (test-only, not part of prod)
- `fortress-inference.service` (oneshot, exited — verify if it's ever re-armed)

---

## 6. spark-2 identity reference summary (numbers)

| Reference type | Count |
|---|---|
| Total `spark-2 / 192.168.0.100 / spark-node-2` matches in repo | **616** |
| Code-only matches (excludes `.md`) | 219 |
| Unique code files affected | **82** |
| Hardcoded `192.168.0.100` defaults in `.py` | ~15 |
| Hardcoded refs in `fortress_atlas.yaml` | 3 (id + management_ip + ollama_url + 4 routing-table mentions) |
| Markdown / runbook mentions (doc sweep needed) | 397 lines |

---

## 7. Migration risk matrix

### 7.1 Hot-path (downtime visible to users / cron)

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| H1 | `crog-ai.com` (Cloudflare → fortress-console:9800) goes dark during cutover | HIGH | Stage MS-01 alongside spark-2; switch tunnel ingress in one cloudflared reload. |
| H2 | Postgres write window — fortress_db is mid-write 24×7 (sync worker, ARQ, sentinel, email_bridge every 5m) | HIGH | Quiesce: stop arq + sync + channex + email_bridge cron, then `pg_dumpall`. Aim for <10 min freeze. |
| H3 | Qdrant queries stop — search/legal_caselaw/RAG paths break | HIGH | Snapshot per collection, restore, verify counts; keep spark-2 Qdrant warm until parity confirmed. |
| H4 | k3s control plane move = whole cluster reschedules pods | HIGH | Plan etcd snapshot + new server cert; phase k3s after data services. |
| H5 | LiteLLM `:8002` is the routing brain for sovereign models — cutover must update atlas + every consumer | HIGH | Lift-and-shift; keep address parameterized via env. |
| H6 | `0 6 * * *` Watchtower briefing email goes to Gary with broken Command Center links if cutover spans 06:00 | MED | Cut over outside the 02:00–07:00 cron storm window. |
| H7 | Cloudflared tunnel cert / tunnel-ID is bound to host — moving naively can leave a zombie tunnel | MED | Recreate tunnel on MS-01 or move credential JSONs intact + DNS update. |
| H8 | Redpanda topics in flight for fortress-channex-egress / revenue_consumer_daemon | MED | Drain or set retention; restore offsets. |

### 7.2 Cold-path (background workers, recoverable)

| # | Risk | Severity |
|---|---|---|
| C1 | Nightly fine-tune / labeling timers skip a night | LOW (re-run next day) |
| C2 | Sentinel re-indexes NAS from scratch on first boot | LOW (idempotent, just slow) |
| C3 | Ray head re-init invalidates active jobs | LOW (no long-running jobs found at audit time) |
| C4 | DGX dashboards drop | NONE (DGX-only) |

### 7.3 Data migration size + complexity

| Store | On-wire | Mechanism | Estimated time @ 10 Gbps |
|---|---|---|---|
| Postgres logical (`pg_dumpall` → restore) | ~46 GiB | dump+restore | ~30–45 min incl. schema rebuild |
| Postgres physical (NOT recommended) | 1.1 TiB | rsync | hours; restores all WAL bloat |
| Qdrant (snapshot API) | 51 GiB | per-collection snapshot + restore | ~15 min |
| Redis (`dump.rdb`) | 24 MiB | scp | seconds |
| Fortress-Prime repo + adapters | 113 GiB | git fetch + selective rsync | 5–15 min |
| Docker NIM/vLLM images | 80+ GiB | **don't migrate** (ARM64 → x86 incompat) | n/a |
| Cloudflared tunnel state | <100 KiB | scp | seconds |
| `/etc/fortress/*` secrets | <10 KiB | scp w/ same perms | seconds |

---

## 8. RAM / CPU sizing analysis (does it fit in MS-01's 32 GiB?)

### Working-set estimate after relocations

Drop ollama (relocate to spark-3/4), DGX-only services, iperf3, and
keep developer Claude sessions OFF the production host:

| Component | RSS at audit | Notes |
|---|---|---|
| redpanda | 8.5 GiB | Largest single RSS. May tune `--reserve-memory` lower. |
| Postgres (sum, working set ~20% of 46 GiB) | ~6–10 GiB | Buffers + connections. 37 active conns observed (mostly fortress_shadow:18). |
| Qdrant | 2.2 GiB | Likely grows with usage. |
| LiteLLM | 1.7 GiB | |
| k3s server | 1.3 GiB | If MS-01 runs k3s control plane. |
| Open WebUI / mission_control | ~0.5 GiB | If kept. |
| ChromaDB ×2 | ~1.0 GiB total | If both kept; ~0.5 GiB if consolidated. |
| RAG retriever | ~0.5 GiB | |
| fortress-backend | 0.5 GiB | |
| fortress-arq-worker | 0.5 GiB | |
| fortress-sync-worker | 0.2 GiB | |
| fortress-sentinel | 0.4 GiB | |
| crog-ai-frontend | 0.5 GiB | |
| Ray head (no inference) | 0.5 GiB | |
| OS + buffers + cache | 2–3 GiB | |
| **Subtotal control plane** | **~26–28 GiB** | |
| **Headroom** | **~4–6 GiB** | Tight but feasible. |

**Verdict: YES, with relocation.** The control-plane working set fits
in 32 GiB **only if**:
1. Ollama runners are off-host (spark-3/4).
2. NIM/vLLM/Hermes containers do **not** run on MS-01.
3. Developer Claude sessions are not pinned to MS-01.
4. Redpanda is tuned (currently 8.5 GiB; can likely run at 4–6 GiB with
   `--memory` and `--reserve-memory` flags).
5. Either ChromaDB is consolidated, or a final decision is made to drop
   one of the two instances.

**Margin is thin (~4–6 GiB headroom).** A single new service or a
Postgres connection burst could push the host to swap. The current
spark-2 already shows **8.5 GiB swap used** at 40 GiB RSS in 121 GiB
RAM — meaning Postgres / Redpanda working sets are already paging
under load. **Recommend testing under realistic load before cutover.**

### CPU

spark-2 shows steady ~2.0 load average with frequent spikes from
ollama runners (72% CPU on a single core at audit). With ollama gone,
load average should drop substantially. MS-01's x86 cores will be
faster per-thread for Postgres/LiteLLM/Python work — likely a **win**.

---

## 9. Open questions for migration brief

1. **Postgres 1.1 TiB vs 46 GiB logical** — what's eating the disk?
   WAL retention? Old base backups? Tablespaces? Run `du -sh
   /var/lib/postgresql/16/main/{base,pg_wal,pg_xact,...}` before brief.
2. **`/home/admin/Fortress-Prime` 113 GiB** — what's not in git?
   Adapter weights? Local datasets? Need an itemized listing.
3. **Two ChromaDB containers** — `:8004` (1.5.3, loopback) vs `:8020`
   (latest, public). Which is authoritative? Can one retire?
4. **Unidentified listeners** on `:3100`, `:9876`, `:18180` — confirm
   service ownership before classifying.
5. **`fortress-nim-brain`, `fortress-apex`, `fortress-vllm-bridge`,
   `fortress-event-consumer`** — enabled at boot but inactive. Keep,
   retire, or document?
6. **Redpanda topic inventory** — which topics, what retention, who
   produces / consumes? Needed for drain plan.
7. **k3s control-plane move** — can we run MS-01 as the new server
   while keeping spark-2 as a worker (graceful), or is this hard
   cutover?
8. **MS-01 IP plan** — does MS-01 take over `192.168.0.100`, or get a
   new IP and force every consumer to update? The 82 hardcoded files
   make IP-takeover the lowest-effort option.
9. **Cloudflared tunnel** — recreate (clean) or migrate credentials?
   Recreate is safer.
10. **Backup window** — `0 2 * * *` `backup_db.sh` writes ~24 GB to
    NAS nightly. Cutover should happen after 03:00 (post-backup) and
    before 05:00 (sync workers fire). Roughly a 2-hour window.
11. **Phase B v0.2** (synthesizer stripping) is in flight on a separate
    branch and uses Postgres + Qdrant. Coordinate cutover so it isn't
    mid-pass.
12. **Phase 5b NIM migration** (spark-1) is a separate in-flight effort
    per memory `project_phase5b_spark1_audit.md`. Make sure the
    spark-2 → MS-01 plan and Phase 5b don't both try to claim
    `fortress-nim-brain`.

---

## 10. Secrets handling

`/etc/fortress/` contains:

| File | Mode | Owner | Purpose |
|---|---|---|---|
| `admin.env` | `600` | root | (probable) admin/root env vars. **Plain-text — handle carefully.** |
| `nim.env` | `640` | root:admin | NIM/NGC creds |
| `nim.env.bak-20260423-112930` | `640` | root:admin | backup |
| `nim.env.phase1-bak-20260423_075155` | `600` | root:admin | backup |
| `secrets.env` | `600` | root:admin | service secrets |
| `secrets.env.phase2-migration-pending` | `640` | root:admin | newer secrets, not yet rotated |
| `secrets.manifest` | `600` | admin:admin | catalog of what lives in secrets.env |

**Audit confirms presence of plain-text secrets but does not commit
contents.** Migration brief should:
- Move all 7 files preserving mode and ownership.
- After cutover, rotate at least DB passwords (since they touch ~20
  service unit drop-ins) using `secrets.env.phase2-migration-pending`
  if it's the prepared rotation set.

---

## 11. Audit telemetry (what we collected, when)

- Probe 1 (services + ports): 08:02 EDT
- Probe 2 (docker + top-RSS + disk): 08:04 EDT
- Probe 3 (configs + crons + timers): 08:05 EDT
- Probe 4 (Postgres + Qdrant + connections): 08:06 EDT
- Phase B v0.2 cross-check: `case_briefing_compose` not running;
  Postgres at 37 active conns (fortress_shadow:18, fortress_db:5,
  paperclip_db:4, fortress_prod:2, fortress_guest:1). Audit did not
  perturb Phase B work.
- Probe 5 (repo grep + qdrant volume size + drop-ins): 08:08 EDT
- Total wall-clock: ~10 minutes.
- No services touched. No data modified.

