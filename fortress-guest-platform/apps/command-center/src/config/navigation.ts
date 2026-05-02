type CommandRole = "operator" | "manager" | "admin" | "legal";

type StaffLike = {
  role?: string | null;
  is_superuser?: boolean | null;
} | null | undefined;

type NavBase = {
  label: string;
  roles?: CommandRole[];
  isMono?: boolean;
};

export type NavRouteItem = NavBase & {
  type: "route";
  href: string;
  actionId?: undefined;
};

export type NavActionItem = NavBase & {
  type: "action";
  href?: undefined;
  actionId: "sync-vrs-ledger" | "auto-schedule-housekeeping" | "dispatch-hunter-target" | "switch-defcon-mode";
};

export type NavCommandItem = (NavRouteItem | NavActionItem) & {
  sector?: string;
  value?: string;
};

export type NavSection = {
  sector: string;
  items: NavCommandItem[];
};

const OPS_ROLES: CommandRole[] = ["operator", "manager", "admin"];
const CONTROL_ROLES: CommandRole[] = ["manager", "admin"];
const LEGAL_ROLES: CommandRole[] = ["legal", "admin"];

const COMMAND_HIERARCHY: NavSection[] = [
  {
    sector: "CROG-VRS",
    items: [
      { type: "route", label: "Operations Dashboard", href: "/analytics", roles: OPS_ROLES },
      { type: "route", label: "Reservations & Calendar", href: "/reservations", roles: OPS_ROLES },
      { type: "route", label: "Guest CRM", href: "/guests", roles: OPS_ROLES },
      { type: "route", label: "Communications", href: "/messages", roles: OPS_ROLES },
      { type: "route", label: "Housekeeping Dispatch", href: "/housekeeping", roles: OPS_ROLES },
      { type: "route", label: "Properties", href: "/properties", roles: OPS_ROLES },
      { type: "route", label: "Work Orders", href: "/work-orders", roles: OPS_ROLES },
      { type: "route", label: "Payments", href: "/payments", roles: CONTROL_ROLES },
      { type: "route", label: "Damage Claims", href: "/damage-claims", roles: CONTROL_ROLES },
    ],
  },
  {
    sector: "Revenue",
    items: [
      { type: "route", label: "VRS Hunter", href: "/vrs/hunter", roles: CONTROL_ROLES },
      { type: "route", label: "VRS Leads", href: "/vrs/leads", roles: CONTROL_ROLES },
      { type: "route", label: "Quote Parity", href: "/command/checkout-parity", roles: CONTROL_ROLES },
      { type: "route", label: "Yield Authority", href: "/command/yield", roles: CONTROL_ROLES },
      { type: "action", label: "Dispatch Hunter Target", actionId: "dispatch-hunter-target", roles: CONTROL_ROLES },
      { type: "action", label: "Sync Adjudication Ledger", actionId: "sync-vrs-ledger", roles: CONTROL_ROLES },
      { type: "action", label: "Auto Schedule Housekeeping", actionId: "auto-schedule-housekeeping", roles: CONTROL_ROLES },
    ],
  },
  {
    sector: "Financial",
    items: [
      { type: "route", label: "Hedge Fund Signals", href: "/financial/hedge-fund", roles: CONTROL_ROLES },
    ],
  },
  {
    sector: "Growth",
    items: [
      { type: "route", label: "SEO Review", href: "/seo-review", roles: CONTROL_ROLES },
      { type: "route", label: "SEO Copilot", href: "/growth/seo-copilot", roles: CONTROL_ROLES },
      { type: "route", label: "Redirect Remaps", href: "/growth/redirect-remaps", roles: CONTROL_ROLES },
      { type: "route", label: "SEM Telemetry", href: "/growth/sem-telemetry", roles: CONTROL_ROLES },
    ],
  },
  {
    sector: "Fortress Legal",
    items: [
      { type: "route", label: "Active Dockets", href: "/legal", roles: LEGAL_ROLES },
      { type: "route", label: "E-Discovery Vault", href: "/vault", roles: LEGAL_ROLES },
      { type: "route", label: "Legal Council", href: "/legal/council", roles: LEGAL_ROLES },
      { type: "route", label: "Legal Email Intake", href: "/legal/email-intake", roles: LEGAL_ROLES },
    ],
  },
  {
    sector: "Command",
    items: [
      { type: "route", label: "System Health", href: "/system-health", roles: CONTROL_ROLES },
      { type: "route", label: "Sovereign Pulse", href: "/command/sovereign-pulse", roles: CONTROL_ROLES },
      { type: "route", label: "Iron Dome Ledger", href: "/trust-review", roles: ["admin"] },
      { type: "route", label: "Nemo Command Center", href: "/nemo-command-center", roles: ["admin"] },
      { type: "action", label: "Switch DEFCON Mode", actionId: "switch-defcon-mode", roles: ["admin"] },
    ],
  },
];

export function getRoleFromUser(user: StaffLike): CommandRole {
  if (user?.is_superuser) return "admin";
  const role = String(user?.role || "").toLowerCase();
  if (role.includes("admin") || role.includes("owner")) return "admin";
  if (role.includes("legal") || role.includes("counsel")) return "legal";
  if (role.includes("manager")) return "manager";
  return "operator";
}

export function getRoleBadgeLabel(role: CommandRole): string {
  switch (role) {
    case "admin":
      return "Administrator";
    case "legal":
      return "Legal";
    case "manager":
      return "Manager";
    default:
      return "Operator";
  }
}

export function getTerminalLabel(label: string): string {
  const words = label.match(/[A-Za-z0-9]+/g) ?? [];
  if (words.length === 0) return label.slice(0, 3).toUpperCase();
  if (words.length === 1) return words[0].slice(0, 3).toUpperCase();
  return words.slice(0, 3).map((word) => word[0]).join("").toUpperCase();
}

export function isRouteItem(item: NavCommandItem): item is NavRouteItem {
  return item.type === "route";
}

export function getNavHref(item: NavCommandItem): string | undefined {
  return item.type === "route" ? item.href : undefined;
}

function canSee(item: NavCommandItem, role: CommandRole): boolean {
  return !item.roles || item.roles.includes(role);
}

export function filterCommandHierarchy(role: CommandRole): NavSection[] {
  return COMMAND_HIERARCHY.map((section) => ({
    ...section,
    items: section.items.filter((item) => canSee(item, role)),
  })).filter((section) => section.items.length > 0);
}
