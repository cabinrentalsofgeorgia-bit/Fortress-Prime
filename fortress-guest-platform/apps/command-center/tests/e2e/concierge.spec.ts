import { expect, test } from "@playwright/test";

const CABIN_SLUG = "aska-escape-lodge";

test.describe("Sovereign concierge", { tag: "@integration" }, () => {
  test.use({ storageState: undefined });

  test("answers a cabin-specific guest question through the live RAG path", async ({ page }) => {
    test.setTimeout(180_000);

    await page.goto(`/cabins/${CABIN_SLUG}`, { waitUntil: "domcontentloaded" });

    const conciergeWidget = page.getByTestId("sovereign-concierge-widget");
    await expect(conciergeWidget).toBeVisible();
    await expect(conciergeWidget.getByText(/ask the cabin concierge/i)).toBeVisible();

    const agentMessages = page.getByTestId("concierge-agent-message");
    await expect(agentMessages.first()).toContainText(/verified knowledge base/i);

    const input = page.getByTestId("concierge-input");
    await input.fill("Does this cabin have wifi?");

    await page.getByTestId("concierge-submit").click();

    await expect(page.getByTestId("concierge-user-message").last()).toContainText(
      "Does this cabin have wifi?",
    );

    const loadingState = page.getByTestId("concierge-loading");
    await expect(loadingState).toBeVisible({ timeout: 15_000 });
    await expect(loadingState).toBeHidden({ timeout: 30_000 });

    await expect(agentMessages).toHaveCount(2, { timeout: 30_000 });

    const finalAgentMessage = agentMessages.last();
    await expect(finalAgentMessage).not.toContainText(/verified knowledge base/i);
    await expect(finalAgentMessage).not.toContainText(/temporarily offline/i);
    await expect(finalAgentMessage).not.toContainText(/returned an empty response/i);
    await expect(finalAgentMessage).toContainText(/\S+/, { timeout: 30_000 });
  });
});
