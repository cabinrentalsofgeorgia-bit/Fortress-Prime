import { isStaffHost } from "./domain-boundaries";

export type AppMode = "storefront" | "command_center";

const DEFAULT_APP_MODE: AppMode = "storefront";

export function getAppMode(): AppMode {
  const rawSiteType = process.env.NEXT_PUBLIC_SITE_TYPE?.trim().toLowerCase();
  if (rawSiteType === "sovereign_glass") {
    return "command_center";
  }

  const rawMode = process.env.APP_MODE?.trim().toLowerCase();
  if (rawMode === "command_center") {
    return "command_center";
  }
  return DEFAULT_APP_MODE;
}

export function isCommandCenterApp(): boolean {
  return getAppMode() === "command_center";
}

/**
 * Command Center UX: env-based build config OR staff hostname (e.g. crog-ai.com).
 * Use on the server with the incoming Host / X-Forwarded-Host header.
 */
export function isCommandCenterExperience(host: string | null | undefined): boolean {
  if (isCommandCenterApp()) return true;
  return isStaffHost(host);
}
