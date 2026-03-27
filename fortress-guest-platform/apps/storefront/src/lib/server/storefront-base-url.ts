import "server-only";

const DEFAULT_STOREFRONT_BASE_URL = "https://cabin-rentals-of-georgia.com";

export function getStorefrontBaseUrl(): string {
  const appUrl = process.env.NEXT_PUBLIC_APP_URL?.trim();
  if (appUrl) {
    return appUrl.replace(/\/$/, "");
  }

  return DEFAULT_STOREFRONT_BASE_URL;
}
