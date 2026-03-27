import { existsSync } from "node:fs";

import { defineConfig, devices } from "@playwright/test";

const FRONTEND_BASE_URL = process.env.E2E_BASE_URL || "http://127.0.0.1:3000";
const QA_STORAGE_STATE_PATH = "playwright/.auth/qa-session.json";
const DEFAULT_STORAGE_STATE = existsSync(QA_STORAGE_STATE_PATH)
  ? QA_STORAGE_STATE_PATH
  : undefined;

export default defineConfig({
  testDir: ".",
  testMatch: ["tests/e2e/**/*.spec.ts"],
  globalSetup: "./playwright/global-setup.ts",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  retries: 1,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: FRONTEND_BASE_URL,
    storageState: DEFAULT_STORAGE_STATE,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
