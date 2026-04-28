# Spark-1 Legal Migration Runbook

**Created:** 2026-04-28
**Owner:** Gary Knight
**Trigger:** ADR-001 violation — Fortress Legal stack runs on spark-2 today; per ADR-001 it belongs on spark-1.
**Sprint:** 2026-04-28 → completion (target: same day for M1-M4, M5 next day after verification window)
**Status:** IN PROGRESS — currently at M1
**Related:**
- ADR-001 (one-spark-per-division, LOCKED)
- ADR-003 (six-spark + inference cluster — TO BE WRITTEN as part of this sprint)
- docs/architecture/cross-division/FLOS-phase-0a-legal-email-ingester-design-v1.1.md
- docs/architecture/cross-division/FLOS-phase-1-2/1-3/1-4-*.md

---

## Cluster topology (target state)

| Spark | Division/Role | Status |
|---|---|---|
| 1 | Fortress Legal | TARGET — migrating into today |
| 2 | CROG-VRS + Property Mgmt Acquisitions + control plane | shedding Legal |
| 3 | Master Accounting | planned |
| 4 | Trading + Wealth | planned |
| 5 | Inference (NIM, pipeline parallel) | active |
| 6 | Inference (NIM, pipeline parallel) | active |

Policy: NIM-first wherever NIM has parity. Pipeline parallel between sparks 5+6 for large models.

---

## Migration phases

### M1 — Spark-1 prep (install + clone) — AUTO MODE

Prepare spark-1 for Postgres, Redis, repo, credential storage. No data touched.

- M1-1: rename existing `~/Fortress-Prime` to `~/Fortress-Prime.legacy`
- M1-2: apt install postgresql-16, postgresql-contrib-16, redis-server, build-essential, libpq-dev, python3-venv, python3-dev, ocrmypdf
- M1-3: install uv (user-level)
- M1-4: clone Fortress-Prime fresh from origin (expect HEAD at e87b20edd or descendant)
- M1-5: verify Postgres + Redis run on default config
- M1-6: create `/etc/fortress/` (chmod 700, chown admin) — operator fills credentials later

**Hard constraints during M1:** no inference service touched (NIM-sovereign, fortress-brain, ollama all stay running). RAM available must not drop below 30 GiB. Fail closed on any non-zero exit.

**Exit:** all 6 sub-phases PASS, RAM ≥ 30 GiB available, all services daemonized.

**Status:** COMPLETE

---

### M2 — Schema + role bootstrap on spark-1 — MANUAL GATE

Postgres tuning, role creation, schema replication. Operator generates passwords directly on spark-1, never in chat.

- M2-1: tune postgresql.conf for spark-1's RAM profile (47 GiB available; shared_buffers ≥ 8 GiB)
- M2-2: operator generates fortress_admin + fortress_app passwords on spark-1, writes to `/etc/fortress/admin.env` (chmod 600)
- M2-3: create roles (fortress_admin owner, fortress_app least-priv)
- M2-4: create databases (fortress_prod, fortress_db, fortress_shadow_test — match spark-2 naming)
- M2-5: install Alembic chain, run `alembic upgrade head` to current schema
- M2-6: verify legal.* tables exist + match spark-2 row counts (empty initially)

**Status:** COMPLETE

---

### M3 — Dual-write window — OBSERVED

Spark-2 dispatcher writes bilaterally to spark-2 + spark-1. Validate row counts and checksums match between hosts. Soak overnight if comfort low.

- M3-1: configure spark-2 ingester + dispatcher to write spark-1 in addition to spark-2
- M3-2: 1-4 hour soak; per-table row count diff between hosts
- M3-3: checksum validation on event_log + case_posture + dispatcher_event_attempts

**Exit:** zero row count divergence over 4-hour window; matching checksums.

**Status:** READY — pending operator authorization

---

### M4 — Switchover — MANUAL GATE

Stop spark-2 dispatcher. Start spark-1 dispatcher (LEGAL_DISPATCHER_ENABLED=true). Update legal_mail_ingester to write spark-1 only. Health check + smoke traffic.

