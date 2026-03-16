import type { FullConfig } from "@playwright/test";

export default async function globalSetup(_config: FullConfig): Promise<void> {
  // Intentionally empty: tests can provide their own auth flow.
}
