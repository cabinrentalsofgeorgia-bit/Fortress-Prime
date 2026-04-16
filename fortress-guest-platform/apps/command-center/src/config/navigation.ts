import type { AuthUser } from "@/lib/store";

export type NavItemType = "route" | "action";
export type Role = "super_admin" | "ops_manager" | "legal" | "staff";
export type CommandActionId =
  | "sync-vrs-ledger"
  | "auto-schedule-housekeeping"
  | "dispatch-hunter-target"
  | "switch-defcon-mode";

export interface NavItem {
  label: string;
  href?: string;
  actionId?: CommandActionId;
  type: NavItemType;
  isMono?: boolean;
  allowedRoles: Role[];
}

export interface NavGroup {
  sector: string;
  allowedRoles: Role[];
  items: NavItem[];
}

export interface NavCommandItem extends NavItem {
  sector: string;
}

const ALL_ROLES: Role[] = ["super_admin", "ops_manager", "legal", "staff"];
const OPS_ROLES: Role[] = ["super_admin", "ops_manager", "staff"];
const COMMAND_ROLES: Role[] = ["super_admin", "ops_manager"];
const LEGAL_ROLES: Role[] = ["super_admin", "legal"];

export const commandHierarchy: NavGroup[] = [
  {
    sector: "SHADOW OPS",
    allowedRoles: COMMAND_ROLES,
    items: [
      { label: "Fortress Prime", href: "/command", type: "route", allowedRoles: COMMAND_ROLES },
      { label: "Checkout Parity", href: "/command/checkout-parity", type: "route", allowedRoles: COMMAND_ROLES },
      {
        label: "Iron Dome Ledger",
        href: "/prime",
        type: "route",
        isMono: true,
        allowedRoles: ["super_admin"],
      },
      { label: "System Health", href: "/system-health", type: "route", allowedRoles: COMMAND_ROLES },
      {
        label: "NeMo Command Center",
        href: "/nemo-command-center",
        type: "route",
        isMono: true,
        allowedRoles: ["super_admin"],
      },
      { label: "Admin Ops", href: "/admin", type: "route", allowedRoles: ["super_admin"] },
      {
        label: "Owner Statements",
        href: "/admin/statements",
        type: "route",
        allowedRoles: COMMAND_ROLES,
      },
      {
        label: "Owner Charges",
        href: "/admin/owner-charges",
        type: "route",
        allowedRoles: COMMAND_ROLES,
      },
      {
        label: "Switch DEFCON Mode",
        actionId: "switch-defcon-mode",
        type: "action",
        isMono: true,
        allowedRoles: ["super_admin"],
      },
    ],
  },
  {
    sector: "CROG-VRS",
    allowedRoles: OPS_ROLES,
    items: [
      { label: "Operations Dashboard", href: "/analytics", type: "route", allowedRoles: OPS_ROLES },
      {
        label: "Reservations & Calendar",
        href: "/reservations",
        type: "route",
        allowedRoles: OPS_ROLES,
      },
      { label: "Guest CRM", href: "/guests", type: "route", allowedRoles: OPS_ROLES },
      { label: "Communications", href: "/messages", type: "route", allowedRoles: OPS_ROLES },
      { label: "Property Fleet", href: "/properties", type: "route", allowedRoles: OPS_ROLES },
      { label: "Cabin Profiles", href: "/properties", type: "route", allowedRoles: OPS_ROLES },
      {
        label: "IoT Command",
        href: "/iot",
        type: "route",
        isMono: true,
        allowedRoles: OPS_ROLES,
      },
      { label: "Field Logistics", href: "/work-orders", type: "route", allowedRoles: OPS_ROLES },
      {
        label: "Housekeeping Dispatch",
        href: "/housekeeping",
        type: "route",
        allowedRoles: OPS_ROLES,
      },
      {
        label: "Work Orders & Maintenance",
        href: "/work-orders",
        type: "route",
        allowedRoles: OPS_ROLES,
      },
      {
        label: "Sovereign Treasury",
        href: "/payments",
        type: "route",
        isMono: true,
        allowedRoles: ["super_admin", "ops_manager"],
      },
      {
        label: "Run Housekeeping Auto-Schedule",
        actionId: "auto-schedule-housekeeping",
        type: "action",
        isMono: true,
        allowedRoles: ["super_admin", "ops_manager"],
      },
    ],
  },
  {
    sector: "PAPERCLIP AI",
    allowedRoles: COMMAND_ROLES,
    items: [
      { label: "Adjudication Glass", href: "/vrs", type: "route", allowedRoles: COMMAND_ROLES },
      {
        label: "Reactivation Hunter",
        href: "/vrs/hunter",
        type: "route",
        allowedRoles: COMMAND_ROLES,
      },
      {
        label: "Quotes",
        href: "/vrs/quotes",
        type: "route",
        allowedRoles: COMMAND_ROLES,
      },
      {
        label: "Dispatch Hunter Target",
        actionId: "dispatch-hunter-target",
        type: "action",
        isMono: true,
        allowedRoles: COMMAND_ROLES,
      },
      { label: "Dispatch Radar", href: "/ai-engine", type: "route", allowedRoles: COMMAND_ROLES },
      { label: "Market Canary", href: "/intelligence", type: "route", allowedRoles: COMMAND_ROLES },
      {
        label: "Rule Engine",
        href: "/automations",
        type: "route",
        isMono: true,
        allowedRoles: COMMAND_ROLES,
      },
      {
        label: "Sync Adjudication Ledger",
        actionId: "sync-vrs-ledger",
        type: "action",
        isMono: true,
        allowedRoles: COMMAND_ROLES,
      },
    ],
  },
  {
    sector: "FORTRESS LEGAL",
    allowedRoles: LEGAL_ROLES,
    items: [
      { label: "Active Dockets", href: "/legal", type: "route", allowedRoles: LEGAL_ROLES },
      { label: "E-Discovery Vault", href: "/vault", type: "route", allowedRoles: LEGAL_ROLES },
      { label: "Email Intake", href: "/email-intake", type: "route", allowedRoles: LEGAL_ROLES },
      {
        label: "Agreements & Contracts",
        href: "/agreements",
        type: "route",
        allowedRoles: LEGAL_ROLES,
      },
      { label: "Damage Claims", href: "/damage-claims", type: "route", allowedRoles: LEGAL_ROLES },
    ],
  },
  {
    sector: "STAKEHOLDERS",
    allowedRoles: ["super_admin", "ops_manager"],
    items: [
      {
        label: "Owner Statements",
        href: "/admin/statements",
        type: "route",
        allowedRoles: ["super_admin", "ops_manager"],
      },
      {
        label: "Owner Charges",
        href: "/admin/owner-charges",
        type: "route",
        allowedRoles: ["super_admin", "ops_manager"],
      },
      {
        label: "Growth Deck",
        href: "/analytics/insights",
        type: "route",
        allowedRoles: ["super_admin", "ops_manager"],
      },
    ],
  },
];

