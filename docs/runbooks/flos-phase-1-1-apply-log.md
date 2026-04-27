# FLOS Phase 1-1 — apply log

**Migration:** `r3c4d5e6f7g8` (revises `q2b3c4d5e6f7` / Phase 0a-1)
**Applied:** 2026-04-27
**Pattern:** Issue #204 multi-row `alembic_version` (Path A — append-only revision rows; one row per applied revision per DB)
**Per:** `docs/architecture/cross-division/FLOS-phase-1-state-store-design-v1.1.md` (LOCKED v1.1, all Q1–Q5 closed)

## Apply sequence

| step | DB | apply | result |
|---|---|---|---|
| 1 | `fortress_shadow_test` | atomic `BEGIN…COMMIT` via `flos-phase-1-1-apply.sql` | ✅ COMMIT — 5 CREATE TABLE, 6 CREATE INDEX, INSERT 0 6 (dispatcher_routes seed), INSERT 0 1 (alembic_version) |
| 2 | `fortress_db` | same SQL | ✅ COMMIT — same DDL output |
| 3 | `fortress_prod` | same SQL | ✅ COMMIT — same DDL output |

`fortress_shadow` skipped — out of Phase 1-1 scope.

## Verification (V1–V8) — all 3 DBs

| check | spec | shadow_test | fortress_db | fortress_prod |
|---|---|---|---|---|
| **V1** | 5 new tables present in `legal.*` | ✅ 5 | ✅ 5 | ✅ 5 |
| **V2** | `dispatcher_routes`: 4 enabled, 2 disabled | ✅ TRUE=4, FALSE=2 | ✅ TRUE=4, FALSE=2 | ✅ TRUE=4, FALSE=2 |
| **V3** | All 6 event_types seeded correctly | ✅ | ✅ | ✅ |
| **V4a** | Bad `procedural_phase` blocked | ✅ rolled back | ✅ rolled back | ✅ rolled back |
| **V4b** | Bad `theory_of_defense_state` blocked | ✅ rolled back | ✅ rolled back | ✅ rolled back |
| **V4c** | Bad `leverage_score=2.5` blocked | ✅ rolled back | ✅ rolled back | ✅ rolled back |
| **V5** | Bad `outcome` blocked | ✅ rolled back | ✅ rolled back | ✅ rolled back |
| **V6** | FKs `case_posture` → `legal.event_log` (×2) | ✅ | ✅ | ✅ |
| **V6b** | FK `dispatcher_event_attempts` → `legal.event_log` | ✅ | ✅ | ✅ |
| **V6c** | FK `dispatcher_dead_letter` → `legal.event_log` | ✅ | ✅ | ✅ |
| **V7** | `alembic_version` contains `r3c4d5e6f7g8` (multi-row) | ✅ q2b3…+r3c4… | ✅ q2b3…+r3c4… | ✅ q2b3…+r3c4… |
| **V8** | 11 indexes total (5 PK + 6 explicit) | ✅ 11 | ✅ 11 | ✅ 11 |

## Bilateral parity (fortress_db ↔ fortress_prod)

| table | fortress_db | fortress_prod |
|---|---|---|
| `case_posture` | 0 | 0 |
| `dispatcher_dead_letter` | 0 | 0 |
| `dispatcher_event_attempts` | 0 | 0 |
| `dispatcher_pause` | 0 | 0 |
| `dispatcher_routes` | **6** | **6** |

Schema-layer parity holds. Row-count parity holds. Phase 1 dispatcher (when it ships in Phase 1-2/1-3) will be the only writer to `case_posture`, `dispatcher_event_attempts`, `dispatcher_dead_letter` per design Principle 1 + Principle 7.

## Per-DB DDL output (Step 1, fortress_shadow_test)

```
BEGIN
DO
CREATE TABLE
CREATE INDEX
CREATE TABLE
CREATE TABLE
CREATE INDEX
CREATE INDEX
CREATE INDEX
CREATE TABLE
CREATE INDEX
CREATE INDEX
CREATE TABLE
INSERT 0 6
INSERT 0 1
COMMIT
```

Step 2 (fortress_db) and Step 3 (fortress_prod) produced identical output.

## Cross-references

- Migration file: `backend/alembic/versions/r3c4d5e6f7g8_flos_phase_1_1_state_store_dispatcher_schema.py`
- Apply SQL: `docs/runbooks/flos-phase-1-1-apply.sql`
- Design (LOCKED): `docs/architecture/cross-division/FLOS-phase-1-state-store-design-v1.1.md`
- Predecessor (review history): `docs/architecture/cross-division/FLOS-phase-1-state-store-design.md`
- Phase 0a-1 (event_log producer schema): `q2b3c4d5e6f7`
- Issue #204 — alembic chain divergence (multi-row alembic_version pattern)
- ADR-001 — bilateral mirror discipline (forward-only, ratified)

## Next gates

- **Phase 1-2** worker skeleton (default OFF) — gates on this PR merge
- **Phase 1-3** initial event handlers — gates on 1-2 merge
- **Phase 1-4** CLI + health endpoint — gates on 1-3 merge
- **Phase 1-5** cutover (operator-explicit) — gates on 1-4 merge
- **Phase 1-6** 24h soak validation — gates on 1-5 cutover
