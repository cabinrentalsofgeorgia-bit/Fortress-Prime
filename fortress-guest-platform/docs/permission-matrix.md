# Permission Matrix

This document maps the frontend capability helpers in `frontend-next/src/lib/roles.ts`
to the current backend authorization posture.

See also `docs/privileged-surface-checklist.md` for the implementation checklist
to use when adding new privileged routes or controls.

It exists for two reasons:

1. Keep frontend gating aligned with backend enforcement where possible.
2. Make intentional UI hardening visible when a sensitive page is stricter in the UI than the current API route implementation.

## Role Sets

| Helper Set | Roles |
|---|---|
| `ADMIN_ROLES` | `super_admin`, `admin` |
| `MANAGER_ROLES` | `super_admin`, `admin`, `manager` |
| `OPERATOR_VIEW_ROLES` | `super_admin`, `admin`, `manager`, `reviewer`, `operator` |

## Capability Map

| Frontend Helper | Intended Surface | Frontend Roles | Backend Reference | Parity Status | Notes |
|---|---|---|---|---|---|
| `canViewHunter()` | Hunter read-only visibility | `super_admin`, `admin`, `manager`, `reviewer`, `operator` | `require_operator_manager_admin` | Aligned | Used for view-only inspection of targets, queue state, telemetry, and audit history. |
| `canManageHunter()` | Hunter dispatch/review/retry/export | `super_admin`, `admin`, `manager` | `require_manager_or_admin` on Hunter mutators | Aligned | Backend helper now treats `super_admin` as elevated. |
| `canManageStaff()` | Settings staff management | `super_admin`, `admin` | `require_admin` on auth/invite routes | Aligned | Backend `require_admin` now accepts `super_admin` and `admin`. |
| `canManageAdminOps()` | Fleet/admin financial controls | `super_admin`, `admin` | `/api/admin/*` critical mutation/finance routes use `require_admin` | Mostly aligned | Main admin finance surfaces are now backend-guarded; continue tightening any residual JWT-only admin endpoints discovered later. |
| `canManageContracts()` | Contract generation/dispatch | `super_admin`, `admin` | Contract/admin surfaces are intended admin-only | Mostly aligned | Uses `canManageAdminOps()`; frontend contract controls are now capability-gated. |
| `canManageDisputes()` | Dispute evidence + resubmission controls | `super_admin`, `admin` | `require_admin` on dispute APIs | Aligned | Frontend dispute actions now use the same capability gate. |
| `canViewPrimeTelemetry()` | Prime live telemetry stream | `super_admin`, `admin`, `manager` | `/api/admin/prime/stream` and `/api/admin/prime/snapshot` use `require_manager_or_admin` | Aligned | Frontend and backend now share the same manager+ visibility model. |
| `canManagePayments()` | Virtual terminal charge actions | `super_admin`, `admin`, `manager` | `require_manager_or_admin` in payments API | Aligned | Frontend payment controls are capability-gated and backend-enforced. |
| `canManageLegalOps()` | Legal extraction, council, war-room, sanctions controls | `super_admin`, `admin`, `manager` | Key legal mutation/export routes now use `require_manager_or_admin` | Mostly aligned | Major legal controls are frontend-gated and backend-enforced; continue extending route-level dependencies to any remaining case mutation endpoints as they are surfaced. |

## Current Frontend Usage

These helpers currently gate the following dashboard areas:

- `canViewHunter()`
  - Reserved for Hunter visibility semantics.

- `canManageHunter()`
  - `vrs/hunter` dispatch, approve, edit, reject, retry, export, bulk actions.

- `canManageStaff()`
  - `settings` staff management and invitations.

- `canManageAdminOps()`
  - `admin` fleet operations, onboarding, CapEx controls.

- `canManageContracts()`
  - `admin/components/ContractManagementPanel`.

- `canManageDisputes()`
  - `admin/components/DisputeExceptionDesk`.

- `canViewPrimeTelemetry()`
  - `prime` live telemetry SSE connection and operator UX.

- `canManagePayments()`
  - `payments` virtual terminal charge flow.

- `canManageLegalOps()`
  - `legal/council`
  - `legal/cases/[slug]/_components/case-detail-shell`
  - `legal/cases/[slug]/_components/evidence-upload`
  - `legal/cases/[slug]/_components/document-viewer`
  - `legal/cases/[slug]/_components/sanctions-tripwire-panel`
  - `legal/cases/[slug]/_components/hitl-deadline-queue`
  - `legal/cases/[slug]/_components/extraction-panel`
  - `legal/cases/[slug]/_components/counsel-threat-matrix`
  - `legal/cases/[slug]/_components/deposition-war-room`

## Important Parity Notes

### 1. `super_admin` handling is now normalized in core elevated dependencies

The shared backend helpers now treat `super_admin` as elevated for:

- `require_admin`
- `require_manager_or_admin`

This closes the most obvious parity gap with the frontend helper sets.

### 2. Some admin/legal surfaces may still be UI-hardened before full API hardening

Most operator-facing privileged actions covered by the current frontend helpers are now
explicitly guarded in FastAPI as well.

Continue treating the matrix as the source of truth and tighten any newly discovered
JWT-only admin/legal endpoints to the matching backend dependency.

### 3. Preferred migration direction

For long-term parity:

1. Pick canonical backend dependencies per domain.
2. Keep frontend helpers as thin mirrors of those backend capabilities.
3. Continue replacing raw role arrays in UI with named helpers only.
4. Extend route authorization tests whenever a new privileged route is added.
