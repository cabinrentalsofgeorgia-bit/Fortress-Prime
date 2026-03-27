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

type AvailabilityResult = {
  date: string;
  available: boolean;
};

type AvailabilityPayload = {
  month_grid?: Record<string, AvailabilityResult>;
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

  const searchCursor = new Date();
  searchCursor.setUTCDate(searchCursor.getUTCDate() + SEARCH_START_OFFSET_DAYS);

  for (let monthOffset = 0; monthOffset < 6; monthOffset += 1) {
    const monthCursor = new Date(Date.UTC(searchCursor.getUTCFullYear(), searchCursor.getUTCMonth() + monthOffset, 1));
    const year = monthCursor.getUTCFullYear();
    const month = monthCursor.getUTCMonth() + 1;
    const calendarResponse = await request.get(
      `${BACKEND_URL}/api/direct-booking/property/${CABIN_SLUG}/calendar-v2?year=${year}&month=${month}`,
    );
    expect(
      calendarResponse.ok(),
      `calendar lookup failed for ${CABIN_SLUG} ${year}-${String(month).padStart(2, "0")}`,
    ).toBeTruthy();

    const calendar = (await calendarResponse.json()) as AvailabilityPayload;
    const monthGrid = Object.values(calendar.month_grid ?? {})
      .filter((day) => day.available)
      .map((day) => day.date)
      .sort();

    for (let index = 0; index <= monthGrid.length - NIGHT_COUNT; index += 1) {
      const start = new Date(`${monthGrid[index]}T00:00:00Z`);
      if (start < searchCursor) {
        continue;
      }

      let hasContiguousWindow = true;
      for (let night = 1; night < NIGHT_COUNT; night += 1) {
        const expected = new Date(start);
        expected.setUTCDate(expected.getUTCDate() + night);
        const expectedIso = expected.toISOString().slice(0, 10);
        if (monthGrid[index + night] !== expectedIso) {
          hasContiguousWindow = false;
          break;
        }
      }

      if (hasContiguousWindow) {
        const checkIn = start.toISOString().slice(0, 10);
        const checkOut = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), start.getUTCDate() + NIGHT_COUNT))
          .toISOString()
          .slice(0, 10);

        return {
          propertyId: property.id,
          checkIn,
          checkOut,
        };
      }
    }
  }

  throw new Error(`No contiguous ${NIGHT_COUNT}-night ${CABIN_SLUG} stay found in the next 6 months`);
}

test.describe("Guest booking critical path", () => {
  test.use({ storageState: undefined });

  test("renders a live quote and routes into secure checkout", async ({ page, request }) => {
    test.setTimeout(180_000);

    const stay = await findAvailableStay(request);

    await page.goto(`/cabins/${CABIN_SLUG}`, { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(new RegExp(`/cabins/${CABIN_SLUG}$`));

    const quoteWidget = page.getByTestId("sovereign-quote-widget");
    await expect(quoteWidget).toBeVisible();

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
