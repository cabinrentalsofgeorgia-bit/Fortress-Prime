# Phase G.0.8 Report — Repository State Reconciliation
**Date:** 2026-04-15  
**Branch:** `feature/owner-statements-and-stabilization` (created from `fix/storefront-quote-light-mode` at `ea987812`)

---

## 1. Snapshot Reference

Safety snapshot taken before this phase:  
`~/fortress-snapshot-20260415_091137.tar.gz` (1.4 GB)

If anything needs to be rolled back, restore from this tarball.

---

## 2. Branch Created

```
git checkout -b feature/owner-statements-and-stabilization
```
Created from HEAD `ea987812` (Phase G.1.5 commit).  
No stash needed — `git checkout -b` carries working tree state cleanly.

---

## 3. Classification Summary

| Bucket | Description | Count | Action |
|---|---|---|---|
| A | Phase A-F backend (new files) | ~50 files | Committed in 7 logical chunks |
| B | G.0.x reports + scripts (new files) | 23 files | Committed in 1 chunk |
| C | Pre-existing modifications (M files) + unrelated untracked | ~90 M files + many ?? | Left untouched |
| D | Junk (one-off scripts, env backups) | 17 patterns | Added to .gitignore |
| E | Parent-dir items (`/home/admin/Fortress-Prime/`) | ~20+ | Gary decision |

Full classification details: `PHASE_G08_CLASSIFICATION.md`

---

## 4. Commits Made

| Commit | Message | Files |
|---|---|---|
| `858bec8e` | phase G.0.7: fix auth gap on GET /api/v1/admin/statements | 3 (already staged from G.0.7) |
| `9abe2165` | phase A: owner ledger foundation | 8 |
| `522cc998` | phase B: revenue math fixes | 2 |
| `0ddcf474` | phase C: owner charges | 4 |
| `c0230260` | phase D: statement workflow and APIs | 5 |
| `4095c84a` | phase E: PDF rendering, addresses, parity | 15 |
| `4453c689` | phase F: monthly cron jobs and email send | 2 |
| `f00f4fd8` | phase A-F: supporting tests, fixtures, admin payouts | 29 |
| `e7bd524d` | docs: phase A-F and G.0.x discovery reports | 23 |
| `30df5f8b` | gitignore: exclude one-off fix scripts and env backups | 1 |

**Total new commits on this branch:** 10 (including G.0.7 which was previously only staged)  
**Total files committed:** ~92 new files

---

## 5. .gitignore Additions

```
# Phase G.0.8: one-off fix/sync scripts (not production code)
/check_duplicates.py
/force_sync_schema.py
/genesis_backfill.py
/live_fire_test.py
/patch_final_columns.py
/backend/fix_missing_tables.py
/backend/fix_missing_tables_v2.py
/backend/robust_fix.py
/backend/sync_db.py
/backend/sync_db_all.py
/scripts/cancel_native_test_reservations.py
/scripts/e2e_sovereign_ledger_test.py
/scripts/trigger_reconcile_revenue.py

# Env backups and secrets
/.env.backup
/.env.production.local
/.env.telemetry_backup
/.vercelignore
```

Verification: all 17 patterns correctly removed from `git status --short` output.

---

## 6. Bucket C Files Left Untouched

These are modified tracked files (M) that remain in the working tree unchanged. They belong to separate efforts and must not be mixed into the owner-statement commits.

**~90 modified tracked files across:**
- `apps/command-center/src/` (25+ files) — pre-existing CC UI work
- `apps/storefront/src/` (6+ files) — pre-existing storefront work
- `backend/api/` (13 files) — API modifications with mixed concerns
- `backend/core/` (2 files) — core modifications
- `backend/integrations/` (3 files) — integration modifications
- `backend/main.py` — includes Phase A-F router mounts mixed with other work
- `backend/models/__init__.py` (and 9 other model files) — mixed modifications
- `backend/requirements.txt` — mixed new dependencies
- `backend/services/` (14 files) — service modifications
- `backend/tests/` (4 modified test files) — pre-existing test modifications
- `backend/vrs/` (2 files), `backend/workers/event_consumer.py`
- `deploy/systemd/` (2 files), `run.py`
- Config/build: `.cursorrules`, `.env.example`, `apps/*/next.config.ts`, etc.

