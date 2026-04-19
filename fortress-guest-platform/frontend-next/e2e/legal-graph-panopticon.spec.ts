import { expect, test } from "@playwright/test";

test.describe("Legal Graph Panopticon", { tag: "@integration" }, () => {
  test.use({ storageState: undefined });

  test("renders graph radar for live case snapshot", async ({ page, baseURL }) => {
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

    const graphResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        response
          .url()
          .includes(`/api/internal/legal/cases/${caseSlug}/graph/snapshot`) &&
        response.status() === 200,
      { timeout: 120_000 },
    );

    await page.goto(`${baseURL}/legal/cases/${caseSlug}`, {
      waitUntil: "domcontentloaded",
    });

    await expect(page.getByRole("heading", { name: /legal fortress mvp/i })).toBeVisible();
    await expect(page.getByText("Graph Radar")).toBeVisible();

    const graphResponse = await graphResponsePromise;
    const graphPayload = await graphResponse.json().catch(() => ({}));
    const nodes = Array.isArray(graphPayload?.nodes) ? graphPayload.nodes : [];

    expect(nodes.length).toBeGreaterThan(0);

    const entityLabel = nodes.length === 1 ? "Entity" : "Entities";
    await expect(page.getByText(`${nodes.length} Entities Mapped`, { exact: false })).toBeVisible();
    await expect(page.getByText(`Graph Synced: ${nodes.length} ${entityLabel}`)).toBeVisible();
  });
});
