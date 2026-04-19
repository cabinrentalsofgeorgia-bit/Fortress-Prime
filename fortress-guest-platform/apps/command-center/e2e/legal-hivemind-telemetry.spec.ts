import { expect, test } from "@playwright/test";
import { loginAsE2EStaff } from "./helpers/auth";

test.describe("Hive Mind telemetry editor", { tag: "@integration" }, () => {
  test.use({ storageState: undefined });

  test("syncs counsel edits and shows telemetry pulse", async ({ page, baseURL }) => {
    test.setTimeout(240_000);

    const caseSlug = process.env.E2E_CASE_SLUG || "fish-trap-suv2026000013";

    await loginAsE2EStaff(page, baseURL);

    // PRECISION MOCK: Route by strict pathname, completely ignoring query strings.
    await page.route(`**/api/legal/cases/${caseSlug}**`, async (route) => {
      const requestUrl = new URL(route.request().url());

      // Let the specific Hive Mind mocks below own their dedicated requests.
      if (
        requestUrl.pathname.includes("/discovery/draft-pack") ||
        requestUrl.pathname.includes("/feedback/telemetry") ||
        requestUrl.pathname.includes("/sanctions/alerts")
      ) {
        await route.fallback();
        return;
      }

      // Exact match for the base case shell, tolerant of query params and trailing slash.
      if (
        requestUrl.pathname === `/api/legal/cases/${caseSlug}` ||
        requestUrl.pathname === `/api/legal/cases/${caseSlug}/`
      ) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            case: {
              id: 123,
              case_slug: caseSlug,
              case_number: "CI-2026-001",
              case_name: "CI Deterministic Case",
              court: "Fortress Prime Superior Court",
              judge: "Halcyon",
              case_type: "civil",
              our_role: "plaintiff",
              risk_score: 4,
              extraction_status: "complete",
              critical_date: "2026-04-01",
              critical_note: "CI mock critical date",
              notes: "Synthetic case payload for deterministic legal shell rendering.",
              our_claim_basis: "Contract and negligence",
              days_remaining: 9,
            },
            deadlines: [],
            recent_actions: [],
            evidence: [],
          }),
        });
        return;
      }

      // Swallow other case-scoped widget requests so shell rendering stays deterministic.
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          nodes: [],
          edges: [],
          packs: [],
          count: 0,
          latest_pack: null,
          alerts: [],
          total: 0,
          kill_sheets: [],
          items: [],
          status: "mocked",
        }),
      });
    });

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

    await page.route(/\/api\/legal\/cases\/[^/]+\/feedback\/telemetry$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "ok",
          synced: true,
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
