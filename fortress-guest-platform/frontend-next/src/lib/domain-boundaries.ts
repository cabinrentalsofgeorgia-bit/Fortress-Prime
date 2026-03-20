const STOREFRONT_HOSTS = new Set([
  "cabin-rentals-of-georgia.com",
  "www.cabin-rentals-of-georgia.com",
]);

function normalizeHost(host: string | null | undefined): string {
  return (host ?? "").trim().toLowerCase().split(":")[0] ?? "";
}

export function isStorefrontHost(host: string | null | undefined): boolean {
  const normalizedHost = normalizeHost(host);
  return normalizedHost.length > 0 && STOREFRONT_HOSTS.has(normalizedHost);
}
