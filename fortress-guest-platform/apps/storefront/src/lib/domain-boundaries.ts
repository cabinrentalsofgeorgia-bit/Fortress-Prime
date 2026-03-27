const STOREFRONT_HOSTS = new Set([
  "cabin-rentals-of-georgia.com",
  "www.cabin-rentals-of-georgia.com",
]);

/**
 * Storefront app: staff / Zone B hostnames are not recognized here by design.
 * Command Center runs from `apps/command-center` on the DGX.
 */
export function staffHostsForServerActions(): string[] {
  return [];
}

function normalizeHost(host: string | null | undefined): string {
  return (host ?? "").trim().toLowerCase().split(":")[0] ?? "";
}

export function isStorefrontHost(host: string | null | undefined): boolean {
  const normalizedHost = normalizeHost(host);
  return normalizedHost.length > 0 && STOREFRONT_HOSTS.has(normalizedHost);
}

export function isStaffHost(_host: string | null | undefined): boolean {
  return false;
}
