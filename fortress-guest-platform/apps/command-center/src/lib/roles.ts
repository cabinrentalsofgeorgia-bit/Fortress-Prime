"use client";

/**
 * Frontend capability helpers.
 *
 * These helpers serve two purposes:
 * 1. Mirror backend auth dependencies where the API already enforces roles.
 * 2. Provide stricter UI hardening on sensitive surfaces that are currently only
 *    JWT-protected server-side, so lower-privilege users are kept in view-only mode.
 *
 * See `docs/permission-matrix.md` for the current frontend/backend parity map.
 * See `docs/privileged-surface-checklist.md` for the contributor workflow when
 * introducing new privileged routes or controls.
 */
export type RoleLike = { role?: string | null } | null | undefined;

export const ADMIN_ROLES = ["super_admin", "admin"] as const;
export const MANAGER_ROLES = ["super_admin", "admin", "manager"] as const;
export const OPERATOR_VIEW_ROLES = [
  "super_admin",
  "admin",
  "manager",
  "reviewer",
  "operator",
] as const;

export function hasRequiredRole(user: RoleLike, allowedRoles: string[]): boolean {
  const role = (user?.role || "").trim();
  return role !== "" && allowedRoles.includes(role);
}

export function canManageHunter(user: RoleLike): boolean {
  // Mirrors the Hunter backend's manager/admin operational guard.
  return hasRequiredRole(user, [...MANAGER_ROLES]);
}

export function canViewHunter(user: RoleLike): boolean {
  // Mirrors the Hunter backend's operator/reviewer/manager/admin visibility guard.
  return hasRequiredRole(user, [...OPERATOR_VIEW_ROLES]);
}

export function canManageStaff(user: RoleLike): boolean {
  // UI hardening for staff administration.
  return hasRequiredRole(user, [...ADMIN_ROLES]);
}

export function canManageAdminOps(user: RoleLike): boolean {
  // UI hardening for financial/owner operations.
  return hasRequiredRole(user, [...ADMIN_ROLES]);
}

export function canManageContracts(user: RoleLike): boolean {
  // UI hardening for contract generation/dispatch.
  return canManageAdminOps(user);
}

export function canManageDisputes(user: RoleLike): boolean {
  // UI hardening for dispute evidence and resubmission controls.
  return canManageAdminOps(user);
}

export function canViewPrimeTelemetry(user: RoleLike): boolean {
  // UI hardening: Prime telemetry is treated as manager+ visibility in the dashboard.
  return hasRequiredRole(user, [...MANAGER_ROLES]);
}

export function canManagePayments(user: RoleLike): boolean {
  // Mirrors payment endpoints that require manager/admin for charge operations.
  return hasRequiredRole(user, [...MANAGER_ROLES]);
}

export function canManageLegalOps(user: RoleLike): boolean {
  // UI hardening for counsel/extraction/war-room mutation controls.
  return hasRequiredRole(user, [...MANAGER_ROLES]);
}
