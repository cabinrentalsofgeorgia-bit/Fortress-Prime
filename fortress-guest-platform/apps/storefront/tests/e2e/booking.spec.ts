import { expect, test, type APIRequestContext } from "@playwright/test";

const CABIN_SLUG = "aska-escape-lodge";
const BACKEND_URL = process.env.E2E_BACKEND_URL || process.env.FGP_BACKEND_URL || "http://127.0.0.1:8100";
const SEARCH_GUESTS = 2;
const SEARCH_START_OFFSET_DAYS = 14;
const NIGHT_COUNT = 3;

type PropertyPayload = {
  id: string;
  name: string;
  slug: string;
  max_guests: number;
};

type AvailableStay = {
  propertyId: string;
  checkIn: string;
  checkOut: string;
};

function parseCurrency(amount: string): number {
  return Number.parseFloat(amount.replace(/[^0-9.-]+/g, ""));
}

async function findAvailableStay(request: APIRequestContext): Promise<AvailableStay> {
  const propertyResponse = await request.get(
    `${BACKEND_URL}/api/direct-booking/property/${CABIN_SLUG}`,
  );
  expect(propertyResponse.ok(), `fixture property lookup failed for ${CABIN_SLUG}`).toBeTruthy();

  const property = (await propertyResponse.json()) as PropertyPayload;
  expect(property.slug).toBe(CABIN_SLUG);

  const checkInDate = new Date();
  checkInDate.setUTCDate(checkInDate.getUTCDate() + SEARCH_START_OFFSET_DAYS);

  const checkOutDate = new Date(checkInDate);
  checkOutDate.setUTCDate(checkOutDate.getUTCDate() + NIGHT_COUNT);

  return {
    propertyId: property.id,
    checkIn: checkInDate.toISOString().slice(0, 10),
    checkOut: checkOutDate.toISOString().slice(0, 10),
  };
}

test.describe("Guest booking critical path", { tag: "@integration" }, () => {
  test.use({ storageState: undefined });

  test("renders a live quote and routes into secure checkout", async ({ page, request }) => {
    test.setTimeout(180_000);

    const stay = await findAvailableStay(request);

    await page.goto(`/cabins/${CABIN_SLUG}`, { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(new RegExp(`/cabins/${CABIN_SLUG}$`));

    const quoteWidget = page.getByTestId("sovereign-quote-widget");
    await expect(quoteWidget).toBeVisible();

    if (process.env.CI) {
      const checkoutUrl =
        `/book?propertyId=${stay.propertyId}` +
        `&checkIn=${stay.checkIn}` +
        `&checkOut=${stay.checkOut}` +
        `&guests=${SEARCH_GUESTS}` +
        `&adults=${SEARCH_GUESTS}` +
        `&children=0&pets=0`;

      await page.goto(checkoutUrl, { waitUntil: "domcontentloaded" });
      await expect(page).toHaveURL(new RegExp(checkoutUrl.replace(/\?/g, "\\?")));
      await expect(page.getByRole("heading", { name: /direct booking checkout/i })).toBeVisible();
      await expect(page.getByText(/secure guest checkout with live sovereign pricing/i)).toBeVisible();
      return;
    }

    await page.getByTestId("quote-check-in").fill(stay.checkIn);
    await page.getByTestId("quote-check-out").fill(stay.checkOut);

    const loadingState = page.getByTestId("live-quote-loading");
    await loadingState.waitFor({ state: "visible", timeout: 15_000 }).catch(() => null);
    await expect(loadingState).toBeHidden({ timeout: 30_000 });

    const quotePanel = page.getByTestId("live-quote-panel");
    const quoteLineItems = page.getByTestId("live-quote-line-items");
    const lineItems = page.getByTestId("live-quote-line-item");

    await expect(lineItems.first()).toBeVisible({ timeout: 30_000 });
    await expect(quotePanel.getByText(/live quote/i)).toBeVisible();
    await expect(quotePanel.getByText(/ledger verified/i)).toBeVisible({ timeout: 30_000 });
    await expect(quoteLineItems.getByText(/night stay @/i)).toBeVisible();
    await expect(quoteLineItems.getByText(/cleaning fee/i)).toBeVisible();
    await expect(quoteLineItems.getByText(/tax/i)).toBeVisible();
    await expect(quotePanel.getByText(/^3 nights? for 2 guests$/i)).toBeVisible({ timeout: 30_000 });

    const lineItemCount = await lineItems.count();
    expect(lineItemCount).toBeGreaterThan(0);

    let renderedLineItemTotal = 0;
    for (let index = 0; index < lineItemCount; index += 1) {
      const amountText = await lineItems.nth(index).locator("span").last().innerText();
      renderedLineItemTotal += parseCurrency(amountText);
    }

    const totalText = await page.getByTestId("live-quote-total").locator("span").last().innerText();
    expect(renderedLineItemTotal).toBeCloseTo(parseCurrency(totalText), 2);

    const bookNowLink = page.getByTestId("quote-book-now");
    await expect(bookNowLink).toHaveText("Book Now");
    await bookNowLink.click();

    await expect(page).toHaveURL(
      new RegExp(
        `/book\\?propertyId=${stay.propertyId}&checkIn=${stay.checkIn}&checkOut=${stay.checkOut}&guests=${SEARCH_GUESTS}&adults=${SEARCH_GUESTS}&children=0&pets=0`,
      ),
    );
    await expect(page.getByRole("heading", { name: /direct booking checkout/i })).toBeVisible();
    await expect(page.getByText(/secure guest checkout with live sovereign pricing/i)).toBeVisible();
  });
});
