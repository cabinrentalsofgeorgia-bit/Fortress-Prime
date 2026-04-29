# Spark-2 → Spark-1 Migration Provenance

**Status:** mid-flight, additive M3 trilateral-write phase pending
**Initiated:** 2026-04-28 (Postgres bootstrap on spark-1; operator-confirmed deliberate)
**Driver:** ADR-001 (one spark per division) — Fortress Legal moves to spark-1
**Owner:** Gary Knight
**Last updated:** 2026-04-29

---

## Why this document exists

Until Phase A1, the spark-2 → spark-1 migration lived in operator's head and a single in-progress runbook. This document is the durable written record so a fresh session — or a second operator — can pick up context without reconstructing it from `apt history`, file timestamps, and tribal knowledge.

## What's been done

- **2026-04-28 08:02 EDT** — apt bootstrap on spark-1 by `admin` user: `postgresql-16`, `postgresql-contrib-16`, `redis-server`, `build-essential`, `libpq-dev`, `python3-venv`, `python3-dev`, `ocrmypdf`. Postgres 16.13 from Ubuntu repo (not PGDG). Redis from Ubuntu repo. OCR toolchain (`ocrmypdf`, `pikepdf`, `lxml`, etc.) installed alongside.
- **2026-04-28 ~08:30 EDT** — `~/Fortress-Prime` renamed to `~/Fortress-Prime.legacy`; fresh clone of `cabinrentalsofgeorgia-bit/Fortress-Prime` to `~/Fortress-Prime.new` with symlink `~/Fortress-Prime` → `~/Fortress-Prime.new`.
- **2026-04-28 10:39 EDT** — `/etc/fortress/admin.env` written by operator (mode 600, `admin:admin`). Contains `POSTGRES_FORTRESS_ADMIN_PASSWORD`, `POSTGRES_FORTRESS_API_PASSWORD`, and a stale `POSTGRES_FORTRESS_APP_PASSWORD` (residual from earlier draft of `spark-1-legal-migration-runbook.md` M2-2 step that referenced `fortress_app` before canonical 004 contract was finalized).
- **2026-04-28 10:52 EDT** — `postgresql-16-postgis-3` and `postgresql-16-pgvector` installed.
- **2026-04-28 ~11:13 EDT** — `postgresql.conf` tuned for spark-1's RAM profile (8 GB shared_buffers, 24 GB effective_cache_size, 200 max_connections, `pg_stat_statements` preloaded). `pg_hba.conf` opened for `fortress_admin` from spark-2's LAN IP into `fortress_prod` only.
- **2026-04-28 11:16 EDT** — `postgresql@16-main.service` started.
- **2026-04-28 (during the day)** — Roles `fortress_admin` (CREATEDB) and `fortress_api` (login only) created on spark-1; matches canonical 004 Postgres contract. **No `fortress_app` role created** despite admin.env key — explicit choice by operator to follow canonical contract over the older runbook draft.
- **2026-04-28 (during the day)** — Schema dump from spark-2 `fortress_db` loaded into spark-1's `fortress_db`, `fortress_prod`, and `fortress_shadow_test` (the third DB is the CROG-AI shadow-testing convention). All three DBs identical: 13 schemas, 291 tables, 36 MB each, zero application data.
- **2026-04-28 22:49 EDT** — Original `flos-phase-a1-postgres-spark1-brief.md` saved in `~/`. Brief assumed clean-host install — an assumption that no longer matched reality. Operator paused execution, asked for state capture instead.
- **2026-04-28 23:30 EDT** — Comprehensive state captured in `docs/operational/spark1-current-state-2026-04-29.md` (this PR also commits that file into the repo for durability).
- **2026-04-29 09:16 EDT** — `spark1-phase-a1-reshaped-brief.md` written. New shape: additive overlays only, no schema mutations.
- **2026-04-29** — Phase A1 (this PR) executes the reshaped brief.

## What remains

| Phase | Description | Owner | Blockers |
|---|---|---|---|
| **M3** | Trilateral additive write — spark-2 mirrors writes to spark-1 behind default-OFF flag | TBD | M3 activation step 4 blocks on alembic merge (Issue filed by this PR) |
| **M3 activation** | Flip the default-OFF flag, run `alembic upgrade head` against `SPARK1_DATABASE_URL` | TBD | Alembic merge on spark-2 must complete first |
| **M4** | Parity verification — both DBs receive the same writes; row-by-row diff stays clean | TBD | M3 activation must be live |
| **M5** | Read-source switchover spark-2 → spark-1 | TBD | M4 parity must be verified for soak window |
| **M6** | Retire spark-2 legal writes (decommission) | TBD | M5 stable for soak window |

## Known issues inherited from the schema dump

1. **Two divergent alembic heads** in all three DBs:
   - `q2b3c4d5e6f7`
   - `r3c4d5e6f7g8`
   
   Plus the previously-known orphaned head `7a1b2c3d4e5f` (Issue #204).
   
   This blocks M3 activation step 4 (`alembic upgrade head`). Phase A1 (additive overlays) is unblocked. Tracking issue filed by this PR.

2. **Stale `fortress_app` reference in admin.env.** Three password keys exist (`ADMIN`, `APP`, `API`); only `fortress_admin` and `fortress_api` are real DB roles. Zero code references `fortress_app` or `POSTGRES_FORTRESS_APP_PASSWORD` anywhere in the repo (verified via grep over `*.py`, `*.env*`, `*.yaml`, `*.yml`, `*.sh`, `*.toml`, `*.cfg`, `*.ini`, `*.md`). The APP key is dead weight from the earlier runbook draft that named the runtime role `fortress_app` before the canonical 004 contract settled on `fortress_api`. Phase A1 leaves admin.env unchanged because the brief's literal "rename APP→API value-carried-over" would overwrite the working `fortress_api` password (APP and API values differ). The APP key is harmless residual; cleanup is a one-line follow-up if desired.

## Authoritative artifacts

- `docs/architecture/cross-division/_architectural-decisions.md` — ADR-001 (one-spark-per-division)
- `docs/operational/spark-1-legal-migration-runbook.md` — broader migration sprint runbook (M1–M6)
- `docs/operational/spark1-current-state-2026-04-29.md` — frozen snapshot of spark-1 at the moment Phase A1 began
- `docs/operational/spark1-phase-a1-runbook.md` — operator runbook for verifying / re-running the Phase A1 overlay steps
- `docs/runbooks/m3-spark1-mirror-activation.md` — M3 activation runbook (companion)
- `~/spark1-phase-a1-reshaped-brief.md` (spark-1 only, intentionally not in repo) — the brief this PR executes

## Naming conventions

- `fortress_db` — canonical operational DB on spark-1 (target for legal services per `postgres-schemas.md`)
- `fortress_prod` — canonical mirror target; receives the same writes as `fortress_db` once M3 is active
- `fortress_shadow_test` — shadow-testing DB (CROG-AI convention); receives writes during shadow-test runs and is otherwise idle
- `fortress_admin` — canonical owner role per 004 contract (CREATEDB; for migrations, ownership)
- `fortress_api` — canonical runtime role per 004 contract (login only; for service authentication)

`fortress_app` is **not** a canonical role — see "Known issues" above.
