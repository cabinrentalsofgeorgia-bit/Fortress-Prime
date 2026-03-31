import { expect, test } from "@playwright/test";

test.describe("Legal Discovery Arsenal", () => {
  test.use({ storageState: undefined });

  test("generates a discovery draft pack for a live case", async ({ page, baseURL }) => {
    test.setTimeout(180_000);

    const email = process.env.E2E_LOGIN_EMAIL || "vrs.operator+live@crog-ai.com";
    const password = process.env.E2E_LOGIN_PASSWORD || "Fortress!2026Reset#";
    const caseSlug = process.env.E2E_CASE_SLUG || "legal-fortress-mvp";

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

    const generateResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response
          .url()
          .includes(`/api/internal/legal/cases/${caseSlug}/discovery/draft-pack`) &&
        response.status() === 200,
      { timeout: 150_000 },
    );

    await page.goto(`${baseURL}/legal/cases/${caseSlug}`, {
      waitUntil: "domcontentloaded",
    });

    await expect(page.getByRole("heading", { name: /legal fortress mvp/i })).toBeVisible();
    await page.getByRole("tab", { name: /vanguard/i }).click();
    await expect(page.getByText("Discovery Arsenal")).toBeVisible();

    await page.getByRole("button", { name: /generate new draft pack/i }).click();

    const generateResponse = await generateResponsePromise;
    const payload = await generateResponse.json().catch(() => ({}));
    const generatedCount = Number(payload?.items_generated ?? 0);

    expect(generatedCount).toBeGreaterThan(0);

    await expect(page.getByText("No discovery draft items available yet.")).toHaveCount(0);
    await expect(page.getByText(/Lethality:/).first()).toBeVisible();
  });
});
