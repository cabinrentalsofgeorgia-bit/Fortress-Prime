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

    // PRECISION MOCK: Route by strict pathname, completely ignoring query strings.
    await page.route(`**/api/legal/cases/${caseSlug}**`, async (route) => {
      const requestUrl = new URL(route.request().url());

      // Let the specific sanctions alert mock above own its dedicated request.
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