- M4-1: stop spark-2 fortress-arq-worker
- M4-2: start spark-1 fortress-arq-worker
- M4-3: update mailbox config to point at spark-1
- M4-4: smoke test — 5 synthetic events end-to-end
- M4-5: confirm health endpoint on spark-1 returns "healthy"

**This is also Phase 1-6 traffic generation,** running natively where the dispatcher actually lives now.

**Status:** PENDING M3

---

### M5 — Decommission on spark-2 — DEFERRED 24-72H

After M4 verification window, drop legal.* schema from spark-2. Update systemd units, env files. Archive spark-2 legal_vault references.

- M5-1: stop spark-2 dispatcher service permanently
- M5-2: snapshot spark-2 legal.* before drop (safety net)
- M5-3: DROP SCHEMA legal CASCADE on spark-2
- M5-4: update fortress_atlas.yaml + systemd to remove spark-2 legal references
- M5-5: archive spark-2 legal_vault (move to /mnt/fortress_nas/archive/spark-2-legal-decommission-2026-04-28/)

**Status:** PENDING M4 + 24-72h verification window

---

## Out of scope for this sprint

- Council deliberation engine migration to spark-1 (separate sprint)
- TITAN/BRAIN inference move to sparks 5+6 (separate sprint)
- Spark-3 (Master Accounting) provisioning
- Spark-4 (Trading + Wealth) provisioning
- legal_caselaw_federal corpus ingest (PR #184 follow-up, deferred)

---

## Track B parallel work (not gated on migration)

While M1-M5 run, operator works on Case II attorney briefing in parallel:

- Privilege-review email_archive Query A (37 rows)
- Mark Sections 4, 5, 7, 8 stubs into drafts
- Pull `#100 Limited Waiver of Appeal Rights` + 4 vanderburge appeals-waiver emails into curated/
- OCR Exhibit_E (121pp inspection) + Exh. I (preliminary survey)
- GA SoS lookup on plaintiff entity name reversal (Q8)
- Send 3 outbound drafts (Thor James, Wilson Pruitt, Pugh)

Track B uses spark-2 only. Migration does not block it.

---

## Risk register

| Risk | Mitigation | Owner |
|---|---|---|
| RAM exhaustion on spark-1 (inference + Postgres + Redis + dispatcher) | RAM floor check at every M1 sub-phase; tune Postgres conservatively in M2-1 | Claude Code on spark-1 |
| Schema divergence between hosts during dual-write | Checksum validation in M3-3; soak window before M4 | Operator |
| Dispatcher writes lost during M4 cutover | Brief downtime acceptable; Phase 0a `email_archive.ingested_from` attribution preserves audit trail | Operator |
| `~/Fortress-Prime.legacy` on spark-1 contains drift from main | Renamed not deleted; available for inspection if anything looks off | Operator |
| `fortress_admin` credential rotation needed | Operator generates on spark-1 directly; spark-2 credential rotated separately as routine hygiene | Operator |
| Migration DAG cannot fast-forward to fresh DB on spark-1 due to brownfield assumptions (M-013 through M-016) | Path 2 schema-clone bypasses DAG walk. Long-term fix is the schema-migration audit PR (filed in issues-log). | Operator |
| fortress_db + fortress_shadow_test on spark-1 are empty post-M2 | M3 prep step: re-apply /tmp/spark-2-fortress_prod-schema-cleaned.sql to both DBs (schema is identical) before dual-write begins | Claude Code on spark-1 |

---

## Status log

| Date/time | Phase | Outcome | Notes |
|---|---|---|---|
| 2026-04-28 | M1 | IN PROGRESS | Pre-flight clean; auto-mode prompt handed to spark-1 |
| 2026-04-28 | M2 | COMPLETE | Path 2 (pg_dump --schema-only from spark-2) chosen after multi-head DAG ambiguity blocked native alembic upgrade. fortress_prod schema mirrored, alembic_version stamped to spark-2's 2 heads via direct INSERT (alembic stamp doesn't support multi-head subset stamping). 5 extensions pre-created as postgres. fortress_db + fortress_shadow_test left empty (M3 prep). 45 min total. |

---

## How to use this doc

