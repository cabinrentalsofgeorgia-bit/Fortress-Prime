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
- **2026-04-28 10:39 EDT** — `/etc/fortress/admin.env` written by operator (mode 600, `admin:admin`). Contains `POSTGRES_FORTRESS_ADMIN_PASSWORD`, `POSTGRES_FORTRESS_API_PASSWORD`, and `POSTGRES_FORTRESS_APP_PASSWORD`. The APP key was pre-staged in anticipation of the M3 runbook's `CREATE USER fortress_app` step (per `docs/runbooks/m3-spark1-mirror-activation.md:42`), but the role itself was never created on spark-1 (M3 hasn't run yet) and does not exist on spark-2 either (spark-2's FGP runtime role is `fgp_app`). Phase A1 (2026-04-29) drops the APP_PASSWORD line because the credential authenticates no role anywhere — see "Known issues" #2 for the unresolved naming reconciliation.
- **2026-04-28 10:52 EDT** — `postgresql-16-postgis-3` and `postgresql-16-pgvector` installed.
- **2026-04-28 ~11:13 EDT** — `postgresql.conf` tuned for spark-1's RAM profile (8 GB shared_buffers, 24 GB effective_cache_size, 200 max_connections, `pg_stat_statements` preloaded). `pg_hba.conf` opened for `fortress_admin` from spark-2's LAN IP into `fortress_prod` only.
- **2026-04-28 11:16 EDT** — `postgresql@16-main.service` started.
- **2026-04-28 (during the day)** — Roles `fortress_admin` (Create role + Create DB, *not* Superuser) and `fortress_api` (login only) created on spark-1. **NOT** created on spark-1: `fortress_app` (referenced by M3 runbook + `.env.example`), `fgp_app` (the canonical FGP runtime role on spark-2), and per-service roles spark-2 has (`crog_ai_app`, `miner_bot`, `trader_bot`). Privilege divergence to surface: spark-2's `fortress_admin` is **Superuser**; spark-1's is **Create role, Create DB**. Whether spark-1 should match spark-2's privilege set is an operator decision tied to the canonical-name question (see "Known issues" #2).
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

2. **`fortress_app` canonical-name reconciliation (operator-owned).** `fortress_app` is referenced in:

   - `fortress-guest-platform/.env.example:195` — the `SPARK1_DATABASE_URL` template
   - `docs/runbooks/m3-spark1-mirror-activation.md:42-46, 74` — `CREATE USER` + grants + `Environment=SPARK1_DATABASE_URL`
   - `docs/operational/spark-1-legal-migration-runbook.md:57-58` — M2-2 / M2-3 steps

   …yet the role exists on **neither** spark-1 nor spark-2. Spark-2's runtime role for FGP is `fgp_app`. Three names are floating around for the same conceptual runtime role:

   - canonical 004 contract (per `flos-phase-a1-postgres-spark1-brief.md` Section 3): `fortress_api`, with explicit "DO NOT create `fgp_app`"
   - spark-2 operational reality: `fgp_app` (which the original brief forbade)
   - M3 mirror activation runbook + `.env.example`: `fortress_app`

   This naming divergence is unresolved as of Phase A1. Phase A1 (2026-04-29) drops the dead `POSTGRES_FORTRESS_APP_PASSWORD` line from `/etc/fortress/admin.env` because it authenticates no role anywhere. The "which name is canonical for spark-1's runtime role" question follows separately as an operator decision.

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

`fortress_app` is currently a name without a role on either host — see "Known issues" #2 for the unresolved naming reconciliation. Spark-2's per-service FGP runtime role is `fgp_app`; canonical 004 contract says `fortress_api`; M3 runbook prescribes `fortress_app`. Operator will pick.
