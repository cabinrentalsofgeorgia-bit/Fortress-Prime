# Phase G.0.7 Report — Auth Gap Fix: GET /api/v1/admin/statements/{owner_id}
**Date:** 2026-04-15  
**Commit:** Staged only — Gary must commit manually.  
**Scope:** One route handler change + one new test file. No other files modified.

---

## 1. The Fix

### File changed
`backend/api/admin_statements.py`

### Before / After diff

**Before (lines 25–35):**
```python
from backend.core.database import get_db
from backend.models.property import Property
from backend.services.statement_computation import (
    StatementComputationError,
    StatementResult,
    compute_owner_statement,
)

logger = structlog.get_logger(service="owner_statements")
router = APIRouter()
```

**After (lines 25–36):**
```python
from backend.core.database import get_db
from backend.core.security import require_manager_or_admin
from backend.models.property import Property
from backend.services.statement_computation import (
    StatementComputationError,
    StatementResult,
    compute_owner_statement,
)

logger = structlog.get_logger(service="owner_statements")
router = APIRouter(dependencies=[Depends(require_manager_or_admin)])
```

**Two lines changed:**
1. Added `from backend.core.security import require_manager_or_admin` (line 26, new import)
2. Changed `router = APIRouter()` → `router = APIRouter(dependencies=[Depends(require_manager_or_admin)])` (line 35)

`Depends` was already imported from `fastapi` on line 20 — no change needed there.

### Why router-level (not route-level)

`admin_statements_workflow.py` line 53 uses the identical pattern:
```python
router = APIRouter(dependencies=[Depends(require_manager_or_admin)])
```

Router-level is consistent, future-proof (any additional routes added to this file inherit the guard automatically), and matches the established convention for all other statement endpoints.

### What `require_manager_or_admin` enforces (from `backend/core/security.py` lines 273–281)

```python
async def require_manager_or_admin(
    user: StaffUser = Depends(get_current_user),
) -> StaffUser:
    if user.role not in ("super_admin", "admin", "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager, admin, or super admin access required",
        )
    return user
```

- Allowed: `super_admin`, `admin`, `manager`
- Blocked (403): `staff`, `reviewer`, `operator`, any unrecognized role
- No credentials: 401 (from `get_current_user` before role check runs)

---

## 2. The Test

### File
`backend/tests/test_phase_g07_admin_statements_auth.py`

### Pattern
`FastAPI()` test app + `app.dependency_overrides[get_current_user]` — matching `test_route_authorization.py` exactly. No JWT keys, no real DB, no fixtures.

### Test cases

| Test | Setup | Expected | Result |
|---|---|---|---|
| `test_no_auth_header_returns_401` | No `get_current_user` override; no Authorization header | 401 | **PASSED** |
| `test_staff_role_returns_403` | `get_current_user` → `role="staff"` | 403 | **PASSED** |
| `test_manager_role_passes_auth` | `get_current_user` → `role="manager"` | 200 or 404 (not 403) | **PASSED** (returned 404) |
| `test_super_admin_role_passes_auth` | `get_current_user` → `role="super_admin"` | 200 or 404 (not 403) | **PASSED** (returned 404) |

The 404 in tests 3 and 4 comes from `get_owner_statement` finding no active properties for "nonexistent-owner-99999" — proving auth passed and the handler executed.

### Full pytest output

```
collected 4 items

test_phase_g07_admin_statements_auth.py::test_no_auth_header_returns_401  PASSED [ 25%]
test_phase_g07_admin_statements_auth.py::test_staff_role_returns_403       PASSED [ 50%]
test_phase_g07_admin_statements_auth.py::test_manager_role_passes_auth     PASSED [ 75%]
test_phase_g07_admin_statements_auth.py::test_super_admin_role_passes_auth PASSED [100%]

4 passed, 17 warnings in 0.29s
```

Warnings are pre-existing Pydantic v2 deprecation notices in `statement_computation.py`. Unrelated to this change.

---

## 3. Smoke Check

Collection run on all Phase D-F statement test files to confirm the import chain is unbroken after the `admin_statements.py` change:

```bash
pytest --collect-only \
  backend/tests/test_phase_d_statement_workflow.py \
  backend/tests/test_phase_e_pdf.py \
  backend/tests/test_phase_e5_parity.py \
  backend/tests/test_phase_e51_hygiene.py \
  backend/tests/test_phase_f_cron.py
```

Result: **99 tests collected in 0.10s — zero collection errors.**

---

## 4. Confidence Rating

| Item | Confidence |
|---|---|
| The fix closes the auth gap | **CERTAIN** — `require_manager_or_admin` now on router; test 2 confirms 403 for blocked role |
| The fix is non-breaking for allowed roles | **CERTAIN** — tests 3 and 4 confirm 200/404 for manager and super_admin |
| No regression in Phase D-F tests | **HIGH** — 99 tests collect cleanly; the change only adds a dependency |
| Pattern consistency with sibling file | **CERTAIN** — router-level Depends, identical to admin_statements_workflow.py:53 |

---

## 5. Files Modified

| File | Change |
|---|---|
| `backend/api/admin_statements.py` | Added `require_manager_or_admin` import and router-level dependency |
| `backend/tests/test_phase_g07_admin_statements_auth.py` | New — 4 auth regression tests |
| `PHASE_G07_REPORT.md` | New — this report |

**No other files were modified.** `conftest.py` was not touched — no new helpers were needed. The `SimpleNamespace`/`dependency_overrides` pattern used in `test_route_authorization.py` was reused directly.

---

## Cross-reference: docs updated in G.0.6

The G.0.6 documentation pass (`b3ac6120`) documented this gap in three places:
- `docs/permission-matrix.md` — "GAP — JWT only" note in the Phase A-F table
- `docs/api-surface-auth-classification.md` — §5 "Owner Statement Computation Endpoint — JWT-Only"
- `docs/privileged-surface-checklist.md` — follow-up item #1

All three documents should be updated in a follow-up to mark the gap as **resolved**.
