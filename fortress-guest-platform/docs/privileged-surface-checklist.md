# Privileged Surface Checklist

Use this checklist whenever you add or change a privileged route, mutation, export,
stream, or UI control in the Fortress Guest Platform.

This is the operational follow-through for `docs/permission-matrix.md`.

See also `docs/api-surface-auth-classification.md` for the current route-level
classification of public, webhook, M2M, and staff-protected API surfaces.

## Goal

Every privileged surface should be aligned across:

- backend authorization
- frontend capability helpers
- UI affordances
- tests
- docs

## Backend Checklist

1. Pick the correct backend dependency.
   Use `require_admin` for admin-only financial/owner/staff actions.
   Use `require_manager_or_admin` for manager-grade operational actions.
   Use `require_operator_manager_admin` only for read-only or broad operator visibility when intentional.

2. Add the dependency explicitly to the route signature.
   Do not rely only on global JWT middleware for sensitive actions.

3. Normalize `super_admin` expectations.
   If the route is intended to allow `super_admin`, verify the dependency already does.

4. Audit sensitive actions.
   If the action changes state, sends communications, retries delivery, exports data, or triggers background work, consider `record_audit_event(...)`.

5. Keep route groups consistent.
   If one route in a mutation family is manager/admin-gated, sibling mutators should usually match.

## Frontend Checklist

1. Never hardcode raw role arrays in page components.
   Add or reuse a named helper from `frontend-next/src/lib/roles.ts`.

2. Prefer semantic capability names.
   Good: `canManageHunter`, `canManagePayments`, `canManageLegalOps`
   Avoid: `hasRequiredRole(user, ["admin", "manager"])` directly inside pages

3. Use the shared affordance wrapper.
   Wrap privileged controls with `RoleGatedAction` from `src/components/access/role-gated-action.tsx`.

4. Support read-only inspection when appropriate.
   When a page is intentionally viewable by lower roles, disable only the privileged controls and show a view-only indicator.

5. Mirror backend route semantics.
   If the backend is manager/admin, the frontend helper should describe the same capability unless the UI is intentionally stricter.

## Testing Checklist

1. Add or update route authorization tests.
   Use `backend/tests/test_route_authorization.py` for representative dependency coverage.

2. Add focused endpoint tests when behavior changed.
   Especially for dispatch, retry, export, bulk actions, and audit writes.

3. Keep compile or lint confidence for touched files.
   Run the smallest meaningful verification for the changed area.

## Documentation Checklist

1. Update `docs/permission-matrix.md` if capability scope changed.

2. If you add a new named helper in `roles.ts`, document:
   the intended surface,
   allowed frontend roles,
   backend dependency it should mirror,
   whether the helper is exact parity or UI hardening.

3. If a known mismatch remains, document it explicitly.
   Do not leave parity gaps implicit.

## Decision Guide

### Use `require_admin` / admin capability when:

- changing money movement or trust accounting
- owner onboarding or owner-facing financial controls
- dispute operations
- staff administration
- contract dispatch/generation

### Use `require_manager_or_admin` / manager capability when:

- sending or retrying outbound guest communications
- charging cards
- running legal extraction/council/sanctions/deposition workflows
- viewing high-sensitivity live telemetry

### Use broad operator visibility when:

- the surface is informational
- lower roles need to inspect but not mutate
- the page intentionally supports view-only operational awareness

## Anti-Patterns

- Adding a new privileged button without `RoleGatedAction`
- Adding a new privileged route without an explicit dependency
- Introducing a new raw role array in a page instead of a named helper
- Treating docs as optional after changing capability behavior
- Allowing frontend and backend role models to drift silently
