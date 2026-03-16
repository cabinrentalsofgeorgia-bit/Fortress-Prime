import { expect, test } from "@playwright/test";

test.describe("Sanctions Tripwire Panel", () => {
  test.use({ storageState: undefined });

  test("renders tripwire header and pre-computed alerts", async ({ page, baseURL }) => {
    test.setTimeout(180_000);

    const email = process.env.E2E_LOGIN_EMAIL || "vrs.operator+live@crog-ai.com";
    const password = process.env.E2E_LOGIN_PASSWORD || "Fortress!2026Reset#";
    const caseSlug = process.env.E2E_CASE_SLUG || "fish-trap-suv2026000013";

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

    const alertsResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        response
          .url()
          .includes(`/api/legal/cases/${caseSlug}/sanctions/alerts`) &&
        response.status() === 200,
      { timeout: 120_000 },
    );

    await page.goto(`${baseURL}/legal/cases/${caseSlug}`, {
      waitUntil: "domcontentloaded",
    });

    await page.getByRole("tab", { name: /vanguard/i }).click();

    const alertsResponse = await alertsResponsePromise;
    const alertsPayload = await alertsResponse.json().catch(() => ({}));
    const alerts = Array.isArray(alertsPayload?.alerts) ? alertsPayload.alerts : [];
    expect(alerts.length).toBeGreaterThanOrEqual(2);

    await expect(page.getByText("Sanctions Tripwire")).toBeVisible();

    const contradictionSections = page.locator("text=Detected Contradiction");
    await expect(contradictionSections).toHaveCount(alerts.length);
    await expect(contradictionSections).toHaveCount(3);
  });
});
