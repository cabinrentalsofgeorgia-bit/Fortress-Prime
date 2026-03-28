import { expect, test } from "@playwright/test";

test.describe("Workforce Matrix glass", () => {
  test("renders the Paperclip iframe on the workforce route", async ({ page }) => {
    await page.addInitScript(() => {
      class MockWebSocket {
        static readonly CONNECTING = 0;
        static readonly OPEN = 1;
        static readonly CLOSING = 2;
        static readonly CLOSED = 3;

        readyState = MockWebSocket.OPEN;
        onopen: ((this: WebSocket, ev: Event) => unknown) | null = null;
        onmessage: ((this: WebSocket, ev: MessageEvent) => unknown) | null = null;
        onclose: ((this: WebSocket, ev: CloseEvent) => unknown) | null = null;
        onerror: ((this: WebSocket, ev: Event) => unknown) | null = null;

        constructor() {
          queueMicrotask(() => {
            this.onopen?.call(this as unknown as WebSocket, new Event("open"));
          });
        }

        close(): void {
          this.readyState = MockWebSocket.CLOSED;
          this.onclose?.call(this as unknown as WebSocket, new Event("close") as CloseEvent);
        }

        send(): void {}

        addEventListener(): void {}

        removeEventListener(): void {}

        dispatchEvent(): boolean {
          return true;
        }
      }

      Object.defineProperty(window, "WebSocket", {
        configurable: true,
        writable: true,
        value: MockWebSocket,
      });
    });

    await page.route("**/api/auth/me", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "staff-1",
          email: "ops@crog-ai.com",
          first_name: "Ops",
          last_name: "Commander",
          role: "manager",
          access_token: "workforce-token",
        }),
      });
    });

    await page.route("**/orchestrator", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<html><body><div id='paperclip-root'>Paperclip control plane online</div></body></html>",
      });
    });

    await page.route("**/orchestrator/**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<html><body><div id='paperclip-root'>Paperclip control plane online</div></body></html>",
      });
    });

    await page.goto("/workforce", { waitUntil: "domcontentloaded" });

    await expect(
      page.getByRole("heading", { name: "Paperclip Control Plane" }),
    ).toBeVisible();
    await expect(page.getByText("Sovereign Workforce Matrix")).toBeVisible();

    const iframe = page.frameLocator('iframe[title="Paperclip Control Plane"]');
    await expect(iframe.locator("#paperclip-root")).toHaveText("Paperclip control plane online");
  });
});
