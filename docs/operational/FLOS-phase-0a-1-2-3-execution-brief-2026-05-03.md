# FLOS Phase 0a-1 + 0a-2 + 0a-3 — Execution Brief (Sunday 2026-05-03)

**Operator:** Gary Knight
**Authority:** v1.1 design signed off 2026-05-02
**Target:** Claude Code on spark-2, fresh `flos_phase_0a` tmux session
**Scope:** Full Day 1 of FLOS Phase 0a v1.1 §11 — schema + service + CLI/health
**Spec of record:** `docs/operational/FLOS-phase-0a-legal-email-ingester-design-v1_1.md` (commit reference at execution time)
**NOT in scope:** 0a-4 (worker registration / cutover) and 0a-5 (24h soak). `LEGAL_MAIL_INGESTER_ENABLED=False` stays default. No production traffic.

---

## 0. Standing constraints (non-negotiable)

- Branch from `origin/main` only. Never `--admin`, never `--force`, never self-merge.
- Single Claude Code session per host. **Verify spark-2 has no other active CC session before starting.**
- Cluster untouchable through 2026-05-08 except mission-critical. **This brief is mission-critical for Case II readiness** (counsel hire 2026-05-08; FLOS data substrate must exist).
- Parallel: Wave 7 Case II briefing is in a **different** tmux session (`email_pipeline` or named for Wave 7) on spark-2. **Do not touch other tmux sessions, do not stop other workers, do not restart `fortress-arq-worker`.** Coexistence is the design intent.
- Frontier health (`http://10.10.10.3:8000/health`) MUST stay 200. Hands off spark-3/4 entirely.
- All work in PRs. Phase-per-commit. Surface diffs before merge. Operator merges (never CC merges itself).

---

## 1. Pre-flight (5 min)

```bash
# In flos_phase_0a tmux on spark-2
cd /home/admin/Fortress-Prime
git fetch origin
git status
git log --oneline origin/main..HEAD     # must be empty (clean local main)
git checkout main
git reset --hard origin/main             # only if local main has drift; otherwise skip

# Confirm no concurrent CC session on this host
tmux ls
ps -ef | grep -i 'claude' | grep -v grep
```

**HALT condition:** if another `claude` process or a tmux session with active CC is running on spark-2, stop. Resolve session collision before proceeding.

**HALT condition:** if `git status` is dirty, stop. Resolve before branching.

```bash
# Frontier sanity (spark-3+4, hands-off but verify before starting)
curl -fsS http://10.10.10.3:8000/health
```

Expected: 200. If non-200 → stop, escalate to operator. Do NOT touch spark-3/4 to investigate; this brief does not own the frontier.

---

## 2. Branch + PR strategy

**One PR**, three commits, phase-per-commit:

- Branch: `feat/flos-phase-0a-day-1-2026-05-03`
- Commit 1: schema migration + seed (Phase 0a-1)
- Commit 2: ingester service (Phase 0a-2)
- Commit 3: CLI + health endpoint (Phase 0a-3)
- PR title: `FLOS Phase 0a Day 1 — schema + ingester service + CLI/health (LEGAL_MAIL_INGESTER_ENABLED=False default)`
- PR body: cross-link v1.1 design doc, list all 5 new tables, note `ingested_from` NOT NULL enforcement, note bilateral mirror is forward-only per §10, confirm worker registration deferred.

```bash
git checkout -b feat/flos-phase-0a-day-1-2026-05-03 origin/main
```

---

## 3. Phase 0a-1 — Schema migration + seed + bilateral mirror

### 3.1 Alembic migration creation

Create one Alembic revision. Honor Issue #204 chain divergence pattern — apply via raw psql, not `alembic upgrade head`, to fortress_db / fortress_prod / fortress_shadow_test (skip fortress_shadow per #204).

**Filename convention:** `backend/alembic/versions/<rev>_flos_phase_0a_1_legal_mail_ingester.py`

**Migration contents** (per v1.1 §9, §3.3, §4, §10):

