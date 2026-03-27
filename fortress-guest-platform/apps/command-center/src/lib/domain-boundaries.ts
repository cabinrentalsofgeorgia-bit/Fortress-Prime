const STOREFRONT_HOSTS = new Set([
  "cabin-rentals-of-georgia.com",
  "www.cabin-rentals-of-georgia.com",
]);

/** Staff Command Center hostnames (Zone B). */
const DEFAULT_STAFF_HOSTS = ["crog-ai.com", "www.crog-ai.com"] as const;

let cachedStaffHosts: ReadonlySet<string> | null = null;

function staffHostSet(): ReadonlySet<string> {
  if (cachedStaffHosts) {
    return cachedStaffHosts;
  }
  const extras = (process.env.NEXT_PUBLIC_STAFF_HOSTS ?? "")
    .split(",")
    .map((h) => h.trim().toLowerCase().split(":")[0])
    .filter((h) => h.length > 0);
  cachedStaffHosts = new Set<string>([...DEFAULT_STAFF_HOSTS, ...extras]);
  return cachedStaffHosts;
}

/** Hostnames for `experimental.serverActions.allowedOrigins` (build-time; keep in sync with staff detection). */
export function staffHostsForServerActions(): string[] {
  return [...staffHostSet()];
}

function normalizeHost(host: string | null | undefined): string {
  return (host ?? "").trim().toLowerCase().split(":")[0] ?? "";
}

export function isStorefrontHost(host: string | null | undefined): boolean {
  const normalizedHost = normalizeHost(host);
  return normalizedHost.length > 0 && STOREFRONT_HOSTS.has(normalizedHost);
}

/**
 * True when the HTTP Host is the internal staff / Command Center domain.
 * Does not include localhost — use APP_MODE / NEXT_PUBLIC_SITE_TYPE for local dev.
 */
export function isStaffHost(host: string | null | undefined): boolean {
  const normalizedHost = normalizeHost(host);
  return normalizedHost.length > 0 && staffHostSet().has(normalizedHost);
}
