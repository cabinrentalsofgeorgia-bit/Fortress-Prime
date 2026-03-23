import { expect, type Page } from "@playwright/test";

const DEFAULT_E2E_EMAIL = "cabin.rentals.of.georgia@gmail.com";
const DEFAULT_E2E_PASSWORD = "FortressPrime2026!";

export async function loginAsE2EStaff(page: Page, baseURL: string | undefined): Promise<void> {
  if (!baseURL) {
    throw new Error("Playwright baseURL is required for E2E staff login.");
  }

  const email = process.env.E2E_LOGIN_EMAIL || DEFAULT_E2E_EMAIL;
  const password = process.env.E2E_LOGIN_PASSWORD || DEFAULT_E2E_PASSWORD;

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