```python
"""flos phase 0a-1 legal mail ingester

Revision ID: <generated>
Revises: <current head>
Create Date: 2026-05-03

Phase 0a-1 of FLOS — adds:
  - legal.priority_sender_rules (+ seed rows)
  - legal.mail_ingester_pause
  - legal.mail_ingester_state
  - legal.mail_ingester_metrics
  - legal.event_log
  - email_archive.ingested_from NOT NULL + format CHECK
  - bilateral mirror table on fortress_prod (forward-only)

Spec: docs/operational/FLOS-phase-0a-legal-email-ingester-design-v1_1.md
"""

# === legal.priority_sender_rules ===
CREATE TABLE legal.priority_sender_rules (
    id BIGSERIAL PRIMARY KEY,
    sender_pattern TEXT NOT NULL,
    priority TEXT NOT NULL,
    case_slug TEXT,
    rationale TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_priority CHECK (priority IN ('P1', 'P2', 'P3'))
);
CREATE INDEX idx_priority_sender_rules_active ON legal.priority_sender_rules(is_active) WHERE is_active;
CREATE INDEX idx_priority_sender_rules_case ON legal.priority_sender_rules(case_slug) WHERE case_slug IS NOT NULL;

# === legal.mail_ingester_pause ===
CREATE TABLE legal.mail_ingester_pause (
    mailbox TEXT PRIMARY KEY,
    paused_at TIMESTAMPTZ DEFAULT NOW(),
    paused_by TEXT,
    reason TEXT
);

# === legal.mail_ingester_state ===
CREATE TABLE legal.mail_ingester_state (
    mailbox TEXT PRIMARY KEY,
    last_patrol_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_error TEXT,
    last_error_at TIMESTAMPTZ,
    consecutive_failures INTEGER DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

# === legal.mail_ingester_metrics ===
CREATE TABLE legal.mail_ingester_metrics (
    id BIGSERIAL PRIMARY KEY,
    metric_name TEXT NOT NULL,
    mailbox TEXT,
    case_slug TEXT,
    priority TEXT,
    reason TEXT,
    event_type TEXT,
    counter_value BIGINT NOT NULL DEFAULT 0,
    bucket_start TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_mail_ingester_metrics_lookup
    ON legal.mail_ingester_metrics(metric_name, mailbox, bucket_start);

# === legal.event_log ===
CREATE TABLE legal.event_log (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    case_slug TEXT,
    event_payload JSONB NOT NULL,
    emitted_at TIMESTAMPTZ DEFAULT NOW(),
    emitted_by TEXT NOT NULL,
    processed_at TIMESTAMPTZ,
    processed_by TEXT
);
CREATE INDEX idx_event_log_unprocessed
    ON legal.event_log(emitted_at) WHERE processed_at IS NULL;
CREATE INDEX idx_event_log_case
    ON legal.event_log(case_slug, emitted_at) WHERE case_slug IS NOT NULL;
CREATE INDEX idx_event_log_type
    ON legal.event_log(event_type, emitted_at);

# === email_archive.ingested_from discipline (per v1.1 §4) ===

-- Backfill legacy producer rows
UPDATE email_archive
   SET ingested_from = 'legacy_imap_producer:unknown'
 WHERE ingested_from IS NULL
   AND file_path LIKE 'imap://%'
   AND id BETWEEN 166582 AND 174961;

-- Pre-legacy historical rows
UPDATE email_archive
   SET ingested_from = 'historical:unknown'
 WHERE ingested_from IS NULL;

ALTER TABLE email_archive
    ALTER COLUMN ingested_from SET NOT NULL,
    ADD CONSTRAINT chk_ingested_from_format
        CHECK (ingested_from ~ '^[a-z_]+:[a-z0-9_.-]+$');

# === Seed: priority_sender_rules (per v1.1 §3.3) ===

INSERT INTO legal.priority_sender_rules (sender_pattern, priority, case_slug, rationale) VALUES
  -- Cross-case (court systems)
  ('%@peachcourt.com',         'P1', NULL, 'Georgia court e-filing system; any inbound is procedural'),
  ('%@fanninclerk%',           'P1', NULL, 'Fannin County clerk; orders + scheduling'),
  ('%@fanninsuperior%',        'P1', NULL, 'Fannin Superior Court chambers / clerks'),
  -- fish-trap-suv2026000013 (Generali v CROG)
  ('%@stuartattorneys.com',    'P1', 'fish-trap-suv2026000013', 'Plaintiff counsel (J. David Stuart)'),
  ('%@rtsfg.com',              'P1', 'fish-trap-suv2026000013', 'Plaintiff collections (RTS Financial / Aaron Reaney)'),
  ('%@judgesosebee.com',       'P2', 'fish-trap-suv2026000013', 'Recused judge — historical; surface but lower priority'),
  -- prime-trust-23-11161
  ('%@wbd-us.com',             'P1', 'prime-trust-23-11161', 'Plan Administrator (Weil, Bankruptcy & Desai)'),
  ('%detweiler%',              'P1', 'prime-trust-23-11161', 'Don Detweiler — Plan Administrator');
```

