import { expect, test } from "@playwright/test";
import { loginAsE2EStaff } from "./helpers/auth";

test.describe("Sanctions Tripwire Panel", () => {
  test.use({ storageState: undefined });

  test("renders tripwire header and pre-computed alerts", async ({ page, baseURL }) => {
    test.setTimeout(180_000);

    const caseSlug = process.env.E2E_CASE_SLUG || "fish-trap-suv2026000013";

    await loginAsE2EStaff(page, baseURL);

    await page.route(/\/api\/legal\/cases\/[^/]+\/sanctions\/alerts$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          alerts: [
            {
              title: "Detected Contradiction",
              contradiction: "Timeline mismatch between maintenance dispatch and incident statement.",
            },
            {
              title: "Detected Contradiction",
              contradiction: "Guest contact log conflicts with claimed notice window.",
            },
            {
              title: "Detected Contradiction",
              contradiction: "Photographic evidence sequence diverges from filing chronology.",
            },
          ],
        }),
      });
    });

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
