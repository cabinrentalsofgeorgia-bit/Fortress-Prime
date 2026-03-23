import { expect, type Page } from "@playwright/test";

const DEFAULT_E2E_EMAIL = "cabin.rentals.of.georgia@gmail.com";
const DEFAULT_E2E_PASSWORD = "FortressPrime2026!";

type LoginResponse = {
  access_token: string;
  user?: Record<string, unknown>;
};

export async function loginAsE2EStaff(page: Page, baseURL: string | undefined): Promise<void> {
  if (!baseURL) {
    throw new Error("Playwright baseURL is required for E2E staff login.");
  }
  const email = process.env.E2E_LOGIN_EMAIL || DEFAULT_E2E_EMAIL;
  const password = process.env.E2E_LOGIN_PASSWORD || DEFAULT_E2E_PASSWORD;

  const loginResponse = await page.request.post(`${baseURL}/api/auth/login`, {
    data: { email, password },
    headers: { "Content-Type": "application/json" },
  });

  expect(loginResponse.status()).toBe(200);

  const loginJson = (await loginResponse.json()) as LoginResponse;
  expect(loginJson).toHaveProperty("access_token");

  await page.context().addCookies([
    {
      name: "fortress_session",
      value: loginJson.access_token,
      url: baseURL,
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    },
  ]);

  await page.goto(baseURL, { waitUntil: "domcontentloaded" });
  await page.evaluate(({ token, user }) => {
    localStorage.setItem("fgp_token", token as string);
    if (user) {
      localStorage.setItem("fgp_user", JSON.stringify(user));
    }
  }, { token: loginJson.access_token, user: loginJson.user ?? null });

  await page.addInitScript(({ token, user }) => {
    localStorage.setItem("fgp_token", token as string);
    if (user) {
      localStorage.setItem("fgp_user", JSON.stringify(user));
    }
  }, { token: loginJson.access_token, user: loginJson.user ?? null });
}