### 3.2 Bilateral mirror — `email_archive` on fortress_prod

Per v1.1 §10 — forward-only mirror. Phase 0a-1 creates the mirror table on `fortress_prod` with **identical schema** to `fortress_db.email_archive`, including the new NOT NULL `ingested_from` and CHECK constraint. **Does not bulk-copy historical rows.**

```sql
-- On fortress_prod only:
CREATE TABLE email_archive (
    -- IDENTICAL to fortress_db.email_archive schema as of post-migration state
    -- Pull `\d email_archive` from fortress_db, replicate exactly
    -- Include UNIQUE(file_path) constraint
    -- Include ingested_from NOT NULL + chk_ingested_from_format CHECK
);
```

**Action:** before generating the CREATE TABLE statement, dump the current schema:

```bash
ssh fortress_db_host "psql -d fortress_db -c '\\d email_archive'" > /tmp/email_archive_schema.txt
```

Then generate the matching CREATE TABLE for fortress_prod, applying the post-0a-1 column constraints.

### 3.3 Apply order (per Issue #204 chain divergence)

```bash
# 1. Apply to fortress_db (canonical / production reads)
psql -h <fortress_db_host> -d fortress_db -f /tmp/flos-0a-1.sql

# 2. Apply to fortress_prod (bilateral mirror destination)
psql -h <fortress_prod_host> -d fortress_prod -f /tmp/flos-0a-1.sql

# 3. Apply to fortress_shadow_test
psql -h <fortress_shadow_test_host> -d fortress_shadow_test -f /tmp/flos-0a-1.sql

# Skip fortress_shadow per Issue #204
```

### 3.4 Verification — Phase 0a-1 exit criteria

```sql
-- All 5 tables exist on fortress_db
\dt legal.priority_sender_rules
\dt legal.mail_ingester_pause
\dt legal.mail_ingester_state
\dt legal.mail_ingester_metrics
\dt legal.event_log

-- Seed data present
SELECT COUNT(*) FROM legal.priority_sender_rules;          -- expect 8
SELECT COUNT(*) FROM legal.priority_sender_rules WHERE case_slug = 'fish-trap-suv2026000013';  -- expect 3
SELECT COUNT(*) FROM legal.priority_sender_rules WHERE case_slug = 'prime-trust-23-11161';     -- expect 2
SELECT COUNT(*) FROM legal.priority_sender_rules WHERE case_slug IS NULL;                      -- expect 3

-- ingested_from enforcement
SELECT COUNT(*) FROM email_archive WHERE ingested_from IS NULL;  -- expect 0
SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='chk_ingested_from_format';  -- expect ~ regex def

-- Bilateral mirror parity (forward-only — historical rows not mirrored)
-- fortress_db row count
SELECT COUNT(*) FROM email_archive;
-- fortress_prod row count (expect 0 at this point — forward-only)
-- Run on fortress_prod separately
```

**Exit criterion 0a-1 met when all queries above match expected.** Commit:

```
git add backend/alembic/versions/<rev>_flos_phase_0a_1_legal_mail_ingester.py docs/operational/FLOS-phase-0a-1-apply-runbook.md
git commit -m "FLOS Phase 0a-1: schema + seed + bilateral mirror

- legal.priority_sender_rules + 8 seed rows
- legal.mail_ingester_pause / _state / _metrics / event_log
- email_archive.ingested_from NOT NULL + format CHECK
- fortress_prod email_archive mirror table (forward-only per v1.1 §10)
- Applied to fortress_db / fortress_prod / fortress_shadow_test
- Skipped fortress_shadow per Issue #204

Spec: docs/operational/FLOS-phase-0a-legal-email-ingester-design-v1_1.md"
```

