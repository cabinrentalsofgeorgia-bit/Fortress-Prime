# FLOS Phase 0a-1 — Apply Log

**Migration:** `q2b3c4d5e6f7_flos_phase_0a_1_legal_mail_ingester_schema.py`
**Down revision:** `o0a1b2c3d4e5`
**Apply date:** 2026-04-27
**Branch:** `feat/flos-phase-0a-1-schema`
**Design ref:** [FLOS-phase-0a-legal-email-ingester-design-v1.1.md](../architecture/cross-division/FLOS-phase-0a-legal-email-ingester-design-v1.1.md)

Apply via raw psql per Issue #204 chain divergence pattern (matches PR #228 Phase A.1 precedent). Atomic transaction (BEGIN ... COMMIT). Each DB applied separately with explicit operator authorization between steps.

## Apply sequence

| step | DB | order | rationale |
|---|---|---|---|
| 1 | `fortress_shadow_test` | first | smallest blast radius; no email_archive table → tests `DO $$ IF EXISTS $$` graceful skip |
| 2 | `fortress_db` | second | primary DB; substantive backfill of 42,396 rows |
| 3 | `fortress_prod` | third | mirror DB; verifies bilateral parity (ADR-001) |
| — | `fortress_shadow` | **skipped** | per Issue #204 chain divergence |

## Per-step verification (7 sub-conditions each)

### Step 1 — `fortress_shadow_test`

| check | result |
|---|---|
| 5 new tables present | ✅ event_log, mail_ingester_metrics, mail_ingester_pause, mail_ingester_state, priority_sender_rules |
| 8 seed rows in priority_sender_rules (P1=7, P2=1) | ✅ |
| email_archive backfill | N/A — table doesn't exist on shadow_test (DO block correctly skipped) |
| NOT NULL enforced | N/A (no email_archive) |
| CHECK constraint exists | N/A (no email_archive) |
| Bad-format insert blocked | N/A (no email_archive) |
| alembic_version INSERT'd (was empty) | ✅ → `q2b3c4d5e6f7` |

### Step 2 — `fortress_db` (primary)

| check | result |
|---|---|
| 5 new tables present | ✅ |
| 8 seed rows (P1=7, P2=1) | ✅ |
| `legacy_imap_producer:unknown` count | ✅ **35,804** (exact match to expected) |
| `historical:unknown` count | ✅ **6,592** (exact match to expected) |
| NULL ingested_from count | ✅ **0** |
| Total rows | ✅ 42,396 (matches pre-migration) |
| NOT NULL enforced — INSERT NULL blocked | ✅ |
| CHECK constraint exists with regex `^[a-z_]+:[a-z0-9_.-]+$` | ✅ |
| Bad-format insert blocked | ✅ rejected `'BadFormat With Spaces'` |
| alembic_version UPDATE'd | ✅ `7a1b2c3d4e5f` → `q2b3c4d5e6f7` |

### Step 3 — `fortress_prod` (mirror)

| check | result |
|---|---|
| 5 new tables present | ✅ |
| 8 seed rows (P1=7, P2=1) | ✅ |
| `legacy_imap_producer:unknown` count | **35,580** (fortress_prod-specific) |
| `historical:unknown` count | **6,592** (matches fortress_db — Maildir scrape was bilateral) |
| NULL ingested_from count | ✅ **0** |
| Total rows | ✅ 42,172 (matches pre-migration) |
| NOT NULL enforced — INSERT NULL blocked | ✅ |
| CHECK constraint exists with expected pattern | ✅ |
| Bad-format insert blocked | ✅ |
| alembic_version UPDATE'd | ✅ `d4e5f6a7b8c9` → `q2b3c4d5e6f7` |

## Bilateral parity check

| metric | fortress_db | fortress_prod | parity |
|---|---:|---:|---|
| seed rows in priority_sender_rules | 8 | 8 | ✅ |
| alembic_version | q2b3c4d5e6f7 | q2b3c4d5e6f7 | ✅ |
| `historical:unknown` count | 6,592 | 6,592 | ✅ exact |
| `legacy_imap_producer:unknown` count | 35,804 | 35,580 | Δ=224 (known split-brain) |
| total email_archive rows | 42,396 | 42,172 | Δ=224 (matches above delta) |

## Notable findings

- **Maildir-scraped historical rows are bilaterally identical** (6,592 each side). Those producers were apparently dual-write at the time.
- **The legacy `imap://` producer was split-brain** — fortress_db has 224 more rows than fortress_prod for that population. This Δ predates Phase 0a; not addressed by this migration.
- **Historical bulk-mirror is intentionally NOT performed** in Phase 0a-1 per design v1.1 §10. Forward-only mirror discipline applies; new ingester writes will be bilaterally consistent. Operator may authorize a separate Phase 0a-1b sub-task if historical reconciliation is desired.

## Test-INSERT side-effect note

The two failed test inserts during V4 + V6 verification consumed sequence ids on each DB (PG advances sequence on attempt regardless of outcome). No actual rows were inserted — both failed at constraint check before commit. Sequence advance is acceptable side-effect of verification design; not a data integrity issue.

| DB | sequence ids consumed by failed tests |
|---|---|
| fortress_db | 174962, 174963 |
| fortress_prod | 174738, 174739 |

## All 3 DBs aligned post-apply

```
fortress_db:           q2b3c4d5e6f7
fortress_prod:         q2b3c4d5e6f7
fortress_shadow_test:  q2b3c4d5e6f7
fortress_shadow:       (skipped per Issue #204)
```

## Cross-references

- [FLOS-phase-0a-legal-email-ingester-design-v1.1.md](../architecture/cross-division/FLOS-phase-0a-legal-email-ingester-design-v1.1.md) — design source
- [FLOS-design-v1.md](../architecture/cross-division/FLOS-design-v1.md) — parent strategic doc
- ADR-001 — bilateral mirror discipline (this migration honors)
- Issue #204 — alembic chain divergence (apply pattern follows)
- Issue #177 — IMAP SEARCH overflow (the bug Phase 0a-2 ingester will defend against)
- PR #228 / Phase A.1 — phase-per-commit migration discipline precedent
- [flos-phase-0a-1-apply.sql](./flos-phase-0a-1-apply.sql) — exact SQL applied
