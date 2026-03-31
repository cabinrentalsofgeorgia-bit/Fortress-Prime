import { expect, type Page } from "@playwright/test";

const DEFAULT_E2E_EMAIL = "cabin.rentals.of.georgia@gmail.com";
const DEFAULT_E2E_PASSWORD = "FortressPrime2026!";

export async function loginAsE2EStaff(page: Page, baseURL: string | undefined): Promise<void> {
  if (!baseURL) {
    throw new Error("Playwright baseURL is required for E2E staff login.");
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

  const email = process.env.E2E_LOGIN_EMAIL || DEFAULT_E2E_EMAIL;
  const password = process.env.E2E_LOGIN_PASSWORD || DEFAULT_E2E_PASSWORD;

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
