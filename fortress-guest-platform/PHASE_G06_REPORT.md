# Phase G.0.6 Report — Documentation Reconciliation
**Date:** 2026-04-15  
**Commit:** `b3ac6120`  
**Branch:** `fix/storefront-quote-light-mode`  
**Type:** Docs-only. No code changes. No migrations. No DB writes.

---

## 1. Files Renamed (with deprecation header added)

| Original | Renamed to | Header prepended? |
|---|---|---|
| `docs/alembic-reconciliation-plan.md` | `docs/alembic-reconciliation-plan.deprecated-2026-04-15.md` | Yes |
| `docs/alembic-prod-rollout-runbook.md` | `docs/alembic-prod-rollout-runbook.deprecated-2026-04-15.md` | Yes |

**Note on sequencing:** `docs/alembic-reconciliation-report.md` was not renamed before the
audit script ran. The audit script overwrote the old report in-place. The old report's
content is no longer on disk. It was still readable in the G.0.5 session context at the
time of this phase. No claim in any new document depends on the old report's content.

---

## 2. Files Newly Written

| File | Purpose |
|---|---|
| `docs/owner-statements-migration-map.md` | Verbatim DDL for all 11 Phase A-F revisions; per-table column lists; indexes; constraints; cross-table summary; audit script limitation note |
| `docs/g0_6_verification.log` | 10 verified claims; sequencing note; open questions |

---

## 3. Files Updated (summary of changes)

### `docs/alembic-reconciliation-report.md`
Regenerated from scratch by `backend/scripts/audit_alembic_reconciliation.py`
against fortress_shadow. Added required header block documenting: generation
timestamp, live alembic version (`e6a1b2c3d4f5`), and the parser limitation note
explaining why Phase A-F revisions show as `no_op` (raw SQL not detected by the
lightweight regex parser).

New audit summary: 39 present, 2 missing (`str_signals`, `channex_webhook_events`),
1 partial (`b6f0a2c4d8e1` acquisition tables), 24 no-op. All 7 original watchlist
tables now present. Phase A-F tables added to watchlist section.

### `docs/alembic-reconciliation-plan.md`
Complete rewrite. Seven sections replacing the deprecated pre-Phase-A-F plan:
1. Current state — live alembic heads (both DBs), DB routing, single-head confirmation
2. Two-database model — fortress_shadow vs fortress_guest summary with row counts
3. Phase A-F additions table — 11 revisions mapped to what they add
4. Watchlist tables — all 11 present; 3 non-statement tables still missing
5. Known issues — test data contamination, conftest isolation gap, auth gap in admin_statements.py
6. Operator guidance — safe upgrade procedure, migration-per-DB policy
7. Recommended next phase — pointer to SYSTEM_ORIENTATION.md §11

### `docs/permission-matrix.md`
Added new section "Owner Statements (Phase A-F additions — 2026-04-15)" with a
15-row table covering all endpoints, frontend helpers, backend routes, auth
dependencies, parity status, and notes. Includes source verification (grep output)
and explicit documentation of the known auth gap on `GET /api/v1/admin/statements/{owner_id}`.

### `docs/api-surface-auth-classification.md`
Added Phase A-F endpoint group to the "Staff-Role Protected" bullet list:
- `/api/admin/payouts/statements/*` — 9 endpoints — `require_manager_or_admin`
- `/api/admin/payouts/charges/*` — 5 endpoints — `require_manager_or_admin`
- `/api/v1/admin/statements/{owner_id}` — 1 endpoint — JWT-only (noted as gap)

Added §5 to "Residual Ambiguities" section documenting the `admin_statements.py`
JWT-only gap with recommended fix and scope of impact.

### `docs/privileged-surface-checklist.md`
Added "Phase A-F Owner Statement Endpoints" section with a per-endpoint checklist
table showing router-level auth, route-level role, and audit write status for all
15 endpoints. Includes three follow-up items: add role dep to admin_statements.py,
add audit writes to lifecycle transitions, add route auth tests.

---

## 4. Verification Results (from docs/g0_6_verification.log)

All 10 concrete claims independently re-verified against the live system:

| Claim | Result |
|---|---|
| fortress_shadow alembic head = `e6a1b2c3d4f5` | **CONFIRMED** — `alembic current` output |
| fortress_guest alembic head = `c4a8f1e2b9d0` | **CONFIRMED** — direct SQL query |
| `settings.database_url` → fortress_shadow | **CONFIRMED** — code read verbatim |
| All 11 watchlist tables present | **CONFIRMED** — 11 rows returned |
| Row counts match (17692, 1261, 311, 55, 401) | **CONFIRMED** — exact match |
| Test data counts (1047, 92, 17492, 200) | **CONFIRMED** — exact match |
| All 9 Phase A-F columns present | **CONFIRMED** — all returned count=1 |
| `properties.city` present (e6a1 migration proxy) | **CONFIRMED** |
| Auth guards on 3 route files | **CONFIRMED** — read verbatim |
| 15-endpoint count (9+5+1) | **CONFIRMED** — grep output |

No discrepancies found. All docs match live reality.

---

## 5. Open Questions / "Needs Gary Decision" Items

1. **fortress_guest long-term plan.** All new docs flag that fortress_guest holds
   2,665 real historical reservations not available to fortress_shadow's statement
   computation. Gary needs to decide: wind-down, archive, or migrate? This affects
   statement accuracy for historical periods.

2. **Auth gap: `GET /api/v1/admin/statements/{owner_id}`.** Documented in three docs.
   Fix is one line (`dependencies=[Depends(require_manager_or_admin)]` in
   `backend/api/admin_statements.py` line 34). Requires Gary's approval to change code.

3. **Conftest isolation.** Test suite writes permanently to fortress_shadow. Documented
   as a G.1.5 task. Needs Gary to confirm the preferred fix: transactional rollback
   wrapper, or separate `fortress_test` database.

4. **Missing tables `str_signals` and `channex_webhook_events`.** Revisions
   `d3a7c1b9e4f2` and `f4c2b7d9e1a0` are in the Alembic graph but their tables
   don't exist. Not statement-related; documented in plan §4. No action recommended
   in this phase.

5. **Audit writes on approve/void/mark-paid.** The checklist audit identified that
   three lifecycle-changing endpoints do not call `record_audit_event(...)`. These
   change financial state (transitioning statement status). Gary should decide if
   audit trail writes are required before G.2.

---

## 6. Confidence Rating Per Document

| Document | Confidence | Basis |
|---|---|---|
| `alembic-reconciliation-plan.md` | **VERY HIGH** | Every claim backed by live query or verbatim code; independently re-verified |
| `alembic-reconciliation-report.md` | **HIGH** | Machine-generated; parser has known limitation for raw-SQL migrations (documented) |
| `owner-statements-migration-map.md` | **VERY HIGH** | Migration files read verbatim; every table/column listed from actual DDL |
| `permission-matrix.md` additions | **VERY HIGH** | Auth guards verified by reading source files; routes verified by grep |
| `api-surface-auth-classification.md` additions | **VERY HIGH** | Same sourcing as permission matrix |
| `privileged-surface-checklist.md` additions | **HIGH** | Per-endpoint audit done; audit write gap is an observation, not a verified absence (no comprehensive grep for all audit calls) |
| `g0_6_verification.log` | **CERTAIN** | Contains the actual query output |

---

**STOPPED. Awaiting Gary's review of commit `b3ac6120` and this report.**  
**Do not begin G.1.5.**