export function normalizeRole(role?: string | null): Role {
  switch ((role ?? "").trim().toLowerCase()) {
    case "super_admin":
    case "super-admin":
    case "admin":
      return "super_admin";
    case "ops_manager":
    case "ops-manager":
    case "manager":
      return "ops_manager";
    case "legal":
    case "legal_counsel":
    case "legal-counsel":
    case "counsel":
      return "legal";
    case "staff":
    case "maintenance":
    default:
      return "staff";
  }
}

export function canAccessNav(allowedRoles: Role[], role: Role): boolean {
  return allowedRoles.includes(role);
}

export function getRoleFromUser(user: Pick<AuthUser, "role"> | null | undefined): Role {
  return normalizeRole(user?.role);
}

export function filterCommandHierarchy(roleInput?: Role | string | null): NavGroup[] {
  const role = normalizeRole(roleInput);

  return commandHierarchy.flatMap((group) => {
    if (!canAccessNav(group.allowedRoles, role)) {
      return [];
    }

    const items = group.items.filter((item) => canAccessNav(item.allowedRoles, role));
    if (items.length === 0) {
      return [];
    }

    return [{ ...group, items }];
  });
}

export function flattenCommandHierarchy(groups: NavGroup[]): NavCommandItem[] {
  return groups.flatMap((group) =>
    group.items.map((item) => ({
      ...item,
      sector: group.sector,
    })),
  );
}

export function getNavHref(item: NavItem): string | undefined {
  return item.type === "route" ? item.href : undefined;
}

export function isRouteItem(item: NavItem): boolean {
  return item.type === "route";
}

export function isActionItem(item: NavItem): boolean {
  return item.type === "action";
}

export function getTerminalLabel(label: string): string {
  const letters = label
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .replace(/[^A-Za-z0-9]/g, "")
    .slice(0, 2)
    .toUpperCase();

  return letters || ">>";
}

export function getRoleBadgeLabel(role: Role): string {
  switch (role) {
    case "super_admin":
      return "SUPER_ADMIN";
    case "ops_manager":
      return "OPS_MANAGER";
    case "legal":
      return "LEGAL";
    case "staff":
    default:
      return "STAFF";
  }
}

export { ALL_ROLES };
