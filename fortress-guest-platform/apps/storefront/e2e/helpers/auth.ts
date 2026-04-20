import { expect, type Page } from "@playwright/test";

export async function loginAsE2EStaff(page: Page, baseURL: string | undefined): Promise<void> {
  if (!baseURL) {
    throw new Error("Playwright baseURL is required for E2E staff login.");
  }

  const email = process.env.E2E_LOGIN_EMAIL;
  const password = process.env.FORTRESS_SMOKE_PASSWORD ?? process.env.E2E_LOGIN_PASSWORD;
  if (!email || !password) {
    throw new Error(
      "E2E_LOGIN_EMAIL and FORTRESS_SMOKE_PASSWORD (or E2E_LOGIN_PASSWORD) must be set. " +
      "See docs/OPERATIONS.md.",
    );
  }

  page.on("console", (msg) => console.log(`[PLAYWRIGHT BROWSER]: ${msg.text()}`));
  page.on("pageerror", (error) => console.log(`[PLAYWRIGHT CRASH]: ${error.message}`));
  page.on("response", (response) => {
    if (response.status() === 401) {
      console.log(
        `[PLAYWRIGHT 401 TRACE]: ${response.request().method()} ${response.url()}`,
      );
    }
  });

  await page.goto(`${baseURL}/login`, { waitUntil: "domcontentloaded" });

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);

  const loginResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/api/auth/login") &&
      response.status() === 200,
    { timeout: 30_000 },
  );

  await page.getByRole("button", { name: /sign in/i }).click();

  const loginResponse = await loginResponsePromise;
  expect(loginResponse.status()).toBe(200);

  await page.waitForURL((url) => !url.pathname.startsWith("/login"), {
    timeout: 30_000,
  });
}