---

## 4. Phase 0a-2 — Ingester service

### 4.1 Files to create

```
backend/services/legal_mail_ingester.py     (~700 lines per v1.1 §11)
```

### 4.2 Required behavior (per v1.1 §3, §4, §5, §7, §8, §10)

- **arq background task** registered in `backend/core/worker.py` import path **but not in worker class registry** until Phase 0a-4. Service code is on disk + imported; not yet scheduled.
- **MAILBOXES_CONFIG read** — filter by `ingester == 'legal_mail'`. Default `'captain'` for backward compatibility.
- **Pause check** before each patrol: `SELECT 1 FROM legal.mail_ingester_pause WHERE mailbox=$1` → skip if found.
- **IMAP SEARCH banding** — `UNSEEN SINCE <today - search_band_days>`. Never unbounded. Cap at `max_messages_per_patrol`.
- **BODY.PEEK[]** for fetch. **Never set `\Seen`** (Captain owns that flag).
- **Per-message try/except** — one bad message does not abort the patrol. Increment `legal_mail_messages_errored_total{reason=…}`.
- **Stage 1 privilege classifier** (deterministic, ~1ms): ILIKE against `priority_sender_rules` → regex on subject for case identifiers → mailbox routing_tag inheritance. Output: `(priority, case_slug, privilege_class, watchdog_matches[])`.
- **Bilateral write** per v1.1 §10 — fortress_db first, capture id, mirror to fortress_prod. Idempotent on `file_path` UNIQUE.
- **Event emission** — INSERT into `legal.event_log` with full v1.1 §8 payload.
- **State update** — UPDATE `legal.mail_ingester_state` per patrol with `last_patrol_at`, `last_success_at` (only on success), `last_error` (only on failure), `consecutive_failures`.
- **Metrics emission** — Prometheus counters if exporter present; else INSERT/UPDATE on `legal.mail_ingester_metrics`.
- **Structured logging** — per-patrol summary line + per-message error line per v1.1 §7.
- **Versioning** — every event payload + every email_archive row carries `ingested_from='legal_mail_ingester:v1'`. Hard-coded constant; bump for v2.

### 4.3 Required imports / patterns to mirror