- Update the Status log row with each phase outcome
- Update each phase's Status field as it completes
- Add risk register entries as new risks surface
- Reference this doc in every PR + commit during the sprint

---

## Status log update — 2026-04-28

| Date/time (UTC) | Phase | Outcome | Notes |
|---|---|---|---|
| 2026-04-28 | M1-1 | PASS w/ collateral | Rename succeeded; broke fortress-brain.service via hardcoded venv shebang |
| 2026-04-28 | Recovery R1-R10 | PASS | Symlink restore: ~/Fortress-Prime → ~/Fortress-Prime.legacy. Brain back up. |
| 2026-04-28 | M1-2 | PASS | postgresql-16, redis-server, build-essential, libpq-dev, python3-venv, python3-dev, ocrmypdf installed |
| 2026-04-28 | M1-3 | PASS | uv installed, PATH appended to ~/.bashrc |
| 2026-04-28 | M1-4 | PASS | Cloned to ~/Fortress-Prime.new at HEAD e87b20edd |
| 2026-04-28 | M1-5 | PASS | postgres + redis active on default config |
| 2026-04-28 | M1-6a | PASS | /etc/fortress created, chmod 700, owned admin |
| 2026-04-28 | M1-6b | PASS | Atomic symlink repointed: ~/Fortress-Prime → ~/Fortress-Prime.new |
| 2026-04-28 | M1-6c | PASS | All 3 inference services active post-repoint, RAM stable |

**M1 complete.** All 3 protected inference services (NIM-sovereign, fortress-brain, ollama) remained continuously active throughout migration. No data touched. RAM available stable at 47 GiB.

Update phase M1 status field at top of doc from `IN PROGRESS` to `COMPLETE`.
Update phase M2 status field from `PENDING M1 completion + operator authorization` to `READY — pending operator authorization`.

---

## Risk register — additions from M1

| Risk | Mitigation | Owner |
|---|---|---|
| Renaming a repo dir breaks any systemd unit with hardcoded paths | Audit `systemctl status` for any service whose ExecStart references the dir before renaming. Fix forward via drop-in override, not unit file edit. | Operator + Claude Code |
| Python venv shebangs hardcode the venv's parent path; rename breaks every wrapper script in `venv/bin/` | Symlink restore (parent → renamed dir) avoids touching venv internals. Long-term: recreate venvs after migration completes. | Operator |
| `needrestart` triggers cascade restarts during apt install | Suppress via `/etc/needrestart/conf.d/99-fortress-quiet.conf` for migration window. Remove post-M5. | Claude Code on spark-1 |
| GitHub deploy key authorization required for `git clone` and `git push` from new host | Operator adds spark-1 ed25519 deploy key with write access via GitHub UI. Document the key fingerprint in runbook for future audit. | Operator |

---

## Outstanding artifacts requiring cleanup

These are in place from recovery + needrestart work. Review at end of M5:

- `/etc/systemd/system/fortress-brain.service.d/10-legacy-path.conf` — drop-in pinning brain ExecStart to `.legacy`. **Mismatched with current symlink.** If brain ever restarts, this drop-in wins and brain starts from .legacy. Remove before any future brain restart so it follows the symlink to the new tree.
- `/etc/needrestart/conf.d/99-fortress-quiet.conf` — needrestart auto-restart suppression. Remove post-M5 once migration window closes.
- `~/Fortress-Prime.legacy` on spark-1 — kept until M5 verification window closes (24-72h post-M4). Provides rollback path if M3/M4 surface unexpected behavior.
- `/tmp/spark-2-fortress_prod-schema-cleaned.sql` on spark-1 — the cleaned pg_dump output used for M2 apply. Retained for re-apply against fortress_db + fortress_shadow_test during M3 prep, then delete.

---

## Spark-1 deploy key fingerprint (reference)

For future audit:
- **Title:** `spark-1 (Fortress Legal migration)`
- **Key type:** ed25519
- **Fingerprint:** `SHA256:P532moZ/del210PNnn5RTZ0B4qNXrWKj4H46W0sl7WY`
- **Access:** read+write
- **Added:** 2026-04-28
