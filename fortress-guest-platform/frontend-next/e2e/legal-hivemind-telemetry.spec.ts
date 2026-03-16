import { expect, test } from "@playwright/test";

test.describe("Hive Mind telemetry editor", () => {
  test.use({ storageState: undefined });

  test("syncs counsel edits and shows telemetry pulse", async ({ page, baseURL }) => {
    test.setTimeout(240_000);

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

    await page.goto(`${baseURL}/legal/cases/${caseSlug}`, {
      waitUntil: "domcontentloaded",
    });

    await page.getByRole("tab", { name: /vanguard/i }).click();

    await page.route(/\/api\/legal\/cases\/[^/]+\/discovery\/draft-pack$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          proportionality_cap_used: 1,
          item_limit: 1,
          items: [
            {
              category: "interrogatory",
              target_entity: "Opposing Party",
              content: "Swarm draft text for Rule 26 interrogatory.",
              relevance_score: 0.93,
              justification: "Mocked draft item for deterministic Hive Mind telemetry test.",
            },
          ],
        }),
      });
    });

    await page.getByRole("button", { name: /generate draft/i }).click();

    const editor = page.locator('textarea').first();
    await expect(editor).toBeVisible({ timeout: 30_000 });
    await editor.fill("Counsel revised version approved for filing. [E2E]");

    const telemetryResponsePromise = page.waitForResponse(
      (res) =>
        res.request().method() === "POST" &&
        /\/api\/legal\/cases\/[^/]+\/feedback\/telemetry$/.test(res.url()),
      { timeout: 60_000 },
    );

    await page.getByRole("button", { name: /approve & file/i }).first().click();
    const telemetryResponse = await telemetryResponsePromise;
    expect(telemetryResponse.status()).toBe(200);
    await expect(page.getByText("[TELEMETRY SYNCED TO HIVE MIND]")).toBeVisible({ timeout: 15_000 });
  });
});
