export type AppMode = "storefront" | "command_center";

/**
 * Storefront-only deployment: this binary never serves the Command Center.
 */
export function getAppMode(): AppMode {
  return "storefront";
}

export function isCommandCenterApp(): boolean {
  return false;
}

export function isCommandCenterExperience(_host: string | null | undefined): boolean {
  return false;
}