- IMAP banded SEARCH: mirror `backend/scripts/email_backfill_legal.py` (PR #225 lineage) for the SEARCH + PEEK pattern.
- Bilateral mirror write: mirror `LegacySession` / `AsyncSessionLocal` pattern from PR D / PR I.
- arq registration boilerplate: mirror Captain's worker registration in `backend/core/worker.py:589`-style.

### 4.4 Tests required in this commit

`backend/tests/services/test_legal_mail_ingester.py`:

- Stage 1 classifier matrix: 8 priority_sender_rules × known sender → expected (priority, case_slug)
- Idempotency: re-poll same UID → ON CONFLICT DO NOTHING, no duplicate event
- Error isolation: one malformed message in a batch → patrol completes, errored_total increments by 1, others ingested
- SEARCH banding: confirm `UNSEEN SINCE` is always paired (no unbounded SEARCH path exists)
- Pause check: pause row present → patrol skips that mailbox

### 4.5 Phase 0a-2 exit criteria

- File on disk, imports cleanly
- Tests pass
- **No worker registration yet** — `LEGAL_MAIL_INGESTER_ENABLED=False`, ingester does not run
- Lint / type checks clean

```
git add backend/services/legal_mail_ingester.py backend/tests/services/test_legal_mail_ingester.py
git commit -m "FLOS Phase 0a-2: legal_mail_ingester service

- arq-style background task (not yet registered with worker)
- Banded IMAP SEARCH + BODY.PEEK[] (Captain coexistence per v1.1 §3.4)
- Stage 1 deterministic privilege classifier (v1.1 §5)
- Bilateral write fortress_db → fortress_prod (v1.1 §10)
- email.received event emission to legal.event_log (v1.1 §8)
- Pause/state/metrics tables wired
- Tests cover classifier matrix, idempotency, error isolation, banding, pause
- LEGAL_MAIL_INGESTER_ENABLED defaults False; not active in worker

Spec: docs/operational/FLOS-phase-0a-legal-email-ingester-design-v1_1.md"
```

---

## 5. Phase 0a-3 — CLI + health endpoint

### 5.1 Files to create

```
backend/scripts/legal_mail_ingester_cli.py     (~150 lines)
backend/api/legal_mail_health.py               (~100 lines)
```

### 5.2 CLI commands (per v1.1 §6)

- `fgp legal mail status` — reads `legal.mail_ingester_state` + today's metrics, formats per-mailbox table
- `fgp legal mail pause --mailbox <name> [--reason "..."]` — INSERT/UPDATE legal.mail_ingester_pause
- `fgp legal mail resume --mailbox <name>` — DELETE from legal.mail_ingester_pause
- `fgp legal mail poll --mailbox <name> --dry-run` — single-shot connect + fetch up to 5 messages, log intent, **no DB writes, no events**
- `fgp legal mail backfill --mailbox <name> --since <YYYY-MM-DD>` — forward-only backfill. Hard floor 2026-03-26 (LOCKED Q3). Idempotent. **Add `--until <YYYY-MM-DD>` parameter** (5 lines, enables future selective-window recovery — see v1.2 backlog note in §6.4).

### 5.3 Health endpoint (per v1.1 §7)

```
GET /api/internal/legal/mail/health

200 if all mailboxes have last_success_at within (2 × poll_interval_sec)
503 if any mailbox has gone >2 patrol intervals without success
```

Response body per v1.1 §7. Pulls from `legal.mail_ingester_state`.

### 5.4 Tests required

- CLI status format snapshot (golden file)
- pause/resume idempotency
- dry-run does not insert email_archive rows
- backfill `--since` rejects dates < 2026-03-26 (hard floor)
- backfill `--until` accepts and bounds correctly
- health endpoint 200 / 503 logic

### 5.5 Phase 0a-3 exit criteria

- CLI commands callable, tests pass
- Health endpoint responds (locally; not yet wired to Phase 1 dashboard)
- Operator can run `fgp legal mail status` and see all 4 mailboxes in `mail_ingester_state` (will show `last_patrol_at = NULL` since worker not registered — that's correct)

```
git add backend/scripts/legal_mail_ingester_cli.py backend/api/legal_mail_health.py backend/tests/...
git commit -m "FLOS Phase 0a-3: CLI + health endpoint

- fgp legal mail status / pause / resume / poll --dry-run / backfill
- backfill --since hard floor 2026-03-26 (v1.1 LOCKED Q3)
- backfill --until added (5-line addition; enables Phase 0b selective-window recovery)
- GET /api/internal/legal/mail/health (200/503 per v1.1 §7)
- Tests cover CLI commands, hard floor enforcement, health logic

Spec: docs/operational/FLOS-phase-0a-legal-email-ingester-design-v1_1.md"
```

---

## 6. Final steps

### 6.1 Push + PR

```bash
git push -u origin feat/flos-phase-0a-day-1-2026-05-03
gh pr create --base main --head feat/flos-phase-0a-day-1-2026-05-03 \
  --title "FLOS Phase 0a Day 1 — schema + ingester service + CLI/health (LEGAL_MAIL_INGESTER_ENABLED=False default)" \
  --body "$(cat <<'EOF'
## Summary

Day 1 of FLOS Phase 0a v1.1 §11. Three commits, phase-per-commit:

- 0a-1: 5 new tables in `legal` schema, 8 priority_sender_rules seed rows, `email_archive.ingested_from` NOT NULL + format CHECK, bilateral mirror table on fortress_prod (forward-only per v1.1 §10).
- 0a-2: `legal_mail_ingester` service. arq-style task, NOT yet registered with worker. `LEGAL_MAIL_INGESTER_ENABLED=False` default.
- 0a-3: CLI (`fgp legal mail …`) + health endpoint.

## NOT in this PR

- 0a-4 worker registration / cutover
- 0a-5 24h soak
- MAILBOXES_CONFIG `ingester=legal_mail` flips for the 3 legal mailboxes

These land in a separate PR after operator review and after the 2026-05-08 counsel hire window stabilizes.

## Verification

- All schema verification queries from execution brief §3.4 pass
- Test suite green for service + CLI + health
- Frontier health (10.10.10.3:8000) untouched throughout

## Risk

Zero production traffic — service is on disk, not active. PR is reviewable + revertible without affecting any running pipeline.

## Spec

`docs/operational/FLOS-phase-0a-legal-email-ingester-design-v1_1.md` (signed off 2026-05-02 by operator).

## Cross-refs

- ADR (bilateral mirror discipline) — see _architectural-decisions.md ADR-001 *or* corresponding ADR; v1.1 §13 cross-ref to be cleaned up in v1.2
- Issue #177 — IMAP SEARCH overflow defended via banding (v1.1 §3.2)
- Issue #204 — alembic chain divergence; raw psql apply per skip-fortress_shadow rule
- PR #225 — banded SEARCH precedent in email_backfill_legal.py
- PR #228 — phase-per-commit precedent
EOF
)"
```

### 6.2 Operator merges

CC does **not** merge. Surface the PR URL and stop.

### 6.3 Post-merge sanity (operator-driven, optional Sunday afternoon)

```bash
# After operator merges:
ssh admin@spark-2 'cd /home/admin/Fortress-Prime && git pull && fgp legal mail status'
```

Expected: 4 mailboxes listed (the 3 legal-tagged + nothing for info-crog since it's Captain-only). All `last_patrol_at = NULL`, all `consecutive_failures = 0`. That's correct — worker not registered yet.

### 6.4 Backlog note for operator (do not act this Sunday)

`backfill --until` parameter exists. **Phase 0b selective-window backfill** for `gary@garyknight.com` 2025-03-19 → 2025-05-31 is now a one-line invocation post-counsel-hire:

```bash
fgp legal mail backfill --mailbox gary-gk --since 2025-03-19 --until 2025-05-31
```

Hard floor 2026-03-26 prevents this from running today — that's intentional. Lifting the floor for selective historical recovery is a Phase 0b operator decision (not Phase 0a). Track this as v1.2 backlog: "selective-window backfill below 2026-03-26 floor — operator-gated, separate runbook."

---

## 7. Hard stops

Halt + escalate to operator if any of these fire:

1. Frontier health degrades to non-200 sustained >60s during any commit
2. Wave 7 Case II briefing pipeline interferes (other tmux session crashes, fortress-arq-worker restarts unexpectedly)
3. Migration apply fails on fortress_db (do NOT proceed to fortress_prod / fortress_shadow_test)
4. Migration applies on fortress_db but fails on fortress_prod (rollback fortress_db is required — chain-divergence risk)
5. `email_archive.ingested_from` backfill UPDATE affects unexpected row counts (sanity check id range 166582–174961 before applying)
6. Test suite red on any commit
7. PR creation fails (auth, branch protection)
8. Branch contamination detected (local main differs from origin/main at any point)

If a hard stop fires: **stop, do not retry, surface the failure to operator.** Do not roll forward.

---

## 8. Time budget

- Pre-flight: 5 min
- Phase 0a-1 (schema + seed + mirror + verify): 60–90 min
- Phase 0a-2 (service + tests): 120–180 min
- Phase 0a-3 (CLI + health + tests): 60–90 min
- PR creation: 15 min
- **Total: 4–6 hours.**

Sunday master plan has Case II v2→v3 iteration + Wave 5 Evaluator scoring on the same day. **Run this brief first thing Sunday morning** (07:00–13:00 window). Case II Block C (NeMo Evaluator) starts afternoon; FLOS work must be PR-open by then.

---

## 9. Reference

- Spec: `docs/operational/FLOS-phase-0a-legal-email-ingester-design-v1_1.md`
- Master plan: `MASTER-PLAN-case-ii-2026-05-01.md`
- ADRs: `_architectural-decisions.md` (note: v1.1 §13 cross-references need cleanup in v1.2; ADR numbering between FLOS doc and registry is misaligned — flagged for operator)
- Issue #177, Issue #204, PR #225, PR #228 — listed in v1.1 §13

---

**End of brief.** Single PR, three commits, operator merges, no service activation. Ready to paste into fresh Claude Code session in `flos_phase_0a` tmux on spark-2 Sunday 2026-05-03 morning.