**Critical note on `backend/main.py`:** It contains the `app.include_router(...)` calls that mount the Phase A-F routers. This file is classified as Bucket C (too mixed to commit in isolation) meaning the committed router files are not yet registered in the git-tracked version of main.py. This is an imperfect but acceptable state for retroactive history — the files exist and the production server has main.py already wired correctly.

**Many unrelated untracked files (new, not committed):**
- ~25 non-Phase-A-F alembic migrations
- New frontend pages (admin/payouts/, acquisition/, etc.)
- New backend agents, APIs, models unrelated to statements
- These should be committed separately in a future cleanup phase

---

## 7. Bucket E — Parent Directory Items (Gary Decision)

Items in `/home/admin/Fortress-Prime/` (the git root) that are outside `fortress-guest-platform/`:

| Item | Status | Recommended action |
|---|---|---|
| `config.py` (M) | Modified tracked file | Review and commit with parent-dir work |
| `.defcon_state` | Runtime state file | Add to parent `.gitignore` |
| `.env.bak_*` | Env backups | Add to parent `.gitignore` |
| `.litellm.env*` | LiteLLM config | Add to parent `.gitignore` if not needed |
| `CLAUDE.md` | Project instructions | Commit to parent repo |
| `cabin-rentals-of-georgia/` | Separate project | Separate repo or commit |
| `deploy/systemd/fortress-nightly-finetune.*` | New systemd units | Commit to parent repo |
| `personas/legal/seat*.json` (D status — DELETED) | Deleted tracked files | Commit the deletions |
| `tools/`, `src/daemons/` | Python tooling | Commit to parent repo |

**None of these were touched in this phase.**

---

## 8. Verification — Bucket A and B Work Fully Committed

Verified by:
```bash
git status --short | grep "^??" | grep -E "owner_balance_period|statement_workflow|admin_statements|PHASE_[A-F]|SYSTEM_ORIENTATION"
# Result: empty — all Phase A-F and report files are committed
```

Also verified:
- `git log --oneline -15` shows all 10 expected commits
- Bucket C M-files still show as ` M` (untouched)
- Bucket D patterns now absent from `git status --short` (gitignored)

---

## 9. Confidence Rating

| Item | Confidence |
|---|---|
| All Phase A-F files committed | **VERY HIGH** — verified by empty grep result |
| All report files committed | **VERY HIGH** — verified |
| Bucket C untouched | **CERTAIN** — no git add on any M file |
| Bucket D gitignored | **CERTAIN** — verified by git status output |
| No sensitive data committed | **HIGH** — only .py, .md, .sql files; no .env values |
| main.py / models/__init__.py not committed (correct) | **CERTAIN** — these were intentionally left as M |

---

## 10. Recommended Next Phase

**G.1.6 — Execute the fortress_shadow cleanup (COMMIT form)**

The foundation is now stable:
- All Phase A-F backend work is committed and traceable
- The G.1.5 cleanup script is in git (as ROLLBACK form)
- The classification is documented

G.1.6 steps:
1. Gary reviews `backend/scripts/g1_5_real_data_review.md` (all tables marked DELETE ALL — zero real rows)
2. Run backup: `bash backend/scripts/g1_5_backup_fortress_shadow.sh`
3. Edit `g1_5_cleanup_fortress_shadow.sql` — replace `ROLLBACK` with `COMMIT`
4. Execute: `psql "postgresql://fortress_admin:fortress@127.0.0.1:5432/fortress_shadow" -f backend/scripts/g1_5_cleanup_fortress_shadow.sql`
5. Verify post-counts (all 5 tables = 0 rows)
6. Then proceed to G.2 (admin statement workflow UI)
