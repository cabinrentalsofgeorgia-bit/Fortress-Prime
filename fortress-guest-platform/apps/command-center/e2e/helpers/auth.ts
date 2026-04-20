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

  const loginResponse = await page.request.post(`${baseURL}/api/auth/login`, {
    data: { email, password },
    headers: { "Content-Type": "application/json" },
  });
  expect(loginResponse.status()).toBe(200);

  const loginJson = await loginResponse.json();
  expect(loginJson).toHaveProperty("access_token");

  await page.addInitScript((token) => {
    localStorage.setItem("fgp_token", token as string);
  }, loginJson.access_token);
}
